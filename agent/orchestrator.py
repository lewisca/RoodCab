"""Orchestrator: the agent loop. Eyes -> Brain -> Verifier -> Hand, around Memory.

Every event resolves to exactly one terminal state -- sent / no_action / held / quarantine
-- and is written to Memory. The Verifier owns all compliance/eligibility/idempotency
gates; on SEND, the Brain picks the best lending offer for the band and the orchestrator
fires it and records the attribution (partner, offer, subid) for payout reconciliation.
A safety leash (REQUIRE_APPROVAL / MAX_SENDS_PER_DAY) can HOLD an otherwise-valid send.

Memory-write policy by outcome:
  sent       -> history + advance (last_mid, last_event_at) + record referral
  no_action  -> stale replay: no writes; otherwise history + advance baseline
  quarantine -> history + advance last_event_at ONLY (preserve last_mid) + log reason
"""
import config
from agent import optout, providers, alerts
from agent.brain import (
    propose, select_offer, offer_link, build_message, subid, idempotency_key,
)
from agent.verifier import Verifier, SEND, NO_ACTION, QUARANTINE


def _hold_reason(memory):
    """Safety leash: reason a would-be send should be HELD, or None to allow it."""
    if config.REQUIRE_APPROVAL:
        return "approval required (REQUIRE_APPROVAL)"
    cap = config.MAX_SENDS_PER_DAY
    if cap and memory.sends_today() >= cap:
        return f"daily send cap reached ({cap})"
    return None


def process_event(client, verifier, sender, memory, offers=None, provider_id="default"):
    """Run one client-updated event through the full pipeline. Returns the outcome str."""
    offers = offers or []
    state = memory.get(client.client_id)
    prev_mid = state.get("last_mid_score") if state else None
    proposal = propose(client, prev_mid)
    verdict = verifier.verify(client, proposal, state)

    eq, ex, tu = client.equifax, client.experian, client.transunion
    cid = client.client_id

    if verdict.outcome == SEND:
        band = proposal.band

        # Opt-out suppression (CAN-SPAM): never email an address that unsubscribed.
        if memory.is_suppressed(optout.email_hash(client.email)):
            print(f"[suppressed] {cid}: recipient opted out; not emailing")
            memory.append_history(cid, eq, ex, tu, proposal.mid_score)
            memory.upsert_state(cid, last_mid_score=proposal.mid_score,
                                last_event_at=client.updated_at)
            return "no_action"

        offer = select_offer(client, band, offers)
        if offer is None:
            # Crossed upward, but the provider has no eligible offer for this band -> there
            # is nothing to monetize. Record the crossing (advance baseline so we don't
            # re-fire) and flag the gap; adding an offer for this band captures it next time.
            print(f"[no-offer] {cid}: crossed {proposal.prev_band} -> {band}, "
                  f"but no eligible offer is configured")
            memory.append_history(cid, eq, ex, tu, proposal.mid_score)
            memory.upsert_state(cid, last_mid_score=proposal.mid_score,
                                last_event_at=client.updated_at)
            return "no_action"

        sid = subid(cid, band)

        # Safety leash: hold the send for approval / when the daily cap is hit. The
        # crossing is preserved (last_mid not advanced) so it re-fires on the next import.
        hold = _hold_reason(memory)
        if hold:
            print(f"[held] {cid}: {proposal.prev_band} -> {band} ({offer.partner}) -- {hold}")
            alerts.notify("held", provider_id, cid, band, hold)
            memory.append_history(cid, eq, ex, tu, proposal.mid_score)
            memory.upsert_state(cid, last_event_at=client.updated_at)
            memory.record_held(cid, band, offer_id=offer.id, partner=offer.partner,
                               subid=sid, reason=hold)
            return "held"

        link = offer_link(offer, sid)
        message = build_message(client, band, offer, link)
        unsub = optout.unsubscribe_url(config.UNSUBSCRIBE_URL, provider_id, client.email)
        print(f"[fire] {cid}: {proposal.prev_band} -> {band}  "
              f"({offer.partner} | {offer.link_source()} link | subid={sid})")
        cfg = config.ROUTING.get(band, {})
        if cfg.get("compliance_note"):
            print(f"       [!] {cfg['compliance_note']}")
        sender.send(client, message, unsubscribe_url=unsub)
        memory.append_history(cid, eq, ex, tu, proposal.mid_score)
        memory.upsert_state(cid, last_mid_score=proposal.mid_score,
                            last_event_at=client.updated_at)
        memory.record_referral(cid, band, idempotency_key(cid, band), offer_id=offer.id,
                               partner=offer.partner, product=offer.product, subid=sid)
        if provider_id != "default":       # multi-tenant: route future conversion postbacks
            providers.index_subid(sid, provider_id)
        return "sent"

    if verdict.outcome == QUARANTINE:
        print(f"[quarantine] {cid}: (gate {verdict.gate}) {verdict.reason}")
        alerts.notify("quarantine", provider_id, cid, proposal.band or "-", verdict.reason)
        memory.append_history(cid, eq, ex, tu, proposal.mid_score)
        # Advance freshness so Zapier retries don't re-quarantine; KEEP last_mid so a
        # real crossing isn't lost if the client later becomes eligible/compliant.
        memory.upsert_state(cid, last_event_at=client.updated_at)
        memory.record_quarantine(cid, verdict.reason)
        return "quarantine"

    # NO_ACTION
    if verdict.gate == 1:                       # stale/replayed duplicate -> already processed
        return "no_action"
    memory.append_history(cid, eq, ex, tu, proposal.mid_score)
    memory.upsert_state(cid, last_mid_score=proposal.mid_score,
                        last_event_at=client.updated_at)
    return "no_action"


def run(source, sender, memory, verifier=None, offers=None):
    """Batch / reconciliation driver: process every client the source yields."""
    verifier = verifier or Verifier()
    offers = offers or []
    clients = source.fetch()
    counts = {"sent": 0, "no_action": 0, "quarantine": 0, "held": 0}
    for c in clients:
        counts[process_event(c, verifier, sender, memory, offers)] += 1

    print(f"\nDone. sent={counts['sent']}  no_action={counts['no_action']}  "
          f"held={counts['held']}  quarantine={counts['quarantine']}  total={len(clients)}")
    return {**counts, "total": len(clients)}
