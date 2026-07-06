# CLAUDE.md — Credit-Repair → Lending Referral Agent

**Operating contract for an autonomous loop-with-verifier agent.** Read it fully
before changing code. When in doubt, quarantine — do not send.

---

## 1. Mission / definition of "done"
Watch each client's three bureau scores. When a client **crosses upward** into a
higher lending band, send **one** matched lending-product referral for that band —
but only after the Verifier confirms the crossing is real, fresh, non-duplicate,
eligible, and compliant. Every event ends in exactly one of three states:
**sent**, **no_action**, or **quarantine**, and is written to Memory.

## 2. Architecture — Eyes / Brain / Verifier / Hand / Memory
```
DisputeFox "New Report Imported"  ──Zapier──▶  webhook.py
                                              │
   EYES ──▶ BRAIN ──▶ VERIFIER ──▶ HAND      (one event = one iteration)
  ingest   derive    gates 1–6    send
  +sanity  crossing  (2nd pass)   referral
            └──────── MEMORY ────────┘   (quarantine / no_action also written)
```
- **Eyes** — `agent/eyes.py` — perceive scores. `DisputeFoxPayloadSource` (one webhook
  event, primary), `CSVScoreSource` (batch/reconciliation), `MonitoringAPIScoreSource`
  (pull sensor; **assumed contract, unverified** — see the docstring before relying on it).
- **Brain** — `agent/brain.py` — `mid_score` (median), `band_for`, `propose`, `select_offer`, message copy.
- **Offers** — `agent/offers.py` — per-provider lending catalog (affiliate links + house fallback);
  the monetization layer the Brain selects from.
- **Verifier** — `agent/verifier.py` — the load-bearing 2nd pass; gates 1–6 → verdict.
- **Hand** — `agent/hand.py` — EMAIL delivery to the client's DisputeFox address (no SMS).
  `ConsoleSender` (dry-run preview) + `SMTPEmailSender` (live); `build_sender()` picks by `DRY_RUN`.
- **Memory** — `agent/memory.py` — SQLite; per-client mid-score history + referrals + quarantine log.
- **Orchestrator** — `agent/orchestrator.py` — `process_event` (one event) + `run` (batch).
- **Config** — `config.py` — bands, routing, eligibility, consent gate, links (via env).

The Verifier between Brain and Hand is the load-bearing half of the autonomy: a second
pass confirming a referral before anything irreversible fires is what makes the loop
safe to leave running.

## 3. Data contract — DisputeFox "New Report Imported" payload
Fields the agent **uses**: `client_id`, `credit_scores{equifax,experian,transunion}`,
`updated_at`, `status`, `folder`, and (optional) a configured agreement marker.
Fields the agent must **never read or persist**: name, email, phones, `date_of_birth`,
`ssn_hidden`, address. Contact is used in-flight by Hand only; never written to Memory.

## 4. Decision logic (Brain)
- **Decision score** = `mid_score = median(equifax, experian, transunion)`.
- **Bands B0–B5**, boundaries `[580, 620, 660, 700, 740]` (`config.BANDS`). B0 (<580) has
  no lending product.
- **Crossing** = `last_mid < boundary ≤ new_mid` (strictly upward vs. Memory's last mid).
  A multi-boundary jump routes to the **highest** band reached and sends **one** referral.
  First-ever sighting (`last_mid is None`) records a baseline and does **not** fire.

## 4a. Offers / monetization (the payout core)
On a confirmed crossing the Brain calls `select_offer(client, band, offers)` and surfaces the
provider's **highest-priority eligible** offer for that band. Each offer (`data/offers_sample.json`,
`OFFERS_PATH`) carries links tried in order: (1) the provider's own `affiliate_link` (payout goes
straight to them), (2) a Rood Cab `house_link` fallback still attributed via `subid` until they
have their own, (3) `apply_link` (UI only — where they get an affiliate id). Eligibility = enabled
AND band match AND usable link AND `serves_state(client.state)`. The chosen link gets the unique
`subid` (client+band+month) injected for conversion attribution; partner/offer/subid are recorded
in `referrals_sent`. A crossing with **no eligible offer** → `no_action` (logged `[no-offer]`).
RESPA: B5/mortgage offers are `compliance:"respa"` (licensed-partner/marketing-fee), not per-referral.

## 5. Memory schema (data-minimized — NO PII)
`client_state(client_id, last_mid_score, last_event_at)` ·
`scores_history(client_id, ts, eq, ex, tu, mid)` ·
`referrals_sent(client_id, band, product, ts, key)` where `key = "{client_id}:{band}"` ·
`quarantine_log(client_id, ts, reason)` · `suppressions(email_hash, ts)` — opt-out list keyed by a
HASH of the email (never plaintext) · `conversions(subid, status, amount, currency, partner_ref, ts, key)`
— partner-reported conversions, joined to `referrals_sent` by `subid` for payout reconciliation.
No name/email/phone/DOB/SSN/address — ever. The orchestrator checks `is_suppressed(hash(email))`
before every send; `/unsubscribe` (server.py) populates suppressions; `/v1/conversions` populates
conversions (routed by the global `subid → provider` index).

## 6. Verifier gates (any hard-fail → quarantine)
1. **Sanity / freshness** — every bureau ∈ [300, 850] (reject 0/null/missing → quarantine);
   reject `updated_at ≤ last processed` → **no_action** (stale/replayed duplicate).
2. **Real upward crossing** — else **no_action**.
3. **Idempotency** — `{client_id}:{band}` not already sent, else **no_action**.
4. **Eligibility** — `status == ELIGIBLE_STATUS` AND `folder ∉ EXCLUDED_FOLDERS`.
5. **Compliance — HARD STOP.** Documented permissible purpose / referral consent must
   exist. Consent is captured in the **client agreement** (`CONSENT_VIA_AGREEMENT`); if
   `AGREEMENT_MARKER_FIELD` is set, a per-client evidence marker is also required. Never
   inferred silently — the assumption is an explicit, auditable config switch.
6. **Independent re-derivation** — Verifier recomputes mid + band from raw scores and
   confirms it equals Brain's selection. Mismatch → quarantine.

> Verdict nuance: the three idempotent no-ops (stale replay, no crossing, already sent)
> resolve to **no_action**, not quarantine, so retries don't flood human review. Gates
> 1 (bad scores), 4, 5, 6 → **quarantine**. See the mapping table in `verifier.py`.
> On quarantine, `last_event_at` advances (stops retry re-quarantine) but `last_mid_score`
> is **preserved**, so a real crossing blocked on eligibility/consent re-fires later.

## 7. The loop
- **Event path (primary):** DisputeFox → Zapier → `webhook.py` → one `process_event`.
- **Batch / reconciliation:** `run.py` over a CSV (or the monitoring API) — backstop for
  dropped webhooks and clients sitting just under a boundary.

## 8. Config to set before first run
- [ ] Provider offers in `data/offers_sample.json` (`OFFERS_PATH`) → real partners + affiliate links + priorities
- [ ] `EXCLUDED_FOLDERS` (eligibility, gate 4)
- [ ] `AGREEMENT_MARKER_FIELD` if you want per-client consent evidence (gate 5)
- [ ] Webhook intake auth (`webhook.py._verify_auth`) + hosting
- [ ] Reconciliation cadence

## 9. Red lines — never do these
- Never send with the compliance gate (gate 5) unset/unverifiable.
- Never persist PII to Memory.
- Never act on downward / in-band / out-of-range / zeroed scores.
- Never send a duplicate referral for a band already in `referrals_sent`.
- Never treat a first-ever sighting as a crossing.
- When uncertain, quarantine. A missed referral is recoverable; a wrongful one may not be.

## 10. Compliance constraints (keep intact in any change)
- **CAN-SPAM**: delivery is email only (to the client's DisputeFox address) — every email needs a
  working unsubscribe link + a valid physical postal address. Agreement consent must not be a
  coercive condition of the credit-repair service itself.
- **FCRA**: the credit pull stays on the lender/aggregator side; this agent never pulls or
  stores credit-report line items, tradelines, or dispute data — scores + contact + consent only.
- **RESPA**: the mortgage band (B5) cannot pay a per-referral fee — licensed partner or
  bona-fide marketing-fee structure. See `compliance_note` in `config.ROUTING`.
- **CROA**: message copy makes no credit-outcome promises or guarantees.

## 11. Run / test / conventions
- `python run.py` — dry-run baseline; `CLIENTS_CSV=data/clients_next.csv python run.py` — crossings.
- `echo '<payload>' | python webhook.py` — one-shot event smoke test.
- `python server.py` — multi-tenant HTTP API (register / save offers / per-provider intake).
  Each provider is isolated: own memory `data/state/<id>.db` + offers `data/offers/<id>.json`
  (registry: `agent/providers.py`). One-click Zapier connect is the Node `connect-server/` (scaffold).
- `python tests/test_{brain,eyes,verifier,memory,offers,orchestrator,providers,server}.py` — all suites.
- Standard library first; external deps optional and guarded. Sources and Senders are ABCs —
  add providers as subclasses, never inline into the orchestrator.
