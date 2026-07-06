"""Conversions: recording partner postbacks, idempotency, and the earnings join.

    python tests/test_conversions.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.memory import Memory


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.unlink(path)
    return path


def test_conversion_joins_to_its_referral():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.record_referral("C1", "B2", "C1:B2", offer_id="drivenow",
                          partner="DriveNow Auto", product="auto loan", subid="C1-B2-202606")
        m.record_conversion("C1-B2-202606", status="funded", amount=125.50, partner_ref="cv_1")
        e = m.earnings()
        assert e["count"] == 1
        assert e["total_amount"] == 125.5
        c = e["conversions"][0]
        assert c["subid"] == "C1-B2-202606"
        assert c["status"] == "funded"
        assert c["partner"] == "DriveNow Auto" and c["band"] == "B2"   # joined to the referral
    finally:
        os.unlink(path)
    print("ok test_conversion_joins_to_its_referral")


def test_idempotent_on_partner_ref():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.record_conversion("C1-B2-202606", status="approved", amount=100, partner_ref="cv_1")
        m.record_conversion("C1-B2-202606", status="funded", amount=125, partner_ref="cv_1")  # same ref -> update
        e = m.earnings()
        assert e["count"] == 1                     # not duplicated
        assert e["total_amount"] == 125.0          # latest wins
        assert e["conversions"][0]["status"] == "funded"
    finally:
        os.unlink(path)
    print("ok test_idempotent_on_partner_ref")


def test_orphan_conversion_has_no_referral():
    path = _fresh_db()
    try:
        m = Memory(path)
        m.record_conversion("UNKNOWN-SUBID", amount=50)     # no matching referral
        e = m.earnings()
        assert e["count"] == 1
        assert e["conversions"][0]["partner"] is None       # LEFT JOIN -> null referral fields
    finally:
        os.unlink(path)
    print("ok test_orphan_conversion_has_no_referral")


if __name__ == "__main__":
    test_conversion_joins_to_its_referral()
    test_idempotent_on_partner_ref()
    test_orphan_conversion_has_no_referral()
    print("all tests passed")
