# Concierge onboarding: connect one provider's DisputeFox

The step-by-step you follow (with or for a pilot provider) to wire their DisputeFox to Rood Cab.
DisputeFox is Zapier-only, so the pipe is: **DisputeFox → Zapier ("New Report Imported") → Rood Cab webhook.**

**Before you start:**
- The API is deployed at a public URL (see [DEPLOY.md](DEPLOY.md)) — call it `$API` below.
- A **Zapier account with Premium apps** (Starter plan or higher). *"Webhooks by Zapier" is a
  Premium app — it is not on the free plan.*
- Keep `DRY_RUN=true` on the server for the first tests (crossings get logged, nothing is emailed).

---

## Step 1 — Register the provider in Rood Cab
This mints their unique webhook URL + secret + API token.

```bash
curl -X POST "$API/v1/providers" \
  -H "Content-Type: application/json" \
  -d '{"company":"Acme Credit Repair"}'
```
Response (save all three):
```json
{ "provider_id": "acme-credit-repair-xxxx",
  "webhook_url": "https://<host>/v1/intake/acme-credit-repair-yyyy",
  "secret": "rc_whsec_…",        // goes in the X-RoodCab-Secret header
  "api_token": "rc_tok_…" }      // for saving their offers
```

## Step 2 — Add their lending offers (before any real crossing)
Easiest: have them fill the site's **"Add your lending offers"** step. Or do it via API:
```bash
curl -X POST "$API/v1/providers/<provider_id>/offers" \
  -H "Authorization: Bearer <api_token>" -H "Content-Type: application/json" \
  -d '{"offers":[{"id":"drivenow","partner":"DriveNow Auto","product":"a subprime auto loan",
       "bands":["B2","B3"],"affiliate_link":"https://drivenow.com/apply?aff=ACME&subid={subid}",
       "priority":20}]}'
```
*(A crossing with no eligible offer just logs `[no-offer]` and does nothing — so set these first.)*

## Step 3 — Build the Zap: the trigger
In the provider's Zapier account:
1. **Create → Zap.**
2. **Trigger app:** DisputeFox.
3. **Trigger event:** **New Report Imported**.
4. **Connect** the provider's DisputeFox account.
5. **Test trigger** — Zapier pulls a sample client. Note the field names it shows (you'll map them next).

## Step 4 — The action: POST to Rood Cab
1. **Action app:** Webhooks by Zapier → **Event: POST**.
2. **URL:** the provider's `webhook_url` from Step 1.
3. **Payload type:** Json.
4. **Data** — add these keys and map each value to the matching DisputeFox trigger field:

   | Rood Cab key | DisputeFox field (map from the trigger sample) |
   |---|---|
   | `client_id` | the client's id |
   | `first_name`, `last_name` | client name |
   | `email` | client email |
   | `equifax`, `experian`, `transunion` | the three bureau scores |
   | `status` | client status (e.g. "Active Client") |
   | `folder` | client folder / stage |
   | `current_state` | client state (for offer eligibility; optional) |
   | `updated_at` | the report import timestamp |

   *(Scores can be flat like this — no nested JSON needed. They can arrive as text; Rood Cab coerces them.)*
5. **Headers:** add one — `X-RoodCab-Secret` = the provider's `secret` from Step 1.
6. **Test action.** A good result is HTTP **200** with `{"outcome":"no_action"}` — the first event is
   a **baseline** (records the score, doesn't fire). That's correct.
7. **Publish / turn the Zap on.**

## Step 5 — Verify
- The server logs (e.g. Render → Logs) show the event handled.
- A later import that raises the client's **median** across a band boundary logs `[fire] … -> B#`
  (in dry-run it's logged, not emailed).
- `GET $API/v1/providers/<provider_id>/earnings` (Bearer `api_token`) shows conversions once a partner reports them.

---

## Gotchas (read these)
- **Webhooks by Zapier needs a paid Zapier plan.** Confirm the account has Premium apps before you start.
- **Payload field names are provisional.** Map to whatever the real "New Report Imported" trigger
  actually outputs. **Open question:** it may return **one blended score** rather than three bureaus
  (its description says "credit score", singular). If so, tell the Rood Cab team — the parser
  (`agent/eyes.py`, `TODO(verify-live)`) is adjusted in minutes. It already accepts the three scores
  either flat (`equifax`) or nested (`credit_scores.equifax`).
- **Re-testing the same sample = `no_action`.** The freshness gate rejects an `updated_at` it has
  already seen, and the idempotency gate blocks a second referral for the same band. A real *new*
  import with a higher score is what triggers a send.
- **`DRY_RUN=true`** means crossings are logged but not emailed. Flip to `false` only after email is
  configured and you've watched a few dry-run events (see [DEPLOY.md](DEPLOY.md)).
