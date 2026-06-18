"""Verifier: the six gates and how each maps to send / no_action / quarantine.

    python tests/test_verifier.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from agent.eyes import ClientScore
from agent.brain import propose, Proposal
from agent.verifier import Verifier, SEND, NO_ACTION, QUARANTINE


def mk(eq, ex, tu, status="Active Client", folder="In Progress",
       updated="2026-06-16T20:30:00Z", marker=""):
    return ClientScore("C1", "Test Name", "e@x.com", "+10000000000",
                       eq, ex, tu, status, folder, updated, agreement_marker=marker)


def state(last_mid=None, last_event=None, refs=None):
    return {"client_id": "C1", "last_mid_score": last_mid,
            "last_event_at": last_event, "referrals_sent": refs or []}


V = Verifier()


# --- gate 1: sanity / freshness -------------------------------------------

def test_gate1_out_of_range_quarantines():
    c = mk(0, 640, 615)                       # zeroed bureau
    v = V.verify(c, propose(c, 600), state(last_mid=600))
    assert v.outcome == QUARANTINE and v.gate == 1


def test_gate1_stale_event_is_no_action():
    c = mk(638, 640, 642, updated="2026-05-01T00:00:00Z")   # older than last_event
    v = V.verify(c, propose(c, 600), state(last_mid=600, last_event="2026-06-16T20:30:00Z"))
    assert v.outcome == NO_ACTION and v.gate == 1


# --- gate 2: real crossing -------------------------------------------------

def test_gate2_no_crossing_is_no_action():
    c = mk(630, 630, 630)                      # mid 630 (B2)
    v = V.verify(c, propose(c, 625), state(last_mid=625))   # 625->630 both B2
    assert v.outcome == NO_ACTION and v.gate == 2


def test_gate2_first_sighting_is_no_action():
    c = mk(638, 640, 642)
    v = V.verify(c, propose(c, None), None)
    assert v.outcome == NO_ACTION and v.gate == 2


# --- gate 3: idempotency ---------------------------------------------------

def test_gate3_already_sent_is_no_action():
    c = mk(638, 640, 642)                      # mid 640 (B2), crossing from 600
    st = state(last_mid=600, refs=[{"band": "B2", "product": "x", "ts": "t", "key": "C1:B2"}])
    v = V.verify(c, propose(c, 600), st)
    assert v.outcome == NO_ACTION and v.gate == 3


# --- gate 4: eligibility ---------------------------------------------------

def test_gate4_wrong_status_quarantines():
    c = mk(638, 640, 642, status="Paused")
    v = V.verify(c, propose(c, 600), state(last_mid=600))
    assert v.outcome == QUARANTINE and v.gate == 4


def test_gate4_excluded_folder_quarantines():
    c = mk(638, 640, 642, folder="Cancelled")
    saved = config.EXCLUDED_FOLDERS
    config.EXCLUDED_FOLDERS = {"Cancelled"}
    try:
        v = V.verify(c, propose(c, 600), state(last_mid=600))
    finally:
        config.EXCLUDED_FOLDERS = saved
    assert v.outcome == QUARANTINE and v.gate == 4


# --- gate 5: consent / permissible purpose (HARD STOP) --------------------

def test_gate5_consent_switch_off_quarantines():
    c = mk(638, 640, 642)
    saved = config.CONSENT_VIA_AGREEMENT
    config.CONSENT_VIA_AGREEMENT = False
    try:
        v = V.verify(c, propose(c, 600), state(last_mid=600))
    finally:
        config.CONSENT_VIA_AGREEMENT = saved
    assert v.outcome == QUARANTINE and v.gate == 5


def test_gate5_missing_marker_quarantines():
    c = mk(638, 640, 642, marker="")          # no evidence
    saved = config.AGREEMENT_MARKER_FIELD
    config.AGREEMENT_MARKER_FIELD = "agreement_signed_at"
    try:
        v = V.verify(c, propose(c, 600), state(last_mid=600))
    finally:
        config.AGREEMENT_MARKER_FIELD = saved
    assert v.outcome == QUARANTINE and v.gate == 5


def test_gate5_present_marker_passes():
    c = mk(638, 640, 642, marker="2026-01-02")
    saved = config.AGREEMENT_MARKER_FIELD
    config.AGREEMENT_MARKER_FIELD = "agreement_signed_at"
    try:
        v = V.verify(c, propose(c, 600), state(last_mid=600))
    finally:
        config.AGREEMENT_MARKER_FIELD = saved
    assert v.outcome == SEND


# --- gate 6: independent re-derivation ------------------------------------

def test_gate6_band_mismatch_quarantines():
    c = mk(638, 640, 642)                      # really mid 640 -> B2
    tampered = Proposal(mid_score=640, band="B5", prev_mid=600, prev_band="B1", is_crossing=True)
    v = V.verify(c, tampered, state(last_mid=600))
    assert v.outcome == QUARANTINE and v.gate == 6


# --- happy path ------------------------------------------------------------

def test_all_gates_pass_sends():
    c = mk(638, 640, 642)                      # mid 640 (B2), crossing from 600 (B1)
    v = V.verify(c, propose(c, 600), state(last_mid=600))
    assert v.outcome == SEND


if __name__ == "__main__":
    test_gate1_out_of_range_quarantines()
    test_gate1_stale_event_is_no_action()
    test_gate2_no_crossing_is_no_action()
    test_gate2_first_sighting_is_no_action()
    test_gate3_already_sent_is_no_action()
    test_gate4_wrong_status_quarantines()
    test_gate4_excluded_folder_quarantines()
    test_gate5_consent_switch_off_quarantines()
    test_gate5_missing_marker_quarantines()
    test_gate5_present_marker_passes()
    test_gate6_band_mismatch_quarantines()
    test_all_gates_pass_sends()
    print("all tests passed")
