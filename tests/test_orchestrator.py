"""Orchestrator: end-to-end event resolution + the Memory-write policy per outcome.

    python tests/test_orchestrator.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eyes import ClientScore
from agent.memory import Memory
from agent.verifier import Verifier
from agent.offers import Offer
from agent.brain import subid as make_subid
from agent.orchestrator import process_event


OFFERS = [
    Offer(id="o-b2", partner="DriveNow Auto", product="a subprime auto loan", bands=["B2"],
          affiliate_link="https://drivenow.com/go?aff=P123&subid={subid}", priority=10),
]


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, client, message, unsubscribe_url=None):
        self.sent.append((client.client_id, message, unsubscribe_url))
        return True


def mk(eq, ex, tu, status="Active Client", updated="2026-06-16T20:30:00Z"):
    return ClientScore("C1", "Maria Lopez", "m@x.com", "+10000000000",
                       eq, ex, tu, status, "In Progress", updated)


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.unlink(path)
    return path


def test_full_lifecycle():
    path = _fresh_db()
    try:
        m, s, v = Memory(path), FakeSender(), Verifier()

        # 1) baseline / first sighting -> no_action, records last_mid
        out = process_event(mk(598, 600, 602, updated="2026-05-01T00:00:00Z"), v, s, m, OFFERS)
        assert out == "no_action"
        assert m.get("C1")["last_mid_score"] == 600
        assert s.sent == []

        # 2) upward crossing B1 -> B2 -> sent, offer picked + attributed
        out = process_event(mk(638, 640, 642, updated="2026-06-16T20:30:00Z"), v, s, m, OFFERS)
        assert out == "sent"
        assert [t[0] for t in s.sent] == ["C1"]
        msg, unsub = s.sent[0][1], s.sent[0][2]
        assert "DriveNow Auto" in msg and ("subid=" + make_subid("C1", "B2")) in msg
        assert unsub and "u=" in unsub                                  # per-recipient unsubscribe link
        st = m.get("C1")
        ref = st["referrals_sent"][0]
        assert ref["key"] == "C1:B2" and ref["partner"] == "DriveNow Auto"
        assert ref["subid"] == make_subid("C1", "B2")

        # 3) replay the exact same crossing event -> no_action (freshness), no resend
        out = process_event(mk(638, 640, 642, updated="2026-06-16T20:30:00Z"), v, s, m, OFFERS)
        assert out == "no_action" and len(s.sent) == 1

        # 4) idempotency: a NEW, fresher event still in B2 -> no resend for that band
        out = process_event(mk(650, 652, 648, updated="2026-06-20T00:00:00Z"), v, s, m, OFFERS)
        assert out == "no_action" and len(s.sent) == 1
    finally:
        os.unlink(path)
    print("ok test_full_lifecycle")


def test_crossing_with_no_offer_is_no_action():
    path = _fresh_db()
    try:
        m, s, v = Memory(path), FakeSender(), Verifier()
        process_event(mk(598, 600, 602, updated="2026-05-01T00:00:00Z"), v, s, m, [])  # baseline
        # real B2 crossing but NO offers configured -> nothing to monetize
        out = process_event(mk(638, 640, 642, updated="2026-06-16T20:30:00Z"), v, s, m, [])
        assert out == "no_action"
        assert s.sent == []
        assert m.get("C1")["last_mid_score"] == 640        # baseline still advanced
    finally:
        os.unlink(path)
    print("ok test_crossing_with_no_offer_is_no_action")


def test_suppressed_recipient_is_not_emailed():
    path = _fresh_db()
    try:
        from agent import optout
        m, s, v = Memory(path), FakeSender(), Verifier()
        process_event(mk(598, 600, 602, updated="2026-05-01T00:00:00Z"), v, s, m, OFFERS)  # baseline
        m.suppress(optout.email_hash("m@x.com"))                       # client opts out
        out = process_event(mk(638, 640, 642, updated="2026-06-16T20:30:00Z"), v, s, m, OFFERS)
        assert out == "no_action"          # real B2 crossing, but suppressed -> not sent
        assert s.sent == []
    finally:
        os.unlink(path)
    print("ok test_suppressed_recipient_is_not_emailed")


def test_quarantine_preserves_last_mid():
    path = _fresh_db()
    try:
        m, s, v = Memory(path), FakeSender(), Verifier()
        process_event(mk(598, 600, 602, updated="2026-05-01T00:00:00Z"), v, s, m, OFFERS)
        out = process_event(mk(638, 640, 642, status="Paused",
                                updated="2026-06-16T20:30:00Z"), v, s, m, OFFERS)
        assert out == "quarantine"
        st = m.get("C1")
        assert st["last_mid_score"] == 600                 # crossing preserved
        assert st["last_event_at"] == "2026-06-16T20:30:00Z"
        assert s.sent == []
    finally:
        os.unlink(path)
    print("ok test_quarantine_preserves_last_mid")


def test_invalid_scores_quarantine():
    path = _fresh_db()
    try:
        m, s, v = Memory(path), FakeSender(), Verifier()
        out = process_event(mk(0, 640, 642), v, s, m, OFFERS)
        assert out == "quarantine"
        assert s.sent == []
    finally:
        os.unlink(path)
    print("ok test_invalid_scores_quarantine")


if __name__ == "__main__":
    test_full_lifecycle()
    test_crossing_with_no_offer_is_no_action()
    test_suppressed_recipient_is_not_emailed()
    test_quarantine_preserves_last_mid()
    test_invalid_scores_quarantine()
    print("all tests passed")
