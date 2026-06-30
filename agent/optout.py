"""Opt-out plumbing: hashed email identity + signed, tamper-proof unsubscribe tokens.

The suppression list stores a **hash** of the email, never the address itself, so the
no-PII-at-rest discipline holds while still honoring CAN-SPAM opt-out. The unsubscribe
link carries a signed token encoding (provider_id, email_hash) so:
  * clicking it can't be forged or used to opt out an arbitrary address, and
  * the endpoint knows which provider's suppression list to write to,
all without putting the raw email in the URL.
"""
import base64
import hashlib
import hmac

import config


def email_hash(email):
    """Stable hash of a normalized email — the suppression-list key (no plaintext stored)."""
    norm = (email or "").strip().lower().encode("utf-8")
    return hashlib.sha256(norm).hexdigest()


def _sign(payload):
    return hmac.new(config.UNSUBSCRIBE_SECRET.encode("utf-8"),
                    payload.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def make_token(provider_id, email):
    """Signed, URL-safe token binding a provider to an email hash."""
    payload = f"{provider_id}:{email_hash(email)}"
    raw = f"{payload}:{_sign(payload)}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def parse_token(token):
    """Verify a token; return (provider_id, email_hash) or None if invalid/tampered."""
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode("utf-8")
        provider_id, eh, sig = raw.split(":")
    except (ValueError, TypeError, base64.binascii.Error):
        return None
    if not hmac.compare_digest(sig, _sign(f"{provider_id}:{eh}")):
        return None
    return provider_id, eh


def unsubscribe_url(base, provider_id, email):
    """Append a signed unsubscribe token to the base /unsubscribe URL."""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}u={make_token(provider_id, email)}"
