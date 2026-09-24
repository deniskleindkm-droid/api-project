"""
International pricing model v1 (REVIEW ONLY -- nothing here is wired into live pricing).

Owner decisions (2026-09-24):
  * clean profit (contribution) of $45 on every order;
  * ONE price per product worldwide;
  * the price pays for DHL EXPRESS shipping (Standard is not part of the pricing);
  * Mikisi holds NO VAT/GST registration anywhere and does NOT collect tax at checkout.

Per order, in USD (all amounts before the customer's own border taxes):

  contribution = P - W - ship - duty_borne - import_vat_borne - supplier_fees - payment_fees - reserve

    P             the price the customer pays Mikisi (one worldwide price)
    W             Silverbene wholesale cost of the items
    ship          Silverbene DHL Express cost, cost basis = the MAXIMUM observed price (checkout_intl/catalog.py)
    duty          import duty on the DECLARED value (assumed = wholesale)
    payment_fees  card/PayPal fee on the full amount charged; reserve = refunds/chargebacks/lost parcels, % of P

TAX MODES (no collection, so only two):
  "prepaid"        DDP: Mikisi pays duty AND import VAT up front (DHL duty-tax-paid) on (declared + shipping + duty).
                   Unregistered, that VAT is an unrecoverable cost, so it is BUILT INTO the price; the customer
                   pays nothing extra at the door.
  "receiver_pays"  Nothing prepaid: the customer pays duty + VAT/GST (+ the courier's handling fee) to the courier
                   at the door -- Mikisi's cost is lower (price is lower) but the customer gets a surprise bill
                   (`door_bill`): refused parcels, chargebacks, bad reviews.

Closed form (linear in P):   P = (target + W + ship + duty_borne + vat_borne + fixed) / (1 - pay_pct - reserve - supplier_pct)

EVERY input carries a `status`: "sourced" (a public source was read), "assumed" (owner statement / conservative
default) or "unverified" (could not confirm). See ASSUMPTIONS_TO_VERIFY.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TARGET_CONTRIBUTION = 45.00       # owner: "$45 clean profit"
EUR_USD = 1.17                    # planning rate for the EU EUR3 flat duty / EUR150 threshold
LADDER_STEP = 1.0                 # round UP to whole dollars (charm pricing is a later choice)


@dataclass(frozen=True)
class PaymentCosts:
    pct: float
    fixed: float
    status: str
    note: str = ""


# Published pricing as generally known -- NOT re-verified in this session.
STRIPE_DOMESTIC = PaymentCosts(0.029, 0.30, "unverified", "Stripe US cards 2.9% + $0.30")
STRIPE_INTERNATIONAL = PaymentCosts(0.044, 0.30, "unverified", "2.9% + 1.5% international card surcharge + $0.30")
PAYPAL_DOMESTIC = PaymentCosts(0.0349, 0.49, "unverified", "PayPal US 3.49% + $0.49")
PAYPAL_INTERNATIONAL = PaymentCosts(0.0499, 0.49, "unverified", "PayPal international 4.99% + $0.49")


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    duty_rate: float                      # ad valorem, on the declared value
    duty_flat_per_item: float             # USD per item (EU low-value flat duty)
    flat_applies_below: Optional[float]   # declared value (USD) under which the flat duty replaces ad valorem
    import_tax_rate: float                # VAT/GST charged AT THE BORDER on (declared + shipping + duty)
    payment_domestic: bool                # True -> domestic card rates
    status: str                           # sourced | assumed | unverified
    notes: List[str] = field(default_factory=list)


# US duty: the sources conflict. LOW = the Silverbene reference stack quoted to the owner (22.5%); HIGH = base ~6.3%
# + Section 301 25% + the 12.5% Section 301 tariff of 2026-07-24 = 43.8%. Default HIGH (safe) until confirmed.
US_DUTY_LOW, US_DUTY_HIGH = 0.225, 0.438

MARKETS: Dict[str, Market] = {
    "US": Market("US", "United States", US_DUTY_HIGH, 0.0, None, 0.0, True, "unverified", [
        "De minimis suspended (Federal Register 2026-06-24). Duty stack for China-origin silver jewelry uncertain: 22.5%-43.8%.",
        "Owner's DHL sample was charged duty at delivery despite 'customs duty included' -> duty is a real cost.",
        "US state sales tax not modelled (economic-nexus thresholds not reached; revisit as volume grows)."]),
    "GB": Market("GB", "United Kingdom", 0.0, 0.0, None, 0.20, False, "sourced", [
        "Duty relief on consignments <= GBP135 (2% otherwise) until 2029 (GOV.UK).",
        "VAT 20% is charged on import when the seller has not charged it at checkout (unregistered seller)."]),
    "DE": Market("DE", "Germany", 0.025, 3.0 * EUR_USD, 150.0 * EUR_USD, 0.19, False, "sourced", [
        "EU flat EUR3 duty per item on parcels < EUR150 from 2026-07-01 (until 2028-07-01); 2.5% above (TARIC).",
        "Import VAT 19% is charged at the border when the seller has no IOSS registration."]),
    "FR": Market("FR", "France", 0.025, 3.0 * EUR_USD, 150.0 * EUR_USD, 0.20, False, "sourced", [
        "Same EU rules as Germany; import VAT 20%."]),
    "AU": Market("AU", "Australia", 0.0, 0.0, None, 0.0, False, "unverified", [
        "Imports <= A$1,000 are generally duty/GST free at the border; overseas sellers only register for GST at A$75,000 "
        "of Australian sales (ATO). A 5% duty on finished jewelry was NOT confirmed for <= A$1,000.",
        "Modelled as 0 -- monitor Australian sales against the threshold."]),
    "CA": Market("CA", "Canada", 0.08, 0.0, None, 0.13, False, "unverified", [
        "China-origin courier duty-free limit is only CAD 20; jewelry duty 6.5-8% (CBSA); 8% used.",
        "GST 5% + provincial tax 0-10% on duty-paid value at import; 13% (Ontario HST) used as a planning value."]),
}

ASSUMPTIONS_TO_VERIFY = [
    "TARGET: $45 is per ORDER (a cart), not per item; the shipping cost basis is single-item.",
    "Silverbene's own fees/taxes on an order (e.g. a fee when paying by card/PayPal on their page) -- unknown, modelled 0.",
    "Customs declared value = Silverbene's invoice value (wholesale). Customs may instead use the price the customer paid "
    "(see the 'retail declared value' sensitivity) -- ask Silverbene what they declare, and get a customs broker's view.",
    "US duty stack (22.5% vs 43.8%) -- confirm the HS code and declared value with Silverbene/DHL or a customs broker.",
    "Whether DHL's duty-and-tax-paid fee (Europe: 2%, min ~EUR16.50) applies to shipments Silverbene books -- modelled 0.",
    "Whether a Silverbene DHL shipment can actually be booked duty-and-tax-PREPAID (the 'prepaid' mode) -- unconfirmed.",
    "Payment provider rates (Stripe 2.9%+30c, +1.5% international; PayPal 3.49%+49c / 4.99%+49c) -- not re-verified.",
    "Reserve for refunds/chargebacks/lost parcels: 2% of price (assumed).",
]


@dataclass
class Params:
    target: float = TARGET_CONTRIBUTION
    reserve_pct: float = 0.02
    supplier_pct: float = 0.0          # Silverbene fee as % of price (unknown)
    supplier_fixed: float = 0.0
    dtp_fixed: float = 0.0             # DHL duty/tax processing fee per order, prepaid mode (unknown)
    duty_rate_override: Optional[Dict[str, float]] = None
    declared_basis: str = "wholesale"  # or "retail" (sensitivity: customs uses the selling price)
    provider: str = "stripe"           # or "paypal"
    items: int = 1
    tax_mode: str = "prepaid"          # "prepaid" | "receiver_pays"
    courier_handling_fee: float = 0.0  # courier's fee to the receiver on a duty-unpaid parcel (unknown)


def payment_costs(market: Market, provider: str) -> PaymentCosts:
    if provider == "paypal":
        return PAYPAL_DOMESTIC if market.payment_domestic else PAYPAL_INTERNATIONAL
    return STRIPE_DOMESTIC if market.payment_domestic else STRIPE_INTERNATIONAL


def duty_cost(market: Market, declared_value: float, params: Params) -> float:
    rate = (params.duty_rate_override or {}).get(market.code, market.duty_rate)
    if market.flat_applies_below is not None and declared_value < market.flat_applies_below:
        return market.duty_flat_per_item * params.items
    return declared_value * rate


def _costs_borne(market: Market, declared: float, ship_cost: float, params: Params):
    """(duty, duty_borne, import_vat_borne, dtp_fee) for the tax mode."""
    if params.tax_mode not in ("prepaid", "receiver_pays"):
        raise ValueError(f"unknown tax_mode {params.tax_mode!r}")
    duty = duty_cost(market, declared, params)
    if params.tax_mode == "receiver_pays":
        return duty, 0.0, 0.0, 0.0
    return duty, duty, market.import_tax_rate * (declared + ship_cost + duty), params.dtp_fixed


def solve(market: Market, wholesale: float, ship_cost: float, params: Optional[Params] = None) -> dict:
    """The price P that leaves exactly `params.target` contribution in this market."""
    params = params or Params()
    pay = payment_costs(market, params.provider)
    d = 1 - pay.pct - params.reserve_pct - params.supplier_pct
    if d <= 0:
        raise ValueError("cost percentages consume the whole price")

    def price_for(declared: float):
        duty, duty_b, vat_b, dtp = _costs_borne(market, declared, ship_cost, params)
        p = (params.target + wholesale + ship_cost + duty_b + vat_b + params.supplier_fixed + dtp + pay.fixed) / d
        return p, duty, duty_b, vat_b, dtp

    if params.declared_basis == "retail":                       # duty depends on P itself: iterate
        p = 0.0
        for _ in range(100):
            p_new = price_for(p)[0]
            if abs(p_new - p) < 1e-9:
                break
            p = p_new
        declared = p
    else:
        declared = wholesale
    p, duty, duty_b, vat_b, dtp = price_for(declared)
    fees = pay.pct * p + pay.fixed
    reserve = params.reserve_pct * p
    contribution = p - wholesale - ship_cost - duty_b - vat_b - params.supplier_pct * p - params.supplier_fixed - dtp - fees - reserve
    door_bill = (duty + market.import_tax_rate * (declared + ship_cost + duty) + params.courier_handling_fee
                 if params.tax_mode == "receiver_pays" else 0.0)
    return {"price": p, "duty": duty, "duty_borne": duty_b, "import_vat_borne": vat_b, "payment_fees": fees,
            "reserve": reserve, "wholesale": wholesale, "ship_cost": ship_cost, "contribution": contribution,
            "door_bill": door_bill, "tax_mode": params.tax_mode, "provider": params.provider}


def round_up(price: float, step: float = LADDER_STEP) -> float:
    return math.ceil(price / step - 1e-9) * step


def contribution_at(market: Market, price: float, wholesale: float, ship_cost: float,
                    params: Optional[Params] = None) -> float:
    """Contribution if the customer actually pays `price` -- used to check a rounded, shared or live price."""
    params = params or Params()
    pay = payment_costs(market, params.provider)
    declared = price if params.declared_basis == "retail" else wholesale
    _, duty_b, vat_b, dtp = _costs_borne(market, declared, ship_cost, params)
    return (price - wholesale - ship_cost - duty_b - vat_b - params.supplier_pct * price - params.supplier_fixed - dtp
            - (pay.pct * price + pay.fixed) - params.reserve_pct * price)


def global_price(wholesale: float, express_costs: Dict[str, float], params: Optional[Params] = None,
                 markets: Optional[Dict[str, Market]] = None) -> dict:
    """
    ONE worldwide price (owner: "price should be one", paying for DHL Express): the smallest price that leaves AT
    LEAST the target in EVERY country. The most expensive country sets it; the others then earn more than the target.
    express_costs = {country: DHL Express cost basis}.
    """
    markets = markets or MARKETS
    params = params or Params()
    need = {cc: solve(markets[cc], wholesale, cost, params)["price"] for cc, cost in express_costs.items()}
    driver = max(need, key=need.get)
    price = round_up(need[driver])
    profits = {cc: contribution_at(markets[cc], price, wholesale, express_costs[cc], params) for cc in need}
    return {"price": price, "driver": driver, "required": need, "profit_at_price": profits}
