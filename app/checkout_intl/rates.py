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


STANDARD = "STANDARD"
EXPRESS = "EXPRESS"

# Per (country, supplier method id) tier overrides established from probe evidence.
TIER_OVERRIDES: dict = {}

_STANDARD_HINT = re.compile(
    r"global\s*mail|econom|e-?packet|standard|registered|royal\s*mail|hermes|la\s*poste|colissimo|"
    r"canada\s*post|australia\s*post|usps|china\s*(?:ems\s*)?post|yanwen|4px|airmail|air\s*mail", re.I)
_EXPRESS_HINT = re.compile(r"\bdhl\b|fedex|\bups\b|\bems\b|\btnt\b|express|priority", re.I)
_TRUE_EXPRESS = re.compile(r"dhl\s*express|fedex|\bups\b", re.I)


def classify_tier(title: str, way: str, eta: Optional[dict], country: str = "") -> str:
    """
    Map a supplier method to the customer-facing service tier. Evidence order:
    explicit override > economy wording (wins even when the word "express" appears,
    e.g. "Economic Express") > express carrier wording > ETA (<=8 business days ->
    EXPRESS) > STANDARD. Raw carrier names never become the customer contract.
    """
    override = TIER_OVERRIDES.get((country.upper(), way))
    if override:
        return override
    text = f"{title} {way}"
    if _STANDARD_HINT.search(text) and not _TRUE_EXPRESS.search(text):
        return STANDARD
    if _EXPRESS_HINT.search(text):
        return EXPRESS
    if eta and eta["max_days"] <= 8:
        return EXPRESS
    return STANDARD


def normalize(raw_methods: list, country: str = "") -> List[dict]:
    """Supplier methods -> internal options (all tiers). Skips anything without a method id."""
    by_way: dict = {}
    for m in raw_methods or []:
        way = str(m.get("way") or m.get("method_code") or m.get("carrier_code") or "").strip()
        if not way:
            continue
        title = str(m.get("title") or way).strip()
        try:
            price = float(m["price"]) if m.get("price") is not None else None
        except (TypeError, ValueError):
            price = None
        eta = parse_eta(title)
        opt = {
            "method_id": way,
            "name": title,
            "family": _family(title, way),
            "tier": classify_tier(title, way, eta, country),
            "eta": eta,
            "supplier_price": price,
        }
        prior = by_way.get(way)
        if prior is None:
            by_way[way] = opt
            continue
        # Silverbene can return DIFFERENT services (different title/price) under ONE `way`
        # (observed: ITDIDA_ECO = "International Economy" $3.50 AND "International Standard"
        # $5.52). create_order takes only `way`, so the customer's exact pick between them
        # cannot be expressed. Keep the dearer one (worst case for cost bookkeeping) and
        # record the ambiguity for audit; it must be resolved with the supplier.
        keep, other = (opt, prior) if (price or 0) > (prior["supplier_price"] or 0) else (prior, opt)
        keep["ambiguous_method_id"] = True
        keep["alternatives"] = prior.get("alternatives", []) + [
            {"title": other["name"], "price": other["supplier_price"]}]
        by_way[way] = keep
    return list(by_way.values())


def _by_price(opts):
    return sorted(opts, key=lambda o: (o["supplier_price"] is None, o["supplier_price"] or 0))


def present(options: List[dict]) -> List[dict]:
    """
    The options a customer may pick from, per flags.tier_exposure(). All tiers stay
    quoted/persisted on the transaction; only the offered subset reaches the browser.
    """
    if not options:
        return []
    if flags.tier_exposure() == "all":
        # Fastest tier first, then cheapest within a tier, so the list reads naturally.
        return sorted(options, key=lambda o: (o["tier"] != EXPRESS, o["supplier_price"] is None,
                                              o["supplier_price"] or 0))
    std = _by_price([o for o in options if o["tier"] == STANDARD])
    exp = _by_price([o for o in options if o["tier"] == EXPRESS])
    if flags.tier_exposure() == "both":
        return ([std[0]] if std else []) + ([exp[0]] if exp else [])
    if exp:
        # Standing rule (owner, 2026-09-12): ship DHL when the supplier offers it, even if
        # another express carrier is cheaper. Only fall back to the cheapest express otherwise.
        dhl = [o for o in exp if o["family"] == "dhl"]
        return [(dhl or exp)[0]]
    return [{**std[0], "fallback": True}] if std else []


def display_name(option: dict) -> str:
    """Customer-facing label: the service name with the supplier's parenthetical ETA/notes removed."""
    base = re.sub(r"\s*\(.*?\)\s*", " ", option.get("name") or "").strip()
    base = re.sub(r"\s+", " ", base) or ("Express delivery" if option["tier"] == EXPRESS else "Standard delivery")
    return base


def resolve_class_method(country: str, live_methods: list, cls: str) -> Optional[dict]:
    """
    Pick the real supplier method for a customer's chosen CLASS ("EXPRESS" / "STANDARD") from the live
    rates for the exact cart + address. Returns {method_id, name, supplier_price, tier, fallback,
    reason} or None when nothing suitable is available (caller must hold the order, never guess).

    EXPRESS  : DHL; if the supplier has no DHL for this cart, FedEx (fallback=True -> owner alert).
    STANDARD : the country's preferred order (national post first, e.g. Royal Mail); then any other
               STANDARD-tier method by price (fallback=True). NEVER upgraded to express on its own:
               that would silently raise the cost.
    """
    from app.checkout_intl import catalog
    opts = normalize(live_methods, country)
    by_way = {o["method_id"]: o for o in opts}

    def pick(way, fallback=False, reason=""):
        o = by_way[way]
        return {"method_id": o["method_id"], "name": o["name"], "supplier_price": o["supplier_price"],
                "tier": o["tier"], "fallback": fallback, "reason": reason}

    if cls == EXPRESS:
        for way in catalog.EXPRESS_PREFERENCE:
            if way in by_way:
                return pick(way)
        for way in catalog.EXPRESS_FALLBACK:
            if way in by_way:
                return pick(way, True, "DHL not offered for this cart/address")
        return None
    if cls == STANDARD:
        for way in catalog.STANDARD_PREFERENCE.get(country.upper(), ()):
            if way in by_way and by_way[way]["tier"] == STANDARD:
                return pick(way)
        others = _by_price([o for o in opts if o["tier"] == STANDARD])
        if others:
            return pick(others[0]["method_id"], True, "no preferred standard method available")
        return None
    return None


def customer_view(option: dict) -> dict:
    """What the browser sees. Never the supplier price."""
    return {
        "method_id": option["method_id"],   # opaque choice key sent back on pay
        "tier": option["tier"],
        "name": display_name(option),
        "eta_text": (option.get("eta") or {}).get("text"),
        "customer_price": 0.0,          # pricing frozen: shipping absorbed in product price
        "included": True,
    }
