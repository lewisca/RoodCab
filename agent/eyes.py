"""Eyes (perception): ingest current client scores + light sanity.

Three sources:
  * CSVScoreSource          -- batch export / reconciliation (works today)
  * DisputeFoxPayloadSource -- one webhook "New Report Imported" event (primary path)
  * MonitoringAPIScoreSource-- production pull sensor (assumed contract; unverified)

FCRA boundary (compliance invariant -- DO NOT relax): Eyes reads ONLY the three
bureau scores, contact (name/email/phone), eligibility fields (status/folder),
freshness (updated_at), and the consent-agreement marker. It must never fetch,
parse, or store credit-report line items, tradelines, or dispute data, even if the
source carries them. Scores + contact + eligibility + consent only.
"""
import csv
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import config

log = logging.getLogger(__name__)


@dataclass
class ClientScore:
    """One client's current observation. Raw data only -- mid-score and band are
    derived downstream (Brain) and independently re-derived (Verifier).

    PII discipline: name/email/phone and the agreement marker are used in-flight
    (Hand needs contact to send) but are NEVER written to Memory. See memory.py.
    """
    client_id: str
    name: str
    email: str
    phone: str
    equifax: Optional[int]
    experian: Optional[int]
    transunion: Optional[int]
    status: str
    folder: str
    updated_at: str
    agreement_marker: str = ""   # evidence for consent gate 5 (optional)
    state: str = ""              # 2-letter state, in-flight ONLY for offer eligibility; never persisted

    def bureau_scores(self):
        return [self.equifax, self.experian, self.transunion]

    def scores_in_range(self):
        """True only if all three bureaus are present and within [SCORE_MIN, SCORE_MAX]."""
        vals = self.bureau_scores()
        return all(
            isinstance(v, int) and config.SCORE_MIN <= v <= config.SCORE_MAX
            for v in vals
        )


class ScoreSource(ABC):
    @abstractmethod
    def fetch(self) -> list: ...


def _to_int(value):
    """Coerce a score to int; return None for missing/blank/non-numeric."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _row_to_client(row):
    """Map a flat dict (CSV row or webhook payload's flat fields) to a ClientScore.

    Only the FCRA-safe fields are read. Bureau scores coerce to int-or-None (the
    Verifier's sanity gate rejects None/out-of-range); this never raises on a bad row.
    """
    marker = ""
    if config.AGREEMENT_MARKER_FIELD:
        marker = str(row.get(config.AGREEMENT_MARKER_FIELD, "") or "").strip()
    return ClientScore(
        client_id=str(row.get("client_id", "")),
        name=row.get("name", ""),
        email=row.get("email", ""),
        phone=row.get("phone", ""),
        equifax=_to_int(row.get("equifax")),
        experian=_to_int(row.get("experian")),
        transunion=_to_int(row.get("transunion")),
        status=row.get("status", ""),
        folder=row.get("folder", ""),
        updated_at=str(row.get("updated_at", "")),
        agreement_marker=marker,
        state=str(row.get("current_state", row.get("state", "")) or "").strip(),
    )


class CSVScoreSource(ScoreSource):
    """Batch source. Expected columns:
        client_id,name,email,phone,equifax,experian,transunion,status,folder,updated_at
    plus the AGREEMENT_MARKER_FIELD column if one is configured.
    """
    def __init__(self, path):
        self.path = path

    def fetch(self):
        with open(self.path, newline="") as f:
            return [_row_to_client(r) for r in csv.DictReader(f)]


class DisputeFoxPayloadSource(ScoreSource):
    """Primary path: one DisputeFox 'New Report Imported' webhook payload -> one client.

    The payload nests bureau scores under "credit_scores" (see CLAUDE.md §3); we
    flatten just those three plus the FCRA-safe top-level fields and ignore the
    rest (SSN, DOB, address, etc. are never read or stored).

    TODO(verify-live): field mapping below is against the spec doc, not the live
    'New Report Imported' trigger. Run Zapier's "Try It" and confirm: (1) it delivers
    all THREE bureau scores (its description says "credit score", singular) and their
    real field names, and (2) the report line items it carries ("negative and deleted
    items") stay dropped here — FCRA: score + contact + consent only.
    """
    def __init__(self, payload: dict):
        self.payload = payload or {}

    def fetch(self):
        p = self.payload
        scores = p.get("credit_scores", {}) or {}
        flat = {
            "client_id": p.get("client_id", ""),
            "name": " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x),
            "email": p.get("email", ""),
            "phone": p.get("phone_cell") or p.get("phone_home", ""),
            "equifax": scores.get("equifax"),
            "experian": scores.get("experian"),
            "transunion": scores.get("transunion"),
            "status": p.get("status", ""),
            "folder": p.get("folder", ""),
            "updated_at": p.get("updated_at", ""),
            "current_state": p.get("current_state", ""),
        }
        if config.AGREEMENT_MARKER_FIELD:
            flat[config.AGREEMENT_MARKER_FIELD] = p.get(config.AGREEMENT_MARKER_FIELD, "")
        return [_row_to_client(flat)]


class MonitoringAPIScoreSource(ScoreSource):
    """Production pull sensor: fetch current scores from the monitoring vendor's HTTP API.

    ============================ ASSUMED CONTRACT ============================
    !! UNVERIFIED -- written WITHOUT the real vendor docs. Adjust the endpoint,
    !! field names, and pagination shape below once the real API spec is in hand.
    !! Everything in this block is an assumption, not a confirmed fact.

      Request:
        GET {base_url}/v1/clients/scores
        Header:       Authorization: Bearer {api_key}
        Query params: page (1-indexed), per_page (default 200)

      200 response body (JSON):
        {
          "clients": [
            {"id": "C001", "name": "First Last", "email": "a@b.com",
             "phone": "+13055550101",
             "equifax": 620, "experian": 640, "transunion": 615,
             "status": "Active Client", "folder": "In Progress",
             "updated_at": "2026-06-16T20:30:00Z"}
          ],
          "next_page": 2      // integer for the next page, or null when done
        }

      Pagination: follow "next_page" until it is null.
      Row mapping: id->client_id; equifax/experian/transunion coerced to int-or-skip;
                   status/folder/updated_at carried through for the Verifier gates.
    =========================================================================

    FCRA boundary: reads ONLY scores + contact + eligibility + freshness. Never
    tradelines or dispute data, even if the real response carries them.
    """

    SCORES_PATH = "/v1/clients/scores"
    DEFAULT_PER_PAGE = 200
    TIMEOUT_SECONDS = 30

    def __init__(self, base_url, api_key, per_page=DEFAULT_PER_PAGE):
        self.base_url = base_url.rstrip("/")   # avoid // against SCORES_PATH
        self.api_key = api_key
        self.per_page = per_page

    def fetch(self):
        # Optional, guarded import: keep the repo stdlib-first. `requests` is only
        # needed for the live API path, so import it here and fail loudly if absent.
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "MonitoringAPIScoreSource requires the 'requests' package. "
                "Install it (pip install requests) or use SCORE_SOURCE=csv."
            ) from exc

        out = []
        page = 1
        while page is not None:
            resp = requests.get(
                f"{self.base_url}{self.SCORES_PATH}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"page": page, "per_page": self.per_page},
                timeout=self.TIMEOUT_SECONDS,
            )
            if resp.status_code == 401:
                raise PermissionError(
                    "Monitoring API rejected the credentials (HTTP 401). "
                    "Check MONITORING_API_KEY."
                )
            resp.raise_for_status()
            body = resp.json()

            for row in body.get("clients", []):
                # Vendor rows key the id as "id"; normalize to the shared "client_id".
                # Reuse the FCRA-safe mapper -- bad/missing bureaus -> None, which the
                # Verifier's sanity gate rejects (no crash here).
                normalized = {**row, "client_id": row.get("id", row.get("client_id", ""))}
                out.append(_row_to_client(normalized))

            # TODO(real-docs): confirm the pagination key is "next_page" and that
            # null/absent means "no more pages". Some APIs use a cursor token or a
            # total-pages count instead.
            page = body.get("next_page")
        return out


def build_score_source():
    """Construct the batch score source from the environment.

    SCORE_SOURCE=csv (default) -> CSVScoreSource(CLIENTS_CSV or sample baseline)
    SCORE_SOURCE=api           -> MonitoringAPIScoreSource(MONITORING_BASE_URL,
                                                           MONITORING_API_KEY)

    The webhook path uses DisputeFoxPayloadSource directly (one event), not this
    factory. The default path (no env set) is the unchanged dry-run-on-sample behavior.
    """
    kind = os.getenv("SCORE_SOURCE", "csv").strip().lower()
    if kind == "csv":
        return CSVScoreSource(os.getenv("CLIENTS_CSV", "data/clients_sample.csv"))
    if kind == "api":
        base_url = os.getenv("MONITORING_BASE_URL")
        api_key = os.getenv("MONITORING_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError(
                "SCORE_SOURCE=api requires MONITORING_BASE_URL and MONITORING_API_KEY."
            )
        return MonitoringAPIScoreSource(base_url, api_key)
    raise RuntimeError(f"Unknown SCORE_SOURCE={kind!r} (expected 'csv' or 'api').")
