"""
Shipping-method catalog per country, built from read-only Silverbene probe evidence
(artifacts/silverbene_market_probe.json + artifacts/silverbene_lane_probe.json). Lets the
Delivery step answer INSTANTLY instead of waiting 6-110 s for a live rate lookup.

OWNER POLICY (2026-09-24): offer the fast, reputable methods only -- DHL Express in every market,
plus the national post where Silverbene actually offers one -- and NEVER the China-system
economy methods (Cainiao, International Economy/Standard, YunExpress), which take far too long.
Silverbene's API returned no USPS / La Poste / Australia Post / Canada Post / Hermes for any
tested product; the only national post it offers is Royal Mail (way "GTG") to the UK. Add a way
to METHOD_POLICY when Silverbene enables another lane (e.g. USPS for the US).

Known limitation: availability varies per product (a few products had no DHL to some countries),
so a listed method can occasionally be unavailable for a specific cart; the supplier order then
fails and the existing recovery/alert path raises it. Refresh the evidence by re-running
scripts/probe_silverbene_wave1.py, analyze_silverbene_probe.py and probe_silverbene_lanes.py.

Countries with no policy fall back to the methods common to every probed call, or to a live lookup.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Dict, List, Optional, Tuple

# country -> supplier method ids (`way`) customers may be offered, in display order.
METHOD_POLICY: Dict[str, Tuple[str, ...]] = {
    "US": ("DHLI",),            # USPS: not offered by the Silverbene API yet -> ask Silverbene
    "GB": ("GTG", "DHL"),       # Royal Mail + DHL Express
    "DE": ("DHL",),
    "FR": ("DHL",),
    "AU": ("DHL",),
    "CA": ("DHL",),
}

_cache: Optional[Dict[str, List[dict]]] = None
_ART = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts")


def reset_cache() -> None:
    global _cache
    _cache = None


def _evidence() -> Dict[str, List[List[dict]]]:
    """country -> list of successful rate calls, each a list of {way,title,price}."""
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


def _build() -> Dict[str, List[dict]]:
    result: Dict[str, List[dict]] = {}
    for code, calls in _evidence().items():
        policy = METHOD_POLICY.get(code)
        if policy is not None:
            # Deliberately chosen methods: offer each one seen in ANY successful probe call.
            picked = []
            for way in policy:
                seen = [m for call in calls for m in call if m.get("way") == way]
                if not seen:
                    continue
                title = Counter(m["title"] for m in seen).most_common(1)[0][0]
                prices = sorted(m["price"] for m in seen if m.get("title") == title and m.get("price") is not None)
                picked.append({"way": way, "title": title, "price": prices[len(prices) // 2] if prices else None})
            if picked:
                result[code] = picked
            continue
        # No policy for this country: only methods present in EVERY probed call.
        sets = [{(m["way"], m["title"]): m for m in call} for call in calls]
        common = set(sets[0])
        for s in sets[1:]:
            common &= set(s)
        if common:
            result[code] = [{"way": w, "title": t, "price": sets[0][(w, t)]["price"]} for (w, t) in sorted(common)]
    return result


def methods_for(country: str) -> Optional[List[dict]]:
    """Raw supplier-shaped methods [{way,title,price}] for the country, or None if not catalogued."""
    global _cache
    if _cache is None:
        _cache = _build()
    m = _cache.get(country.upper())
    return list(m) if m else None
