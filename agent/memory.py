"""Memory (state): persistent per-client history in SQLite.

State is what makes the agent fire on a CROSSING rather than on the current value,
and what enforces one-referral-per-band idempotency. Schema (CLAUDE.md §5):

  client_state    (client_id PK, last_mid_score, last_event_at)
  scores_history  (client_id, ts, eq, ex, tu, mid)
  referrals_sent  (client_id, band, product, ts, key UNIQUE)   -- key = "{client_id}:{band}"
  quarantine_log  (client_id, ts, reason)

DATA MINIMIZATION (compliance red line): NO PII is ever written here -- no name,
email, phone, DOB, SSN, or address. Only client_id, scores, bands, product labels,
idempotency keys, timestamps, and quarantine reasons. Callers must not pass PII in.
"""
import sqlite3
import datetime
from contextlib import contextmanager

_UNSET = object()   # sentinel so upsert can distinguish "skip" from "set to None"


def _now():
    return datetime.datetime.utcnow().isoformat()


class Memory:
    def __init__(self, path):
        self.path = path
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS client_state(
                client_id TEXT PRIMARY KEY,
                last_mid_score INTEGER,
                last_event_at TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS scores_history(
                client_id TEXT, ts TEXT, eq INTEGER, ex INTEGER, tu INTEGER, mid INTEGER)""")
            c.execute("""CREATE TABLE IF NOT EXISTS referrals_sent(
                client_id TEXT, band TEXT, offer_id TEXT, partner TEXT, product TEXT,
                subid TEXT, ts TEXT, key TEXT UNIQUE)""")
            c.execute("""CREATE TABLE IF NOT EXISTS quarantine_log(
                client_id TEXT, ts TEXT, reason TEXT)""")
            # Opt-out suppression: stores a HASH of the email (no plaintext), see agent/optout.py
            c.execute("""CREATE TABLE IF NOT EXISTS suppressions(
                email_hash TEXT PRIMARY KEY, ts TEXT)""")
            # Conversions reported by lending partners, keyed to a sent referral by subid.
            c.execute("""CREATE TABLE IF NOT EXISTS conversions(
                subid TEXT, status TEXT, amount REAL, currency TEXT, partner_ref TEXT,
                ts TEXT, key TEXT PRIMARY KEY)""")
            # Sends held by the safety leash (approval gate / daily cap). No PII.
            c.execute("""CREATE TABLE IF NOT EXISTS held_log(
                client_id TEXT, band TEXT, offer_id TEXT, partner TEXT, subid TEXT,
                reason TEXT, ts TEXT)""")

    def get(self, client_id):
        """Return the client's state dict (incl. referrals_sent list), or None."""
        with self._conn() as c:
            row = c.execute(
                "SELECT last_mid_score, last_event_at FROM client_state WHERE client_id=?",
                (client_id,)).fetchone()
            refs = c.execute(
                "SELECT band, offer_id, partner, product, subid, ts, key "
                "FROM referrals_sent WHERE client_id=?", (client_id,)).fetchall()
        if row is None and not refs:
            return None
        return {
            "client_id": client_id,
            "last_mid_score": row[0] if row else None,
            "last_event_at": row[1] if row else None,
            "referrals_sent": [
                {"band": b, "offer_id": oid, "partner": pn, "product": pr,
                 "subid": sid, "ts": t, "key": k}
                for (b, oid, pn, pr, sid, t, k) in refs
            ],
        }

    def upsert_state(self, client_id, last_mid_score=_UNSET, last_event_at=_UNSET):
        """Update only the fields provided; leave the rest untouched."""
        sets, vals = [], []
        if last_mid_score is not _UNSET:
            sets.append("last_mid_score"); vals.append(last_mid_score)
        if last_event_at is not _UNSET:
            sets.append("last_event_at"); vals.append(last_event_at)
        if not sets:
            return
        cols = ",".join(sets)
        placeholders = ",".join("?" for _ in sets)
        updates = ",".join(f"{s}=excluded.{s}" for s in sets)
        with self._conn() as c:
            c.execute(
                f"INSERT INTO client_state(client_id,{cols}) VALUES(?,{placeholders}) "
                f"ON CONFLICT(client_id) DO UPDATE SET {updates}",
                (client_id, *vals))

    def append_history(self, client_id, eq, ex, tu, mid):
        with self._conn() as c:
            c.execute("INSERT INTO scores_history(client_id,ts,eq,ex,tu,mid) "
                      "VALUES(?,?,?,?,?,?)", (client_id, _now(), eq, ex, tu, mid))

    def record_referral(self, client_id, band, key, offer_id="", partner="", product="", subid=""):
        """Persist a sent referral. UNIQUE(key) is the last-line idempotency backstop.

        `subid` is the attribution id the lending partner reports conversions against, so
        payouts reconcile to this provider/client/band.
        """
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO referrals_sent"
                "(client_id,band,offer_id,partner,product,subid,ts,key) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (client_id, band, offer_id, partner, product, subid, _now(), key))

    def has_referral(self, key):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM referrals_sent WHERE key=?",
                             (key,)).fetchone() is not None

    def record_quarantine(self, client_id, reason):
        with self._conn() as c:
            c.execute("INSERT INTO quarantine_log(client_id,ts,reason) VALUES(?,?,?)",
                      (client_id, _now(), reason))

    def suppress(self, email_hash):
        """Add an email hash to the opt-out list. Idempotent."""
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO suppressions(email_hash,ts) VALUES(?,?)",
                      (email_hash, _now()))

    def is_suppressed(self, email_hash):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM suppressions WHERE email_hash=?",
                             (email_hash,)).fetchone() is not None

    def record_conversion(self, subid, status="converted", amount=0.0, currency="USD",
                          partner_ref=""):
        """Record a partner-reported conversion. Idempotent on the partner's ref (or subid),
        so retries/status updates (approved -> funded) overwrite rather than duplicate."""
        key = partner_ref or subid
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO conversions"
                      "(subid,status,amount,currency,partner_ref,ts,key) VALUES(?,?,?,?,?,?,?)",
                      (subid, status, float(amount or 0), currency, partner_ref, _now(), key))

    def sends_today(self):
        """Count referrals sent today (UTC) — the daily-cap circuit breaker reads this."""
        today = datetime.datetime.utcnow().date().isoformat()
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM referrals_sent WHERE substr(ts,1,10)=?",
                             (today,)).fetchone()[0]

    def record_held(self, client_id, band, offer_id="", partner="", subid="", reason=""):
        """Log a send the leash held (approval gate / daily cap). No PII stored."""
        with self._conn() as c:
            c.execute("INSERT INTO held_log(client_id,band,offer_id,partner,subid,reason,ts) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (client_id, band, offer_id, partner, subid, reason, _now()))

    def earnings(self):
        """Conversions joined to the referral they came from (partner/band/client) + totals."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.subid, c.status, c.amount, c.currency, c.ts, "
                "r.partner, r.band, r.client_id "
                "FROM conversions c LEFT JOIN referrals_sent r ON r.subid = c.subid "
                "ORDER BY c.ts").fetchall()
        convs = [{"subid": s, "status": st, "amount": a, "currency": cur, "ts": t,
                  "partner": p, "band": b, "client_id": cid}
                 for (s, st, a, cur, t, p, b, cid) in rows]
        return {"count": len(convs),
                "total_amount": round(sum(x["amount"] or 0 for x in convs), 2),
                "conversions": convs}
