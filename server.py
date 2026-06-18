"""Rood Cab API (standard library only): multi-tenant intake + provider config.

Routes
  GET  /healthz
  POST /v1/providers                       {company}              -> register a provider
  POST /v1/providers/{id}/offers           (Bearer api_token)     -> save that provider's offers
  POST /v1/intake/{webhook_path}           (X-RoodCab-Secret)     -> process one DisputeFox event

Every event/config call is scoped to ONE provider and uses that provider's ISOLATED
memory ({DATA_DIR}/state/{id}.db) and offers ({DATA_DIR}/offers/{id}.json). See
agent/providers.py. Run:  python server.py   (PORT env, default 8000)

This is the real backend the static site (site/) talks to: signup -> /v1/providers,
"save offers" -> /v1/providers/{id}/offers, and the provider's Zap posts to /v1/intake/{path}.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from agent import providers
from agent.eyes import DisputeFoxPayloadSource
from agent.hand import ConsoleSender
from agent.memory import Memory
from agent.offers import load_offers
from agent.orchestrator import process_event
from agent.verifier import Verifier

PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")


def process_event_for(provider, payload, sender=None):
    """Run one event through the pipeline using the provider's isolated resources."""
    memory = Memory(providers.db_path_for(provider["provider_id"]))
    offers = load_offers(providers.offers_path_for(provider["provider_id"]))
    (client,) = DisputeFoxPayloadSource(payload).fetch()
    return process_event(client, Verifier(), sender or ConsoleSender(), memory, offers)


class Handler(BaseHTTPRequestHandler):
    # --- helpers ----------------------------------------------------------
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")   # static site is a different origin
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-RoodCab-Secret")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None

    def _bearer_ok(self, rec):
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and auth[7:] == rec["api_token"]

    def log_message(self, *args):
        pass   # quiet

    # --- routes -----------------------------------------------------------
    def do_OPTIONS(self):                      # CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-RoodCab-Secret")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path == "/healthz":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        body = self._read_json()
        if body is None:
            return self._send(400, {"error": "invalid json"})

        # POST /v1/providers  -> register
        if parts == ["v1", "providers"]:
            company = (body.get("company") or "").strip()
            if not company:
                return self._send(400, {"error": "company is required"})
            rec = providers.register(company)
            return self._send(201, {
                "provider_id": rec["provider_id"],
                "webhook_url": f'{PUBLIC_BASE}/v1/intake/{rec["webhook_path"]}',
                "secret": rec["secret"],
                "api_token": rec["api_token"],
                "offers_url": f'{PUBLIC_BASE}/v1/providers/{rec["provider_id"]}/offers',
            })

        # POST /v1/providers/{id}/offers  -> save offers (auth)
        if len(parts) == 4 and parts[:2] == ["v1", "providers"] and parts[3] == "offers":
            rec = providers.get(parts[2])
            if not rec:
                return self._send(404, {"error": "unknown provider"})
            if not self._bearer_ok(rec):
                return self._send(401, {"error": "bad or missing api token"})
            try:
                saved = providers.save_offers(parts[2], body.get("offers"))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, {"saved": saved})

        # POST /v1/providers/{id}/zapier  -> attach a Zapier connection (auth)
        # Called by the Node connect-server after the provider authorizes DisputeFox.
        if len(parts) == 4 and parts[:2] == ["v1", "providers"] and parts[3] == "zapier":
            rec = providers.get(parts[2])
            if not rec:
                return self._send(404, {"error": "unknown provider"})
            if not self._bearer_ok(rec):
                return self._send(401, {"error": "bad or missing api token"})
            cid = body.get("connection_id")
            providers.attach_zapier(parts[2], cid)
            return self._send(200, {"attached": cid})

        # POST /v1/intake/{webhook_path}  -> process one event (secret)
        if len(parts) == 3 and parts[:2] == ["v1", "intake"]:
            rec = providers.get_by_webhook_path(parts[2])
            if not rec:
                return self._send(404, {"error": "unknown intake path"})
            if self.headers.get("X-RoodCab-Secret") != rec["secret"]:
                return self._send(401, {"error": "bad webhook secret"})
            outcome = process_event_for(rec, body)
            return self._send(200, {"outcome": outcome})

        self._send(404, {"error": "not found"})


def main():
    port = int(os.getenv("PORT", "8000"))
    print(f"Rood Cab API on :{port}  (DATA_DIR={providers.data_dir()})")
    ThreadingHTTPServer(("", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
