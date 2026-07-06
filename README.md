# Rood Cab — a DisputeFox monetization feature

> **What this is:** Rood Cab is designed to become a **native feature inside DisputeFox**.
> It watches the credit scores DisputeFox already tracks and, the moment a client graduates
> into a higher lending tier, surfaces **one** compliant, matched financing referral — turning
> a credit-repair win into commission revenue for the provider, all in one place.

Watches credit-repair clients' three bureau scores and, when a client's **mid-score
crosses up** into a new band, sends **one** matched financing offer (tracked link) —
but only after a Verifier confirms the crossing is real, fresh, non-duplicate, eligible,
and compliant. Built as an **Eyes / Brain / Verifier / Hand / Memory** agent. Every event
resolves to **sent**, **no_action**, or **quarantine**.

Today it runs **standalone** (DisputeFox → Zapier → webhook) so it can be demoed and tested
end-to-end without DisputeFox's cooperation. The same core is built to drop **inside**
DisputeFox as a built-in feature — see [Built to become a DisputeFox feature](#built-to-become-a-disputefox-feature).

## Built to become a DisputeFox feature
The data source, the provider accounts, and the client comms all already live in DisputeFox.
So most of this repo is **glue that exists only because Rood Cab is currently external** — once
it's a native feature, that glue is replaced by DisputeFox's own primitives, and the
**decision + compliance core is the durable asset**.

| Area | Standalone today | Native DisputeFox feature |
|---|---|---|
| **Keep (the asset)** | `brain.py` (median, bands, crossing), `verifier.py` (gates 1–6), `offers.py` (offer selection + `subid` attribution), no-PII discipline, tests | Unchanged — this is the IP |
| **Ingest** | DisputeFox → Zapier ("New Report Imported" trigger) → `webhook.py` (`/v1/intake`, `X-RoodCab-Secret`) | Internal report-import event reads scores straight from DisputeFox's DB — no Zapier, no webhook, no secrets |
| **Onboarding / connect** | `connect-server/` (Zapier SDK), `site/` signup + connect steps | Removed — providers are already DisputeFox accounts; a settings toggle, not a separate site |
| **Tenancy** | `agent/providers.py` per-provider files + tokens | Reuse DisputeFox tenancy, auth/RBAC, and audit log |
| **Send** | `ConsoleSender` / Twilio + SendGrid stubs | DisputeFox's existing client comms + STOP/opt-out handling |
| **Consent (gate 5)** | `CONSENT_VIA_AGREEMENT` assumption | A real consent field captured at DisputeFox client onboarding |
| **Add for native** | — | Data-mapping adapter (their schema → `ClientScore`), conversion/payout callback against `subid`, in-app offers settings + earnings dashboard + quarantine-review UI |

**Pitch framing:** lead with the Verifier. The hard part of monetizing credit-repair clients
isn't the offer — it's the FCRA / TCPA / RESPA / CROA risk. Rood Cab is the guardrail that makes
it safe, already modeled on DisputeFox's own "New Report Imported" payload.

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
agent/hand.py          EMAIL delivery: ConsoleSender (preview) + SMTPEmailSender (live)
agent/memory.py        SQLite: mid-score history, referrals (idempotency + attribution), quarantine log
agent/orchestrator.py  process_event (one event) + run (batch/reconciliation)
agent/providers.py     multi-tenant registry: per-provider id, webhook secret, isolated paths
run.py                 batch entrypoint;  webhook.py  single-event entrypoint
server.py              multi-tenant HTTP API (stdlib): register / save offers / intake
connect-server/        Node service (scaffold) that mints Zapier connect-links
data/                  sample client CSVs (3-bureau) + offers_sample.json
tests/                 brain / eyes / verifier / memory / offers / orchestrator / providers / server / hand
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
- `GET /unsubscribe?u=<token>` / `POST /unsubscribe` → honor an opt-out (clickable link + RFC 8058
  one-click). The signed token (`agent/optout.py`) binds provider + email **hash** — no plaintext
  email in the URL. The address is added to that provider's suppression list and the pre-send check
  in the orchestrator skips it forever after.
- `POST` / `GET /v1/conversions` (secret via `X-RoodCab-Postback-Secret` header or `?key=`) → a lending
  partner reports a conversion, keyed by our `subid` (`{subid, status, amount, currency, partner_ref}`).
  The global `subid → provider` index (written when the referral fires) routes it to that provider's
  isolated `conversions` store. Idempotent on the partner's ref. This closes the payout loop.
- `GET /v1/providers/{id}/earnings` (Bearer) → that provider's conversions joined to the referral they
  came from (partner / band / client) + totals, so payouts reconcile.

The static site talks to this API when you set `API_BASE` in `site/app.js` (default "" = demo mode).
The one-click Zapier connect uses the **Node** `connect-server/` (scaffold — needs `npm install` +
Zapier credentials; see its README) via `CONNECT_LINK_ENDPOINT`.

## Going live
1. **Sensor / intake** — primary path is `webhook.py` (DisputeFox → Zapier). Add intake auth
   in `_verify_auth` and mount `handle_payload` in your web framework before exposing it.
   For the pull alternative, finish `MonitoringAPIScoreSource` against the **real** vendor docs
   (the in-file contract is assumed/unverified) and run with `SCORE_SOURCE=api`.
2. **Offers** — add each provider's real affiliate links (or the Rood Cab house link) in their
   offers catalog — by editing `data/offers_sample.json` / their `data/offers/<id>.json`, or via
   the site's "Add your lending offers" step. See [Lending offers](#lending-offers-how-the-provider-gets-paid).
3. **Eligibility / consent** — set `EXCLUDED_FOLDERS`; consent is assumed via the client
   agreement (`CONSENT_VIA_AGREEMENT=true`). To require per-client evidence, set
   `AGREEMENT_MARKER_FIELD` to the payload/CSV field that proves a signed agreement.
4. **Email** — referrals are emailed to the client's DisputeFox address. Configure an SMTP relay
   (SendGrid / Amazon SES / Mailgun / Postmark, etc.) and a CAN-SPAM footer, then go live:
   ```bash
   export SMTP_HOST=... SMTP_USER=... SMTP_PASSWORD=... FROM_EMAIL="offers@yourdomain.com"
   export UNSUBSCRIBE_URL="https://yourdomain.com/unsubscribe" PHYSICAL_ADDRESS="Your LLC, 123 Main St, City, ST 00000"
   export DRY_RUN=false   # ConsoleSender (preview) -> SMTPEmailSender (real)
   ```
   Authenticate your sending domain (SPF/DKIM/DMARC) for deliverability.

Optional personalized messages: `pip install anthropic`, set `ANTHROPIC_API_KEY`, `export USE_CLAUDE=true`.

## Scheduling
Webhook handles real-time events. Run `run.py` on a cadence (e.g. cron `0 9 1 * *`) as a
reconciliation backstop for dropped webhooks.

## Compliance checklist (read before going live)
- [ ] Consent to lending-offer referrals captured in the **client agreement**.
- [ ] Delivery is **email only** (to the client's DisputeFox address) — every email has a working
      unsubscribe (`/unsubscribe`, signed token → per-provider suppression list, checked before every
      send) + a valid physical postal address (CAN-SPAM). No SMS.
- [ ] Sending domain authenticated (SPF/DKIM/DMARC) for deliverability.
- [ ] This app never pulls or stores credit-report data — scores + contact + consent only (FCRA).
- [ ] Mortgage band (B5) routed via licensed partner / marketing-fee, never per-referral (RESPA).
- [ ] Message copy makes no credit-outcome promises (CROA).
- [ ] No PII persisted to Memory; unique sub-id per send so payouts reconcile.

*Not legal advice — confirm structure with counsel before launch.*
