# Deploying the Rood Cab API (`server.py`) to a public URL

Zapier can only send DisputeFox events to a **public HTTPS address** — it can't reach your
laptop. This guide puts `server.py` on the internet so it has a permanent URL like
`https://roodcab-api.onrender.com`. You do this **once**; it then serves every provider.

The server is Python **standard library only** (no framework), reads its port from `$PORT`,
and stores all state under `DATA_DIR`. That makes it simple to host — the only thing to get
right is a **persistent disk** so provider/offer/suppression/conversion data survives restarts.

---

## Option A — Render (recommended, simplest)

### 1. Push this repo to GitHub
Already done: <https://github.com/lewisca/RoodCab>.

### 2. Create the service from the blueprint
This repo includes `render.yaml`, so Render can set everything up automatically:

1. Go to <https://dashboard.render.com> → **New** → **Blueprint**.
2. Connect the `lewisca/RoodCab` repo. Render reads `render.yaml` and proposes a web service
   `roodcab-api` with a 1 GB disk and generated secrets.
3. Click **Apply**. First build/deploy takes a couple of minutes.
4. When it's live, copy the URL Render gives you, e.g. `https://roodcab-api.onrender.com`.

### 3. Set `PUBLIC_BASE_URL`
Render leaves this blank on purpose (you don't know the URL until step 2 finishes).
In the service → **Environment** → add:

```
PUBLIC_BASE_URL = https://roodcab-api.onrender.com
```

Save — Render redeploys. This makes the `webhook_url` / `offers_url` the API hands back point
at the real host.

### 4. Verify it's up
```
https://roodcab-api.onrender.com/healthz   →   {"ok": true}
```
That's it — the destination exists. Next is the per-provider **concierge Zap** step (separate
checklist) that points a provider's DisputeFox at this URL.

---

## Environment variables

| Var | Set it to | When |
|---|---|---|
| `PORT` | *(Render sets this automatically)* | — |
| `DATA_DIR` | `/var/data` (the disk mount) | from blueprint |
| `DRY_RUN` | `true` | now — keep true until email is ready |
| `PUBLIC_BASE_URL` | your `https://…onrender.com` URL | after first deploy |
| `UNSUBSCRIBE_SECRET` | *(auto-generated)* | from blueprint |
| `CONVERSIONS_SECRET` | *(auto-generated)* | from blueprint |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_EMAIL` | your email provider's SMTP relay | **only when going live with email** |
| `UNSUBSCRIBE_URL` | `https://…onrender.com/unsubscribe` | when going live |
| `PHYSICAL_ADDRESS` | your business postal address (CAN-SPAM) | when going live |

**Going live with email:** set the `SMTP_*` + `FROM_EMAIL` + `UNSUBSCRIBE_URL` + `PHYSICAL_ADDRESS`
vars, then flip `DRY_RUN=false`. Until then, the server processes events and logs what it *would*
send, but emails nothing.

---

## Why the persistent disk matters (don't skip it)

The API keeps state on the filesystem: registered providers, their offers, the opt-out
suppression list, sent-referral idempotency keys, and conversions — all under `DATA_DIR`.
On a host **without** a persistent disk, that filesystem is wiped on every redeploy/restart,
which would drop opt-outs and re-send referrals. The `render.yaml` mounts a 1 GB disk at
`/var/data` and sets `DATA_DIR=/var/data`, so it persists. (This is also why the recommended
plan is `starter`, not the free tier — the free tier has no disks and spins down after 15 min
of inactivity, which would make Zapier webhooks unreliable.)

---

## Alternatives (same idea, different host)

- **Railway** (<https://railway.app>) — New Project → Deploy from GitHub. Start command
  `python server.py`. Add a **Volume** mounted at `/var/data` and set `DATA_DIR=/var/data`.
  Set the same env vars. Railway provides HTTPS automatically.
- **Fly.io** (<https://fly.io>, CLI-based) — `fly launch` (Python), add a `fly volume` mounted at
  `/var/data`, set `DATA_DIR`, deploy. Good if you're comfortable with a CLI.

All three terminate HTTPS for you, so `server.py` keeps serving plain HTTP internally and you get
an `https://` URL — which is what Zapier needs.

---

## Security before real traffic
- The dev defaults for `UNSUBSCRIBE_SECRET` / `CONVERSIONS_SECRET` must be replaced — the blueprint
  auto-generates strong values, so just don't override them with the dev ones.
- Add real intake auth: `webhook.py`/`server.py` validate a per-provider `X-RoodCab-Secret` on the
  intake route (generated at registration), so a caller needs the secret to post events.
- Keep `DRY_RUN=true` until you've watched a few dry-run events and wired real email.
