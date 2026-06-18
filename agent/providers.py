"""Provider registry (multi-tenant): who's onboarded, and their isolated resources.

Each provider (a credit-repair company / tenant) gets:
  * a unique provider_id
  * a webhook intake path + secret  (DisputeFox -> Zapier -> /v1/intake/<path>)
  * an api_token for authenticated config calls (saving offers)
  * an ISOLATED SQLite memory file   -> {DATA_DIR}/state/{id}.db
  * an ISOLATED offers catalog file  -> {DATA_DIR}/offers/{id}.json

So one provider's clients, scores, and affiliate links can never mix with another's.

Stored as JSON at {DATA_DIR}/providers.json. DATA_DIR is read at call time (default
"data") so tests can point it at a temp dir.

SECURITY: secrets/tokens are plaintext here for the dev scaffold. PRODUCTION must hash
them at rest and never hand the api_token to a browser (use a server-side session).
"""
import json
import os
import re
import secrets
import datetime


def data_dir():
    return os.getenv("DATA_DIR", "data")


def _providers_file():
    return os.path.join(data_dir(), "providers.json")


def state_dir():
    return os.path.join(data_dir(), "state")


def offers_dir():
    return os.path.join(data_dir(), "offers")


def db_path_for(provider_id):
    return os.path.join(state_dir(), f"{provider_id}.db")


def offers_path_for(provider_id):
    return os.path.join(offers_dir(), f"{provider_id}.json")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "provider").lower()).strip("-")[:24] or "provider"


def _load():
    try:
        with open(_providers_file(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(providers):
    os.makedirs(data_dir(), exist_ok=True)
    with open(_providers_file(), "w", encoding="utf-8") as f:
        json.dump(providers, f, indent=2)


def _now():
    return datetime.datetime.utcnow().isoformat()


def register(company):
    """Create a provider, initialize an empty offers file, return the full record."""
    providers = _load()
    pid = f"{_slug(company)}-{secrets.token_hex(3)}"
    rec = {
        "provider_id": pid,
        "company": company,
        "webhook_path": f"{_slug(company)}-{secrets.token_hex(4)}",
        "secret": "rc_whsec_" + secrets.token_hex(16),     # validates inbound webhooks
        "api_token": "rc_tok_" + secrets.token_hex(16),     # authorizes config calls
        "zapier_connection_id": None,
        "created_at": _now(),
    }
    providers[pid] = rec
    _save(providers)
    os.makedirs(state_dir(), exist_ok=True)    # isolated memory dir exists before first event
    _init_offers_file(pid)
    return rec


def _init_offers_file(provider_id):
    os.makedirs(offers_dir(), exist_ok=True)
    path = offers_path_for(provider_id)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"provider_id": provider_id, "offers": []}, f, indent=2)


def get(provider_id):
    return _load().get(provider_id)


def get_by_webhook_path(path):
    for rec in _load().values():
        if rec["webhook_path"] == path:
            return rec
    return None


def attach_zapier(provider_id, connection_id):
    providers = _load()
    if provider_id in providers:
        providers[provider_id]["zapier_connection_id"] = connection_id
        _save(providers)
    return providers.get(provider_id)


def save_offers(provider_id, offers):
    """Validate + persist a provider's offers to their isolated catalog file."""
    if not isinstance(offers, list):
        raise ValueError("offers must be a list")
    for o in offers:
        missing = [k for k in ("id", "partner", "product", "bands") if k not in o]
        if missing:
            raise ValueError(f"offer missing fields {missing}")
    os.makedirs(offers_dir(), exist_ok=True)
    with open(offers_path_for(provider_id), "w", encoding="utf-8") as f:
        json.dump({"provider_id": provider_id, "offers": offers}, f, indent=2)
    return len(offers)
