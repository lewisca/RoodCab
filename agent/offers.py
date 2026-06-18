"""Offers (monetization catalog): the lending products a provider can surface.

Each offer ties a lending partner to one or more bands and to the LINKS that earn
the provider a commission on conversion. Links are tried in priority order:

  1. affiliate_link  -- the provider's OWN affiliate URL (payout goes straight to them)
  2. house_link      -- Rood Cab's master link, still attributed to the provider via
                        subid, used until they have their own affiliate ID (no missed revenue)
  3. (apply_link)    -- NOT used for routing; it's where the provider applies to get
                        their own affiliate ID. Surfaced in the setup UI only.

A link may contain a literal "{subid}" placeholder; if absent, the subid is appended.

This is per-provider configuration (data/offers_sample.json). It is NOT credit-report
data -- it's the provider's affiliate setup, safe to store.
"""
import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Offer:
    id: str
    partner: str
    product: str
    bands: List[str]                       # e.g. ["B2", "B3"]
    affiliate_link: Optional[str] = None   # provider's own (preferred)
    house_link: Optional[str] = None       # Rood Cab fallback
    apply_link: Optional[str] = None       # where to get your own affiliate id (UI only)
    priority: int = 0                       # higher = surfaced first
    states: List[str] = field(default_factory=lambda: ["*"])  # ["*"] = nationwide
    enabled: bool = True
    compliance: str = "standard"           # "standard" | "respa" (mortgage)

    def usable_link(self):
        """The link that would actually be sent (own first, then house), or None."""
        return self.affiliate_link or self.house_link

    def link_source(self):
        if self.affiliate_link:
            return "affiliate"
        if self.house_link:
            return "house"
        return None

    def serves_state(self, state):
        if "*" in self.states:
            return True
        if not state:
            return False                    # state-restricted offer needs a known state
        return state.upper() in {s.upper() for s in self.states}


def load_offers(path):
    """Load a provider's offers from JSON. Returns a list[Offer] (empty if file absent)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    rows = raw.get("offers", raw) if isinstance(raw, dict) else raw
    offers = []
    for r in rows:
        offers.append(Offer(
            id=r["id"], partner=r["partner"], product=r["product"], bands=r["bands"],
            affiliate_link=r.get("affiliate_link"), house_link=r.get("house_link"),
            apply_link=r.get("apply_link"), priority=int(r.get("priority", 0)),
            states=r.get("states", ["*"]), enabled=bool(r.get("enabled", True)),
            compliance=r.get("compliance", "standard"),
        ))
    return offers
