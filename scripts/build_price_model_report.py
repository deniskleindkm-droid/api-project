"""
Builds artifacts/price_model.md: the price needed for a $45 clean profit per order, per country and delivery
class, for a range of Silverbene wholesale costs, compared with today's live price ladder. REVIEW ONLY.

    python scripts/build_price_model_report.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.agents.jewelry_pricing import calculate_mikisi_price  # noqa: E402
from app.checkout_intl import catalog  # noqa: E402
from app.commerce import pricing_model as pm  # noqa: E402

WHOLESALE = (10, 20, 40, 60, 100)
COUNTRIES = ("US", "GB", "DE", "FR", "AU", "CA")
rc = catalog.ratecard()
P = pm.Params()
lines = ["# Price model: $45 clean profit per order (REVIEW ONLY, not live)\n",
         f"Target contribution ${P.target:.0f}/order, reserve {P.reserve_pct:.0%}, Stripe rates, duty on wholesale declared value, "
         "one item per order, USD. Net = price before VAT/GST; Gross = what the customer pays incl. VAT where Mikisi collects it.\n"]


def ship(cc, cls):
    return rc[cc][cls]["max"] if cls in rc[cc] else None


lines += ["## Shipping cost basis (max observed) and duty/tax assumptions\n",
          "| Country | Express (DHL) | Standard | Duty on declared value | VAT/GST Mikisi collects | Confidence |", "|---|---|---|---|---|---|"]
for cc in COUNTRIES:
    m = pm.MARKETS[cc]
    duty = (f"EUR3/item flat (<EUR150), else {m.duty_rate:.1%}" if m.flat_applies_below else f"{m.duty_rate:.1%}")
    std = f"${ship(cc, 'standard'):.2f}" if ship(cc, "standard") else "n/a"
    lines.append(f"| {cc} | ${ship(cc, 'express'):.2f} | {std} | {duty} | {m.vat_rate:.0%}{' (needs registration)' if m.vat_registered else ''} | {m.status} |")

lines.append("\n## Required NET price for $45 profit, by wholesale cost (Express / Standard)\n")
lines.append("| Country | " + " | ".join(f"W=${w}" for w in WHOLESALE) + " |")
lines.append("|---|" + "---|" * len(WHOLESALE))
for cc in COUNTRIES:
    cells = []
    for w in WHOLESALE:
        e = pm.round_up(pm.solve(pm.MARKETS[cc], w, ship(cc, "express"), P)["net_price"])
        s = ship(cc, "standard")
        st = f"${pm.round_up(pm.solve(pm.MARKETS[cc], w, s, P)['net_price']):.0f}" if s else "n/a"
        cells.append(f"${e:.0f} / {st}")
    lines.append(f"| {cc} | " + " | ".join(cells) + " |")

lines.append("\n## Customer-facing GROSS price (incl. VAT where collected), Express / Standard\n")
lines.append("| Country | " + " | ".join(f"W=${w}" for w in WHOLESALE) + " |")
lines.append("|---|" + "---|" * len(WHOLESALE))
for cc in COUNTRIES:
    cells = []
    for w in WHOLESALE:
        e = pm.round_up(pm.solve(pm.MARKETS[cc], w, ship(cc, "express"), P)["gross_price"])
        s = ship(cc, "standard")
        st = f"${pm.round_up(pm.solve(pm.MARKETS[cc], w, s, P)['gross_price']):.0f}" if s else "n/a"
        cells.append(f"${e:.0f} / {st}")
    lines.append(f"| {cc} | " + " | ".join(cells) + " |")

lines.append("\n## Today's live ladder vs the price needed (US Express) and the profit today's price actually leaves\n")
lines.append("| Wholesale | Live price | Needed for $45 (US Express) | Profit at live price (US Express) | Profit at live price (GB Express, ex-VAT) |")
lines.append("|---|---|---|---|---|")
for w in WHOLESALE:
    live = calculate_mikisi_price(w)["final_price"]
    need = pm.round_up(pm.solve(pm.MARKETS["US"], w, ship("US", "express"), P)["net_price"])
    c_us = pm.contribution_at(pm.MARKETS["US"], live, w, ship("US", "express"), P)
    live_gb_net = live / (1 + pm.MARKETS["GB"].vat_rate)
    c_gb = pm.contribution_at(pm.MARKETS["GB"], live_gb_net, w, ship("GB", "express"), P)
    lines.append(f"| ${w} | ${live:.0f} | ${need:.0f} | ${c_us:.0f} | ${c_gb:.0f} |")

lines.append("\n## Express upcharge over Standard (net price difference, W=$40)\n")
for cc in COUNTRIES:
    if ship(cc, "standard"):
        e = pm.solve(pm.MARKETS[cc], 40, ship(cc, "express"), P)["net_price"]
        s = pm.solve(pm.MARKETS[cc], 40, ship(cc, "standard"), P)["net_price"]
        lines.append(f"- {cc}: Express costs ${e - s:.2f} more than Standard")

lines.append("\n## Sensitivities (W=$40, Express): how much the uncertain inputs move the NET price\n")
lines.append("| Scenario | US | GB | DE | AU | CA |")
lines.append("|---|---|---|---|---|---|")
scen = {
    "Base": pm.Params(),
    "US duty LOW 22.5%": pm.Params(duty_rate_override={"US": pm.US_DUTY_LOW}),
    "Customs uses RETAIL as declared value": pm.Params(declared_basis="retail"),
    "DHL duty/tax fee $19 per order": pm.Params(dtp_fixed=19.0),
    "Silverbene fee 3% of net": pm.Params(supplier_pct=0.03),
    "PayPal instead of Stripe": pm.Params(provider="paypal"),
    "Reserve 5%": pm.Params(reserve_pct=0.05),
}
for name, prm in scen.items():
    row = [f"${pm.solve(pm.MARKETS[c], 40, ship(c, 'express'), prm)['net_price']:.0f}" for c in ("US", "GB", "DE", "AU", "CA")]
    lines.append(f"| {name} | " + " | ".join(row) + " |")

lines.append("\n## Assumptions still to verify\n")
lines += [f"- {a}" for a in pm.ASSUMPTIONS_TO_VERIFY]
lines.append("\n## Country notes\n")
for cc in COUNTRIES:
    lines.append(f"**{cc}**")
    lines += [f"- {n}" for n in pm.MARKETS[cc].notes]
open(os.path.join(os.path.dirname(__file__), "..", "artifacts", "price_model.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
