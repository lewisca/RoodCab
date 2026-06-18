"""Verifier (second pass): gate a Brain proposal before anything irreversible fires.

Sits between Brain and Hand (CLAUDE.md §2/§6). Runs gates 1-6 and resolves every
event to exactly one terminal state:

  * SEND       -- all gates pass; fire one referral
  * NO_ACTION  -- nothing to do (no crossing / stale replay / already sent)
  * QUARANTINE -- something is off; a human must look before any offer goes out

Verdict mapping (note vs. the spec's literal "any fail -> quarantine"):
  gate 1 scores out-of-range/missing/zeroed .... QUARANTINE  (data integrity)
  gate 1 stale / replayed event ................ NO_ACTION   (duplicate delivery)
  gate 2 no upward crossing .................... NO_ACTION   (per spec)
  gate 3 referral already sent for band ........ NO_ACTION   (idempotency working)
  gate 4 ineligible (status/folder) ............ QUARANTINE
  gate 5 consent/permissible-purpose ........... QUARANTINE  (HARD STOP)
  gate 6 re-derivation mismatch ................ QUARANTINE
The three NO_ACTION cases are idempotent no-ops, not anomalies, so they don't flood
the human review queue -- which is what the "no action (no crossing)" state is for.
This mapping is a confirmed decision: stale replays / duplicates / non-crossings do
NOT quarantine. Only genuine anomalies (bad scores, ineligible, no consent, mismatch) do.
"""
import datetime
import statistics
from dataclasses import dataclass

import config
from agent.brain import band_for, idempotency_key

SEND = "send"
NO_ACTION = "no_action"
QUARANTINE = "quarantine"


@dataclass
class Verdict:
    outcome: str       # SEND | NO_ACTION | QUARANTINE
    reason: str        # human-readable; used for logs + quarantine record
    gate: int = 0      # which gate decided (0 = n/a)


def _parse_ts(value):
    """Parse an ISO-8601 timestamp (tolerating a trailing 'Z'); None if unparseable."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class Verifier:
    def verify(self, client, proposal, state):
        """Run gates 1-6. `state` is the Memory record dict for this client (or None)."""

        # --- gate 1a: score sanity --------------------------------------------
        if not client.scores_in_range():
            return Verdict(QUARANTINE,
                           f"scores out of range/missing: {client.bureau_scores()}", 1)

        # --- gate 1b: freshness (reject stale / replayed events) --------------
        incoming = _parse_ts(client.updated_at)
        last_seen = _parse_ts(state.get("last_event_at")) if state else None
        if incoming and last_seen and incoming <= last_seen:
            return Verdict(NO_ACTION,
                           f"stale/replayed event (updated_at {client.updated_at} "
                           f"<= last {state.get('last_event_at')})", 1)

        # --- gate 2: real upward crossing -------------------------------------
        if not proposal.is_crossing:
            return Verdict(NO_ACTION,
                           f"no upward crossing ({proposal.prev_band} -> {proposal.band})", 2)

        band = proposal.band

        # --- gate 3: idempotency (one referral per client per band, ever) -----
        key = idempotency_key(client.client_id, band)
        sent_keys = {r.get("key") for r in (state or {}).get("referrals_sent", [])}
        if key in sent_keys:
            return Verdict(NO_ACTION, f"referral already sent for {key}", 3)

        # --- gate 4: eligibility ----------------------------------------------
        if client.status != config.ELIGIBLE_STATUS:
            return Verdict(QUARANTINE,
                           f"ineligible status {client.status!r} "
                           f"(need {config.ELIGIBLE_STATUS!r})", 4)
        if client.folder in config.EXCLUDED_FOLDERS:
            return Verdict(QUARANTINE, f"folder {client.folder!r} is excluded", 4)

        # --- gate 5: compliance / permissible purpose (HARD STOP) -------------
        consent = self._consent_ok(client)
        if consent is not True:
            return Verdict(QUARANTINE, consent, 5)   # consent holds the failure reason

        # --- gate 6: independent re-derivation --------------------------------
        recomputed_mid = int(statistics.median(client.bureau_scores()))
        recomputed_band = band_for(recomputed_mid)
        if recomputed_mid != proposal.mid_score or recomputed_band != band:
            return Verdict(QUARANTINE,
                           f"re-derivation mismatch: verifier {recomputed_mid}/{recomputed_band} "
                           f"vs brain {proposal.mid_score}/{band}", 6)

        # Offer availability is decided downstream (Brain.select_offer): a crossing with
        # no eligible offer resolves to no_action in the orchestrator, not here.
        return Verdict(SEND, f"crossed {proposal.prev_band} -> {band} at mid {proposal.mid_score}", 6)

    @staticmethod
    def _consent_ok(client):
        """Return True if consent gate passes, else a string reason for quarantine."""
        if not config.CONSENT_VIA_AGREEMENT:
            return "consent gate hard-stopped (CONSENT_VIA_AGREEMENT=false)"
        if config.AGREEMENT_MARKER_FIELD and not client.agreement_marker:
            return (f"no agreement marker ({config.AGREEMENT_MARKER_FIELD}) on file; "
                    f"consent unverifiable")
        return True
