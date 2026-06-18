"""Brain (reasoning): derive mid-score, classify band, detect upward crossings,
compose the nudge.

Decision score = MID-SCORE = median(equifax, experian, transunion) (CLAUDE.md §4.1).
A crossing is an UPWARD move across a band boundary vs. the client's last mid-score;
a multi-boundary jump routes to the HIGHEST band reached and fires ONE referral.

Message generation has two modes: a deterministic template (default, free) and an
optional Claude-generated personalized message (USE_CLAUDE=true). Keep all copy
FCRA/CROA-safe: no guarantees, no "we'll fix your credit" claims.
"""
import datetime
import statistics
from dataclasses import dataclass
from typing import Optional

from config import BANDS, ROUTING, CONSENT_LINE, USE_CLAUDE, CLAUDE_MODEL


@dataclass
class Proposal:
    """Brain's output, handed to the Verifier. Nothing irreversible has happened yet."""
    mid_score: Optional[int]      # None if scores aren't sane (Verifier gate 1 catches)
    band: Optional[str]
    prev_mid: Optional[int]
    prev_band: Optional[str]
    is_crossing: bool


def mid_score(client):
    """Median of the three bureaus, or None if any is missing/out-of-range."""
    if not client.scores_in_range():
        return None
    return int(statistics.median(client.bureau_scores()))


def band_for(score):
    for name, lo, hi in BANDS:
        if lo <= score <= hi:
            return name
    return BANDS[0][0] if score < BANDS[0][1] else BANDS[-1][0]


def band_rank(name):
    for i, (n, _, _) in enumerate(BANDS):
        if n == name:
            return i
    return -1


def is_upward_crossing(prev_band, current_band):
    if prev_band is None:        # first observation: record baseline, don't fire
        return False
    return band_rank(current_band) > band_rank(prev_band)


def propose(client, prev_mid):
    """Derive the decision score, band, and whether this is an upward crossing."""
    mid = mid_score(client)
    band = band_for(mid) if mid is not None else None
    prev_band = band_for(prev_mid) if prev_mid is not None else None
    crossing = is_upward_crossing(prev_band, band) if band is not None else False
    return Proposal(mid_score=mid, band=band, prev_mid=prev_mid,
                    prev_band=prev_band, is_crossing=crossing)


def idempotency_key(client_id, band):
    """Permanent one-referral-per-client-per-band key (Verifier gate 3)."""
    return f"{client_id}:{band}"


def subid(client_id, band):
    """Per-send attribution id (may repeat across months; distinct from the key)."""
    return f"{client_id}-{band}-{datetime.datetime.utcnow():%Y%m}"


def link_with_subid(link, sid):
    sep = "&" if "?" in link else "?"
    return f"{link}{sep}subid={sid}"


def select_offer(client, band, offers):
    """Pick the best lending offer to surface for this band (the monetization core).

    Eligible = enabled AND serves this band AND has a usable link AND serves the client's
    state. Among eligible offers, the highest-`priority` one wins (file order breaks ties).
    Returns the Offer, or None if the provider has no eligible offer for this band.
    """
    state = getattr(client, "state", "")
    eligible = [o for o in offers
                if o.enabled and band in o.bands and o.usable_link() and o.serves_state(state)]
    if not eligible:
        return None
    eligible.sort(key=lambda o: o.priority, reverse=True)   # stable: ties keep file order
    return eligible[0]


def offer_link(offer, sid):
    """Build the outbound tracked link for an offer, injecting the attribution subid."""
    raw = offer.usable_link()
    if raw is None:
        return None
    return raw.replace("{subid}", sid) if "{subid}" in raw else link_with_subid(raw, sid)


def template_message(client, band, offer, link):
    label = ROUTING[band]["label"]
    first = client.name.split()[0] if client.name.strip() else "there"
    return (f"Hi {first}, your credit just moved into a new tier ({label}). "
            f"A strong next step could be {offer.product} with {offer.partner}. "
            f"Here's a matched option to explore (soft check, no score impact): {link}\n{CONSENT_LINE}")


def claude_message(client, band, offer, link):
    """Personalized nudge via Claude. Requires `anthropic` + ANTHROPIC_API_KEY."""
    from anthropic import Anthropic
    label = ROUTING[band]["label"]
    first = client.name.split()[0] if client.name.strip() else "there"
    prompt = (
        f"Write one short SMS (max 320 chars) to {first}, a credit-repair "
        f"client whose score just improved into the {label} tier. Recommend exactly ONE "
        f"next step: {offer.product} with {offer.partner}. Include this URL verbatim: {link}. "
        f"End with this exact sentence: {CONSENT_LINE} "
        f"Rules: warm and plain, no hype, no promises or guarantees about credit outcomes, "
        f"FCRA/CROA-safe. Output only the message text."
    )
    resp = Anthropic().messages.create(
        model=CLAUDE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def build_message(client, band, offer, link):
    if USE_CLAUDE:
        try:
            return claude_message(client, band, offer, link)
        except Exception as e:
            print(f"[brain] Claude generation failed ({e}); using template.")
    return template_message(client, band, offer, link)
