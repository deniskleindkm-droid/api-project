"""
Normalize Silverbene shipping-rate responses into customer-presentable choices.

Only fields the working adapter proves are read: `way` (the method id we send
back in create_order), `title` and `price`. ETA is NOT a proven response field,
so it is parsed out of the title text when Silverbene embeds it (their titles
look like "USPS(8-10 workdays)") and is otherwise absent -- never invented.

Two views are kept apart on purpose:
  - supplier_price / raw: internal cost, stored on the CheckoutTransaction,
    never returned to customers;
  - customer-facing option: name, ETA, and `customer_price` (0.0 while pricing
    is frozen -- shipping is absorbed in the product price, exactly as today).
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.checkout_intl import flags


def _family(title: str, way: str) -> str:
    t = f"{title} {way}".lower()
    for fam in ("dhl", "fedex", "ups", "usps", "epacket", "china post", "australia post", "la poste"):
        if fam in t:
            return fam.replace(" ", "_")
    return "other"


_ETA_RANGE = re.compile(r"(\d{1,3})\s*[-–~to]+\s*(\d{1,3})\s*(?:work(?:ing)?\s*|business\s*)?days?", re.I)
_ETA_SINGLE = re.compile(r"(\d{1,3})\s*(?:work(?:ing)?\s*|business\s*)?days?", re.I)


def parse_eta(title: str) -> Optional[dict]:
    m = _ETA_RANGE.search(title or "")
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < lo <= hi <= 120:
            return {"min_days": lo, "max_days": hi, "text": f"{lo}–{hi} business days"}
    m = _ETA_SINGLE.search(title or "")
    if m and 0 < int(m.group(1)) <= 120:
        d = int(m.group(1))
        return {"min_days": d, "max_days": d, "text": f"{d} business days"}
    return None


def normalize(raw_methods: list) -> List[dict]:
    """Supplier methods -> list of internal option dicts. Skips anything without a method id."""
    out, seen = [], set()
    for m in raw_methods or []:
        way = str(m.get("way") or m.get("method_code") or m.get("carrier_code") or "").strip()
        if not way or way in seen:
            continue
        seen.add(way)
        title = str(m.get("title") or way).strip()
        try:
            price = float(m["price"]) if m.get("price") is not None else None
        except (TypeError, ValueError):
            price = None
        out.append({
            "method_id": way,
            "name": title,
            "family": _family(title, way),
            "eta": parse_eta(title),
            "supplier_price": price,
        })
    return out


def present(options: List[dict]) -> List[dict]:
    """
    Apply the shipping policy and return the options a customer may pick from.

    dhl_only (default): today's standing rule -- ship DHL when Silverbene
    offers it. If it doesn't for this destination, offer the single cheapest
    method (flagged fallback=True) instead of blocking, same as the legacy
    fulfillment fallback. 'all': every method.
    """
    if not options:
        return []
    if flags.shipping_policy() == "all":
        return sorted(options, key=lambda o: (o["supplier_price"] is None, o["supplier_price"] or 0))
    dhl = [o for o in options if o["family"] == "dhl"]
    if dhl:
        return sorted(dhl, key=lambda o: (o["supplier_price"] is None, o["supplier_price"] or 0))[:1]
    priced = [o for o in options if o["supplier_price"] is not None] or options
    cheapest = min(priced, key=lambda o: o["supplier_price"] if o["supplier_price"] is not None else 0)
    return [{**cheapest, "fallback": True}]


def customer_view(option: dict) -> dict:
    """What the browser sees. No supplier cost, no supplier name."""
    return {
        "method_id": option["method_id"],
        "name": _customer_name(option),
        "eta_text": (option.get("eta") or {}).get("text"),
        "customer_price": 0.0,          # pricing frozen in Stage 1: shipping absorbed in product price
        "included": True,
    }


def _customer_name(option: dict) -> str:
    """Customers never learn the supplier's raw title/route wording."""
    fam = option.get("family")
    return {
        "dhl": "Express delivery (DHL)",
        "fedex": "Express delivery (FedEx)",
        "ups": "Express delivery (UPS)",
    }.get(fam, "Standard delivery")
