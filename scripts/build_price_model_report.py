"""
Builds artifacts/price_model.md: ONE worldwide price that leaves a $45 clean profit per order while paying for
DHL Express shipping, for a range of Silverbene wholesale costs. REVIEW ONLY -- not wired into live pricing.

    python scripts/build_price_model_report.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.agents.jewelry_pricing import calculate_mikisi_price  # noqa: E402
from app.checkout_intl import catalog  # noqa: E402
from app.commerce import pricing_model as pm  # noqa: E402

WHOLESALE = (10, 20, 30, 40, 60, 80, 100, 150)
COUNTRIES = ("US", "GB", "DE", "FR", "AU", "CA")
rc = catalog.ratecard()
EXPRESS = {c: rc[c]["express"]["max"] for c in COUNTRIES}
PRE, REC = pm.Params(tax_mode="prepaid"), pm.Params(tax_mode="receiver_pays")
L = ["# One worldwide price for a $45 clean profit (REVIEW ONLY, not live)\n",
     "Price pays for **DHL Express**. No tax is collected by Mikisi. Two ways the border taxes can be settled:\n",
     "- **Prepaid (DDP):** Mikisi pays duty + import VAT up front; the customer pays nothing at the door.",
     "- **Receiver pays:** the customer pays duty + VAT to DHL at the door (a surprise bill); the price is lower.\n",
     f"Assumes target ${pm.TARGET_CONTRIBUTION:.0f}/order, one item, Stripe fees, 2% reserve, duty on the wholesale declared value, USD.\n"]

L += ["## Inputs: DHL Express cost basis (max observed) and border rules\n",
      "| Country | DHL Express | Duty | Border VAT/GST | Confidence |", "|---|---|---|---|---|"]
for c in COUNTRIES:
    m = pm.MARKETS[c]
    duty = f"EUR3/item flat (<EUR150), else {m.duty_rate:.1%}" if m.flat_applies_below else f"{m.duty_rate:.1%}"
    L.append(f"| {c} | ${EXPRESS[c]:.2f} | {duty} | {m.import_tax_rate:.0%} | {m.status} |")

for title, prm in (("PREPAID (customer pays nothing extra at the door)", PRE), ("RECEIVER PAYS (customer is billed at the door)", REC)):
    L.append(f"\n## ONE PRICE — {title}\n")
    L.append("| Wholesale | ONE price | Driven by | Live ladder today | Profit in US | GB | DE | FR | AU | CA |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for w in WHOLESALE:
        g = pm.global_price(w, EXPRESS, prm)
        live = calculate_mikisi_price(w)["final_price"]
        prof = " | ".join(f"${g['profit_at_price'][c]:.0f}" for c in COUNTRIES)
        L.append(f"| ${w} | **${g['price']:.0f}** | {g['driver']} | ${live:.0f} | {prof} |")

L.append("\n## What a customer is billed at the door if you do NOT prepay (W=$40)\n")
L.append("| Country | Duty | VAT/GST | Total surprise (before DHL's own handling fee) |")
L.append("|---|---|---|---|")
for c in COUNTRIES:
    r = pm.solve(pm.MARKETS[c], 40, EXPRESS[c], REC)
    vat = r["door_bill"] - r["duty"]
    L.append(f"| {c} | ${r['duty']:.2f} | ${vat:.2f} | **${r['door_bill']:.2f}** |")

L.append("\n## Sensitivities: the ONE price at W=$40 (prepaid / receiver pays)\n")
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

L.append("\n## Country-by-country requirement at W=$40 (prepaid): why the US sets the price\n")
g = pm.global_price(40, EXPRESS, PRE)
for c in sorted(COUNTRIES, key=lambda c: -g["required"][c]):
    L.append(f"- {c}: needs ${g['required'][c]:.0f}; earns ${g['profit_at_price'][c]:.0f} at the one price of ${g['price']:.0f}")

L.append("\n## Assumptions still to verify\n")
L += [f"- {a}" for a in pm.ASSUMPTIONS_TO_VERIFY]
L.append("\n## Country notes\n")
for c in COUNTRIES:
    L.append(f"**{c}**")
    L += [f"- {n}" for n in pm.MARKETS[c].notes]
open(os.path.join(os.path.dirname(__file__), "..", "artifacts", "price_model.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
