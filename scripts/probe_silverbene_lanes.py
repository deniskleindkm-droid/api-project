"""
Read-only: which Silverbene products get which shipping lanes (esp. national posts like USPS,
Hermes, La Poste, Australia Post, Canada Post) in each Wave-1 country?

Samples ~12 products across categories with a mix of weight and `is_really_stock`, requests rates
for one representative address per country, and records the methods returned plus the product traits.
No orders, no payment links, no stock changes.

    python scripts/probe_silverbene_lanes.py [--products 12]

Writes artifacts/silverbene_lane_probe.json and prints a summary.
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from app.agents.suppliers import silverbene_adapter as sba  # noqa: E402
from probe_silverbene_wave1 import classify, raw_post, redact  # noqa: E402

ART = os.path.join(os.path.dirname(__file__), "..", "artifacts")
ADDR = {"US": ("Chicago", "60606"), "GB": ("London", "SW1A 1AA"), "DE": ("Berlin", "10115"),
        "FR": ("Paris", "75001"), "AU": ("Sydney", "2000"), "CA": ("Toronto", "M5H 2N2")}


def sample_products(sb, want):
    sb._to_standard = lambda raw, category="": raw            # keep raw fields (weight, is_really_stock)
    picked, seen = [], set()
    for kw in ("ring", "necklace", "bracelet", "earring", "pendant", "anklet", "chain", "bangle"):
        for p in sb.search(kw, limit=10):
            opts = p.get("option") or []
            if isinstance(opts, str):
                try:
                    opts = eval(opts)
                except Exception:  # noqa: BLE001
                    opts = []
            good = [o for o in opts if o.get("option_id") and (o.get("qty") or 0) >= 3]
            if not good or p["sku"] in seen:
                continue
            seen.add(p["sku"])
            picked.append({"sku": p["sku"], "title": p["title"][:60], "weight": p.get("weight"),
                           "is_really_stock": p.get("is_really_stock"), "keyword": kw,
                           "option_id": str(good[0]["option_id"]), "unit_price": good[0].get("price"),
                           "qty": good[0].get("qty")})
    # balance: half really-stock True, half False, spread over weights
    true_ = sorted([p for p in picked if p["is_really_stock"]], key=lambda p: p["weight"] or 0)
    false_ = sorted([p for p in picked if not p["is_really_stock"]], key=lambda p: p["weight"] or 0)

    def spread(lst, n):
        if len(lst) <= n:
            return lst
        step = len(lst) / n
        return [lst[int(i * step)] for i in range(n)]
    return spread(true_, want // 2) + spread(false_, want - want // 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", type=int, default=12)
    n = ap.parse_args().products
    sb = sba.SilverbeneAdapter()
    products = sample_products(sb, n)
    print(f"{len(products)} products sampled:", flush=True)
    for p in products:
        print(f"  {p['sku']:22} w={p['weight']} really_stock={p['is_really_stock']} {p['title'][:40]}", flush=True)

    out = {"probed_at": datetime.now(timezone.utc).isoformat(), "products": products, "calls": []}
    lock = threading.Lock()

    def job(p, country):
        city, postcode = ADDR[country]
        payload = {"country_id": country, "postcode": postcode, "city": city,
                   "products": [{"option_id": p["option_id"], "qty": 1}]}
        call = raw_post(sb, sba.ENDPOINT_SHIPPING, payload)
        call["outcome"] = classify(call)
        if call.get("error"):
            call["error"] = call["error"].replace(sb.token, "<redacted>")
        rec = {"sku": p["sku"], "country": country, "outcome": call["outcome"], "seconds": call.get("seconds"),
               "methods": [{"way": m.get("way"), "title": m.get("title"), "price": m.get("price")}
                           for m in ((call.get("response") or {}).get("data") or [])]}
        with lock:
            out["calls"].append(rec)
            print(f"  {country} {p['sku'][-8:]} {rec['outcome']:16} {rec['seconds']}s  "
                  + ",".join(sorted({m['way'] for m in rec['methods']})), flush=True)
            json.dump(out, open(os.path.join(ART, "silverbene_lane_probe.json"), "w", encoding="utf-8"),
                      indent=1, ensure_ascii=False)

    jobs = [(p, c) for p in products for c in ADDR]
    with ThreadPoolExecutor(max_workers=int(os.getenv("PROBE_WORKERS", "3"))) as pool:
        list(pool.map(lambda j: job(*j), jobs))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
