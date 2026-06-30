"""Opt-out tokens + email hashing: round-trip, tamper-resistance, normalization.

    python tests/test_optout.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import optout


def test_email_hash_is_normalized_and_not_plaintext():
    h = optout.email_hash("Maria@Example.com ")
    assert h == optout.email_hash("maria@example.com")     # case/space-insensitive
    assert "@" not in h and len(h) == 64                   # sha-256 hex, no plaintext


def test_token_round_trip():
    tok = optout.make_token("acme-ab12", "maria@example.com")
    provider_id, eh = optout.parse_token(tok)
    assert provider_id == "acme-ab12"
    assert eh == optout.email_hash("maria@example.com")


def test_tampered_token_is_rejected():
    tok = optout.make_token("acme-ab12", "maria@example.com")
    assert optout.parse_token(tok[:-2] + ("aa" if tok[-2:] != "aa" else "bb")) is None
    assert optout.parse_token("not-a-real-token") is None
    assert optout.parse_token("") is None


def test_unsubscribe_url_carries_token():
    url = optout.unsubscribe_url("https://api.roodcab.com/unsubscribe", "acme-ab12", "maria@example.com")
    assert url.startswith("https://api.roodcab.com/unsubscribe?u=")
    token = url.split("u=", 1)[1]
    assert optout.parse_token(token)[0] == "acme-ab12"


if __name__ == "__main__":
    test_email_hash_is_normalized_and_not_plaintext()
    test_token_round_trip()
    test_tampered_token_is_rejected()
    test_unsubscribe_url_carries_token()
    print("all tests passed")
