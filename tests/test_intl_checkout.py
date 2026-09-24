"""Stage 1 international checkout qualification. No real supplier/Stripe calls are made."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, rates
from app.checkout_intl import transaction as txn
from conftest import make_product, valid_address

DHL = {"way": "DHL_X", "title": "DHL Express(3-7 workdays)", "price": 31.5}
EPACKET = {"way": "EPK", "title": "ePacket(15-25 workdays)", "price": 4.2}


def fetcher_returning(methods, calls=None):
    def _f(country_id, postcode, city, products):
        if calls is not None:
            calls.append((country_id, postcode, city, products))
        return list(methods)
    return _f


@pytest.fixture()
def fake_rates(monkeypatch):
    calls = []
    state = {"methods": [DHL, EPACKET]}
    monkeypatch.setattr(txn, "default_rate_fetcher",
                        lambda c, p, ci, pr: (calls.append((c, p, ci, pr)) or list(state["methods"])))
    state["calls"] = calls
    return state


@pytest.fixture()
def stock_ok(monkeypatch):
    monkeypatch.setattr("app.routes.payments._live_stock_check_many", lambda pairs: None)


# ── registry / address ────────────────────────────────────────────────────────

def test_registry_covers_every_iso_country_but_enables_only_defaults():
    assert len(countries.all_markets()) == 249
    enabled = {m.iso_country_code for m in countries.all_markets() if m.checkout_enabled}
    assert enabled == set(countries.DEFAULT_ENABLED)


def test_other_and_garbage_are_not_countries_and_sanctioned_never_enable(monkeypatch):
    for bad in ("other", "", "XX", "USA"):
        assert countries.get_market(bad) is None
        assert not countries.is_checkout_country(bad)
    monkeypatch.setattr("app.agents.store_config.get_config", lambda k, default=None: "KP,IR,US")
    assert countries.enabled_country_codes() == {"US"}


def test_enabling_a_market_is_config_only(monkeypatch):
    monkeypatch.setattr("app.agents.store_config.get_config", lambda k, default=None: "US,DE,JP")
    assert countries.is_checkout_country("JP") and countries.is_checkout_country("DE")
    assert not countries.is_checkout_country("CA")


def test_probed_unsupported_market_is_hidden(monkeypatch):
    monkeypatch.setattr(countries, "_probe_cache", {"US": {"supplier_supported": False}})
    assert not countries.is_checkout_country("US")


@pytest.mark.parametrize("cc", ["US", "CA", "GB", "AU", "NG"])
def test_valid_addresses_pass_when_enabled(cc):
    assert addr_mod.validate(addr_mod.StructuredAddress(**valid_address(cc))) is None


@pytest.mark.parametrize("cc", ["DE", "FR", "JP"])
def test_eu_and_asia_addresses_pass_once_market_enabled(cc, monkeypatch):
    monkeypatch.setattr("app.agents.store_config.get_config", lambda k, default=None: "DE,FR,JP")
    assert addr_mod.validate(addr_mod.StructuredAddress(**valid_address(cc))) is None


def test_invalid_postcode_missing_phone_and_missing_state():
    bad_zip = addr_mod.StructuredAddress(**valid_address("US", postal_code="ABC"))
    assert "zip" in addr_mod.validate(bad_zip).lower()
    no_phone = addr_mod.StructuredAddress(**valid_address("US", phone=""))
    assert "phone" in addr_mod.validate(no_phone).lower()
    same_digits = addr_mod.StructuredAddress(**valid_address("US", phone="0000000000"))
    assert addr_mod.validate(same_digits)
    no_state = addr_mod.StructuredAddress(**valid_address("US", admin_area=""))
    assert "state" in addr_mod.validate(no_state).lower()
    other = addr_mod.StructuredAddress(**valid_address("US", country_code="other"))
    assert addr_mod.validate(other)


def test_legacy_string_is_always_five_segments_and_supplier_gets_minimal_data():
    a = addr_mod.StructuredAddress(**valid_address(
        "US", line1="1 Main St, Apt 2", line2="Floor 3", company="Acme", customs_tax_id="X1",
        delivery_note="leave at door"))
    assert len(addr_mod.to_legacy_string(a).split(",")) == 5
    assert addr_mod.to_legacy_string(a).endswith(", US")
    cust = addr_mod.to_supplier_customer(a)
    assert cust["email"] == "hello@mikisi.co"            # customer email never goes to the supplier
    blob = json.dumps([cust, addr_mod.to_parsed_address(a)])
    for private in ("ada@example.com", "Acme", "X1", "leave at door"):
        assert private not in blob


# ── rate normalization ────────────────────────────────────────────────────────

def test_eta_parsed_from_title_never_invented():
    assert rates.parse_eta("USPS(8-10 workdays)")["text"] == "8–10 business days"
    assert rates.parse_eta("China Post") is None


def test_dhl_only_policy_and_fallback(monkeypatch):
    opts = rates.normalize([DHL, EPACKET])
    assert [o["method_id"] for o in rates.present(opts)] == ["DHL_X"]
    only_epacket = rates.present(rates.normalize([EPACKET]))
    assert only_epacket[0]["method_id"] == "EPK" and only_epacket[0]["fallback"] is True
    monkeypatch.setenv("INTL_SHIPPING_POLICY", "all")
    assert [o["method_id"] for o in rates.present(opts)] == ["EPK", "DHL_X"]
    assert rates.present([]) == []


def test_customer_view_hides_supplier_cost_and_route_wording():
    v = rates.customer_view(rates.normalize([DHL])[0])
    assert "supplier_price" not in v and "31.5" not in json.dumps(v)
    assert v["customer_price"] == 0.0 and "Silverbene" not in json.dumps(v)


# ── endpoints ─────────────────────────────────────────────────────────────────

def test_flag_defaults_off(client):
    assert client.get("/checkout/config").json() == {"enabled": False}
    r = client.post("/checkout/delivery", json={"address": valid_address("US"), "items": []})
    assert r.status_code == 404


def test_config_lists_only_enabled_markets(client, flag_on):
    cfg = client.get("/checkout/config").json()
    codes = {m["code"] for m in cfg["markets"]}
    assert cfg["enabled"] and codes == set(countries.DEFAULT_ENABLED) and "other" not in codes


def _delivery(client, country="US", items=None, **addr):
    return client.post("/checkout/delivery", json={
        "address": valid_address(country, **addr),
        "items": items or [{"product_id": 1, "quantity": 1}]})


def test_domestic_and_international_quote_uses_real_cart_and_destination(
        client, session, flag_on, fake_rates, stock_ok):
    make_product(session)
    for cc, postal in (("US", "10001"), ("CA", "K1A 0B1"), ("GB", "SW1A 2AA"), ("AU", "2000")):
        r = _delivery(client, cc)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [o["method_id"] for o in body["options"]] == ["DHL_X"]
        country_id, postcode, city, products = fake_rates["calls"][-1]
        assert country_id == cc and postcode == postal
        assert products == [{"option_id": "OPT1", "qty": 1}]
        assert "supplier_price" not in json.dumps(body)


def test_multi_item_cart_is_quoted_as_one_request(client, session, flag_on, fake_rates, stock_ok):
    make_product(session, pid=1, cj_sku="A")
    make_product(session, pid=2, name="Chain", cj_sku="B")
    r = _delivery(client, "US", items=[{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}])
    assert r.status_code == 200
    assert fake_rates["calls"][-1][3] == [{"option_id": "A", "qty": 2}, {"option_id": "B", "qty": 1}]


def test_no_shipping_available_is_a_clean_422(client, session, flag_on, fake_rates, stock_ok):
    make_product(session)
    fake_rates["methods"] = []
    r = _delivery(client, "US")
    assert r.status_code == 422 and "can't offer delivery" in r.json()["detail"]
    assert session.exec(__import__("sqlmodel").select(__import__(
        "app.models.checkout_transaction", fromlist=["x"]).CheckoutTransaction)).first() is None


def test_unsupported_country_rejected_before_any_supplier_call(client, session, flag_on, fake_rates, stock_ok):
    make_product(session)
    r = _delivery(client, "US", country_code="other")
    assert r.status_code == 400 and fake_rates["calls"] == []


def test_variant_required_product_blocked_before_payment(client, session, flag_on, fake_rates, stock_ok):
    variants = [{"option_id": "R6", "attribute": [{"name": "size", "value": "6"}]},
                {"option_id": "R7", "attribute": [{"name": "size", "value": "7"}]}]
    make_product(session, cj_sku="R6", variants=variants)
    r = _delivery(client, "US")                                  # no size/variant chosen
    assert r.status_code == 400 and "choose a size" in r.json()["detail"].lower()
    ok = _delivery(client, "US", items=[{"product_id": 1, "quantity": 1, "selected_option_id": "R7"}])
    assert ok.status_code == 200
    assert fake_rates["calls"][-1][3] == [{"option_id": "R7", "qty": 1}]


def test_confirmed_sold_out_blocks_quote(client, session, flag_on, fake_rates, monkeypatch):
    make_product(session)
    monkeypatch.setattr("app.routes.payments._live_stock_check_many", lambda pairs: "just sold out")
    assert _delivery(client, "US").status_code == 400


# ── lock / expiry / requote ───────────────────────────────────────────────────

def _quoted(session, fake_rates, stock_ok_=None):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    return txn.create_quoted(session, address=a, items=items, is_guest=True,
                             fetcher=fetcher_returning([DHL, EPACKET]))


def test_lock_records_exact_method_and_supplier_snapshot(session, fake_rates):
    tx = _quoted(session, fake_rates)
    tx = txn.lock_for_payment(session, tx, "DHL_X")
    assert (tx.status, tx.shipping_method_id, tx.shipping_supplier_price) == ("locked", "DHL_X", 31.5)
    assert tx.presentment_currency == "USD" and tx.supplier_settlement_currency == "USD"


def test_selecting_an_unquoted_method_requires_requote(session, fake_rates):
    tx = _quoted(session, fake_rates)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "SOMETHING_ELSE")


def test_expired_quote_same_method_same_price_refreshes_silently(session, fake_rates):
    tx = _quoted(session, fake_rates)
    later = tx.quote_expires_at + timedelta(minutes=1)
    tx = txn.lock_for_payment(session, tx, "DHL_X", fetcher=fetcher_returning([DHL]), now=later)
    assert tx.shipping_method_id == "DHL_X" and tx.quote_expires_at > later


def test_expired_quote_price_change_never_silently_swaps(session, fake_rates):
    tx = _quoted(session, fake_rates)
    later = tx.quote_expires_at + timedelta(minutes=1)
    pricier = dict(DHL, price=71.5)
    with pytest.raises(txn.RequoteRequired) as e:
        txn.lock_for_payment(session, tx, "DHL_X", fetcher=fetcher_returning([pricier]), now=later)
    assert e.value.options and tx.shipping_method_id is None       # nothing locked
    assert txn.load_options(tx)[0]["supplier_price"] == 71.5        # fresh rates stored for re-choice


def test_method_becoming_unavailable_after_expiry_requotes(session, fake_rates):
    tx = _quoted(session, fake_rates)
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired) as e:
        txn.lock_for_payment(session, tx, "DHL_X", fetcher=fetcher_returning([]), now=later)
    assert e.value.options == []


# ── payment step ──────────────────────────────────────────────────────────────

class FakeStripe:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(id="cs_test_1", url="https://stripe.test/pay")


@pytest.fixture()
def stripe_spy(monkeypatch):
    spy = FakeStripe()
    monkeypatch.setattr("stripe.checkout.Session.create", spy.create)
    return spy


def test_pay_step_pricing_is_identical_to_legacy_guest_checkout(
        client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session, price=298.0)
    cid = _delivery(client, "US").json()["checkout_id"]
    assert client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "DHL_X"}).status_code == 200
    intl = stripe_spy.calls[-1]

    legacy = client.post("/payments/guest-checkout", json={
        "items": [{"product_id": 1, "quantity": 1}], "email": "ada@example.com",
        "first_name": "Ada", "last_name": "Lovelace",
        "shipping_address": "1 Main St, New York, NY, 10001, US", "phone": "+44 20 7946 0958"})
    assert legacy.status_code == 200
    old = stripe_spy.calls[-1]
    for key in ("line_items", "payment_method_types", "mode", "success_url", "cancel_url", "customer_email"):
        assert intl[key] == old[key], key
    assert intl["line_items"][0]["price_data"]["currency"] == "usd"
    assert intl["line_items"][0]["price_data"]["unit_amount"] == 29800
    assert intl["payment_method_types"] == ["card"]
    assert intl["metadata"]["checkout_id"] == cid and "checkout_id" not in old["metadata"]


def test_supplier_payment_link_and_cost_never_reach_the_customer(
        client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session)
    d = _delivery(client, "US")
    cid = d.json()["checkout_id"]
    p = client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "DHL_X"})
    text = d.text + p.text
    for leak in ("pay_url", "31.5", "silverbene", "amount_due"):
        assert leak not in text.lower()


def test_pay_requote_is_409_with_fresh_options(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "NOPE"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "requote"
    assert stripe_spy.calls == []


def test_completed_checkout_cannot_be_paid_again(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    from app.checkout_intl import fulfillment
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "DHL_X"})
    fulfillment.mark_paid(cid, "cs_test_1")
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "DHL_X"})
    assert r.status_code == 409


def test_paypal_slot_is_declared_but_disabled(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_method_id": "DHL_X", "payment_provider": "paypal"})
    assert r.status_code == 400 and stripe_spy.calls == []


# ── fulfillment: exact method, no re-decision, idempotent, Meta unchanged ────

class FakeSilverbene:
    placed = []
    rate_lookups = 0

    def check_balance(self):
        return 500.0

    def _alert_low_credit(self, **kw):
        pass

    def get_shipping_methods(self, *a, **kw):
        FakeSilverbene.rate_lookups += 1
        return [DHL]

    def place_order(self, **kw):
        FakeSilverbene.placed.append(kw)
        return {"success": True, "supplier_order_id": f"SB{len(FakeSilverbene.placed)}",
                "shipping_cost": kw.get("shipping_price"), "shipping_carrier": kw.get("shipping_title"),
                "total_charged": 1.0, "currency": "USD", "raw_response": "{}"}


@pytest.fixture()
def fulfil_env(monkeypatch):
    FakeSilverbene.placed, FakeSilverbene.rate_lookups = [], 0
    meta = []
    monkeypatch.setattr("app.agents.suppliers.silverbene_adapter.SilverbeneAdapter", FakeSilverbene)
    monkeypatch.setattr("app.agents.tracking_agent.create_tracking_entry", lambda **kw: None)
    monkeypatch.setattr("app.agents.order_variant_tracker.check_order_item",
                        lambda **kw: SimpleNamespace(match_status="ok"))
    monkeypatch.setattr("app.agents.order_variant_tracker.send_batched_order_alert", lambda *a, **k: None)
    monkeypatch.setattr("app.agents.email_partner.send_email", lambda **kw: None)
    monkeypatch.setattr("app.routes.payments._send_meta_capi_event",
                        lambda *a, **kw: meta.append((a, kw)))
    return meta


def _paid_metadata(cid, session_id, **extra):
    a = addr_mod.StructuredAddress(**valid_address("AU"))
    md = {"user_email": "ada@example.com", "shipping_address": addr_mod.to_legacy_string(a),
          "shipping_method": "intl", "phone": a.phone, "is_guest": "true", "first_name": "Ada",
          "last_name": "Lovelace", "checkout_id": cid, "stripe_session_id": session_id,
          "guest_items": json.dumps([{"product_id": 1, "quantity": 1, "selected_option_id": "OPT1",
                                      "selected_size": None, "selected_color": None, "variant_id": None}])}
    md.update(extra)
    return {"metadata": md}


def _locked_au_tx(session):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("AU"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    tx = txn.create_quoted(session, address=a, items=items, is_guest=True,
                           fetcher=fetcher_returning([DHL, EPACKET]))
    return txn.lock_for_payment(session, tx, "DHL_X")


def test_fulfillment_uses_exact_chosen_method_and_never_looks_up_rates(session, fulfil_env):
    from app.routes.payments import process_order_background
    tx = _locked_au_tx(session)
    process_order_background(_paid_metadata(tx.id, "cs_1"))
    assert len(FakeSilverbene.placed) == 1 and FakeSilverbene.rate_lookups == 0
    placed = FakeSilverbene.placed[0]
    assert placed["shipping_method"] == "DHL_X" and placed["shipping_price"] == 31.5
    assert placed["address"]["country_code"] == "AU" and placed["address"]["postal_code"] == "2000"
    assert placed["customer"]["phone"] == "+44 20 7946 0958" and placed["customer"]["email"] == "hello@mikisi.co"


def test_replayed_webhook_and_second_payment_never_duplicate_supplier_order(session, fulfil_env):
    from app.routes.payments import process_order_background
    tx = _locked_au_tx(session)
    process_order_background(_paid_metadata(tx.id, "cs_1"))
    process_order_background(_paid_metadata(tx.id, "cs_1"))          # webhook redelivery / recover-order
    process_order_background(_paid_metadata(tx.id, "cs_2"))          # customer paid a second session
    assert len(FakeSilverbene.placed) == 1


def test_meta_purchase_event_is_unchanged(session, fulfil_env):
    from app.routes.payments import process_order_background
    tx = _locked_au_tx(session)
    process_order_background(_paid_metadata(tx.id, "cs_meta"))
    (args, kwargs), = fulfil_env
    assert args[0] == "Purchase" and args[1] == 298.0 and args[2] == [1]
    assert kwargs["event_id"] == "cs_meta" and kwargs["email"] == "ada@example.com"


def test_order_links_to_checkout_and_transaction_marked_paid(session, fulfil_env):
    from sqlmodel import select
    from app.models.order import Order
    from app.models.checkout_transaction import CheckoutTransaction
    from app.routes.payments import process_order_background
    tx = _locked_au_tx(session)
    process_order_background(_paid_metadata(tx.id, "cs_1"))
    session.expire_all()
    assert session.exec(select(Order)).first().checkout_id == tx.id
    assert session.get(CheckoutTransaction, tx.id).status == "paid"


def test_recovery_agent_reuses_pre_payment_method_address_and_phone(session, fulfil_env, monkeypatch):
    from app.models.order import Order
    from app.agents import order_recovery_agent
    tx = _locked_au_tx(session)
    session.add(Order(user_id="ada@example.com", product_id=1, quantity=1, total_price=298.0,
                      status="paid", shipping_address="junk, junk", checkout_id=tx.id,
                      created_at=datetime.utcnow() - timedelta(hours=1)))
    session.commit()
    monkeypatch.setattr(order_recovery_agent, "engine", session.get_bind())
    order_recovery_agent.run_order_recovery_agent()
    placed = FakeSilverbene.placed[0]
    assert placed["shipping_method"] == "DHL_X" and FakeSilverbene.rate_lookups == 0
    assert placed["customer"]["phone"] == "+44 20 7946 0958"
    assert placed["address"]["country_code"] == "AU"


# ── legacy path untouched ─────────────────────────────────────────────────────

def test_legacy_place_order_still_chooses_cheapest_dhl_after_payment(monkeypatch):
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    posted = []
    sb = SilverbeneAdapter()
    monkeypatch.setattr(sb, "_post", lambda ep, payload: (posted.append((ep, payload)) or (
        {"code": 0, "data": [{"way": "EPK", "title": "ePacket", "price": 4},
                             {"way": "DHL2", "title": "DHL Express", "price": 60},
                             {"way": "DHL1", "title": "DHL Economy", "price": 40}]}
        if ep.endswith("get_shipping_method") else {"code": 0, "data": {"order_id": "9", "payment_required": True}})))
    monkeypatch.setattr(sb, "_alert_low_credit", lambda **kw: None)
    r = sb.place_order("OPT1", {"first_name": "A", "last_name": "B", "phone": "1234567"},
                       {"line1": "x", "city": "y", "state": "z", "postal_code": "10001", "country_code": "US"},
                       option_id="OPT1")
    order_payload = posted[-1][1]
    assert order_payload["shipping_method"] == "DHL1" and r["shipping_cost"] == 40


def test_preselected_method_skips_rate_lookup_and_is_sent_verbatim(monkeypatch):
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    posted = []
    sb = SilverbeneAdapter()
    monkeypatch.setattr(sb, "_post", lambda ep, payload: (posted.append((ep, payload)) or
                        {"code": 0, "data": {"order_id": "9", "payment_required": True}}))
    monkeypatch.setattr(sb, "_alert_low_credit", lambda **kw: None)
    sb.place_order("OPT1", {"first_name": "A", "last_name": "B", "phone": "1234567"},
                   {"line1": "x", "city": "y", "state": "z", "postal_code": "10001", "country_code": "US"},
                   option_id="OPT1", shipping_method="CHOSEN", shipping_price=12.0, shipping_title="T")
    assert len(posted) == 1 and posted[0][1]["shipping_method"] == "CHOSEN"
    assert posted[0][1]["shipping_address"]["country_id"] == "US"


def test_strict_rate_mode_never_fabricates_a_method(monkeypatch):
    from app.agents.suppliers import silverbene_adapter
    monkeypatch.setattr("time.sleep", lambda s: None)
    sb = silverbene_adapter.SilverbeneAdapter()
    monkeypatch.setattr(sb, "_post", lambda ep, payload: {"code": 0, "data": []})
    assert sb.get_shipping_methods("DE", products=[{"option_id": "A", "qty": 1}], allow_fallback=False) == []
    assert sb.get_shipping_methods("US", option_id="A")[0]["way"] == "SUX"   # legacy fallback preserved
