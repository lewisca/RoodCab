"""Brain: band table, mid-score (median), crossing detection, idempotency key.

    python tests/test_brain.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eyes import ClientScore
from agent.brain import band_for, mid_score, propose, idempotency_key, link_with_subid


def mk(eq, ex, tu):
    return ClientScore("C1", "Test Name", "e@x.com", "+10000000000",
                       eq, ex, tu, "Active Client", "In Progress", "2026-06-16T20:30:00Z")


def test_band_boundaries():
    cases = {
        300: "B0", 579: "B0", 580: "B1", 619: "B1", 620: "B2", 659: "B2",
        660: "B3", 699: "B3", 700: "B4", 739: "B4", 740: "B5", 850: "B5",
    }
    for score, band in cases.items():
        assert band_for(score) == band, f"{score} -> {band_for(score)}, expected {band}"


def test_mid_score_is_median():
    assert mid_score(mk(620, 640, 615)) == 620          # median of 3
    assert mid_score(mk(700, 700, 700)) == 700
    assert mid_score(mk(700, 600, 650)) == 650
    # Unsane inputs -> None (Verifier gate 1 will reject)
    assert mid_score(mk(620, None, 615)) is None         # missing bureau
    assert mid_score(mk(620, 0, 615)) is None            # zeroed (out of range)
    assert mid_score(mk(620, 900, 615)) is None          # > 850


def test_crossing_first_sighting_is_not_a_crossing():
    p = propose(mk(620, 640, 615), None)
    assert p.band == "B2" and p.is_crossing is False


def test_upward_crossing_fires():
    p = propose(mk(620, 640, 615), 600)                  # 600 (B1) -> 620 (B2)
    assert p.is_crossing is True and p.band == "B2"


def test_multi_boundary_jump_routes_to_highest_band():
    # mid 615 -> 690 jumps B1 past B2 into B3; route to highest, one referral.
    p = propose(mk(688, 690, 692), 615)
    assert p.band == "B3" and p.is_crossing is True


def test_downward_and_in_band_do_not_fire():
    assert propose(mk(600, 600, 600), 700).is_crossing is False   # downward
    assert propose(mk(630, 630, 630), 625).is_crossing is False   # 625->630 both B2


def test_idempotency_key_format():
    assert idempotency_key("C001", "B2") == "C001:B2"


def test_subid_attribution_link():
    assert "?subid=" in link_with_subid("https://x.com/a", "C1-B2-202606")
    assert "&subid=" in link_with_subid("https://x.com/a?ref=1", "C1-B2-202606")


if __name__ == "__main__":
    test_band_boundaries()
    test_mid_score_is_median()
    test_crossing_first_sighting_is_not_a_crossing()
    test_upward_crossing_fires()
    test_multi_boundary_jump_routes_to_highest_band()
    test_downward_and_in_band_do_not_fire()
    test_idempotency_key_format()
    test_subid_attribution_link()
    print("all tests passed")
