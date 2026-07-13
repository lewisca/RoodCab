"""Ops alerting: surface quarantined + held events to a human.

Always logs an [ALERT:*] line; if OPS_ALERT_URL is set, best-effort POSTs a JSON
notification (e.g. to a Slack/ops webhook). Carries NO PII -- only client_id, band,
and the reason. Never blocks or fails the pipeline: alerting errors are swallowed.
"""
import json
import urllib.request

import config


def notify(kind, provider_id, client_id, band, reason):
    print(f"[ALERT:{kind}] provider={provider_id} client={client_id} band={band} :: {reason}")
    if not config.OPS_ALERT_URL:
        return
    try:
        body = json.dumps({
            "kind": kind, "provider_id": provider_id, "client_id": client_id,
            "band": band, "reason": reason,
        }).encode("utf-8")
        req = urllib.request.Request(
            config.OPS_ALERT_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass   # alerting is best-effort; never let it break the loop
