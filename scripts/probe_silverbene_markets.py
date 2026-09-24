"""
Read-only probe: for every ISO country, ask Silverbene for shipping rates for
ONE known-good option_id and record which countries return routes and which
shipping families they offer. Creates NO orders and moves no money.

    python scripts/probe_silverbene_markets.py --option-id <a real in-stock option_id>
        [--only US,DE,JP] [--sleep 1.0]

Writes artifacts/silverbene_market_probe.json, which app/checkout_intl/countries.py
overlays onto the registry (supplier_supported, families, standard/express).
Uses SILVERBENE_API_KEY from the environment/.env, like the app.

Each country is probed with that country's example postcode from the address
rules, else a generic one; a country that answers empty may simply need a
different postcode -- treat `supplier_supported: false` as "no route returned
for this sample", and re-probe with a real address before concluding.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter  # noqa: E402
from app.checkout_intl import countries, rates  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--option-id", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    only = {c.strip().upper() for c in args.only.split(",") if c.strip()}
    sb = SilverbeneAdapter()
    out = {}
    for m in countries.all_markets():
        code = m.iso_country_code
        if only and code not in only:
            continue
        rules = m.address_rules
        postcode = rules.postal_example or "10001"
        methods = sb.get_shipping_methods(
            country_code=m.silverbene_country_id, postcode=postcode, city="Capital",
            products=[{"option_id": args.option_id, "qty": 1}], allow_fallback=False)
        opts = rates.normalize(methods)
        fams = sorted({o["family"] for o in opts})
        out[code] = {
            "supplier_supported": bool(opts),
            "families": fams,
            "standard": any(f != "dhl" and f != "fedex" and f != "ups" for f in fams) or None,
            "express": any(f in ("dhl", "fedex", "ups") for f in fams) or None,
            "methods": [{"way": o["method_id"], "title": o["name"], "price": o["supplier_price"]} for o in opts],
        }
        print(f"{code}: {'OK ' + ','.join(fams) if opts else 'no route'}")
        time.sleep(args.sleep)

    path = countries._probe_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"probed_at": datetime.now(timezone.utc).isoformat(),
                   "option_id": args.option_id, "markets": out}, f, indent=1, ensure_ascii=False)
    print(f"wrote {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
