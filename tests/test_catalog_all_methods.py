"""New defaults: instant catalog quotes + every supplier method offered, chosen by method id."""
import json

import pytest

from app.checkout_intl import catalog, countries, rates
from app.checkout_intl import transaction as txn
from conftest import make_product, valid_address


@pytest.fixture(autouse=True)
def new_defaults(monkeypatch):
    monkeypatch.delenv("INTL_TIER_EXPOSURE", raising=False)      # default = all
    monkeypatch.delenv("INTL_QUOTE_SOURCE", raising=False)       # default = catalog
    monkeypatch.setattr("app.routes.payments._live_stock_check_many", lambda pairs: None)
    catalog.reset_cache()


@pytest.fixture()
def no_supplier_calls(monkeypatch):
    calls = []

    def boom(*a):
        calls.append(a)
        raise AssertionError("live Silverbene lookup must not run for catalogued countries")
    monkeypatch.setattr(txn, "default_rate_fetcher", boom)
    return calls


def _delivery(client, country, **addr):
    r = client.post("/checkout/delivery", json={"address": valid_address(country, **addr),
                                                "items": [{"product_id": 1, "quantity": 1}]})
    assert r.status_code == 200, r.text
    return client.get(f"/checkout/{r.json()['checkout_id']}/options").json()


def test_defaults_are_all_methods_and_catalog(monkeypatch):
    from app.checkout_intl import flags
    assert flags.tier_exposure() == "all" and flags.quote_source() == "catalog"


@pytest.mark.parametrize("cc", ["US", "GB", "DE", "FR", "AU", "CA"])
def test_every_wave1_country_has_a_catalog_with_express_and_no_supplier_call(cc):
    methods = catalog.methods_for(cc)
    assert methods, f"{cc} should be catalogued from the probe"
    assert any(o["tier"] == "EXPRESS" for o in rates.normalize(methods, cc))


def test_catalog_only_lists_methods_present_at_every_probed_location():
    """GB: YunExpress appeared for Manchester but not London -> must NOT be offered."""
    ways = {m["way"] for m in catalog.methods_for("GB")}
    assert "BKPHR" not in ways and {"DHL", "Fedex"} <= ways
    assert catalog.methods_for("ZZ") is None and catalog.methods_for("JP") is None


def test_delivery_is_instant_from_catalog_and_offers_all_methods(client, session, flag_on, no_supplier_calls):
    make_product(session)
    for cc, expected_min in (("US", 3), ("GB", 3), ("DE", 3), ("FR", 4), ("AU", 3), ("CA", 3)):
        body = _delivery(client, cc, **({"admin_area": "", "postal_code": {"GB": "SW1A 2AA", "DE": "10117", "FR": "75001"}.get(cc, "")}
                                        if cc in ("GB", "DE", "FR") else {}))
        assert body["status"] == "ready", (cc, body)                       # ready on the first poll: no supplier wait
        assert len(body["options"]) >= expected_min, (cc, body["options"])
        assert "supplier_price" not in json.dumps(body["options"]) and "57.83" not in json.dumps(body["options"])
    assert no_supplier_calls == []


def test_options_are_named_by_service_with_eta_and_express_first(client, session, flag_on, no_supplier_calls):
    make_product(session)
    opts = _delivery(client, "US")["options"]
    assert opts[0]["tier"] == "EXPRESS" and opts[0]["name"] == "DHL Express"
    assert opts[0]["eta_text"] == "4–9 business days"
    names = [o["name"] for o in opts]
    assert "FedEx" in names and any("International" in n for n in names)
    assert all("(" not in n for n in names)                                 # supplier parentheses stripped
    assert {o["tier"] for o in opts} == {"EXPRESS", "STANDARD"}


def test_customer_can_pick_any_offered_method_and_that_exact_one_is_locked(client, session, flag_on,
                                                                          no_supplier_calls, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kw: SimpleNamespace(id="cs", url="https://x"))
    make_product(session)
    body = _delivery(client, "GB", admin_area="", postal_code="SW1A 2AA")
    cheapest_standard = next(o for o in body["options"] if o["tier"] == "STANDARD")
    r = client.post(f"/checkout/{body['checkout_id']}/pay", json={"shipping_method_id": cheapest_standard["method_id"]})
    assert r.status_code == 200
    from app.models.checkout_transaction import CheckoutTransaction
    session.expire_all()
    tx = session.get(CheckoutTransaction, body["checkout_id"])
    assert tx.shipping_method_id == cheapest_standard["method_id"] and tx.shipping_tier == "STANDARD"


def test_unknown_method_id_is_refused(client, session, flag_on, no_supplier_calls):
    make_product(session)
    body = _delivery(client, "US")
    r = client.post(f"/checkout/{body['checkout_id']}/pay", json={"shipping_method_id": "NOT_OFFERED"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "requote"


def test_uncatalogued_country_falls_back_to_live_lookup(session, monkeypatch):
    from app.checkout_intl import address as addr_mod
    monkeypatch.setenv("INTL_ENABLED_COUNTRIES", "US,JP")
    seen = []
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: seen.append(a) or [
        {"way": "DHL", "title": "DHL Express(4 - 9 workdays)", "price": 40}])
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US", country_code="JP", admin_area="Tokyo", postal_code="100-0001"))
    q = txn.fetch_quote(a, [{"product_id": 1, "quantity": 1, "supplier_option_id": "O"}])
    assert seen and q["offered"] == ["DHL"]


def test_live_source_still_available(session, monkeypatch):
    from app.checkout_intl import address as addr_mod
    monkeypatch.setenv("INTL_QUOTE_SOURCE", "live")
    seen = []
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: seen.append(a) or [])
    a = addr_mod.StructuredAddress(**valid_address("US"))
    txn.fetch_quote(a, [{"product_id": 1, "quantity": 1, "supplier_option_id": "O"}])
    assert seen
