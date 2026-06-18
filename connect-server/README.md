# Rood Cab connect-server (Node)

Mints **Zapier connect-links** so a provider authorizes DisputeFox in one click, instead of
hand-building a Zap and pasting a webhook secret. This is a **separate Node service** because
the Zapier SDK (`@zapier/zapier-sdk`) is Node-only — it sits *beside* the Python agent/API,
not inside it.

```
site (Connect button)  ──POST /connect-link──▶  connect-server ──Zapier SDK──▶ connect URL
provider authorizes DisputeFox in Zapier's hosted window
Zapier ──redirect──▶  GET /connected  ──POST /v1/providers/{id}/zapier──▶  Python API (server.py)
```

## Status: scaffold
The two SDK calls in `server.js` are marked `TODO(real-sdk)` and currently return a
clearly-labelled **placeholder** URL so the whole flow is visible end-to-end. It is **not a
working Zapier integration yet** — wire the real calls against <https://docs.zapier.com/sdk>.
This service is not run or tested in the agent's Python test suite.

## Run
```bash
cd connect-server
npm install
npx zapier-sdk login           # use --non-interactive in CI; stores Zapier credentials
ROODCAB_API=http://localhost:8000 PUBLIC_BASE=http://localhost:8787 npm start
```

## Endpoints
- `POST /connect-link` — body `{ provider_id, api_token, app }` → `{ connect_url }`.
- `GET /connected` — Zapier's redirect target; attaches the connection to the provider via the
  Python API's `POST /v1/providers/{id}/zapier`.

## Wire the site to it
In `site/app.js`, set `CONNECT_LINK_ENDPOINT` to `http://<this-host>:8787/connect-link`. The
site opens the returned `connect_url`; on return, the provider is connected.

## What to finish before production
1. Replace both `TODO(real-sdk)` blocks with real `@zapier/zapier-sdk` connect-link calls.
2. Verify the connection server-side (don't trust query params) before calling the API.
3. Don't pass `api_token` through the browser/redirect — use a short-lived signed state value.
