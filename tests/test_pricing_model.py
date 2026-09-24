"""Pricing model v0 (review-only): the solved price must leave exactly the target contribution."""
import pytest

from app.checkout_intl import catalog
from app.commerce import pricing_model as pm

COUNTRIES = ("US", "GB", "DE", "FR", "AU", "CA")
RC = catalog.ratecard()


def ship(cc, cls):
    return RC[cc][cls]["max"]


@pytest.mark.parametrize("cc", COUNTRIES)
@pytest.mark.parametrize("w", [5, 10, 40, 100, 300])
def test_solved_price_leaves_exactly_the_target_contribution(cc, w):
    r = pm.solve(pm.MARKETS[cc], w, ship(cc, "express"))
    assert r["contribution"] == pytest.approx(pm.TARGET_CONTRIBUTION, abs=1e-6)
    assert r["net_price"] > w + ship(cc, "express")


@pytest.mark.parametrize("cc", COUNTRIES)
def test_rounding_up_never_drops_below_the_target(cc):
    for w in (7, 13, 29, 57, 111):
        n = pm.solve(pm.MARKETS[cc], w, ship(cc, "express"))["net_price"]
        assert pm.contribution_at(pm.MARKETS[cc], pm.round_up(n), w, ship(cc, "express")) >= pm.TARGET_CONTRIBUTION - 1e-6


def test_vat_is_a_pass_through_not_revenue():
    gb = pm.MARKETS["GB"]
    r = pm.solve(gb, 40, ship("GB", "express"))
    assert r["gross_price"] == pytest.approx(r["net_price"] * 1.20)
    assert r["vat"] == pytest.approx(r["net_price"] * 0.20)
    # VAT enlarges the payment-provider fee base, so the same costs need a higher NET price than a no-VAT market would
    no_vat = pm.Market("XX", "x", 0.0, 0.0, None, 0.0, False, False, "assumed")
    assert r["net_price"] > pm.solve(no_vat, 40, ship("GB", "express"))["net_price"]


def test_eu_flat_duty_replaces_ad_valorem_below_the_threshold_only():
    de = pm.MARKETS["DE"]
    low = pm.duty_cost(de, 40, pm.Params())
    assert low == pytest.approx(3 * pm.EUR_USD)                           # EUR3 flat for a small parcel
    high = pm.duty_cost(de, 300, pm.Params())
    assert high == pytest.approx(300 * 0.025)                             # 2.5% above EUR150


def test_us_duty_range_and_declared_value_sensitivity():
    base = pm.solve(pm.MARKETS["US"], 40, ship("US", "express"))["net_price"]
    low = pm.solve(pm.MARKETS["US"], 40, ship("US", "express"), pm.Params(duty_rate_override={"US": pm.US_DUTY_LOW}))["net_price"]
    retail = pm.solve(pm.MARKETS["US"], 40, ship("US", "express"), pm.Params(declared_basis="retail"))["net_price"]
    assert low < base < retail                                            # worst case: customs uses the selling price


def test_unknown_costs_move_the_price_in_the_expected_direction():
    p = lambda **k: pm.solve(pm.MARKETS["DE"], 40, ship("DE", "express"), pm.Params(**k))["net_price"]
    assert p(supplier_pct=0.03) > p() and p(dtp_fixed=19) > p() and p(reserve_pct=0.05) > p() and p(provider="paypal") > p()


def test_us_standard_is_far_cheaper_than_express_and_target_holds_for_every_class():
    for cc in COUNTRIES:
        e = pm.solve(pm.MARKETS[cc], 40, ship(cc, "express"))
        s = pm.solve(pm.MARKETS[cc], 40, ship(cc, "standard"))
        assert s["net_price"] < e["net_price"]
        assert s["contribution"] == pytest.approx(45, abs=1e-6) == pytest.approx(e["contribution"], abs=1e-6)
    assert ship("US", "standard") == 7.28


def test_assumptions_are_listed_and_every_market_has_a_status():
    assert len(pm.ASSUMPTIONS_TO_VERIFY) >= 8
    assert all(m.status in ("sourced", "assumed", "unverified") for m in pm.MARKETS.values())
