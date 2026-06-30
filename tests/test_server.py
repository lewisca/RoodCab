"""API server integration: registration, authed offers save, multi-tenant intake, isolation.

Spins up the real stdlib server on an ephemeral port (no external deps, no mocking).

    python tests/test_server.py
"""
import os, sys, json, tempfile, shutil, threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _req(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _b2_offer():
    return {"id": "drivenow", "partner": "DriveNow Auto", "product": "a subprime auto loan",
            "bands": ["B2"], "affiliate_link": "https://drivenow.com/apply?aff=P123&subid={subid}",
            "priority": 20}


def _payload(cid, eq, ex, tu, updated, email="client@acme.com"):
    return {"client_id": cid, "first_name": "Test", "last_name": "User", "email": email,
            "credit_scores": {"equifax": eq, "experian": ex, "transunion": tu},
            "status": "Active Client", "folder": "In Progress", "updated_at": updated}


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    # import AFTER DATA_DIR is set
    from server import Handler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        # health
        assert _req("GET", base + "/healthz") == (200, {"ok": True})
        print("ok healthz")

        # register provider A
        code, a = _req("POST", base + "/v1/providers", {"company": "Acme Credit Repair"})
        assert code == 201 and a["provider_id"] and a["secret"] and a["api_token"]
        print("ok register")

        # save offers: bad token -> 401
        code, _ = _req("POST", base + f"/v1/providers/{a['provider_id']}/offers",
                       {"offers": [_b2_offer()]}, {"Authorization": "Bearer wrong"})
        assert code == 401
        # save offers: good token -> 200
        code, body = _req("POST", base + f"/v1/providers/{a['provider_id']}/offers",
                          {"offers": [_b2_offer()]}, {"Authorization": "Bearer " + a["api_token"]})
        assert code == 200 and body["saved"] == 1
        print("ok offers save (auth enforced)")

        # intake: bad secret -> 401. (webhook_url uses PUBLIC_BASE; hit the same path on the
        # actual test port instead.)
        intake = base + urlparse(a["webhook_url"]).path
        code, _ = _req("POST", intake, _payload("C1", 598, 600, 602, "2026-05-01T00:00:00Z"),
                       {"X-RoodCab-Secret": "nope"})
        assert code == 401
        # intake: baseline then crossing (good secret)
        h = {"X-RoodCab-Secret": a["secret"]}
        code, b1 = _req("POST", intake, _payload("C1", 598, 600, 602, "2026-05-01T00:00:00Z"), h)
        assert code == 200 and b1["outcome"] == "no_action"          # baseline
        code, b2 = _req("POST", intake, _payload("C1", 638, 640, 642, "2026-06-16T20:30:00Z"), h)
        assert code == 200 and b2["outcome"] == "sent"               # crossing -> offer fired
        print("ok intake (secret enforced; baseline -> sent)")

        # multi-tenant isolation: provider B, same client id, fresh state
        code, b = _req("POST", base + "/v1/providers", {"company": "Beta Repair"})
        code, bb = _req("POST", base + urlparse(b["webhook_url"]).path,
                        _payload("C1", 638, 640, 642, "2026-06-16T20:30:00Z"),
                        {"X-RoodCab-Secret": b["secret"]})
        # B has never seen C1 -> first sighting -> no_action (NOT 'sent'); A's state didn't leak
        assert bb["outcome"] == "no_action"
        print("ok multi-tenant isolation")

        # unsubscribe loop: an opted-out client is suppressed and never emailed
        from agent import optout
        code, c = _req("POST", base + "/v1/providers", {"company": "Gamma Repair"})
        _req("POST", base + f"/v1/providers/{c['provider_id']}/offers",
             {"offers": [_b2_offer()]}, {"Authorization": "Bearer " + c["api_token"]})
        email = "optout@acme.com"
        token = optout.make_token(c["provider_id"], email)
        # invalid token -> 400; valid one-click unsubscribe -> 200
        code, _ = _req("POST", base + "/unsubscribe?u=garbage")
        assert code == 400
        code, ub = _req("POST", base + "/unsubscribe?u=" + token)
        assert code == 200 and ub["unsubscribed"] is True
        # baseline + crossing for that email -> suppressed (no_action, not 'sent')
        hC = {"X-RoodCab-Secret": c["secret"]}
        intakeC = base + urlparse(c["webhook_url"]).path
        _req("POST", intakeC, _payload("CX", 598, 600, 602, "2026-05-01T00:00:00Z", email=email), hC)
        code, r = _req("POST", intakeC, _payload("CX", 638, 640, 642, "2026-06-16T20:30:00Z", email=email), hC)
        assert r["outcome"] == "no_action"
        print("ok unsubscribe suppresses future sends")

        print("all tests passed")
    finally:
        srv.shutdown()
        os.environ.pop("DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
