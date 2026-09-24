"""Stage 1 international checkout qualification. No real supplier/Stripe calls are made."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.checkout_intl import address as addr_mod
from app.checkout_intl import countries, rates
from app.checkout_intl import transaction as txn
from conftest import make_product, quoted_tx, valid_address

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


def test_other_and_garbage_are_not_countries():
    for bad in ("other", "", "XX", "USA"):
        assert countries.get_market(bad) is None
        assert not countries.is_checkout_country(bad)


def test_launch_waves_and_removed_markets():
    assert countries.LAUNCH_WAVE_1 == ("US", "GB", "DE", "FR", "AU", "CA")
    assert countries.LAUNCH_WAVE_2_CANDIDATE == ("CH", "JP", "SG", "NZ")
    # All six Wave-1 markets are enabled by default (owner decision); NG/GH are inert ISO records.
    assert set(countries.enabled_country_codes()) == set(countries.LAUNCH_WAVE_1)
    for code in ("NG", "GH"):
        m = countries.get_market(code)
        assert m is not None and not m.checkout_enabled and not countries.is_checkout_country(code)
    assert "NG" not in {m.iso_country_code for m in countries.checkout_markets()}


def test_no_unsourced_country_constants_in_core_policy():
    import inspect
    src = inspect.getsource(countries)
    for code in ('"KP"', '"IR"', '"CU"', '"SY"'):
        assert code not in src
    assert not hasattr(countries, "NEVER_ENABLE")


def test_enabling_a_market_is_config_only(monkeypatch):
    monkeypatch.setattr("app.agents.store_config.get_config", lambda k, default=None: "US,DE,JP")
    assert countries.is_checkout_country("JP") and countries.is_checkout_country("DE")
    assert not countries.is_checkout_country("CA")


def test_probed_unsupported_market_is_hidden(monkeypatch):
    monkeypatch.setattr(countries, "_probe_cache", {"US": {"supplier_supported": False}})
    assert not countries.is_checkout_country("US")


@pytest.mark.parametrize("cc", ["US", "CA", "GB", "AU"])
def test_valid_addresses_pass_when_enabled(cc):
    assert addr_mod.validate(addr_mod.StructuredAddress(**valid_address(cc))) is None


@pytest.mark.parametrize("cc", ["DE", "FR", "JP"])
def test_eu_and_asia_addresses_pass_once_market_enabled(cc, monkeypatch):
    monkeypatch.setattr("app.agents.store_config.get_config", lambda k, default=None: "DE,FR,JP")
    assert addr_mod.validate(addr_mod.StructuredAddress(**valid_address(cc))) is None


def test_invalid_postcode_missing_phone_and_missing_state():
    bad_zip = addr_mod.StructuredAddress(**valid_address("US", postal_code="ABC"))
    assert "zip" in addr_mod.validate(bad_zip).lower() and "ZIP code" in addr_mod.validate(bad_zip)
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


def test_tiers_frozen_exposure_offers_one_express_and_both_mode_offers_two(monkeypatch):
    opts = rates.normalize([DHL, EPACKET])
    assert {o["method_id"]: o["tier"] for o in opts} == {"DHL_X": "EXPRESS", "EPK": "STANDARD"}
    assert [o["method_id"] for o in rates.present(opts)] == ["DHL_X"]           # frozen (default)
    only_epacket = rates.present(rates.normalize([EPACKET]))
    assert only_epacket[0]["method_id"] == "EPK" and only_epacket[0]["fallback"] is True
    monkeypatch.setenv("INTL_TIER_EXPOSURE", "both")
    assert [o["method_id"] for o in rates.present(opts)] == ["EPK", "DHL_X"]
    assert rates.present([]) == []


@pytest.mark.parametrize("title,expected", [
    ("DHL Express(3-7 workdays)", "EXPRESS"), ("DHL Global Mail(5-9 workdays)", "STANDARD"),
    ("Economic Express(8-15 workdays)", "STANDARD"), ("FedEx International Priority", "EXPRESS"),
    ("ePacket(15-25 workdays)", "STANDARD"), ("Hermes(4-10 workdays)", "STANDARD"),
    ("La Poste(4-8 workdays)", "STANDARD"), ("Canada Post(5-10 workdays)", "STANDARD"),
    ("Australia Post(6-10 workdays)", "STANDARD"), ("USPS(5-10 workdays)", "STANDARD"),
    ("Mystery Air(3-5 workdays)", "EXPRESS"), ("Mystery Boat(30-40 workdays)", "STANDARD"),
])
def test_tier_classification(title, expected):
    assert rates.classify_tier(title, "X", rates.parse_eta(title)) == expected


def test_tier_override_wins(monkeypatch):
    monkeypatch.setitem(rates.TIER_OVERRIDES, ("DE", "W1"), "STANDARD")
    assert rates.classify_tier("DHL Express", "W1", None, "DE") == "STANDARD"


def test_customer_view_hides_supplier_cost_and_route_wording():
    v = rates.customer_view(rates.normalize([DHL])[0])
    assert "supplier_price" not in v and "31.5" not in json.dumps(v)
    assert v["customer_price"] == 0.0 and "Silverbene" not in json.dumps(v)
    assert "DHL" not in json.dumps(v) and v["tier"] == "EXPRESS"       # neither carrier names nor supplier ids reach the customer


# ── endpoints ─────────────────────────────────────────────────────────────────

def test_flag_defaults_off(client):
    assert client.get("/checkout/config").json() == {"enabled": False}
    r = client.post("/checkout/delivery", json={"address": valid_address("US"), "items": []})
    assert r.status_code == 404


def test_config_lists_only_enabled_markets(client, flag_on):
    cfg = client.get("/checkout/config").json()
    codes = {m["code"] for m in cfg["markets"]}
    assert cfg["enabled"] and codes == set(countries.DEFAULT_ENABLED) and "other" not in codes


class _Resp:
    def __init__(self, status_code, data):
        self.status_code, self._d = status_code, data
        self.text = json.dumps(data)

    def json(self):
        return self._d


def _delivery(client, country="US", items=None, **addr):
    """Delivery is async: POST returns pending (background task runs), then poll /options."""
    r = client.post("/checkout/delivery", json={
        "address": valid_address(country, **addr),
        "items": items or [{"product_id": 1, "quantity": 1}]})
    if r.status_code != 200:
        return r
    cid = r.json()["checkout_id"]
    assert r.json()["status"] == "pending" and "options" not in r.json()
    o = client.get(f"/checkout/{cid}/options")
    return _Resp(o.status_code, o.json())


def test_domestic_and_international_quote_uses_real_cart_and_destination(
        client, session, flag_on, fake_rates, stock_ok):
    make_product(session)
    for cc, postal in (("US", "10001"), ("CA", "K1A 0B1"), ("GB", "SW1A 2AA"), ("AU", "2000")):
        r = _delivery(client, cc)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [o["tier"] for o in body["options"]] == ["EXPRESS"]
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
    assert r.json()["status"] == "unavailable" and "can't offer delivery" in r.json()["message"]
    assert r.json()["options"] == []
    # ...and such a checkout can never reach a payment provider
    pay = client.post(f"/checkout/{r.json()['checkout_id']}/pay", json={"shipping_tier": "EXPRESS"})
    assert pay.status_code == 409 and pay.json()["detail"]["code"] == "requote"


def test_supplier_failure_fails_closed_as_unavailable(client, session, flag_on, monkeypatch, stock_ok):
    make_product(session)
    def boom(*a):
        raise TimeoutError("supplier timed out")
    monkeypatch.setattr(txn, "default_rate_fetcher", boom)
    r = _delivery(client, "US")
    assert r.json()["status"] == "unavailable"
    from app.models.checkout_transaction import CheckoutTransaction
    session.expire_all()
    assert "TimeoutError" in session.get(CheckoutTransaction, r.json()["checkout_id"]).quote_error


def test_delivery_post_returns_immediately_while_quote_is_pending(client, session, flag_on, stock_ok, monkeypatch):
    make_product(session)
    started = []
    monkeypatch.setattr(txn, "run_quote", lambda cid, fetcher=None: started.append(cid))   # simulate slow supplier
    r = client.post("/checkout/delivery", json={"address": valid_address("US"), "items": [{"product_id": 1}]})
    cid = r.json()["checkout_id"]
    assert r.json() == {"checkout_id": cid, "status": "pending"} and started == [cid]
    assert client.get(f"/checkout/{cid}/options").json()["status"] == "pending"
    pay = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS"})
    assert pay.status_code == 409 and pay.json()["detail"]["pending"] is True


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

def _quoted(session, fake_rates=None, methods=None):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    return quoted_tx(session, a, items, fetcher=fetcher_returning(methods or [DHL, EPACKET]))


def test_lock_records_exact_method_and_supplier_snapshot(session, fake_rates):
    tx = txn.lock_for_payment(session, _quoted(session), "EXPRESS")
    assert (tx.status, tx.shipping_method_id, tx.shipping_supplier_price) == ("locked", "DHL_X", 31.5)
    assert tx.presentment_currency == "USD" and tx.supplier_settlement_currency == "USD"


def test_selecting_an_unoffered_tier_requires_requote(session, fake_rates):
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, _quoted(session), "STANDARD")        # frozen exposure offers EXPRESS only


def test_expired_quote_is_refreshed_in_background_never_inline(session, fake_rates):
    tx = _quoted(session)
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired) as e:
        txn.lock_for_payment(session, tx, "EXPRESS", now=later)
    assert e.value.pending and tx.status == "quoting" and tx.shipping_method_id is None
    txn.run_quote(tx.id, fetcher_returning([DHL]))                              # the background job finishes
    session.expire_all()
    tx = session.get(type(tx), tx.id)
    assert tx.status == "quoted" and tx.quote_expires_at > datetime.utcnow()
    assert txn.lock_for_payment(session, tx, "EXPRESS").shipping_method_id == "DHL_X"


def test_price_change_after_refresh_is_shown_and_never_silently_locked(session, fake_rates):
    tx = _quoted(session)
    assert txn.view_options(session, tx)["changed"] is False                   # customer saw $31.5 EXPRESS
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "EXPRESS", now=later)
    txn.run_quote(tx.id, fetcher_returning([dict(DHL, price=71.5)]))
    session.expire_all()
    tx = session.get(type(tx), tx.id)
    with pytest.raises(txn.RequoteRequired) as e:                                # client that skipped /options
        txn.lock_for_payment(session, tx, "EXPRESS")
    assert e.value.options[0]["supplier_price"] == 71.5 and tx.shipping_method_id is None
    tx = txn.lock_for_payment(session, tx, "EXPRESS")                          # after being shown the new offer
    assert tx.shipping_supplier_price == 71.5


def test_options_view_flags_changes_so_the_ui_can_require_a_fresh_choice(session, fake_rates):
    tx = _quoted(session)
    txn.view_options(session, tx)
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "EXPRESS", now=later)
    txn.run_quote(tx.id, fetcher_returning([dict(DHL, way="DHL_Y")]))            # a different supplier method
    session.expire_all()
    tx = session.get(type(tx), tx.id)
    v = txn.view_options(session, tx)
    assert v["status"] == "ready" and v["changed"] is True
    assert txn.view_options(session, tx)["changed"] is False                    # seen now


def test_method_becoming_unavailable_after_expiry_fails_closed(session, fake_rates):
    tx = _quoted(session)
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "EXPRESS", now=later)
    txn.run_quote(tx.id, fetcher_returning([]))
    session.expire_all()
    tx = session.get(type(tx), tx.id)
    assert tx.status == "unavailable" and txn.view_options(session, tx)["status"] == "unavailable"
    with pytest.raises(ValueError):
        txn.lock_for_payment(session, tx, "EXPRESS")


def test_ambiguous_supplier_method_id_is_flagged_and_keeps_the_dearer_service():
    opts = rates.normalize([
        {"way": "ITDIDA_ECO", "title": "International Economy(10-15 workdays)", "price": 3.5},
        {"way": "ITDIDA_ECO", "title": "International Standard(12-20 workdays)", "price": 5.52},
        {"way": "DHLI", "title": "DHL Express(4 - 9 workdays, customs duty included)", "price": 53.24}], "US")
    eco = next(o for o in opts if o["method_id"] == "ITDIDA_ECO")
    assert eco["ambiguous_method_id"] and eco["supplier_price"] == 5.52
    assert eco["alternatives"] == [{"title": "International Economy(10-15 workdays)", "price": 3.5}]
    assert next(o for o in opts if o["method_id"] == "DHLI")["tier"] == "EXPRESS"
    assert eco["tier"] == "STANDARD"


def test_real_silverbene_titles_parse_eta_with_spaces_and_duty_note():
    assert rates.parse_eta("DHL Express(4 - 9 workdays, customs duty included)")["text"] == "4–9 business days"
    assert rates.parse_eta("International Standard(12-20 workdays)")["min_days"] == 12


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
    assert client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS"}).status_code == 200
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
    p = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS"})
    text = d.text + p.text
    for leak in ("pay_url", "31.5", "silverbene", "amount_due"):
        assert leak not in text.lower()


def test_pay_requote_is_409_with_fresh_options(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "STANDARD"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "requote"
    assert stripe_spy.calls == []


def test_completed_checkout_cannot_be_paid_again(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    from app.checkout_intl import fulfillment
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS"})
    fulfillment.mark_paid(cid, "cs_test_1")
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS"})
    assert r.status_code == 409


def test_paypal_slot_is_declared_but_disabled(client, session, flag_on, fake_rates, stock_ok, stripe_spy):
    make_product(session)
    cid = _delivery(client, "US").json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS", "payment_provider": "paypal"})
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
    tx = quoted_tx(session, a, items, fetcher=fetcher_returning([DHL, EPACKET]))
    return txn.lock_for_payment(session, tx, "EXPRESS")


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


def test_frozen_exposure_prefers_dhl_over_a_cheaper_express_carrier():
    """Real probe evidence: FedEx is cheaper than DHL to GB/DE/FR; the standing rule is DHL."""
    opts = rates.normalize([
        {"way": "DHL", "title": "DHL Express(4 - 9 workdays)", "price": 49.37},
        {"way": "Fedex", "title": "FedEx(4 - 9 workdays)", "price": 32.13},
        {"way": "cainiao", "title": "Cainiao International", "price": 15.57}], "DE")
    assert [o["method_id"] for o in rates.present(opts)] == ["DHL"]
    no_dhl = [o for o in opts if o["method_id"] != "DHL"]
    assert [o["method_id"] for o in rates.present(no_dhl)] == ["Fedex"]


def test_quote_fetch_uses_long_supplier_timeout_and_single_attempt(monkeypatch):
    """Silverbene's rate call takes 6-110 s (median ~51 s); a 30 s cutoff made real checkouts fail."""
    from app.agents.suppliers import silverbene_adapter
    seen = {}

    def fake_post(self, endpoint, payload, timeout=30):
        seen.setdefault("calls", []).append(timeout)
        return {"code": 0, "data": [{"way": "DHLI", "title": "DHL Express(4 - 9 workdays)", "price": 50}]}

    monkeypatch.setattr(silverbene_adapter.SilverbeneAdapter, "_post", fake_post)
    out = txn.default_rate_fetcher("US", "60640", "Chicago", [{"option_id": "1", "qty": 1}])
    assert out and seen["calls"] == [txn.RATE_TIMEOUT_SECONDS] and txn.RATE_TIMEOUT_SECONDS >= 120


def test_supplier_timeout_yields_unavailable_after_one_attempt_not_two(monkeypatch):
    from app.agents.suppliers import silverbene_adapter
    calls = []
    monkeypatch.setattr(silverbene_adapter.SilverbeneAdapter, "_post",
                        lambda self, ep, payload, timeout=30: calls.append(timeout) or {})
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert txn.default_rate_fetcher("US", "60640", "Chicago", [{"option_id": "1", "qty": 1}]) == []
    assert len(calls) == 1
