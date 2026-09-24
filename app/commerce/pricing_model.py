"""
International pricing model v0 (REVIEW ONLY -- nothing here is wired into live pricing).

Goal (owner, 2026-09-24): a CLEAN PROFIT (contribution) of TARGET_CONTRIBUTION dollars on every order after
every cost Mikisi actually bears. The price is SOLVED from that target, never marked up from cost.

Per order, in USD:

  contribution = N - W - ship - duty_borne - supplier_fees - payment_fees - reserve

    N             net price the customer pays Mikisi, EXCLUDING any sales tax / VAT / GST collected
    W             Silverbene wholesale cost of the items
    ship          Silverbene shipping cost for the chosen class (Express/DHL or Standard), cost basis =
                  the MAXIMUM observed price (app/checkout_intl/catalog.py)
    duty_borne    import duty Mikisi pays (policy "absorb": built into the price; the customer sees one price)
    supplier_fees Silverbene's own fees on the order (UNKNOWN today -> parameter, default 0)
    payment_fees  card/PayPal fees, charged on the FULL amount the customer pays (tax included)
    reserve       refunds / chargebacks / lost parcels, a % of N

  VAT / GST is a pass-through: the customer pays N x (1 + vat) and Mikisi remits the tax, so it never counts
  as revenue -- but it does enlarge the amount the payment provider takes a percentage of.

Closed form (everything is linear in N):

  N = (target + W + ship + duty + supplier_fixed + pay_fixed) / (1 - pay_pct * (1 + vat) - reserve_pct - supplier_pct)

EVERY input carries a `status`: "sourced" (a public source was read), "assumed" (an owner statement or a
conservative default), or "unverified" (a number I could not confirm). See ASSUMPTIONS_TO_VERIFY.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TARGET_CONTRIBUTION = 45.00       # owner, 2026-09-24: "$45 clean profit"

EUR_USD = 1.17                    # planning rate; only used for the EU EUR 3 flat duty and EUR thresholds
LADDER_STEP = 1.0                 # prices round UP to the next whole dollar (charm rounding is a later choice)


@dataclass(frozen=True)
class PaymentCosts:
    pct: float                    # of the full amount charged (tax included)
    fixed: float
    status: str
    note: str = ""


# Stripe / PayPal published pricing as generally known -- NOT re-verified in this session.
STRIPE_DOMESTIC = PaymentCosts(0.029, 0.30, "unverified", "Stripe US cards 2.9% + $0.30")
STRIPE_INTERNATIONAL = PaymentCosts(0.044, 0.30, "unverified", "2.9% + 1.5% international card surcharge + $0.30")
PAYPAL_DOMESTIC = PaymentCosts(0.0349, 0.49, "unverified", "PayPal US 3.49% + $0.49")
PAYPAL_INTERNATIONAL = PaymentCosts(0.0499, 0.49, "unverified", "PayPal international 4.99% + $0.49")


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    # import duty on the DECLARED value
    duty_rate: float              # ad valorem
    duty_flat_per_item: float     # USD per item (EU low-value flat duty)
    flat_applies_below: Optional[float]   # declared value (USD) below which the flat duty replaces ad valorem
    vat_rate: float               # collected at checkout and remitted (pass-through); 0 = not collected
    vat_registered: bool          # does Mikisi need / hold a registration to collect it?
    payment_domestic: bool        # True -> domestic card rates
    status: str                   # sourced | assumed | unverified
    notes: List[str] = field(default_factory=list)


# ── per-country inputs ────────────────────────────────────────────────────────
# US duty: the sources conflict. LOW = Silverbene's reference stack quoted to the owner (22.5%);
# HIGH = base ~6.3% + Section 301 25% + new 12.5% (2026-07-24) = 43.8%. Default to HIGH (safe) until a
# customs broker / Silverbene confirms the declared HS code + value.
US_DUTY_LOW, US_DUTY_HIGH = 0.225, 0.438

MARKETS: Dict[str, Market] = {
    "US": Market("US", "United States", US_DUTY_HIGH, 0.0, None, 0.0, False, True, "unverified", [
        "De minimis suspended (Federal Register 2026-06-24). Duty stack for China-origin silver jewelry uncertain: 22.5%-43.8%.",
        "Owner's DHL sample was charged duty at delivery despite 'customs duty included' -> treat duty as a real cost.",
        "US state sales tax NOT modelled (economic-nexus thresholds not reached; revisit)."]),
    "GB": Market("GB", "United Kingdom", 0.0, 0.0, None, 0.20, True, False, "sourced", [
        "Duty relief on consignments <= GBP135 (2% otherwise) until 2029 (GOV.UK).",
        "Seller must REGISTER for UK VAT and charge 20% at checkout for consignments <= GBP135.",
        "Requires a UK VAT registration -- confirm with an accountant."]),
    "DE": Market("DE", "Germany", 0.025, 3.0 * EUR_USD, 150.0 * EUR_USD, 0.19, True, False, "sourced", [
        "EU flat EUR3 duty per item on parcels < EUR150 from 2026-07-01 (until 2028-07-01); 2.5% above (TARIC).",
        "VAT 19% collectable at checkout via IOSS registration (parcels <= EUR150)."]),
    "FR": Market("FR", "France", 0.025, 3.0 * EUR_USD, 150.0 * EUR_USD, 0.20, True, False, "sourced", [
        "Same EU rules as Germany; VAT 20%. IOSS registration needed to collect VAT at checkout."]),
    "AU": Market("AU", "Australia", 0.0, 0.0, None, 0.0, False, False, "unverified", [
        "Imports <= A$1,000 are generally duty/GST free at the border; overseas seller must register and charge 10% GST "
        "once Australian sales reach A$75,000 (ATO). Duty 5% on finished jewelry was NOT confirmed for <= A$1,000.",
        "Modelled as 0 until the threshold is reached -- monitor Australian sales."]),
    "CA": Market("CA", "Canada", 0.08, 0.0, None, 0.0, False, False, "unverified", [
        "China-origin courier duty-free limit is only CAD 20; jewelry duty 6.5-8% (CBSA); 8% used.",
        "GST 5% / HST 13-15% is charged on duty-paid value at import and collected from the receiver by the carrier "
        "-- modelled as receiver-paid (customer surprise!) because Mikisi has no CA registration."]),
}

# Silverbene shipping cost basis (MAX observed, USD, single item) is read live from the rate card.
ASSUMPTIONS_TO_VERIFY = [
    "TARGET: $45 is per ORDER (a cart), not per item.",
    "Silverbene's own fees/taxes on an order (e.g. a fee when paying by card/PayPal on their page) -- unknown, modelled 0.",
    "Customs declared value = Silverbene's invoice value (wholesale). If Silverbene declares something else, duty changes.",
    "US duty stack (22.5% vs 43.8%) -- get the HS code and declared value from Silverbene/DHL, or a customs broker.",
    "DHL 'duty & tax paid' service fee (Europe: 2%, min ~EUR16.50) -- unknown whether it applies to our DHL shipments; modelled 0.",
    "Payment provider rates (Stripe 2.9%+30c, +1.5% international; PayPal 3.49%+49c / 4.99%+49c) -- not re-verified.",
    "Reserve for refunds/chargebacks/lost parcels: 2% of net price (assumed).",
    "UK VAT, EU IOSS and Australian GST registrations -- legal decisions for an accountant; not confirmed.",
    "Shipping cost basis is single-item; multi-item carts are cheaper per item only if Silverbene combines them into ONE order.",
]


@dataclass
class Params:
    target: float = TARGET_CONTRIBUTION
    reserve_pct: float = 0.02
    supplier_pct: float = 0.0          # Silverbene fee as % of wholesale+shipping (unknown)
    supplier_fixed: float = 0.0
    dtp_fixed: float = 0.0             # DHL duty/tax processing fee per order (unknown)
    duty_rate_override: Optional[Dict[str, float]] = None
    declared_basis: str = "wholesale"  # or "retail" (sensitivity: worst case if customs uses the selling price)
    provider: str = "stripe"           # or "paypal"
    items: int = 1


def payment_costs(market: Market, provider: str) -> PaymentCosts:
    if provider == "paypal":
        return PAYPAL_DOMESTIC if market.payment_domestic else PAYPAL_INTERNATIONAL
    return STRIPE_DOMESTIC if market.payment_domestic else STRIPE_INTERNATIONAL


def duty_cost(market: Market, declared_value: float, params: Params) -> float:
    rate = (params.duty_rate_override or {}).get(market.code, market.duty_rate)
    if market.flat_applies_below is not None and declared_value < market.flat_applies_below:
        return market.duty_flat_per_item * params.items
    return declared_value * rate


def solve(market: Market, wholesale: float, ship_cost: float, params: Optional[Params] = None) -> dict:
    """Net price N (ex-tax) that leaves exactly `params.target` contribution; plus the customer-facing gross."""
    params = params or Params()
    pay = payment_costs(market, params.provider)
    denom_terms = lambda: 1 - pay.pct * (1 + market.vat_rate) - params.reserve_pct - params.supplier_pct
    d = denom_terms()
    if d <= 0:
        raise ValueError("cost percentages consume the whole price")

    if params.declared_basis == "retail":
        # duty depends on N itself: iterate (converges fast; duty rate < 1)
        n = 0.0
        for _ in range(60):
            duty = duty_cost(market, n, params)
            n_new = (params.target + wholesale + ship_cost + duty + params.supplier_fixed + params.dtp_fixed + pay.fixed) / d
            if abs(n_new - n) < 1e-9:
                break
            n = n_new
    else:
        duty = duty_cost(market, wholesale, params)
        n = (params.target + wholesale + ship_cost + duty + params.supplier_fixed + params.dtp_fixed + pay.fixed) / d

    gross = n * (1 + market.vat_rate)
    fees = pay.pct * gross + pay.fixed
    reserve = params.reserve_pct * n
    supplier_fees = params.supplier_pct * n + params.supplier_fixed
    contribution = n - wholesale - ship_cost - duty - supplier_fees - params.dtp_fixed - fees - reserve
    return {
        "net_price": n, "gross_price": gross, "vat": gross - n, "duty": duty, "payment_fees": fees,
        "reserve": reserve, "wholesale": wholesale, "ship_cost": ship_cost, "contribution": contribution,
        "provider": params.provider,
    }


def round_up(price: float, step: float = LADDER_STEP) -> float:
    return math.ceil(price / step - 1e-9) * step


def contribution_at(market: Market, price_net: float, wholesale: float, ship_cost: float,
                    params: Optional[Params] = None) -> float:
    """Contribution if the customer actually pays `price_net` (ex-tax) -- used to check a rounded/current price."""
    params = params or Params()
    pay = payment_costs(market, params.provider)
    duty = duty_cost(market, price_net if params.declared_basis == "retail" else wholesale, params)
    gross = price_net * (1 + market.vat_rate)
    return (price_net - wholesale - ship_cost - duty - params.supplier_pct * price_net - params.supplier_fixed
            - params.dtp_fixed - (pay.pct * gross + pay.fixed) - params.reserve_pct * price_net)
