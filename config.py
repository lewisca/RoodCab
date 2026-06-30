"""Configuration: score bands, routing map, message templates, runtime settings.

Everything tunable lives here. The routing map mirrors the Routing Map tab of the
back-door model spreadsheet. Real tracked links come from env vars (see README).

CONFIGURE before first run (see CLAUDE.md §8):
  * ROUTING tiers -> your real matched products + economics
  * EXCLUDED_FOLDERS -> the DisputeFox folders that make a client ineligible
  * AGREEMENT_MARKER_FIELD -> the payload field that evidences signed consent (gate 5)
"""
import os

# --- runtime flags -----------------------------------------------------------
DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"        # safe default
USE_CLAUDE = os.getenv("USE_CLAUDE", "false").lower() == "true"  # personalized msgs
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
SEND_COOLDOWN_DAYS = int(os.getenv("SEND_COOLDOWN_DAYS", "30"))  # frequency cap
DB_PATH = os.getenv("DB_PATH", "state.db")

# --- score bands (ordered low -> high): (name, min_score, max_score) ---------
# Decision score is the MID-SCORE = median(equifax, experian, transunion).
# Boundaries [580, 620, 660, 700, 740]; an upward crossing of any boundary fires.
BANDS = [
    ("B0", 300, 579),   # keep repairing -- no lending product
    ("B1", 580, 619),
    ("B2", 620, 659),
    ("B3", 660, 699),
    ("B4", 700, 739),
    ("B5", 740, 850),
]

# --- band metadata -----------------------------------------------------------
# The actual lending products + tracked links live in the provider's OFFERS catalog
# (see agent/offers.py and OFFERS_PATH below) -- the Brain picks the best offer per
# band. Here we keep only per-band display + compliance metadata. B0 has no product;
# a crossing never targets it.
ROUTING = {
    "B0": {"label": "Under 580", "purpose": "build"},
    "B1": {"label": "580-619",   "purpose": "build"},
    "B2": {"label": "620-659",   "purpose": "monetize"},
    "B3": {"label": "660-699",   "purpose": "monetize"},
    "B4": {"label": "700-739",   "purpose": "monetize"},
    "B5": {"label": "740+",      "purpose": "monetize",
           # RESPA: mortgage referral fees are restricted. Mortgage offers must route to
           # a licensed partner / bona-fide marketing fee -- never a per-referral kickback.
           "compliance_note": "RESPA-restricted: use licensed partner / marketing-fee structure."},
}

# --- offers catalog (monetization) -------------------------------------------
# Per-provider affiliate offers. Each provider supplies their own affiliate links;
# a Rood Cab house_link is the fallback until they have their own. See agent/offers.py.
OFFERS_PATH = os.getenv("OFFERS_JSON", "data/offers_sample.json")

# --- eligibility (Verifier gate 4) -------------------------------------------
ELIGIBLE_STATUS = os.getenv("ELIGIBLE_STATUS", "Active Client")
# CONFIGURE: DisputeFox folders that make a client ineligible for offers.
EXCLUDED_FOLDERS = {
    f.strip() for f in os.getenv("EXCLUDED_FOLDERS", "").split(",") if f.strip()
}

# --- consent / permissible purpose (Verifier gate 5) -------------------------
# Consent to lending offers is captured in the credit-repair client agreement, so
# there is no per-client consent toggle. This flag is the documented, auditable
# assertion of that fact -- the gate stays real (and re-tightenable) rather than
# being inferred silently in code. Set CONSENT_VIA_AGREEMENT=false to hard-stop
# all sends (e.g. if the agreement language is ever in question).
CONSENT_VIA_AGREEMENT = os.getenv("CONSENT_VIA_AGREEMENT", "true").lower() == "true"
# Optional per-client evidence: if set, names a payload/CSV field that must be
# non-empty for the client (e.g. "agreement_signed_at" or "agreement_version").
# Empty (default) = trust CONSENT_VIA_AGREEMENT alone, no per-client marker check.
AGREEMENT_MARKER_FIELD = os.getenv("AGREEMENT_MARKER_FIELD", "").strip()

# --- score sanity (Verifier gate 1) ------------------------------------------
SCORE_MIN, SCORE_MAX = 300, 850

# --- delivery: EMAIL ONLY ----------------------------------------------------
# Referrals are emailed to the client's email already on file in DisputeFox
# (ClientScore.email, in-flight only, never stored). No SMS.
SENDER = os.getenv("SENDER", "smtp").strip().lower()   # real sender when DRY_RUN is false
FROM_EMAIL = os.getenv("FROM_EMAIL", "offers@roodcab.example")
FROM_NAME = os.getenv("FROM_NAME", "Rood Cab")
EMAIL_SUBJECT = os.getenv("EMAIL_SUBJECT", "A financing option matched to your new credit tier")

# CAN-SPAM: a commercial email needs a working opt-out AND a valid physical postal address.
UNSUBSCRIBE_URL = os.getenv("UNSUBSCRIBE_URL", "https://roodcab.example/unsubscribe")
PHYSICAL_ADDRESS = os.getenv("PHYSICAL_ADDRESS", "Rood Cab, 123 Example St, Suite 100, Miami, FL 33132")

# SMTP relay — works with SendGrid / Amazon SES / Mailgun / Postmark / etc.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"

# Appended to every email body (with the unsubscribe link + address) — channel-neutral
# wording; the opt-out mechanism is added by the email footer, not baked into the pitch.
CONSENT_LINE = ("You're receiving this email because lending-offer referrals are part of "
                "your credit-repair client agreement with us.")
