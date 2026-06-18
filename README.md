# score-router-agent

Watches credit-repair clients' three bureau scores and, when a client's **mid-score
crosses up** into a new band, sends **one** matched financing offer (tracked link) —
but only after a Verifier confirms the crossing is real, fresh, non-duplicate, eligible,
and compliant. Built as an **Eyes / Brain / Verifier / Hand / Memory** agent. Every event
resolves to **sent**, **no_action**, or **quarantine**.

## Quickstart (dry-run, no setup)
```bash
python run.py                                    # records baseline (no sends on first run)
CLIENTS_CSV=data/clients_next.csv python run.py  # second cycle -> fires on upward crossings

# one webhook event (DisputeFox payload on stdin):
echo '{"client_id":"C001","credit_scores":{"equifax":638,"experian":640,"transunion":642},
       "status":"Active Client","folder":"In Progress","updated_at":"2026-06-16T20:30:00Z"}' \
  | python webhook.py
```
Dry-run prints the messages it *would* send. Nothing leaves your machine.

## Tests
```bash
python tests/test_brain.py         # mid-score (median), bands, crossing, idempotency key
python tests/test_eyes.py          # 3-bureau sources, pagination, DisputeFox FCRA-filter (HTTP mocked)
python tests/test_verifier.py      # the six gates and their verdicts
python tests/test_memory.py        # schema, idempotency, NO-PII invariant
python tests/test_orchestrator.py  # end-to-end: sent / no_action / quarantine
```

## Layout
```
config.py              bands (B0-B5), band metadata, eligibility, consent gate, offers path
agent/eyes.py          score sources: DisputeFox webhook + CSV + monitoring API (assumed contract)
agent/brain.py         mid-score (median), band logic, crossing detection, select_offer, message copy
agent/offers.py        lending catalog: provider affiliate links + house fallback, eligibility
agent/verifier.py      gates 1-6 -> SEND / NO_ACTION / QUARANTINE
agent/hand.py          senders (console now; Twilio/SendGrid stubs)
agent/memory.py        SQLite: mid-score history, referrals (idempotency + attribution), quarantine log
agent/orchestrator.py  process_event (one event) + run (batch/reconciliation)
agent/providers.py     multi-tenant registry: per-provider id, webhook secret, isolated paths
run.py                 batch entrypoint;  webhook.py  single-event entrypoint
server.py              multi-tenant HTTP API (stdlib): register / save offers / intake
connect-server/        Node service (scaffold) that mints Zapier connect-links
data/                  sample client CSVs (3-bureau) + offers_sample.json
tests/                 brain / eyes / verifier / memory / offers / orchestrator / providers / server
```

## How a score crosses a band
Decision score is the **median of the three bureaus**. Bands B0–B5 split at
`[580, 620, 660, 700, 740]`; B0 (<580) has no product. A crossing is a strictly upward
move of the mid-score across a boundary vs. the client's last recorded mid; a multi-band
jump routes to the highest band and sends **one** referral. First sighting only records a baseline.

## Lending offers (how the provider gets paid)
Each provider's offers live in `data/offers_sample.json` (`OFFERS_PATH`). On a crossing the brain
picks the **highest-priority eligible** offer for the band and injects a unique `subid` for
attribution. Per offer:
- `affiliate_link` — the provider's **own** link; payout goes straight to them. Preferred.
- `house_link` — Rood Cab fallback, used until they have their own, still attributed via `subid`.
- `apply_link` — where they apply for their own affiliate id (shown in the setup UI only).
- `priority`, `bands`, `states`, `enabled`, `compliance` (`"respa"` for mortgage).

Set these up either by editing the JSON, or via the site's onboarding **"Add your lending offers"**
step (`site/`), which writes the same shape. A crossing with no eligible offer logs `[no-offer]`
and takes no action (add an offer for that tier to capture it).

## Backend & multi-tenant (server.py)
For many providers at once, `server.py` is a stdlib HTTP API where each provider is isolated —
their own memory DB (`data/state/<id>.db`) and offers (`data/offers/<id>.json`), tracked in
`agent/providers.py`. Run it with `python server.py` (port 8000). Routes:
- `POST /v1/providers` `{company}` → register; returns `provider_id`, a `webhook_url` + `secret`, and an `api_token`.
- `POST /v1/providers/{id}/offers` (Bearer `api_token`) → save that provider's offers.
- `POST /v1/intake/{webhook_path}` (header `X-RoodCab-Secret`) → process one DisputeFox event.
- `POST /v1/providers/{id}/zapier` (Bearer) → attach a Zapier connection (called by the connect-server).

The static site talks to this API when you set `API_BASE` in `site/app.js` (default "" = demo mode).
The one-click Zapier connect uses the **Node** `connect-server/` (scaffold — needs `npm install` +
Zapier credentials; see its README) via `CONNECT_LINK_ENDPOINT`.

## Going live
1. **Sensor / intake** — primary path is `webhook.py` (DisputeFox → Zapier). Add intake auth
   in `_verify_auth` and mount `handle_payload` in your web framework before exposing it.
   For the pull alternative, finish `MonitoringAPIScoreSource` against the **real** vendor docs
   (the in-file contract is assumed/unverified) and run with `SCORE_SOURCE=api`.
2. **Links** — set real tracked links:
   ```bash
   export LINK_B1="https://...credit-builder..."   LINK_B2="https://...subprime-auto..."
   export LINK_B3="https://...personal-loan..."    LINK_B4="https://...premium-card..."
   export LINK_B5="https://...mortgage-partner..."
   ```
3. **Eligibility / consent** — set `EXCLUDED_FOLDERS`; consent is assumed via the client
   agreement (`CONSENT_VIA_AGREEMENT=true`). To require per-client evidence, set
   `AGREEMENT_MARKER_FIELD` to the payload/CSV field that proves a signed agreement.
4. **Sender** — implement `TwilioSMSSender` or `SendGridEmailSender`, swap it into `run.py`
   /`webhook.py`, then `export DRY_RUN=false`.

Optional personalized messages: `pip install anthropic`, set `ANTHROPIC_API_KEY`, `export USE_CLAUDE=true`.

## Scheduling
Webhook handles real-time events. Run `run.py` on a cadence (e.g. cron `0 9 1 * *`) as a
reconciliation backstop for dropped webhooks.

## Compliance checklist (read before going live)
- [ ] Consent to lending-offer referrals captured in the **client agreement**, and not made a
      coercive condition of the credit-repair service itself (TCPA).
- [ ] SMS from a 10DLC/A2P-registered number (TCPA).
- [ ] Email has unsubscribe + physical address (CAN-SPAM).
- [ ] This app never pulls or stores credit-report data — scores + contact + consent only (FCRA).
- [ ] Mortgage band (B5) routed via licensed partner / marketing-fee, never per-referral (RESPA).
- [ ] Message copy makes no credit-outcome promises (CROA).
- [ ] No PII persisted to Memory; unique sub-id per send so payouts reconcile.

*Not legal advice — confirm structure with counsel before launch.*
