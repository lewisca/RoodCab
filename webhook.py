"""Webhook intake (primary path): DisputeFox -> Zapier -> here -> one iteration.

This is the transport-thin entry point. Zapier POSTs the "New Report Imported" payload
(CLAUDE.md §3) and we run exactly one event through the pipeline.

`handle_payload` is framework-agnostic so you can mount it under whatever host you
deploy to (Flask/FastAPI/Lambda/Azure Function). For a quick local smoke test:

    echo '{"client_id":"C001","credit_scores":{"equifax":638,"experian":640,
      "transunion":642},"status":"Active Client","folder":"In Progress",
      "updated_at":"2026-06-16T20:30:00Z"}' | python webhook.py

CONFIGURE before exposing publicly (CLAUDE.md §8):
  * Intake auth -- verify a shared secret / Zapier signature BEFORE handle_payload.
    Do NOT run an open, unauthenticated endpoint.
  * Hosting -- wire handle_payload into your web framework's POST route.
"""
import json
import sys

from config import DB_PATH, OFFERS_PATH
from agent.eyes import DisputeFoxPayloadSource
from agent.hand import build_sender
from agent.memory import Memory
from agent.orchestrator import process_event
from agent.verifier import Verifier
from agent.offers import load_offers


def handle_payload(payload, memory=None, sender=None, verifier=None, offers=None):
    """Process one DisputeFox payload. Returns the outcome str (sent/no_action/quarantine).

    Pass in shared memory/sender/verifier/offers in a long-lived server; defaults are
    fine for one-shot invocations.
    """
    memory = memory or Memory(DB_PATH)
    sender = sender or build_sender()
    verifier = verifier or Verifier()
    offers = offers if offers is not None else load_offers(OFFERS_PATH)
    (client,) = DisputeFoxPayloadSource(payload).fetch()
    return process_event(client, verifier, sender, memory, offers)


def _verify_auth(_payload):
    # TODO: validate a shared secret / Zapier signature here before processing.
    return True


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    if not _verify_auth(payload):
        print("unauthorized"); sys.exit(1)
    outcome = handle_payload(payload)
    print(f"outcome={outcome}")
