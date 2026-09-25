import pytest

from app.agents.jewelry_pricing import calculate_mikisi_price
from app.commerce import flat_pricing as fp
from app.checkout_intl import rates


def test_default_off_keeps_the_ladder(monkeypatch):
    monkeypatch.delenv("PRICING_MODEL", raising=False)
    assert calculate_mikisi_price(20)["final_price"] == 228.0        # ladder, unchanged


def test_flat_price_leaves_the_target_at_every_price_point(monkeypatch):
    monkeypatch.setenv("PRICING_MODEL", "flat_v2")
    for w in (5, 12, 20, 40, 100, 300, 800):
        price = calculate_mikisi_price(w)["final_price"]
        assert price == fp.item_price(w) and price == int(price)
        assert fp.profit_standard(price, w) >= 45.0          # percentage payment fee: profit holds when price grows
        assert fp.profit_standard(price, w) < 46.5           # ...and is not wildly over target


def test_us_express_is_the_full_dhl_price_driven_by_wholesale():
    assert fp.express_price("US", 6, 64.73) == 54.0 and fp.express_price("US", 40, 64.73) == 61.0
    assert fp.express_price("US", 100, 64.73) > fp.express_price("US", 40, 64.73)
    assert fp.express_price("GB", 40, 45.89) == 46.0


def test_customer_view_shows_price_only_when_charged():
    free = rates.customer_view({"method_id": "STANDARD", "tier": "STANDARD", "name": "Standard delivery", "eta": None})
    paid = rates.customer_view({"method_id": "EXPRESS", "tier": "EXPRESS", "name": "Express delivery (DHL)", "eta": None,
                                "customer_price": 61.0})
    assert free["customer_price"] == 0.0 and free["included"] is True
    assert paid["customer_price"] == 61.0 and paid["included"] is False


# ── through the real checkout path ───────────────────────────────────────────

def _flat_checkout(session, monkeypatch, country="US"):
    from conftest import make_product, quoted_tx, valid_address
    from app.checkout_intl import address as addr_mod, catalog
    monkeypatch.setenv("PRICING_MODEL", "flat_v2")
    monkeypatch.delenv("INTL_TIER_EXPOSURE", raising=False)
    monkeypatch.delenv("INTL_QUOTE_SOURCE", raising=False)
    catalog.reset_cache()
    make_product(session, pid=1, cost=40.0, price=fp.item_price(40.0))
    a = addr_mod.StructuredAddress(**valid_address(country))
    return quoted_tx(session, a, [{"product_id": 1, "quantity": 1, "supplier_option_id": "OPT1"}])


def test_standard_is_free_and_express_is_charged_as_a_separate_line(session, monkeypatch):
    from app.checkout_intl import transaction as txn
    from app.routes import intl_checkout as ic
    tx = _flat_checkout(session, monkeypatch)
    view = {o["tier"]: rates.customer_view(o) for o in txn.offered_options(tx)}
    assert view["STANDARD"]["customer_price"] == 0.0 and view["EXPRESS"]["customer_price"] == 61.0   # 51.83 + 22.5% x 40

    tx = txn.lock_for_payment(session, tx, "STANDARD")
    lines, _, _, value = ic._order_lines(session, tx)
    assert len(lines) == 1 and value == fp.item_price(40.0)

    tx.status = "quoted"
    session.add(tx)
    session.commit()
    tx = txn.lock_for_payment(session, tx, "EXPRESS")
    lines, _, _, value = ic._order_lines(session, tx)
    assert lines[-1]["price_data"]["unit_amount"] == 6100 and value == fp.item_price(40.0) + 61.0
