"""
Read-only Silverbene shipping-rate probe for LaunchWave1 (US, GB, DE, FR, AU, CA).

Creates NO orders, NO payment links, mutates NO stock. It only calls the same
shipping-rate endpoint the checkout uses (and a few GET country-list guesses to
learn whether Silverbene exposes an authoritative country list).

    python scripts/probe_silverbene_wave1.py

Evidence written (token always redacted):
  artifacts/silverbene_probe_raw.json          raw request/response per call
  artifacts/silverbene_market_probe.json       normalized per-country matrix the registry overlays
  artifacts/silverbene_probe_summary.md        human-readable matrix

Real in-stock option_ids are discovered from Silverbene's own catalog (search +
per-option stock), never hardcoded.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.agents.suppliers import silverbene_adapter as sba  # noqa: E402
from app.checkout_intl import countries, rates  # noqa: E402

ART = os.path.join(os.path.dirname(__file__), "..", "artifacts")

# (country, city, postcode) -- two or three real, valid, geographically distinct locations each.
LOCATIONS = [
    ("US", "Chicago", "60601"), ("US", "Atlanta", "30303"), ("US", "Los Angeles", "90012"),
    ("GB", "London", "SW1A 1AA"), ("GB", "Manchester", "M1 1AE"),
    ("DE", "Berlin", "10115"), ("DE", "Munich", "80331"),
    ("FR", "Paris", "75001"), ("FR", "Lyon", "69001"),
    ("AU", "Sydney", "2000"), ("AU", "Melbourne", "3000"),
    ("CA", "Toronto", "M5H 2N2"), ("CA", "Vancouver", "V6B 1A1"),
]
COUNTRY_LIST_GUESSES = [
    "/api/dropshipping/get_country", "/api/dropshipping/country_list",
    "/api/dropshipping/countries", "/api/dropshipping/get_countries",
]


def redact(d):
    d = dict(d)
    if "token" in d:
        d["token"] = "<redacted>"
    return d


def raw_post(sb, endpoint, payload):
    body = dict(payload, token=sb.token)
    t0 = time.time()
    try:
        r = requests.post(f"{sb.base}{endpoint}", json=body, headers={"Content-Type": "application/json"}, timeout=240)
        try:
            data = r.json()
        except ValueError:
            data = {"_non_json": r.text[:500]}
        return {"http_status": r.status_code, "response": data, "seconds": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"http_status": None, "response": None, "error": f"{type(e).__name__}: {str(e).replace(sb.token, '<redacted>')}",
                "seconds": round(time.time() - t0, 2)}


def classify(call):
    if call.get("error"):
        return "transport_error"
    if call["http_status"] != 200:
        return f"http_{call['http_status']}"
    resp = call["response"] or {}
    if resp.get("code") not in (0, "0", None):
        return f"supplier_error_code_{resp.get('code')}"
    return "ok" if resp.get("data") else "ok_but_no_methods"


def pick_options(sb, want=3):
    chosen = []
    for kw in ("ring", "necklace", "bracelet", "earring"):
        for p in sb.search(kw, limit=12):
            try:
                opts = eval(p["variants"]) if isinstance(p.get("variants"), str) else (p.get("variants") or [])
            except Exception:  # noqa: BLE001
                continue
            for o in opts:
                oid = o.get("option_id")
                if oid and (o.get("qty") or 0) >= 5 and str(oid) not in {c["option_id"] for c in chosen}:
                    stock = sb.get_stock(str(oid), timeout=15)
                    if stock >= 5:
                        chosen.append({"option_id": str(oid), "name": p["name"][:60],
                                       "unit_cost": o.get("price"), "stock": stock})
                        break
            if len(chosen) >= want:
                return chosen
            if chosen and len({c["name"] for c in chosen}) == len(chosen) and len(chosen) >= want:
                return chosen
    return chosen


def main():
    os.makedirs(ART, exist_ok=True)
    sb = sba.SilverbeneAdapter()
    stamp = datetime.now(timezone.utc).isoformat()
    print("discovering in-stock options...", flush=True)
    options = pick_options(sb)
    if len(options) < 3:
        sys.exit(f"could not find 3 in-stock options ({len(options)} found)")
    print("options:", [(o["option_id"], o["stock"]) for o in options])

    raw = {"probed_at": stamp, "options": options, "country_list_guesses": [], "rate_calls": []}

    for ep in COUNTRY_LIST_GUESSES:
        try:
            r = requests.get(f"{sb.base}{ep}", params={"token": sb.token}, timeout=20)
            raw["country_list_guesses"].append({"endpoint": ep, "http_status": r.status_code, "body_head": r.text[:200]})
        except Exception as e:  # noqa: BLE001
            raw["country_list_guesses"].append({"endpoint": ep, "error": str(e).replace(sb.token, "<redacted>")})

    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()

    def rate_call(code, city, postcode, products, label):
        market = countries.get_market(code)
        payload = {"country_id": market.silverbene_country_id, "postcode": postcode, "city": city,
                   "products": [{"option_id": p, "qty": q} for p, q in products]}
        call = raw_post(sb, sba.ENDPOINT_SHIPPING, payload)
        call.update({"label": label, "country": code, "city": city, "postcode": postcode,
                     "request": redact(payload), "outcome": classify(call),
                     "at": datetime.now(timezone.utc).isoformat()})
        with lock:
            raw["rate_calls"].append(call)
            print(f"  {label:13} {code} {city:12} {call['outcome']:18} {call['seconds']}s", flush=True)
            with open(os.path.join(ART, "silverbene_probe_raw.json"), "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=1, ensure_ascii=False)
        return call

    A, B, C = (o["option_id"] for o in options)
    jobs = []
    for code, city, postcode in LOCATIONS:
        jobs.append((code, city, postcode, [(A, 1)], "single_A"))
    firsts = {}
    for code, city, postcode in LOCATIONS:
        firsts.setdefault(code, (city, postcode))
    for code, (city, postcode) in firsts.items():      # multi-item evidence, one location per country
        jobs.append((code, city, postcode, [(B, 1)], "single_B"))
        jobs.append((code, city, postcode, [(C, 1)], "single_C"))
        jobs.append((code, city, postcode, [(A, 1), (B, 1), (C, 1)], "combined_ABC"))
    workers = int(os.getenv("PROBE_WORKERS", "4"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda j: rate_call(*j), jobs))

    with open(os.path.join(ART, "silverbene_probe_raw.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=1, ensure_ascii=False)

    # Normalized matrix.
    markets = {}
    for call in raw["rate_calls"]:
        m = markets.setdefault(call["country"], {"supplier_country_id": call["request"]["country_id"],
                                                 "locations": {}, "combined_vs_sum": None})
        resp = (call.get("response") or {})
        methods = [] if call["outcome"] != "ok" else [
            {"method_id": x.get("way"), "title": x.get("title"), "price": x.get("price"),
             "currency": resp.get("currency") or x.get("currency") or "USD(assumed)",
             "delivery_text": {k: v for k, v in x.items() if k not in ("way", "title", "price")} or None}
            for x in resp.get("data", [])]
        m["locations"].setdefault(f"{call['city']} {call['postcode']}", {})[call["label"]] = {
            "outcome": call["outcome"], "at": call["at"], "methods": methods}

    for code, m in markets.items():
        first = next(iter(m["locations"].values()))
        def price_of(label, way):
            for x in first.get(label, {}).get("methods", []):
                if x["method_id"] == way:
                    return x["price"]
        combined = first.get("combined_ABC", {}).get("methods", [])
        cmp = []
        for x in combined:
            singles = [price_of(l, x["method_id"]) for l in ("single_A", "single_B", "single_C")]
            cmp.append({"method_id": x["method_id"], "title": x["title"], "combined_price": x["price"],
                        "sum_of_three_single_orders": (round(sum(singles), 2) if None not in singles else None)})
        m["combined_vs_sum"] = cmp
        ok_any = any(l.get("single_A", {}).get("outcome") == "ok" for l in m["locations"].values())
        titles = {x["title"] for l in m["locations"].values() for x in l.get("single_A", {}).get("methods", [])}
        fams = sorted({rates._family(t, "") for t in titles})
        m["supplier_supported"] = ok_any
        m["families"] = fams
        m["method_titles"] = sorted(titles)

    out = {"probed_at": stamp, "option_ids": [o["option_id"] for o in options],
           "note": "Read-only shipping-rate lookups only. No orders created.", "markets": markets}
    with open(os.path.join(ART, "silverbene_market_probe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    lines = ["# Silverbene Wave-1 probe (read-only)\n", f"Probed {stamp}. Options: {', '.join(o['option_id'] for o in options)}\n"]
    for code, m in markets.items():
        lines.append(f"\n## {code}  (country_id `{m['supplier_country_id']}`)  supported={m['supplier_supported']}")
        for loc, labels in m["locations"].items():
            a = labels.get("single_A", {})
            lines.append(f"- {loc}: {a.get('outcome')} -> " + "; ".join(
                f"{x['title']} [{x['method_id']}] ${x['price']}" for x in a.get("methods", [])))
        for c in m["combined_vs_sum"]:
            lines.append(f"- combined 3 items via {c['title']}: {c['combined_price']} vs 3 separate orders: {c['sum_of_three_single_orders']}")
    with open(os.path.join(ART, "silverbene_probe_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
