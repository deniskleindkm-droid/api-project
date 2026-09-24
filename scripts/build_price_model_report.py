"""
Builds artifacts/price_model.md: the price model for a $45 clean profit PER PRODUCT SOLD, paying for DHL Express.
REVIEW ONLY -- not wired into live pricing.

    python scripts/build_price_model_report.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.agents.jewelry_pricing import calculate_mikisi_price  # noqa: E402
from app.checkout_intl import catalog  # noqa: E402
from app.commerce import pricing_model as pm  # noqa: E402

NL = "\n"
WHOLESALE = (10, 20, 30, 40, 60, 80, 100, 150)
COUNTRIES = ("US", "GB", "DE", "FR", "AU", "CA")
rc = catalog.ratecard()
EXPRESS = {c: rc[c]["express"]["max"] for c in COUNTRIES}
PRE, REC = pm.Params(tax_mode="prepaid"), pm.Params(tax_mode="receiver_pays")
L = [f"# $45 clean profit per product sold (REVIEW ONLY, not live){NL}",
     "Each product is priced on its own, with its own DHL Express shipment (that is how fulfillment works today: one "
     f"Silverbene order per cart line). No tax is collected by Mikisi.{NL}",
     "- **Prepaid (DDP):** Mikisi pays duty + import VAT up front; the customer pays nothing at the door.",
     f"- **Receiver pays:** the customer pays duty + VAT to DHL at the door (a surprise bill); the price is lower.{NL}",
     f"Assumes profit ${pm.TARGET_CONTRIBUTION:.0f} per product, Stripe fees, 2% reserve, duty on the wholesale declared value, USD.{NL}"]

L += [f"## Inputs: DHL Express cost basis (max observed) and border rules{NL}",
      "| Country | DHL Express | Duty | Border VAT/GST | Confidence |", "|---|---|---|---|---|"]
for c in COUNTRIES:
    m = pm.MARKETS[c]
    duty = f"EUR3/item flat (<EUR150), else {m.duty_rate:.1%}" if m.flat_applies_below else f"{m.duty_rate:.1%}"
    L.append(f"| {c} | ${EXPRESS[c]:.2f} | {duty} | {m.import_tax_rate:.0%} | {m.status} |")

for title, prm in (("PREPAID: duty and taxes included in the delivery fee", PRE),
                   ("RECEIVER PAYS: customer also pays duty + tax to DHL at the door", REC)):
    L.append(f"{NL}## ONE ITEM PRICE + DHL EXPRESS DELIVERY FEE PER COUNTRY - {title}{NL}")
    L.append("| Wholesale | ITEM price (worldwide) | US | GB | DE | FR | AU | CA |")
    L.append("|---|---|---|---|---|---|---|---|")
    for w in WHOLESALE:
        sp = {c: pm.split(pm.MARKETS[c], w, EXPRESS[c], prm) for c in COUNTRIES}
        fees = " | ".join(f"+${sp[c]['delivery_fee']:.0f}" for c in COUNTRIES)
        L.append(f"| ${w} | **${sp['US']['item_price']:.0f}** | {fees} |")
    worst = min(pm.split(pm.MARKETS[c], 40, EXPRESS[c], prm)["contribution"] for c in COUNTRIES)
    L.append(f"{NL}(Delivery fee per country; profit at W=$40 in every country is at least ${worst:.2f}.)")

for title, prm in (("PREPAID", PRE), ("RECEIVER PAYS", REC)):
    L.append(f"{NL}## ONE ALL-IN PRICE (no separate delivery fee) - {title}{NL}")
    L.append("| Wholesale | ONE price | Driven by | Live ladder today | Profit in US | GB | DE | FR | AU | CA |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for w in WHOLESALE:
        g = pm.global_price(w, EXPRESS, prm)
        live = calculate_mikisi_price(w)["final_price"]
        prof = " | ".join(f"${g['profit_at_price'][c]:.0f}" for c in COUNTRIES)
        L.append(f"| ${w} | **${g['price']:.0f}** | {g['driver']} | ${live:.0f} | {prof} |")

L.append(f"{NL}## What a customer is billed at the door if you do NOT prepay (W=$40){NL}")
L.append("| Country | Duty | VAT/GST | Total surprise (before DHL's own handling fee) |")
L.append("|---|---|---|---|")
for c in COUNTRIES:
    r = pm.solve(pm.MARKETS[c], 40, EXPRESS[c], REC)
    L.append(f"| {c} | ${r['duty']:.2f} | ${r['door_bill'] - r['duty']:.2f} | **${r['door_bill']:.2f}** |")

L.append(f"{NL}## Sensitivities: the ONE all-in price at W=$40 (prepaid / receiver pays){NL}")
L.append("| Scenario | Prepaid | Receiver pays |")
L.append("|---|---|---|")
scen = {
    "Base": {},
    "US duty LOW 22.5% (not 43.8%)": {"duty_rate_override": {"US": pm.US_DUTY_LOW}},
    "Customs uses RETAIL as declared value": {"declared_basis": "retail"},
    "DHL duty/tax fee $19 per order": {"dtp_fixed": 19.0},
    "Silverbene fee 3% of price": {"supplier_pct": 0.03},
    "PayPal instead of Stripe": {"provider": "paypal"},
    "Reserve 5%": {"reserve_pct": 0.05},
}
for name, kw in scen.items():
    a = pm.global_price(40, EXPRESS, pm.Params(tax_mode="prepaid", **kw))["price"]
    b = pm.global_price(40, EXPRESS, pm.Params(tax_mode="receiver_pays", **kw))["price"]
    L.append(f"| {name} | ${a:.0f} | ${b:.0f} |")

L.append(f"{NL}## Assumptions still to verify{NL}")
L += [f"- {a}" for a in pm.ASSUMPTIONS_TO_VERIFY]
L.append(f"{NL}## Country notes{NL}")
for c in COUNTRIES:
    L.append(f"**{c}**")
    L += [f"- {n}" for n in pm.MARKETS[c].notes]
out = os.path.join(os.path.dirname(__file__), "..", "artifacts", "price_model.md")
open(out, "w", encoding="utf-8").write(NL.join(L) + NL)
print(NL.join(L))
