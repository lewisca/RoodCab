"""Entrypoint. Safe dry-run against sample data by default.

  python run.py                              # dry-run, sample baseline (no sends)
  CLIENTS_CSV=data/clients_next.csv python run.py   # second cycle (shows crossings)

To go live: set DRY_RUN=false, swap ConsoleSender for a real Sender below, and
point Eyes at MonitoringAPIScoreSource (SCORE_SOURCE=api) or the webhook path. See README.
"""
from config import DRY_RUN, DB_PATH, OFFERS_PATH
from agent.eyes import build_score_source
from agent.hand import ConsoleSender
from agent.memory import Memory
from agent.orchestrator import run
from agent.verifier import Verifier
from agent.offers import load_offers


def main():
    source = build_score_source()  # CSV by default; SCORE_SOURCE=api for the monitoring vendor
    sender = ConsoleSender()        # production: TwilioSMSSender(...) / SendGridEmailSender(...)
    memory = Memory(DB_PATH)
    verifier = Verifier()
    offers = load_offers(OFFERS_PATH)
    if not DRY_RUN and isinstance(sender, ConsoleSender):
        print("WARNING: DRY_RUN=false but sender is still ConsoleSender. "
              "Nothing real will send until you swap it in run.py.")
    print(f"Running score-router-agent (DRY_RUN={DRY_RUN}, offers={len(offers)}) ...")
    run(source, sender, memory, verifier, offers)


if __name__ == "__main__":
    main()
