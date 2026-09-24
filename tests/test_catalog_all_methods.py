"""Two-class checkout (STANDARD / EXPRESS): instant rate-card quotes with max-observed cost basis,
and the real carrier chosen AFTER payment from live rates for the exact cart + address."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.checkout_intl import address as addr_mod
from app.checkout_intl import catalog, countries, rates
from app.checkout_intl import transaction as txn
from conftest import make_product, quoted_tx, valid_address

WAVE1 = countries.LAUNCH_WAVE_1


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
        raise AssertionError("live Silverbene lookup must not run at checkout for catalogued countries")
    monkeypatch.setattr(txn, "default_rate_fetcher", boom)
    return calls


def _delivery(client, country, **addr):
    r = client.post("/checkout/delivery", json={"address": valid_address(country, **addr),
                                                "items": [{"product_id": 1, "quantity": 1}]})
    assert r.status_code == 200, r.text
    return client.get(f"/checkout/{r.json()['checkout_id']}/options").json()


# ── rate card ─────────────────────────────────────────────────────────────────

def test_defaults():
    from app.checkout_intl import flags
    assert flags.tier_exposure() == "all" and flags.quote_source() == "catalog"


def test_ratecard_uses_the_maximum_observed_price_per_class():
    card = catalog.ratecard()
    assert card["US"]["express"]["max"] == 64.73 and card["GB"]["express"]["max"] == 45.89
    assert card["DE"]["express"]["max"] == 49.37 and card["AU"]["express"]["max"] == 36.02
    for cc in WAVE1:
        for cls in ("express", "standard"):
            if cls == "standard" and cc == "US":
                continue
            e = card[cc][cls]
            assert e["max"] >= e["median"] >= e["min"] and e["n"] >= 5, (cc, cls, e)
    assert card["GB"]["standard"]["max"] == 22.5 and "GTG" in card["GB"]["standard"]["ways"]   # Royal Mail seen


def test_ratecard_excludes_fedex_from_the_express_cost_basis():
    for cc in WAVE1:
        assert set(catalog.ratecard()[cc]["express"]["ways"]) <= {"DHL", "DHLI"}


SLOW_OR_UNWANTED = {"ITDIDA_ECO", "cainiao", "Fedex", "FedexI"}


@pytest.mark.parametrize("cc", WAVE1)
def test_standard_is_offered_only_where_an_acceptable_non_express_method_exists(cc):
    opts = catalog.class_options(cc)
    expected = ["EXPRESS"] if cc == "US" else ["EXPRESS", "STANDARD"]        # US: only the slow China-system method exists
    assert [o["method_id"] for o in opts] == expected
    assert opts[0]["name"] == "Express delivery (DHL)"
    assert all(o["basis"] == "max_observed" and o["supplier_price"] > 0 for o in opts)
    assert catalog.class_options("ZZ") is None and catalog.class_options("JP") is None


def test_slow_china_system_methods_never_count_toward_standard():
    for cc in WAVE1:
        std = catalog.ratecard()[cc].get("standard")
        assert not std or not (set(std["ways"]) & SLOW_OR_UNWANTED), (cc, std)
        assert not (set(catalog.STANDARD_ALLOWED[cc]) & SLOW_OR_UNWANTED)
    assert "standard" not in catalog.ratecard()["US"] and catalog.STANDARD_ALLOWED["US"] == ()
    for cc in ("DE", "FR", "AU", "CA"):
        assert catalog.STANDARD_ALLOWED[cc] == ("BKPHR",)
    assert catalog.STANDARD_ALLOWED["GB"] == ("GTG", "BKPHR")                # Royal Mail first
    eta = catalog.class_options("GB")[1]["eta"]
    assert eta["max_days"] <= 10                                            # never the 10-20 day service


# ── checkout: instant, two options, no supplier call ──────────────────────────

def test_delivery_is_instant_and_shows_only_two_options_without_supplier_calls(client, session, flag_on,
                                                                              no_supplier_calls):
    make_product(session)
    for cc in WAVE1:
        addr = {"admin_area": "", "postal_code": {"GB": "SW1A 2AA", "DE": "10117", "FR": "75001"}[cc]} \
            if cc in ("GB", "DE", "FR") else {}
        body = _delivery(client, cc, **addr)
        assert body["status"] == "ready"
        assert [o["method_id"] for o in body["options"]] == (["EXPRESS"] if cc == "US" else ["EXPRESS", "STANDARD"]), cc
        blob = json.dumps(body["options"])
        assert "supplier" not in blob and "64.73" not in blob and "cost" not in blob.lower()
    assert no_supplier_calls == []


def test_customer_choice_is_a_class_and_the_max_basis_is_recorded(client, session, flag_on, no_supplier_calls,
                                                                  monkeypatch):
    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kw: SimpleNamespace(id="cs", url="https://x"))
    make_product(session)
    body = _delivery(client, "GB", admin_area="", postal_code="SW1A 2AA")
    r = client.post(f"/checkout/{body['checkout_id']}/pay", json={"shipping_method_id": "STANDARD"})
    assert r.status_code == 200
    from app.models.checkout_transaction import CheckoutTransaction
    session.expire_all()
    tx = session.get(CheckoutTransaction, body["checkout_id"])
    assert (tx.shipping_method_id, tx.shipping_tier, tx.shipping_supplier_price) == ("STANDARD", "STANDARD", 22.5)


def test_us_customers_cannot_choose_standard(client, session, flag_on, no_supplier_calls):
    make_product(session)
    body = _delivery(client, "US")
    r = client.post(f"/checkout/{body['checkout_id']}/pay", json={"shipping_method_id": "STANDARD"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "requote"


def test_unknown_choice_is_refused(client, session, flag_on, no_supplier_calls):
    make_product(session)
    body = _delivery(client, "US")
    r = client.post(f"/checkout/{body['checkout_id']}/pay", json={"shipping_method_id": "DHL"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "requote"      # a carrier id is not a valid choice


def test_uncatalogued_country_still_uses_live_per_method_lookup(session, monkeypatch):
    monkeypatch.setenv("INTL_ENABLED_COUNTRIES", "US,JP")
    seen = []
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: seen.append(a) or [
        {"way": "DHL", "title": "DHL Express(4 - 9 workdays)", "price": 40}])
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US", country_code="JP", admin_area="Tokyo", postal_code="100-0001"))
    q = txn.fetch_quote(a, [{"product_id": 1, "quantity": 1, "supplier_option_id": "O"}])
    assert seen and q["offered"] == ["DHL"] and "class_quote" not in q


# ── real carrier chosen from live rates ───────────────────────────────────────

LIVE_GB = [{"way": "DHL", "title": "DHL Express(4 - 9 workdays)", "price": 45.89},
           {"way": "Fedex", "title": "FedEx(4 - 9 workdays)", "price": 27.56},
           {"way": "GTG", "title": "Royal Mail(5-9 workdays)", "price": 5},
           {"way": "cainiao", "title": "Cainiao International", "price": 10.64},
           {"way": "BKPHR", "title": "YunExpress Registered Priority General(2-10 workdays,TAX included)", "price": 13.22}]


def test_express_resolves_to_dhl_even_when_fedex_is_cheaper():
    r = rates.resolve_class_method("GB", LIVE_GB, "EXPRESS")
    assert (r["method_id"], r["fallback"]) == ("DHL", False)


def test_express_falls_back_to_fedex_only_with_a_flag_when_dhl_is_missing():
    no_dhl = [m for m in LIVE_GB if m["way"] != "DHL"]
    r = rates.resolve_class_method("GB", no_dhl, "EXPRESS")
    assert r["method_id"] == "Fedex" and r["fallback"] is True and "DHL" in r["reason"]
    assert rates.resolve_class_method("GB", [m for m in no_dhl if m["way"] != "Fedex"], "EXPRESS") is None


def test_standard_prefers_the_national_post_then_yunexpress_and_never_the_slow_methods(monkeypatch):
    assert rates.resolve_class_method("GB", LIVE_GB, "STANDARD")["method_id"] == "GTG"          # Royal Mail
    no_rm = [m for m in LIVE_GB if m["way"] != "GTG"]
    assert rates.resolve_class_method("GB", no_rm, "STANDARD")["method_id"] == "BKPHR"
    only_slow = [m for m in LIVE_GB if m["way"] == "cainiao"] + [
        {"way": "ITDIDA_ECO", "title": "International Standard(12-20 workdays)", "price": 5.52}]
    assert rates.resolve_class_method("GB", only_slow, "STANDARD") is None                       # never Cainiao / 10-20 day
    us = [{"way": "ITDIDA_ECO", "title": "International Standard(12-20 workdays)", "price": 5.52}]
    assert rates.resolve_class_method("US", us, "STANDARD") is None
    monkeypatch.setitem(catalog.STANDARD_ALLOWED, "US", ("SUX",))                                # USPS enabled later
    usps = [{"way": "SUX", "title": "USPS(8-10 workdays, accepts packages under $60, customs duty included)", "price": 7.28}] + us
    assert rates.resolve_class_method("US", usps, "STANDARD")["method_id"] == "SUX"


def test_standard_never_silently_upgrades_to_express():
    only_express = [m for m in LIVE_GB if m["way"] in ("DHL", "Fedex")]
    assert rates.resolve_class_method("GB", only_express, "STANDARD") is None


def test_unknown_class_or_empty_rates_resolve_to_nothing():
    assert rates.resolve_class_method("GB", [], "EXPRESS") is None
    assert rates.resolve_class_method("GB", LIVE_GB, "WEIRD") is None


# ── fulfillment: class -> real carrier after payment ──────────────────────────

class FakeSB:
    placed, lookups = [], 0

    def check_balance(self):
        return 500.0

    def _alert_low_credit(self, **kw):
        pass

    def place_order(self, **kw):
        FakeSB.placed.append(kw)
        return {"success": True, "supplier_order_id": "SB1", "shipping_cost": kw.get("shipping_price"),
                "shipping_carrier": kw.get("shipping_title"), "total_charged": 1.0, "currency": "USD", "raw_response": "{}"}


@pytest.fixture()
def fulfil(monkeypatch):
    FakeSB.placed, FakeSB.lookups = [], 0
    emails = []
    monkeypatch.setattr("app.agents.suppliers.silverbene_adapter.SilverbeneAdapter", FakeSB)
    monkeypatch.setattr("app.agents.tracking_agent.create_tracking_entry", lambda **kw: None)
    monkeypatch.setattr("app.agents.order_variant_tracker.check_order_item", lambda **kw: SimpleNamespace(match_status="ok"))
    monkeypatch.setattr("app.agents.order_variant_tracker.send_batched_order_alert", lambda *a, **k: None)
    monkeypatch.setattr("app.agents.email_partner.send_email", lambda **kw: emails.append(kw))
    monkeypatch.setattr("app.routes.payments._send_meta_capi_event", lambda *a, **k: None)
    monkeypatch.setenv("PAYPAL_MODE", "live")            # so the payment reference is treated as a real payment
    monkeypatch.setenv("DENNIS_EMAIL", "owner@example.com")
    return emails


def _class_tx(session, cls="STANDARD"):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("GB"))
    tx = quoted_tx(session, a, [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}])
    return txn.lock_for_payment(session, tx, cls)


def _meta(cid, sid):
    from test_intl_checkout import _paid_metadata
    return _paid_metadata(cid, sid)


def _live(monkeypatch, methods, calls=None):
    def f(country, postcode, city, products):
        if calls is not None:
            calls.append((country, postcode, city, products))
        if isinstance(methods, Exception):
            raise methods
        return methods
    monkeypatch.setattr(txn, "default_rate_fetcher", f)


def test_standard_order_ships_with_royal_mail_chosen_from_live_rates(session, fulfil, monkeypatch):
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "STANDARD")
    assert tx.shipping_method_id == "STANDARD"                       # the customer chose a class, not a carrier
    calls = []
    _live(monkeypatch, LIVE_GB, calls)
    process_order_background(_meta(tx.id, "cs_1"))
    assert len(FakeSB.placed) == 1
    p = FakeSB.placed[0]
    assert p["shipping_method"] == "GTG" and p["shipping_price"] == 5 and p["shipping_title"].startswith("Royal Mail")
    assert calls and calls[0][0] == "GB" and calls[0][3] == [{"option_id": "OPT1", "qty": 1}]   # real cart + address
    assert not any("fallback" in e["subject"].lower() for e in fulfil)   # preferred method available -> no fallback alert


def test_express_order_ships_dhl(session, fulfil, monkeypatch):
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "EXPRESS")
    _live(monkeypatch, LIVE_GB)
    process_order_background(_meta(tx.id, "cs_2"))
    assert FakeSB.placed[0]["shipping_method"] == "DHL"


def test_fallback_is_used_and_the_owner_is_alerted(session, fulfil, monkeypatch):
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "EXPRESS")
    _live(monkeypatch, [m for m in LIVE_GB if m["way"] != "DHL"])
    process_order_background(_meta(tx.id, "cs_3"))
    assert FakeSB.placed[0]["shipping_method"] == "Fedex"
    assert any("fallback" in e["subject"].lower() for e in fulfil)


def test_supplier_lookup_failure_holds_the_order_for_recovery_and_places_nothing(session, fulfil, monkeypatch):
    from sqlmodel import select
    from app.models.order import Order
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "STANDARD")
    _live(monkeypatch, TimeoutError("supplier timed out"))
    process_order_background(_meta(tx.id, "cs_4"))
    assert FakeSB.placed == []
    o = session.exec(select(Order)).first()
    assert o.status == "paid" and o.supplier_notified is False       # recovery agent will retry it


def test_recovery_retry_resolves_and_then_reuses_the_same_method(session, fulfil, monkeypatch):
    from sqlmodel import select
    from app.agents import order_recovery_agent
    from app.models.order import Order
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "STANDARD")
    _live(monkeypatch, TimeoutError("down"))
    process_order_background(_meta(tx.id, "cs_5"))                   # held
    o = session.exec(select(Order)).first()
    o.created_at = datetime.utcnow() - timedelta(hours=1)
    session.add(o)
    session.commit()
    monkeypatch.setattr(order_recovery_agent, "engine", session.get_bind())
    order_recovery_agent.run_order_recovery_agent()                  # still down -> nothing placed
    assert FakeSB.placed == []
    _live(monkeypatch, LIVE_GB)                                      # supplier is back
    order_recovery_agent.run_order_recovery_agent()
    assert [p["shipping_method"] for p in FakeSB.placed] == ["GTG"]
    session.expire_all()
    assert json.loads(session.get(type(tx), tx.id).shipping_resolved_json)["method_id"] == "GTG"


def test_no_suitable_standard_method_holds_instead_of_upgrading(session, fulfil, monkeypatch):
    from app.routes.payments import process_order_background
    tx = _class_tx(session, "STANDARD")
    _live(monkeypatch, [m for m in LIVE_GB if m["way"] in ("DHL", "Fedex")])
    process_order_background(_meta(tx.id, "cs_6"))
    assert FakeSB.placed == []
