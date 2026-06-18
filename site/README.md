# Rood Cab — landing site

Static marketing + signup site for Rood Cab (backdoor revenue for credit-repair providers).
No build step, no dependencies. Plain HTML/CSS/JS.

## Run locally
Just open `index.html` in a browser, or serve the folder:
```bash
cd site
python -m http.server 8000   # then visit http://localhost:8000
```

## Files
```
index.html   page content (hero, what/how/compliance, signup form)
styles.css   dark fintech theme, responsive, reduced-motion aware
app.js        scroll-reveal + signup form handling
```

## Wiring the signup form
The form runs in **local-demo mode** by default: it validates, confirms, and stashes the
lead in the browser's `localStorage` (key `roodcab_signups`) so nothing is silently lost —
but it does not send anywhere.

To receive real leads, set `SIGNUP_ENDPOINT` at the top of `app.js` to a URL that accepts
a JSON `POST`. Options:
- A **Formspree** / **Basin** form endpoint (fastest, no code).
- A **Zapier catch-hook** that drops leads into a sheet / CRM / email.
- Your own endpoint (the agent already has `webhook.py` as a pattern for an authenticated intake).

The POST body looks like:
```json
{ "company": "...", "contact": "...", "email": "...", "phone": "...",
  "crm": "DisputeFox", "clients": "100–500", "notes": "...",
  "consent": true, "submitted_at": "2026-06-17T..." }
```

## Onboarding flow (after a verified signup)
On submit the form shows a short "Verifying…" gate, then reveals two ways to connect:

1. **Connect with Zapier (primary)** — one button that uses the Zapier **SDK connect-link**.
   The provider authorizes DisputeFox in a Zapier-hosted window and Zapier holds the
   credentials — no Zap to build, no webhook secret to copy. To make it real, set
   `CONNECT_LINK_ENDPOINT` in `app.js` to a small **Node** backend that calls the Zapier
   SDK (`@zapier/zapier-sdk`) to mint a connect link and returns `{ "connect_url": "..." }`.
   The SDK is Node-only, so it lives in that backend service, not in the Python agent.
2. **Manual webhook (fallback)** — the original two steps for CRMs not on the SDK path:
   build a "Client Update" Zap, then paste the generated Rood Cab webhook URL + signing
   secret (`X-RoodCab-Secret`) into a "Webhooks by Zapier → POST" action. This maps to the
   Python agent's `webhook.py` intake.

Event delivery stays push (Zapier → `webhook.py`) in both cases; the connect-link only
simplifies the *connection auth*. A pull-based `ZapierScoreSource` (SDK reads on a
schedule) is a possible future addition to `eyes.py`, not built yet.

Connections are recorded (demo mode → `localStorage` key `roodcab_connections`) with a
`method` of `zapier-sdk-connect-link` or `manual-webhook`.

After connecting, the provider hits **"Add your lending offers"** — the monetization step. It
renders a curated partner catalog (`CATALOG` in `app.js`, mirroring `data/offers_sample.json`)
where they paste **their own** affiliate link per partner (blank = Rood Cab house link used, still
attributed via `subid`), set priority, and enable/disable. Saving writes the same JSON shape the
Python agent's `agent/offers.py` loads — demo mode stores it under `localStorage` key
`roodcab_offers`. In production, POST it to a backend that updates the provider's `OFFERS_PATH`.

## Deploy
Any static host works — Netlify, Vercel, Cloudflare Pages, GitHub Pages, or an S3 bucket.
Drag-and-drop the `site/` folder, or point the host at it.

## Notes
- Copy is intentionally compliance-careful (no credit-outcome promises — CROA).
- Update the band/product labels in `index.html` (`.ladder`) to match your real `ROUTING`.
- The anagram brand is not spelled out on the public page by design.
