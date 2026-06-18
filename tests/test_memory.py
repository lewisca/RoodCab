"""Memory: schema, upsert, idempotency keys, and the no-PII invariant.

    python tests/test_memory.py
"""
import os, sys, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.memory import Memory


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)               # let Memory create it fresh
    return path


def test_observation_roundtrip():
    path = _fresh_db()
    try:
        m = Memory(path)
        assert m.get("C1") is None
        m.append_history("C1", 638, 640, 642, 640)
        m.upsert_state("C1", last_mid_score=640, last_event_at="2026-06-16T20:30:00Z")
        st = m.get("C1")
        assert st["last_mid_score"] == 640
        assert st["last_event_at"] == "2026-06-16T20:30:00Z"
        assert st["referrals_sent"] == []
    finally:
        os.unlink(path)
    print("ok test_observation_roundtrip")


def test_upsert_preserves_unset_fields():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.upsert_state("C1", last_mid_score=640, last_event_at="t1")
        m.upsert_state("C1", last_event_at="t2")          # last_mid omitted -> preserved
        st = m.get("C1")
        assert st["last_mid_score"] == 640 and st["last_event_at"] == "t2"
    finally:
        os.unlink(path)
    print("ok test_upsert_preserves_unset_fields")


def test_referral_idempotency_key_is_unique():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.record_referral("C1", "B2", "C1:B2", offer_id="drivenow-auto",
                          partner="DriveNow Auto", product="subprime auto", subid="C1-B2-202606")
        m.record_referral("C1", "B2", "C1:B2", offer_id="drivenow-auto",
                          partner="DriveNow Auto", product="subprime auto", subid="C1-B2-202606")
        assert m.has_referral("C1:B2") is True
        st = m.get("C1")
        assert len(st["referrals_sent"]) == 1                     # not duplicated
        ref = st["referrals_sent"][0]
        assert ref["key"] == "C1:B2"
        assert ref["partner"] == "DriveNow Auto"
        assert ref["subid"] == "C1-B2-202606"                     # attribution persisted
    finally:
        os.unlink(path)
    print("ok test_referral_idempotency_key_is_unique")


def test_quarantine_logged():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.record_quarantine("C1", "ineligible status 'Paused'")
        c = sqlite3.connect(path)
        try:
            rows = c.execute("SELECT client_id, reason FROM quarantine_log").fetchall()
        finally:
            c.close()
        assert rows == [("C1", "ineligible status 'Paused'")]
    finally:
        os.unlink(path)
    print("ok test_quarantine_logged")


def test_no_pii_columns_anywhere():
    # The schema must never have a place to store name/email/phone/dob/ssn/address.
    path = _fresh_db()
    try:
        Memory(path)
        forbidden = {"name", "email", "phone", "first_name", "last_name",
                     "dob", "date_of_birth", "ssn", "ssn_hidden", "address"}
        c = sqlite3.connect(path)
        try:
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for t in tables:
                cols = {r[1].lower() for r in c.execute(f"PRAGMA table_info({t})").fetchall()}
                leaked = cols & forbidden
                assert not leaked, f"PII column(s) {leaked} in table {t}"
        finally:
            c.close()
    finally:
        os.unlink(path)
    print("ok test_no_pii_columns_anywhere")


if __name__ == "__main__":
    test_observation_roundtrip()
    test_upsert_preserves_unset_fields()
    test_referral_idempotency_key_is_unique()
    test_quarantine_logged()
    test_no_pii_columns_anywhere()
    print("all tests passed")
