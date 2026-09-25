"""Pricing model v1 (review-only): one worldwide price paying for DHL Express, no tax collection."""
import pytest

from app.checkout_intl import catalog
from app.commerce import pricing_model as pm

COUNTRIES = ("US", "GB", "DE", "FR", "AU", "CA")
RC = catalog.ratecard()
EXPRESS = {cc: RC[cc]["express"]["max"] for cc in COUNTRIES}
MODES = ("prepaid", "receiver_pays")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("cc", COUNTRIES)
@pytest.mark.parametrize("w", [5, 10, 40, 100, 300])
def test_solved_price_leaves_exactly_the_target_contribution(cc, w, mode):
    r = pm.solve(pm.MARKETS[cc], w, EXPRESS[cc], pm.Params(tax_mode=mode))
    assert r["contribution"] == pytest.approx(pm.TARGET_CONTRIBUTION, abs=1e-6)
    assert r["price"] > w + EXPRESS[cc]


@pytest.mark.parametrize("cc", COUNTRIES)
def test_rounding_up_never_drops_below_the_target(cc):
    for w in (7, 13, 29, 57, 111):
        p = pm.solve(pm.MARKETS[cc], w, EXPRESS[cc])["price"]
        assert pm.contribution_at(pm.MARKETS[cc], pm.round_up(p), w, EXPRESS[cc]) >= pm.TARGET_CONTRIBUTION - 1e-6


def test_there_is_no_tax_collection_mode():
    with pytest.raises(ValueError):
        pm.solve(pm.MARKETS["GB"], 40, EXPRESS["GB"], pm.Params(tax_mode="collect"))
    assert "vat_rate" not in pm.Market.__dataclass_fields__ and "vat_registered" not in pm.Market.__dataclass_fields__


def test_prepaid_builds_duty_and_import_vat_into_the_price_and_the_customer_pays_nothing_at_the_door():
    gb_pre = pm.solve(pm.MARKETS["GB"], 40, EXPRESS["GB"], pm.Params(tax_mode="prepaid"))
    gb_rec = pm.solve(pm.MARKETS["GB"], 40, EXPRESS["GB"], pm.Params(tax_mode="receiver_pays"))
    assert gb_pre["door_bill"] == 0 and gb_pre["import_vat_borne"] == pytest.approx(0.20 * (40 + EXPRESS["GB"]))
    assert gb_pre["price"] > gb_rec["price"]                          # prepaying costs Mikisi -> higher price
    assert gb_rec["door_bill"] == pytest.approx(0.20 * (40 + EXPRESS["GB"])) and gb_rec["import_vat_borne"] == 0


def test_receiver_pays_door_bill_is_the_customers_surprise_and_is_zero_where_nothing_is_due():
    au = pm.solve(pm.MARKETS["AU"], 40, EXPRESS["AU"], pm.Params(tax_mode="receiver_pays"))
    assert au["door_bill"] == 0                                        # <= A$1,000 generally exempt (unverified)
    de = pm.solve(pm.MARKETS["DE"], 40, EXPRESS["DE"], pm.Params(tax_mode="receiver_pays", courier_handling_fee=10))
    flat = 3 * pm.EUR_USD
    assert de["door_bill"] == pytest.approx(flat + 0.19 * (40 + EXPRESS["DE"] + flat) + 10)


def test_eu_flat_duty_replaces_ad_valorem_below_the_threshold_only():
    de = pm.MARKETS["DE"]
    assert pm.duty_cost(de, 40, pm.Params()) == pytest.approx(3 * pm.EUR_USD)
    assert pm.duty_cost(de, 300, pm.Params()) == pytest.approx(300 * 0.025)


def test_us_duty_range_and_declared_value_sensitivity():
    us = lambda **k: pm.solve(pm.MARKETS["US"], 40, EXPRESS["US"], pm.Params(**k))["price"]
    assert us(duty_rate_override={"US": pm.US_DUTY_LOW}) < us() < us(declared_basis="retail")


def test_unknown_costs_move_the_price_in_the_expected_direction():
    p = lambda **k: pm.solve(pm.MARKETS["DE"], 40, EXPRESS["DE"], pm.Params(**k))["price"]
    assert p(supplier_pct=0.03) > p() and p(dtp_fixed=19) > p() and p(reserve_pct=0.05) > p() and p(provider="stripe") < p()


@pytest.mark.parametrize("mode", MODES)
def test_one_global_price_meets_the_target_everywhere_and_the_costliest_country_drives_it(mode):
    prm = pm.Params(tax_mode=mode)
    for w in (10, 40, 100):
        g = pm.global_price(w, EXPRESS, prm)
        assert all(profit >= pm.TARGET_CONTRIBUTION - 1e-6 for profit in g["profit_at_price"].values())
        assert g["driver"] == max(g["required"], key=g["required"].get)
        assert g["price"] >= max(g["required"].values()) - 1e-9
        assert min(g["profit_at_price"].values()) == pytest.approx(pm.TARGET_CONTRIBUTION, abs=1.0)   # the driver is ~exact
    assert pm.global_price(40, EXPRESS, prm)["driver"] in ("US", "DE", "FR")   # US duty already inside the quote: no longer alone at the top


def test_assumptions_are_listed_and_every_market_has_a_status():
    assert len(pm.ASSUMPTIONS_TO_VERIFY) >= 8
    assert all(m.status in ("sourced", "assumed", "unverified") for m in pm.MARKETS.values())


@pytest.mark.parametrize("mode", MODES)
def test_split_one_item_price_plus_country_specific_dhl_fee_meets_the_target_everywhere(mode):
    prm = pm.Params(tax_mode=mode)
    for w in (10, 20, 40, 100, 150):
        parts = {cc: pm.split(pm.MARKETS[cc], w, EXPRESS[cc], prm) for cc in COUNTRIES}
        assert len({p["item_price"] for p in parts.values()}) == 1                       # the item price is ONE
        for cc, p in parts.items():
            assert p["contribution"] >= pm.TARGET_CONTRIBUTION - 1e-6, (cc, w, p)
            assert p["total"] == p["item_price"] + p["delivery_fee"] and p["delivery_fee"] > 0
        fees = {cc: p["delivery_fee"] for cc, p in parts.items()}
        assert fees["AU"] == min(fees.values()) and max(fees.values()) in (fees["US"], fees["DE"], fees["FR"])   # fee follows DHL cost + duty


def test_split_delivery_fee_reflects_dhl_cost_and_prepaid_taxes():
    pre = pm.split(pm.MARKETS["GB"], 40, EXPRESS["GB"], pm.Params(tax_mode="prepaid"))
    rec = pm.split(pm.MARKETS["GB"], 40, EXPRESS["GB"], pm.Params(tax_mode="receiver_pays"))
    assert pre["item_price"] == rec["item_price"] and pre["delivery_fee"] > rec["delivery_fee"] > EXPRESS["GB"]


def test_us_duty_already_inside_the_dhl_quote_is_not_charged_twice():
    us, w = pm.MARKETS["US"], 40
    low = pm.solve(us, w, EXPRESS["US"], pm.Params(duty_rate_override={"US": pm.US_DUTY_LOW}))
    assert low["duty_borne"] == 0                                              # the whole 22.5% is inside the quote
    high = pm.solve(us, w, EXPRESS["US"])
    assert high["duty_borne"] == pytest.approx(w * (pm.US_DUTY_HIGH - pm.US_DUTY_LOW))   # only the excess is added
