"""Provider registry: registration, per-provider isolation, offers persistence.

    python tests/test_providers.py
"""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import providers
from agent.offers import load_offers


def _b2_offer(aff=None):
    return {"id": "drivenow", "partner": "DriveNow Auto", "product": "auto loan",
            "bands": ["B2"], "affiliate_link": aff,
            "house_link": "https://go.roodcab.io/d?subid={subid}", "priority": 10}


def test_registration_and_isolation():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    try:
        a = providers.register("Acme Credit Repair")
        b = providers.register("Beta Repair")

        # distinct identities + isolated resource paths
        assert a["provider_id"] != b["provider_id"]
        assert a["secret"] != b["secret"] and a["api_token"] != b["api_token"]
        assert providers.db_path_for(a["provider_id"]) != providers.db_path_for(b["provider_id"])
        assert providers.offers_path_for(a["provider_id"]) != providers.offers_path_for(b["provider_id"])

        # lookups
        assert providers.get(a["provider_id"])["company"] == "Acme Credit Repair"
        assert providers.get_by_webhook_path(a["webhook_path"])["provider_id"] == a["provider_id"]
        assert providers.get_by_webhook_path("nope") is None

        # offers are per-provider: saving A's doesn't touch B's
        providers.save_offers(a["provider_id"], [_b2_offer(aff="https://drivenow.com/x?subid={subid}")])
        a_offers = load_offers(providers.offers_path_for(a["provider_id"]))
        b_offers = load_offers(providers.offers_path_for(b["provider_id"]))
        assert len(a_offers) == 1 and a_offers[0].affiliate_link
        assert b_offers == []                                  # B untouched
        print("ok test_registration_and_isolation")
    finally:
        os.environ.pop("DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_offers_validates():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    try:
        p = providers.register("Gamma")
        try:
            providers.save_offers(p["provider_id"], [{"id": "x"}])   # missing partner/product/bands
        except ValueError as e:
            assert "missing fields" in str(e)
            print("ok test_save_offers_validates")
            return
        raise AssertionError("expected ValueError on invalid offer")
    finally:
        os.environ.pop("DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_subid_index_routes_to_provider():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    try:
        providers.index_subid("C1-B2-202606", "acme-ab12")
        providers.index_subid("C9-B3-202606", "beta-cd34")
        assert providers.provider_for_subid("C1-B2-202606") == "acme-ab12"
        assert providers.provider_for_subid("C9-B3-202606") == "beta-cd34"
        assert providers.provider_for_subid("never-sent") is None
        print("ok test_subid_index_routes_to_provider")
    finally:
        os.environ.pop("DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_registration_and_isolation()
    test_save_offers_validates()
    test_subid_index_routes_to_provider()
    print("all tests passed")
