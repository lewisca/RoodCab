"""Tests for the Eyes sources (3-bureau model).

The HTTP layer is fully MOCKED -- a fake `requests` module is injected into
sys.modules, so these tests make NO real network calls. Runnable directly:

    python tests/test_eyes.py
"""
import os, sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eyes import (
    MonitoringAPIScoreSource, DisputeFoxPayloadSource, CSVScoreSource,
    build_score_source, ClientScore,
)


# --- fake HTTP layer ------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status called on {self.status_code}")


class FakeRequests:
    """Stand-in for the `requests` module. Serves queued pages by `page` param."""
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self._pages[(params or {}).get("page", 1)]


def _api_row(cid, eq, ex, tu, status="Active Client", folder="In Progress"):
    return {
        "id": cid, "name": f"Name {cid}", "email": f"{cid}@example.com",
        "phone": "+13055550100", "equifax": eq, "experian": ex, "transunion": tu,
        "status": status, "folder": folder, "updated_at": "2026-06-16T20:30:00Z",
    }


def _patch_requests(fake):
    return mock.patch.dict(sys.modules, {"requests": fake})


# --- API source -----------------------------------------------------------

def test_happy_path_single_page():
    fake = FakeRequests({
        1: FakeResponse(200, {
            "clients": [_api_row("C001", 638, 640, 642), _api_row("C002", 700, 705, 710)],
            "next_page": None,
        }),
    })
    with _patch_requests(fake):
        rows = MonitoringAPIScoreSource("https://vendor.test", "key-123").fetch()

    assert [r.client_id for r in rows] == ["C001", "C002"]
    assert all(isinstance(r, ClientScore) for r in rows)
    assert (rows[0].equifax, rows[0].experian, rows[0].transunion) == (638, 640, 642)
    assert rows[0].scores_in_range() is True
    call = fake.calls[0]
    assert call["url"] == "https://vendor.test/v1/clients/scores"
    assert call["headers"] == {"Authorization": "Bearer key-123"}
    assert call["params"] == {"page": 1, "per_page": 200}
    print("ok test_happy_path_single_page")


def test_multi_page_pagination():
    fake = FakeRequests({
        1: FakeResponse(200, {"clients": [_api_row("C001", 600, 600, 600)], "next_page": 2}),
        2: FakeResponse(200, {"clients": [_api_row("C002", 610, 610, 610)], "next_page": 3}),
        3: FakeResponse(200, {"clients": [_api_row("C003", 620, 620, 620)], "next_page": None}),
    })
    with _patch_requests(fake):
        rows = MonitoringAPIScoreSource("https://vendor.test", "k").fetch()

    assert [r.client_id for r in rows] == ["C001", "C002", "C003"]
    assert [c["params"]["page"] for c in fake.calls] == [1, 2, 3]
    print("ok test_multi_page_pagination")


def test_invalid_bureau_yields_unsane_row():
    # New model: rows are NOT dropped at ingest; a bad bureau becomes None and the
    # Verifier's sanity gate rejects it. Eyes just reports what it saw.
    fake = FakeRequests({
        1: FakeResponse(200, {"clients": [
            _api_row("C001", 638, 640, 642),     # sane
            _api_row("C002", "", 640, 642),      # blank bureau -> None
            _api_row("C003", 640, "n/a", 642),   # non-numeric -> None
            _api_row("C004", 0, 640, 642),       # zeroed -> out of range
        ], "next_page": None}),
    })
    with _patch_requests(fake):
        rows = MonitoringAPIScoreSource("https://vendor.test", "k").fetch()

    by_id = {r.client_id: r for r in rows}
    assert len(rows) == 4                                # nothing dropped
    assert by_id["C001"].scores_in_range() is True
    assert by_id["C002"].equifax is None and by_id["C002"].scores_in_range() is False
    assert by_id["C003"].experian is None and by_id["C003"].scores_in_range() is False
    assert by_id["C004"].scores_in_range() is False      # 0 is out of [300,850]
    print("ok test_invalid_bureau_yields_unsane_row")


def test_401_raises_clear_auth_error():
    fake = FakeRequests({1: FakeResponse(401, {})})
    with _patch_requests(fake):
        try:
            MonitoringAPIScoreSource("https://vendor.test", "bad-key").fetch()
        except PermissionError as exc:
            assert "401" in str(exc)
            print("ok test_401_raises_clear_auth_error")
            return
    raise AssertionError("expected PermissionError on HTTP 401")


# --- DisputeFox payload source (FCRA boundary) ----------------------------

def test_disputefox_payload_maps_safe_fields_only():
    payload = {
        "client_id": "12345", "first_name": "John", "last_name": "Doe",
        "email": "john@example.com", "phone_cell": "+13055550101",
        # PII the agent must NOT read/store:
        "date_of_birth": "1985-05-12", "ssn_hidden": "XXX-XX-1234",
        "current_address": "123 Main St",
        "status": "Active Client", "folder": "In Progress",
        "credit_scores": {"equifax": 620, "experian": 640, "transunion": 615},
        "updated_at": "2026-06-16T20:30:00Z",
    }
    (c,) = DisputeFoxPayloadSource(payload).fetch()
    assert c.client_id == "12345"
    assert c.name == "John Doe"
    assert (c.equifax, c.experian, c.transunion) == (620, 640, 615)
    assert c.status == "Active Client" and c.folder == "In Progress"
    # FCRA: no SSN/DOB/address field exists on the dataclass at all.
    for forbidden in ("ssn_hidden", "date_of_birth", "current_address"):
        assert not hasattr(c, forbidden)
    print("ok test_disputefox_payload_maps_safe_fields_only")


# --- CSV source -----------------------------------------------------------

def test_csv_source_parses_three_bureaus(tmp_path=None):
    import tempfile, textwrap
    data = textwrap.dedent("""\
        client_id,name,email,phone,equifax,experian,transunion,status,folder,updated_at
        C001,Maria Lopez,maria@example.com,+13055550101,638,640,642,Active Client,In Progress,2026-06-16T20:30:00Z
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write(data); path = f.name
    try:
        (c,) = CSVScoreSource(path).fetch()
        assert (c.equifax, c.experian, c.transunion) == (638, 640, 642)
        assert c.scores_in_range() is True
    finally:
        os.unlink(path)
    print("ok test_csv_source_parses_three_bureaus")


# --- factory --------------------------------------------------------------

def test_factory_defaults_to_csv():
    env = {k: v for k, v in os.environ.items()
           if k not in ("SCORE_SOURCE", "CLIENTS_CSV")}
    with mock.patch.dict(os.environ, env, clear=True):
        src = build_score_source()
    assert isinstance(src, CSVScoreSource)
    assert src.path == "data/clients_sample.csv"
    print("ok test_factory_defaults_to_csv")


def test_factory_api_requires_credentials():
    with mock.patch.dict(os.environ, {"SCORE_SOURCE": "api"}, clear=True):
        try:
            build_score_source()
        except RuntimeError as exc:
            assert "MONITORING_BASE_URL" in str(exc)
            print("ok test_factory_api_requires_credentials")
            return
    raise AssertionError("expected RuntimeError when api creds are missing")


if __name__ == "__main__":
    test_happy_path_single_page()
    test_multi_page_pagination()
    test_invalid_bureau_yields_unsane_row()
    test_401_raises_clear_auth_error()
    test_disputefox_payload_maps_safe_fields_only()
    test_csv_source_parses_three_bureaus()
    test_factory_defaults_to_csv()
    test_factory_api_requires_credentials()
    print("all tests passed")
