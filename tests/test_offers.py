"""Offers: catalog loading, brain offer-selection (priority + eligibility), link building.

    python tests/test_offers.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eyes import ClientScore
from agent.offers import Offer, load_offers
from agent.brain import select_offer, offer_link


def mk(band_state=""):
    return ClientScore("C1", "Test", "e@x.com", "+1", 638, 640, 642,
                       "Active Client", "In Progress", "2026-06-16T20:30:00Z", state=band_state)


def off(id, bands, priority=0, affiliate=None, house="https://go.roodcab.io/x?subid={subid}",
        states=("*",), enabled=True):
    return Offer(id=id, partner=id.title(), product="a product", bands=list(bands),
                 affiliate_link=affiliate, house_link=house, priority=priority,
                 states=list(states), enabled=enabled)


def test_select_highest_priority_for_band():
    offers = [off("low", ["B2"], priority=10), off("high", ["B2"], priority=20),
              off("other", ["B3"], priority=99)]
    chosen = select_offer(mk(), "B2", offers)
    assert chosen.id == "high"                         # priority wins; B3 offer ignored


def test_select_respects_band_membership():
    offers = [off("b3only", ["B3"], priority=50)]
    assert select_offer(mk(), "B2", offers) is None    # no B2 offer
    assert select_offer(mk(), "B3", offers).id == "b3only"


def test_disabled_and_linkless_offers_are_skipped():
    offers = [
        off("disabled", ["B2"], priority=99, enabled=False),
        off("nolink", ["B2"], priority=99, affiliate=None, house=None),
        off("good", ["B2"], priority=1),
    ]
    assert select_offer(mk(), "B2", offers).id == "good"


def test_state_eligibility():
    fl_only = off("flonly", ["B2"], priority=10, states=["FL"])
    assert select_offer(mk("FL"), "B2", [fl_only]).id == "flonly"   # in-state
    assert select_offer(mk("GA"), "B2", [fl_only]) is None          # out-of-state
    assert select_offer(mk(""),   "B2", [fl_only]) is None          # unknown state, restricted offer


def test_link_source_prefers_affiliate():
    own = off("own", ["B2"], affiliate="https://p.com/a?subid={subid}")
    house = off("house", ["B2"], affiliate=None)
    assert own.link_source() == "affiliate"
    assert house.link_source() == "house"
    assert off("none", ["B2"], affiliate=None, house=None).link_source() is None


def test_offer_link_injects_subid():
    # placeholder form
    o1 = off("a", ["B2"], affiliate="https://p.com/apply?aff=1&subid={subid}")
    assert offer_link(o1, "C1-B2-202606") == "https://p.com/apply?aff=1&subid=C1-B2-202606"
    # no placeholder, existing query -> appended with &
    o2 = off("b", ["B2"], affiliate="https://p.com/apply?aff=1")
    assert offer_link(o2, "S") == "https://p.com/apply?aff=1&subid=S"
    # no placeholder, no query -> appended with ?
    o3 = off("c", ["B2"], affiliate=None, house="https://p.com/h")
    assert offer_link(o3, "S") == "https://p.com/h?subid=S"


def test_load_sample_catalog():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offers = load_offers(os.path.join(here, "data", "offers_sample.json"))
    assert len(offers) >= 5
    # B2 should resolve to DriveNow (priority 20) over FirstCard (priority 10)
    assert select_offer(mk(), "B2", offers).partner == "DriveNow Auto"
    # mortgage offer is RESPA-flagged
    b5 = select_offer(mk(), "B5", offers)
    assert b5 is not None and b5.compliance == "respa"


def test_missing_file_returns_empty():
    assert load_offers("does/not/exist.json") == []


if __name__ == "__main__":
    test_select_highest_priority_for_band()
    test_select_respects_band_membership()
    test_disabled_and_linkless_offers_are_skipped()
    test_state_eligibility()
    test_link_source_prefers_affiliate()
    test_offer_link_injects_subid()
    test_load_sample_catalog()
    test_missing_file_returns_empty()
    print("all tests passed")
