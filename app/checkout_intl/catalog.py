"""
Two-class shipping catalog per country (STANDARD / EXPRESS), built from read-only Silverbene probe
evidence (artifacts/silverbene_market_probe.json + silverbene_lane_probe.json).

WHY CLASSES, NOT CARRIERS: Silverbene's methods and prices vary by address and even by product
(observed: DHL missing for some products; Royal Mail only for some UK carts; USPS on their website
but not in the rate API). Promising a specific carrier at checkout is therefore fragile. Instead:

  * customers choose a CLASS -- Standard or Express (DHL);
  * each class carries a COST BASIS = the MAXIMUM price seen for that class in that country
    (the safe number for the repricing stage);
  * the actual carrier is chosen AFTER payment from the live rates for the exact cart + address
    (see rates.resolve_class_method and checkout_intl/fulfillment.py).

Owner preferences (2026-09-24): Express = DHL; Standard = the national post when Silverbene offers
one (Royal Mail to the UK today; USPS for the US once Silverbene exposes it), otherwise the best
of the remaining methods. Add a way to STANDARD_PREFERENCE when a new lane appears.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from typing import Dict, List, Optional, Tuple

EXPRESS_PREFERENCE: Tuple[str, ...] = ("DHL", "DHLI")            # DHL Express, always first
EXPRESS_FALLBACK: Tuple[str, ...] = ("Fedex", "FedexI")          # only if DHL is unavailable (alerts)

# Standard preference order per country (first available wins). Anything not listed is a last resort.
STANDARD_PREFERENCE: Dict[str, Tuple[str, ...]] = {
    "US": ("SUX", "ITDIDA_ECO"),                                  # SUX = USPS (not returned by the API so far)
    "GB": ("GTG", "BKPHR", "cainiao", "ITDIDA_ECO"),              # Royal Mail first
    "DE": ("BKPHR", "cainiao", "ITDIDA_ECO"),
    "FR": ("BKPHR", "cainiao", "ITDIDA_ECO"),
    "AU": ("BKPHR", "cainiao"),
    "CA": ("BKPHR", "cainiao", "ITDIDA_ECO"),
}

_ART = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts")
_cache: Optional[Dict[str, dict]] = None


def reset_cache() -> None:
    global _cache
    _cache = None


def _evidence() -> Dict[str, List[List[dict]]]:
    """country -> list of successful single-item rate calls, each a list of {way,title,price}."""
    out: Dict[str, List[List[dict]]] = {}
    try:
        with open(os.path.join(_ART, "silverbene_market_probe.json"), encoding="utf-8") as f:
            for code, m in json.load(f).get("markets", {}).items():
                for labels in m.get("locations", {}).values():
                    for label in ("single_A", "single_B", "single_C"):
                        call = labels.get(label)
                        if call and call.get("outcome") == "ok" and call.get("raw_methods"):
                            out.setdefault(code, []).append(call["raw_methods"])
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(_ART, "silverbene_lane_probe.json"), encoding="utf-8") as f:
            for c in json.load(f).get("calls", []):
                if c.get("outcome") == "ok" and c.get("methods"):
                    out.setdefault(c["country"], []).append(c["methods"])
    except (OSError, ValueError):
        pass
    return out


_ETA = re.compile(r"(\d{1,3})\s*[-–]\s*(\d{1,3})\s*work", re.I)


def _eta(title: str) -> Optional[Tuple[int, int]]:
    m = _ETA.search(title or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _stats(prices: List[float]) -> dict:
    return {"max": max(prices), "min": min(prices), "median": round(statistics.median(prices), 2), "n": len(prices)}


def _build() -> Dict[str, dict]:
    from app.checkout_intl import rates
    card: Dict[str, dict] = {}
    for code, calls in _evidence().items():
        exp_prices, std_prices, exp_ways, std_ways, std_etas, exp_etas = [], [], set(), set(), [], []
        for call in calls:
            for m in call:
                if m.get("price") is None:
                    continue
                way, title = m["way"], m["title"]
                if way in EXPRESS_PREFERENCE:
                    exp_prices.append(float(m["price"]))
                    exp_ways.add(way)
                    if _eta(title):
                        exp_etas.append(_eta(title))
                elif way in EXPRESS_FALLBACK:
                    continue                                   # FedEx is a fallback, not a cost basis
                else:
                    std_prices.append(float(m["price"]))
                    std_ways.add(way)
                    if _eta(title):
                        std_etas.append(_eta(title))
        entry = {"n_calls": len(calls)}
        if exp_prices:
            entry["express"] = {**_stats(exp_prices), "ways": sorted(exp_ways),
                                "eta": (min(e[0] for e in exp_etas), max(e[1] for e in exp_etas)) if exp_etas else None}
        if std_prices:
            entry["standard"] = {**_stats(std_prices), "ways": sorted(std_ways),
                                 "eta": (min(e[0] for e in std_etas), max(e[1] for e in std_etas)) if std_etas else None}
        if "express" in entry or "standard" in entry:
            card[code] = entry
    return card


def ratecard() -> Dict[str, dict]:
    """country -> {express: {max,min,median,n,ways,eta}, standard: {...}}; max = the cost basis."""
    global _cache
    if _cache is None:
        _cache = _build()
    return _cache


def class_options(country: str) -> Optional[List[dict]]:
    """
    The two customer-facing options for a country, shaped like rates.normalize() output. The
    supplier_price is the class's MAXIMUM observed price (cost basis, never shown to customers).
    None if the country has no evidence (caller falls back to a live lookup).
    """
    entry = ratecard().get(country.upper())
    if not entry:
        return None
    opts = []
    if "express" in entry:
        e = entry["express"]
        opts.append({"method_id": "EXPRESS", "name": "Express delivery (DHL)", "family": "dhl", "tier": "EXPRESS",
                     "eta": _eta_dict(e["eta"]), "supplier_price": e["max"], "class_choice": True,
                     "basis": "max_observed", "observed": {k: e[k] for k in ("min", "median", "max", "n")}})
    if "standard" in entry:
        s = entry["standard"]
        opts.append({"method_id": "STANDARD", "name": "Standard delivery", "family": "other", "tier": "STANDARD",
                     "eta": _eta_dict(s["eta"]), "supplier_price": s["max"], "class_choice": True,
                     "basis": "max_observed", "observed": {k: s[k] for k in ("min", "median", "max", "n")}})
    return opts or None


def _eta_dict(eta: Optional[Tuple[int, int]]) -> Optional[dict]:
    if not eta:
        return None
    lo, hi = eta
    return {"min_days": lo, "max_days": hi, "text": f"{lo}–{hi} business days"}
