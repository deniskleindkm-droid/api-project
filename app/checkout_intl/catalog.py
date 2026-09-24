"""
Shipping-method catalog per country, built from the read-only Silverbene probe evidence
(artifacts/silverbene_market_probe.json). Lets the Delivery step answer INSTANTLY with every
method Silverbene actually offered, instead of waiting 6-110 s for a live rate lookup.

Safety rule -- a method is offered only if it appeared for EVERY probed location AND every
probed product option in that country (intersection). A method that showed up only for some
addresses/products (e.g. YunExpress for Manchester but not London) is left out, so a customer is
never offered a service the supplier later refuses. Prices are the probe's single-item quotes and
are internal bookkeeping only (never shown to customers).

Countries not in the catalog fall back to the live lookup. Refresh by re-running
scripts/probe_silverbene_wave1.py + scripts/analyze_silverbene_probe.py.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

_cache: Optional[dict] = None


def _path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "silverbene_market_probe.json")


def reset_cache() -> None:
    global _cache
    _cache = None


def _build() -> Dict[str, List[dict]]:
    try:
        with open(_path(), encoding="utf-8") as f:
            markets = json.load(f).get("markets", {})
    except (OSError, ValueError):
        return {}
    out: Dict[str, List[dict]] = {}
    for code, m in markets.items():
        per_call = []
        for labels in m.get("locations", {}).values():
            for label in ("single_A", "single_B", "single_C"):
                call = labels.get(label)
                if call and call.get("outcome") == "ok" and call.get("raw_methods"):
                    per_call.append({(x["way"], x["title"]): x for x in call["raw_methods"]})
        if not per_call:
            continue
        common = set(per_call[0])
        for d in per_call[1:]:
            common &= set(d)
        # Locations differ in which ways they return; keep only what all calls agree on.
        # (Titles can embed price-independent ETA text, so identity is (way, title).)
        out[code] = [{"way": w, "title": t, "price": per_call[0][(w, t)]["price"]} for (w, t) in sorted(common)]
    return out


def methods_for(country: str) -> Optional[List[dict]]:
    """Raw supplier-shaped methods [{way,title,price}] for the country, or None if not catalogued."""
    global _cache
    if _cache is None:
        _cache = _build()
    m = _cache.get(country.upper())
    return list(m) if m else None
