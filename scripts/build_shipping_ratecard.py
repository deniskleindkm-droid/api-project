"""
Writes artifacts/shipping_ratecard.json and .md from the Silverbene probe evidence: per country, the
MAXIMUM observed supplier cost for EXPRESS (DHL) and STANDARD -- the cost basis for the repricing stage.

    python scripts/build_shipping_ratecard.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.checkout_intl import catalog, countries  # noqa: E402

card = catalog.ratecard()
out = {c: card[c] for c in countries.LAUNCH_WAVE_1 if c in card}
art = os.path.join(os.path.dirname(__file__), "..", "artifacts")
json.dump(out, open(os.path.join(art, "shipping_ratecard.json"), "w", encoding="utf-8"), indent=1)
lines = ["# Shipping cost basis (max observed, USD, single item)\n",
         "| Country | Express (DHL) max | median | Standard max | median | probe calls |", "|---|---|---|---|---|---|"]
for c, e in out.items():
    x, s = e.get("express", {}), e.get("standard", {})
    lines.append(f"| {c} | ${x.get('max')} | ${x.get('median')} | ${s.get('max')} | ${s.get('median')} | {e['n_calls']} |")
open(os.path.join(art, "shipping_ratecard.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
