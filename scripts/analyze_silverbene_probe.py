"""
Normalize the raw Silverbene probe evidence (artifacts/silverbene_probe_raw.json) into the
per-country capability matrix, optionally re-trying calls that failed with transport errors
(read-only rate lookups only -- no orders, no payment links).

    python scripts/analyze_silverbene_probe.py [--retry]

Writes:
  artifacts/silverbene_market_probe.json   registry overlay (supplier_supported, families, standard, express, methods)
  artifacts/silverbene_probe_summary.md    human-readable matrix + multi-item economics
"""
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.checkout_intl import countries, rates  # noqa: E402

ART = os.path.join(os.path.dirname(__file__), "..", "artifacts")
RAW = os.path.join(ART, "silverbene_probe_raw.json")


def retry_failed(raw, rounds=2):
    import requests
    from app.agents.suppliers import silverbene_adapter as sba
    sb = sba.SilverbeneAdapter()
    for rnd in range(rounds):
        bad = [c for c in raw["rate_calls"] if c["outcome"] == "transport_error"]
        if not bad:
            break
        print(f"retry round {rnd + 1}: {len(bad)} failed call(s)", flush=True)
        for c in bad:
            body = dict(c["request"], token=sb.token)
            t0 = time.time()
            try:
                r = requests.post(f"{sb.base}{sba.ENDPOINT_SHIPPING}", json=body, timeout=240,
                                  headers={"Content-Type": "application/json"})
                c.update({"http_status": r.status_code, "response": r.json(), "seconds": round(time.time() - t0, 2),
                          "error": None, "retried": True, "at": datetime.now(timezone.utc).isoformat()})
                resp = c["response"]
                c["outcome"] = ("ok" if resp.get("data") else "ok_but_no_methods") if resp.get("code") in (0, "0") \
                    else f"supplier_error_code_{resp.get('code')}"
            except Exception as e:  # noqa: BLE001
                c.update({"error": f"{type(e).__name__}: {str(e).replace(sb.token, '<redacted>')}", "retried": True})
            print(f"  {c['label']} {c['country']} {c['city']} -> {c['outcome']} {c.get('seconds')}s", flush=True)
            time.sleep(2)
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", action="store_true")
    args = ap.parse_args()
    raw = json.load(open(RAW, encoding="utf-8"))
    if args.retry:
        raw = retry_failed(raw)
        json.dump(raw, open(RAW, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    markets = {}
    latencies = [c["seconds"] for c in raw["rate_calls"] if c["outcome"].startswith("ok")]
    for call in raw["rate_calls"]:
        code = call["country"]
        m = markets.setdefault(code, {"supplier_country_id": call["request"]["country_id"], "locations": {}})
        resp = call.get("response") or {}
        methods = resp.get("data") or [] if call["outcome"] == "ok" else []
        norm = rates.normalize(methods, code)
        m["locations"].setdefault(f"{call['city']} {call['postcode']}", {})[call["label"]] = {
            "outcome": call["outcome"], "seconds": call.get("seconds"), "at": call.get("at"),
            "currency": resp.get("currency"), "raw_methods": methods,
            "normalized": [{k: o[k] for k in ("method_id", "name", "tier", "supplier_price", "eta",
                                              "ambiguous_method_id", "alternatives") if k in o} for o in norm]}

    for code, m in markets.items():
        singles = [l["single_A"] for l in m["locations"].values() if "single_A" in l]
        good = [s for s in singles if s["outcome"] == "ok"]
        tiers = {}
        for s in good:
            for o in s["normalized"]:
                tiers.setdefault(o["tier"], set()).add(o["method_id"])
        m["supplier_supported"] = bool(good)
        m["standard"] = "STANDARD" in tiers or None
        m["express"] = "EXPRESS" in tiers or None
        m["families"] = sorted({rates._family(o["name"], o["method_id"]) for s in good for o in s["normalized"]})
        m["method_ids_by_tier"] = {t: sorted(v) for t, v in tiers.items()}
        m["ambiguous_method_ids"] = sorted({o["method_id"] for s in good for o in s["normalized"]
                                            if o.get("ambiguous_method_id")})
        m["usable_for_dropshipping"] = ("undetermined: rate lookup succeeded; wholesale-only restrictions are "
                                        "not exposed by the rate API")
        # price stability across locations, per method id
        stab = {}
        for s in good:
            for o in s["normalized"]:
                stab.setdefault(o["method_id"], []).append(o["supplier_price"])
        m["price_by_method_across_locations"] = {k: sorted(set(v)) for k, v in stab.items()}
        # multi-item economics at the first location that has all four call types
        cmp = []
        for loc, labels in m["locations"].items():
            if all(k in labels and labels[k]["outcome"] == "ok" for k in ("single_A", "single_B", "single_C", "combined_ABC")):
                def price(label, way):
                    return next((o["supplier_price"] for o in labels[label]["normalized"] if o["method_id"] == way), None)
                for o in labels["combined_ABC"]["normalized"]:
                    sing = [price(l, o["method_id"]) for l in ("single_A", "single_B", "single_C")]
                    cmp.append({"location": loc, "method_id": o["method_id"], "title": o["name"], "tier": o["tier"],
                                "combined_price": o["supplier_price"],
                                "sum_of_three_separate_orders": round(sum(sing), 2) if None not in sing else None})
                break
        m["combined_vs_separate"] = cmp

    out = {"probed_at": raw["probed_at"], "analysed_at": datetime.now(timezone.utc).isoformat(),
           "option_ids": [o["option_id"] for o in raw["options"]],
           "note": "Read-only shipping-rate lookups only. No orders created.",
           "latency_seconds": {"n": len(latencies), "min": min(latencies), "median": statistics.median(latencies),
                               "max": max(latencies)} if latencies else None,
           "country_list_endpoints_tried": raw.get("country_list_guesses"),
           "markets": markets}
    json.dump(out, open(os.path.join(ART, "silverbene_market_probe.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    countries.reset_probe_cache()

    L = ["# Silverbene Wave-1 probe (read-only)\n",
         f"Probed {raw['probed_at']}; option_ids {', '.join(out['option_ids'])}.",
         f"Rate-call latency (successful calls): {out['latency_seconds']}\n",
         "Country-list endpoints tried: " + ", ".join(
             f"{g['endpoint'].rsplit('/', 1)[-1]}={g.get('http_status', g.get('error'))}"
             for g in raw.get("country_list_guesses", [])) + "\n"]
    for code in ("US", "GB", "DE", "FR", "AU", "CA"):
        m = markets.get(code)
        if not m:
            L.append(f"\n## {code}: NOT PROBED")
            continue
        L.append(f"\n## {code} (country_id `{m['supplier_country_id']}`) supported={m['supplier_supported']} "
                 f"standard={m['standard']} express={m['express']}")
        for loc, labels in m["locations"].items():
            a = labels.get("single_A")
            if not a:
                continue
            L.append(f"- **{loc}** [{a['outcome']}, {a['seconds']}s, {a.get('currency')}]")
            for o in a["normalized"]:
                flag = " ⚠ duplicate method id" if o.get("ambiguous_method_id") else ""
                L.append(f"  - {o['tier']:8} `{o['method_id']}` {o['name']} — ${o['supplier_price']}{flag}")
        for c in m["combined_vs_separate"]:
            L.append(f"- 3 items at {c['location']} via `{c['method_id']}` ({c['tier']}): "
                     f"one shipment ${c['combined_price']} vs three orders ${c['sum_of_three_separate_orders']}")
        if m["ambiguous_method_ids"]:
            L.append(f"- ambiguous method ids: {m['ambiguous_method_ids']}")
    open(os.path.join(ART, "silverbene_probe_summary.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
