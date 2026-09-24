"""Stage 1B: PayPal (sandbox contract, mocked HTTP), Stripe dynamic methods, compliance policy, tiers persistence."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.checkout_intl import address as addr_mod
from app.checkout_intl import compliance, countries, paypal, rates
from app.checkout_intl import transaction as txn
from conftest import make_product, quoted_tx, valid_address

DHL = {"way": "DHL_X", "title": "DHL Express(3-7 workdays)", "price": 31.5}
POST = {"way": "EPK", "title": "ePacket(15-25 workdays)", "price": 4.2}


# ── fake PayPal HTTP ──────────────────────────────────────────────────────────

class FakePayPal:
    """Records calls; behaves like PayPal Orders v2 incl. idempotent capture replay."""
    def __init__(self):
        self.calls, self.orders, self.captures, self.request_ids = [], {}, {}, []
        self.verify_result = "SUCCESS"
        self.fail_capture = None

    def __call__(self, method, url, json=None, data=None, headers=None, auth=None):
        path = url.split("paypal.com", 1)[1]
        self.calls.append((method, path))
        if rid := (headers or {}).get("PayPal-Request-Id"):
            self.request_ids.append(rid)
        if path == "/v1/oauth2/token":
            return 200, {"access_token": "tok", "expires_in": 3000}
        if path == "/v2/checkout/orders" and method == "POST":
            rid = headers["PayPal-Request-Id"]
            oid = "ORD" + str(abs(hash(rid)) % 10**6)
            self.orders[oid] = {"amount": json["purchase_units"][0]["amount"], "id": oid,
                                "purchase_units": json["purchase_units"]}
            return 201, {"id": oid, "status": "PAYER_ACTION_REQUIRED",
                         "links": [{"rel": "payer-action", "href": f"https://sandbox.paypal.com/approve/{oid}"}]}
        if path.endswith("/capture"):
            oid = path.split("/")[-2]
            if self.fail_capture:
                return self.fail_capture
            if oid in self.captures:
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}
            amt = self.orders[oid]["amount"]
            self.captures[oid] = {"id": "CAP" + oid, "status": "COMPLETED", "amount": amt}
            return 201, self._order_body(oid)
        if path.startswith("/v2/checkout/orders/") and method == "GET":
            return 200, self._order_body(path.split("/")[-1])
        if path.endswith("/refund"):
            return 201, {"id": "REF1", "status": "COMPLETED"}
        if path == "/v1/notifications/verify-webhook-signature":
            return 200, {"verification_status": self.verify_result}
        return 404, {}

    def _order_body(self, oid):
        cap = self.captures.get(oid)
        pu = {"payments": {"captures": [cap]}} if cap else {}
        return {"id": oid, "status": "COMPLETED" if cap else "CREATED", "purchase_units": [pu]}


@pytest.fixture()
def pp(monkeypatch):
    monkeypatch.setenv("INTL_CHECKOUT", "1")
    monkeypatch.setenv("INTL_PAYPAL", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH1")
    fake = FakePayPal()
    real = paypal.PayPalClient
    monkeypatch.setattr(paypal, "PayPalClient", lambda *a, **k: real(*a, http=fake, **k))
    monkeypatch.setattr("app.routes.payments._live_stock_check_many", lambda pairs: None)
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: [DHL, POST])
    fake.processed = []
    monkeypatch.setattr("app.routes.payments.process_order_background", lambda data: fake.processed.append(data))
    monkeypatch.setattr("app.agents.email_partner.send_email", lambda **kw: None)
    return fake


def _start_paypal_checkout(client, session, price=298.0):
    make_product(session, price=price)
    cid = client.post("/checkout/delivery", json={"address": valid_address("US"),
                                                    "items": [{"product_id": 1, "quantity": 1}]}).json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS", "payment_provider": "paypal"})
    assert r.status_code == 200, r.text
    return cid, r.json()["checkout_url"]


# ── PayPal ────────────────────────────────────────────────────────────────────

def test_paypal_unavailable_unless_flagged(client, session, monkeypatch):
    monkeypatch.setenv("INTL_CHECKOUT", "1")
    monkeypatch.setattr("app.routes.payments._live_stock_check_many", lambda pairs: None)
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: [DHL])
    make_product(session)
    cid = client.post("/checkout/delivery", json={"address": valid_address("US"),
                                                    "items": [{"product_id": 1}]}).json()["checkout_id"]
    r = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS", "payment_provider": "paypal"})
    assert r.status_code == 400
    assert "paypal" not in client.get("/checkout/config").json()["payment"]["providers"]


def test_paypal_config_lists_provider_and_live_mode_refused(pp, client, monkeypatch):
    assert "paypal" in client.get("/checkout/config").json()["payment"]["providers"]
    monkeypatch.setenv("PAYPAL_MODE", "live")
    with pytest.raises(paypal.PayPalError):
        paypal.PayPalClient()


def test_create_order_amount_matches_stripe_pricing_and_returns_approval_link(pp, client, session):
    cid, url = _start_paypal_checkout(client, session, price=298.0)
    assert url.startswith("https://sandbox.paypal.com/approve/")
    order = next(iter(pp.orders.values()))
    assert order["amount"]["value"] == "298.00" and order["amount"]["currency_code"] == "USD"
    assert order["purchase_units"][0]["custom_id"] == cid
    assert any(r.startswith(f"mikisi-create-{cid}") for r in pp.request_ids)   # idempotency key present


def test_return_captures_once_verifies_amount_and_fulfills_via_shared_pipeline(pp, client, session):
    cid, url = _start_paypal_checkout(client, session)
    oid = url.rsplit("/", 1)[1]
    r = client.get(f"/checkout/paypal/return?checkout_id={cid}&token={oid}", follow_redirects=False)
    assert r.status_code == 303 and "payment=success" in r.headers["location"]
    assert f"session_id=pp_{oid}" in r.headers["location"]                  # Meta dedupe id
    assert len(pp.processed) == 1
    md = pp.processed[0]["metadata"]
    assert md["checkout_id"] == cid and md["stripe_session_id"] == f"pp_{oid}" and md["is_guest"] == "true"
    assert any(req.startswith("mikisi-capture-") for req in pp.request_ids)


def test_replayed_return_is_idempotent_capture_replays_original(pp, client, session):
    cid, url = _start_paypal_checkout(client, session)
    oid = url.rsplit("/", 1)[1]
    for _ in range(2):
        r = client.get(f"/checkout/paypal/return?checkout_id={cid}&token={oid}", follow_redirects=False)
        assert r.status_code == 303 and "payment=success" in r.headers["location"]
    assert sum(1 for c in pp.calls if c[1].endswith("/capture")) == 2        # PayPal answered the replay...
    assert len(pp.captures) == 1                                              # ...with ONE capture
    keys = {p["metadata"]["stripe_session_id"] for p in pp.processed}
    assert keys == {f"pp_{oid}"}                                              # same pipeline key -> pipeline dedupes


def test_amount_mismatch_is_not_fulfilled(pp, client, session):
    cid, url = _start_paypal_checkout(client, session, price=298.0)
    oid = url.rsplit("/", 1)[1]
    pp.orders[oid]["amount"] = {"currency_code": "USD", "value": "1.00"}       # tampered / drifted
    r = client.get(f"/checkout/paypal/return?checkout_id={cid}&token={oid}", follow_redirects=False)
    assert "payment=success" not in r.headers["location"] and pp.processed == []
    from app.models.checkout_transaction import CheckoutTransaction
    session.expire_all()
    assert session.get(CheckoutTransaction, cid).status == "needs_attention"


def test_capture_failure_redirects_to_failure_and_does_not_fulfill(pp, client, session):
    cid, url = _start_paypal_checkout(client, session)
    oid = url.rsplit("/", 1)[1]
    pp.fail_capture = (422, {"details": [{"issue": "INSTRUMENT_DECLINED"}]})
    r = client.get(f"/checkout/paypal/return?checkout_id={cid}&token={oid}", follow_redirects=False)
    assert r.status_code == 303 and "payment=failed" in r.headers["location"] and pp.processed == []


def test_cancelled_payment_keeps_checkout_payable_and_retry_makes_new_order(pp, client, session):
    cid, url = _start_paypal_checkout(client, session)
    r = client.get(f"/checkout/paypal/cancel?checkout_id={cid}", follow_redirects=False)
    assert r.status_code == 303 and pp.processed == []
    r2 = client.post(f"/checkout/{cid}/pay", json={"shipping_tier": "EXPRESS", "payment_provider": "paypal"})
    assert r2.status_code == 200 and r2.json()["checkout_url"] != url          # attempt counter -> fresh order id
    assert len(pp.orders) == 2


def test_webhook_rejects_bad_signature_and_missing_headers(pp, client):
    ev = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "X"}}
    good_headers = {"paypal-transmission-id": "1", "paypal-transmission-time": "t",
                    "paypal-transmission-sig": "s", "paypal-cert-url": "u", "paypal-auth-algo": "a"}
    assert client.post("/checkout/paypal/webhook", json=ev).status_code == 400              # no signature headers
    pp.verify_result = "FAILURE"
    assert client.post("/checkout/paypal/webhook", json=ev, headers=good_headers).status_code == 400
    assert pp.processed == []


def test_webhook_approved_captures_when_customer_never_returned(pp, client, session):
    cid, url = _start_paypal_checkout(client, session)
    oid = url.rsplit("/", 1)[1]
    headers = {"paypal-transmission-id": "1", "paypal-transmission-time": "t",
               "paypal-transmission-sig": "s", "paypal-cert-url": "u", "paypal-auth-algo": "a"}
    ev = {"event_type": "CHECKOUT.ORDER.APPROVED",
          "resource": {"id": oid, "purchase_units": [{"custom_id": cid}]}}
    assert client.post("/checkout/paypal/webhook", json=ev, headers=headers).status_code == 200
    assert len(pp.processed) == 1 and pp.processed[0]["metadata"]["checkout_id"] == cid


def test_unverifiable_webhook_when_no_webhook_id_configured(pp, client, monkeypatch):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID")
    headers = {"paypal-transmission-id": "1", "paypal-transmission-time": "t",
               "paypal-transmission-sig": "s", "paypal-cert-url": "u", "paypal-auth-algo": "a"}
    assert client.post("/checkout/paypal/webhook", json={"event_type": "X"}, headers=headers).status_code == 400


def test_refund_full_and_partial_are_idempotent_keyed_and_update_status(pp, client, session):
    from app.models.checkout_transaction import CheckoutTransaction
    from app.routes.intl_checkout import refund_checkout
    cid, url = _start_paypal_checkout(client, session)
    oid = url.rsplit("/", 1)[1]
    client.get(f"/checkout/paypal/return?checkout_id={cid}&token={oid}", follow_redirects=False)
    session.expire_all()
    assert session.get(CheckoutTransaction, cid).payment_capture_id == "CAP" + oid
    refund_checkout(session, cid, amount=10.0)
    assert session.get(CheckoutTransaction, cid).status != "refunded"
    refund_checkout(session, cid)
    assert session.get(CheckoutTransaction, cid).status == "refunded"
    assert f"mikisi-refund-CAP{oid}-10.00" in pp.request_ids and f"mikisi-refund-CAP{oid}-full" in pp.request_ids


def test_refund_requires_a_paypal_capture(pp, client, session):
    from app.routes.intl_checkout import refund_checkout
    cid, _ = _start_paypal_checkout(client, session)
    with pytest.raises(ValueError):
        refund_checkout(session, cid)                                       # approved-but-uncaptured


def test_duplicate_payment_across_providers_never_double_fulfills(session, monkeypatch):
    """A PayPal-paid checkout that also gets a Stripe payment must not create a second supplier order."""
    from test_intl_checkout import FakeSilverbene, fulfil_env, _paid_metadata, _locked_au_tx  # noqa: F401
    FakeSilverbene.placed, FakeSilverbene.rate_lookups = [], 0
    monkeypatch.setattr("app.agents.suppliers.silverbene_adapter.SilverbeneAdapter", FakeSilverbene)
    monkeypatch.setattr("app.agents.tracking_agent.create_tracking_entry", lambda **kw: None)
    monkeypatch.setattr("app.agents.order_variant_tracker.check_order_item", lambda **kw: SimpleNamespace(match_status="ok"))
    monkeypatch.setattr("app.agents.order_variant_tracker.send_batched_order_alert", lambda *a, **k: None)
    monkeypatch.setattr("app.agents.email_partner.send_email", lambda **kw: None)
    monkeypatch.setattr("app.routes.payments._send_meta_capi_event", lambda *a, **k: None)
    from app.routes.payments import process_order_background
    monkeypatch.setattr(txn, "default_rate_fetcher", lambda *a: [DHL, POST])
    tx = _locked_au_tx(session)
    process_order_background(_paid_metadata(tx.id, "pp_ORD1"))
    process_order_background(_paid_metadata(tx.id, "cs_stripe_second"))
    assert len(FakeSilverbene.placed) == 1


# ── Stripe dynamic payment methods ────────────────────────────────────────────

def test_stripe_dynamic_mode_omits_payment_method_types(monkeypatch):
    from app.checkout_intl.payment_providers import StripeProvider
    seen = []
    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kw: seen.append(kw) or SimpleNamespace(id="cs", url="u"))
    kw = dict(line_items=[], success_url="s", cancel_url="c", customer_email="e@x.co", metadata={})
    StripeProvider(dynamic=False).create_session(**kw)
    StripeProvider(dynamic=True).create_session(**kw)
    assert seen[0]["payment_method_types"] == ["card"] and "payment_method_types" not in seen[1]


def test_stripe_dynamic_flag_via_env(monkeypatch):
    from app.checkout_intl.payment_providers import StripeProvider
    monkeypatch.setenv("INTL_STRIPE_DYNAMIC_METHODS", "1")
    assert StripeProvider().capabilities.payment_method_types == []
    monkeypatch.delenv("INTL_STRIPE_DYNAMIC_METHODS")
    assert StripeProvider().capabilities.payment_method_types == ["card"]


# ── compliance policy ─────────────────────────────────────────────────────────

def _r(**over):
    base = dict(country="XX", action="block", jurisdiction="Mikisi-policy", source="doc://x", reason="test",
                effective_from="2026-01-01", review_date="2027-01-01")
    base.update(over)
    return base


def test_restriction_requires_full_provenance():
    for missing in ("source", "jurisdiction", "reason", "effective_from", "review_date"):
        bad = _r()
        bad.pop(missing)
        with pytest.raises(ValueError):
            compliance.parse_restriction(bad)
    with pytest.raises(ValueError):
        compliance.parse_restriction(_r(action="allow"))


def test_shipped_policy_is_empty_and_blocks_nothing():
    assert compliance.load_restrictions() == []
    assert not any(compliance.is_blocked(c) for c in countries.LAUNCH_WAVE_1)


def test_blocking_respects_effective_dates_and_removes_market(monkeypatch):
    r = compliance.parse_restriction(_r(country="DE", effective_from="2026-06-01", effective_until="2026-12-01"))
    monkeypatch.setattr(compliance, "load_restrictions", lambda path=None: [r])
    assert not compliance.is_blocked("DE", date(2026, 5, 31))
    assert compliance.is_blocked("de", date(2026, 7, 1))
    assert not compliance.is_blocked("DE", date(2026, 12, 1))
    monkeypatch.setenv("INTL_ENABLED_COUNTRIES", "US,DE")
    monkeypatch.setattr(compliance, "is_blocked", lambda c, today=None: c == "DE")
    assert countries.enabled_country_codes() == {"US"}


def test_overdue_reviews_are_reported(monkeypatch):
    r = compliance.parse_restriction(_r(review_date="2026-01-02"))
    monkeypatch.setattr(compliance, "load_restrictions", lambda path=None: [r])
    assert compliance.overdue_reviews(date(2026, 9, 1)) == [r]


# ── tiers persisted & exposure gating ─────────────────────────────────────────

def test_both_tiers_always_persisted_even_when_only_one_is_offered(session, monkeypatch):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    tx = quoted_tx(session, a, items, fetcher=lambda *x: [DHL, POST])
    assert {o["tier"] for o in txn.load_options(tx)} == {"STANDARD", "EXPRESS"}
    assert [o["tier"] for o in txn.offered_options(tx)] == ["EXPRESS"]               # frozen exposure
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "STANDARD")                               # not offered -> refused


def test_both_exposure_allows_choosing_standard_and_locks_that_method(session, monkeypatch):
    monkeypatch.setenv("INTL_TIER_EXPOSURE", "both")
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    tx = quoted_tx(session, a, items, fetcher=lambda *x: [DHL, POST])
    assert [o["tier"] for o in txn.offered_options(tx)] == ["STANDARD", "EXPRESS"]
    tx = txn.lock_for_payment(session, tx, "STANDARD")
    assert (tx.shipping_method_id, tx.shipping_tier, tx.shipping_supplier_price) == ("EPK", "STANDARD", 4.2)


def test_requote_when_tier_maps_to_a_different_method(session):
    make_product(session)
    a = addr_mod.StructuredAddress(**valid_address("US"))
    items = [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}]
    tx = quoted_tx(session, a, items, fetcher=lambda *x: [DHL, POST])
    txn.view_options(session, tx)
    later = tx.quote_expires_at + timedelta(minutes=1)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "EXPRESS", now=later)
    txn.run_quote(tx.id, lambda *x: [{"way": "FEDEX_1", "title": "FedEx International Priority", "price": 31.5}])
    session.expire_all()
    tx = session.get(type(tx), tx.id)
    with pytest.raises(txn.RequoteRequired):
        txn.lock_for_payment(session, tx, "EXPRESS")
