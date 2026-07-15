"""
Catalog Audit Agent
--------------------
Read-only sanity sweep over every active Silverbene product's variant data.
Flags data that *looks* wrong by content, not by waiting for a customer or
Dennis to spot it live — this is the permanent, rerunnable version of the
one-off comparison scripts written during the 2026-07-15 size/color chip
bug hunt (see memory: feedback_silverbene_price_backed_sizes,
project_compound_variant_fix).

Three checks, each catching a different class of bug this pipeline has
actually shipped:

  1. Unknown attribute names — any variant attribute name Silverbene sends
     that no extraction path recognizes at all. If its values look like a
     real spec (a metal/plating word, or a measurement), it's a strong
     signal of an invisible customer-facing choice, the same shape as the
     "Purity" gap (a genuine finish choice sat unrecognized for months
     because "purity" was never in COLOR_ATTRIBUTE_NAMES). This is the
     proactive catch — it doesn't need a bug report to fire.

  2. Suspicious chip content — a "sizes" entry that looks like a stone
     weight (contains CT/Carat), a "colors" entry that still carries a
     leftover measurement or diameter-label fragment, or either carrying
     stray trailing punctuation. Static checks, independent of any stored
     baseline — a permanent regression net for bugs already fixed once.

  3. Stale stored data — recomputes sizes/colors from each product's own
     already-stored `variants` JSON using the CURRENT extraction code and
     diffs against what's actually stored on the row. Any mismatch means
     a code fix landed but this product was never backfilled — exactly
     the manual step this session kept needing a human to remember.

Read-only: prints a report and returns it as a dict. Never writes to the
database — a human (or a follow-up, explicitly-approved backfill pass)
decides what to do with what it finds.

Safe to run anytime: on a schedule, from a shell, or ad hoc after any
change to silverbene_adapter.py's extraction logic.
"""
import json
import re
from sqlmodel import Session, select
from app.database import engine
from app.models.product import Product

# Every attribute name any extraction path in silverbene_adapter.py actually
# recognizes today. Kept as a local mirror (not an import) deliberately —
# this file's whole job is to notice when that set falls behind reality, so
# it re-derives its own understanding of "known" rather than trusting the
# adapter's sets never drift out of sync with what's actually handled.
_KNOWN_ATTR_NAMES = {
    "color", "colour", "metal color", "metal finish", "finish",
    "main stone", "stone", "stone color", "stone type", "birthstone",
    "size", "ring size", "length", "bracelet size", "anklet size", "chain length",
    "wrist size", "inner diameter", "bracelet length",
    "purity",  # partially handled — see _extract_variants' _purity_is_real gate
}

# A value under an unrecognized attribute name is only worth flagging if it
# looks like it might actually mean something — plain noise ("Yes", "N/A")
# isn't interesting. Same "does it look like a metal/plating word or a real
# measurement" shape as the Purity fix itself.
_SUSPICIOUS_VALUE_RE = re.compile(
    r'\b(gold|silver|platinum|plating|plated|rhodium)\b|\d+(\.\d+)?\s*(mm|cm|ct)\b',
    re.I,
)

_CARAT_RE = re.compile(r'\d\s*c\.?t\.?\b|\bcarat\b', re.I)
_DIAMETER_LEAK_RE = re.compile(r'\b(outer|inner)?\s*diameter\b', re.I)
_BARE_MEASUREMENT_RE = re.compile(r'\b\d+(\.\d+)?\s*(mm|cm)\b', re.I)
_TRAILING_PUNCT_RE = re.compile(r'[,;]\s*$')


def _load_sizes_colors(raw_json_str):
    """Parse a Product.sizes/colors column (JSON-encoded list, or None) safely."""
    if not raw_json_str:
        return []
    try:
        v = json.loads(raw_json_str)
        if isinstance(v, str):
            v = json.loads(v) if v else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _audit_unknown_attributes(products):
    """Check 1 — attribute names no extraction path recognizes, with a
    suspicious-looking value. Returns {attr_name: [(product_id, name, value), ...]}."""
    findings = {}
    for p in products:
        try:
            options = json.loads(p.variants or "[]")
        except Exception:
            continue
        for opt in options:
            for attr in opt.get("attribute", []):
                name = (attr.get("name") or "").lower().strip()
                value = (attr.get("value") or "").strip()
                if not name or not value or name in _KNOWN_ATTR_NAMES:
                    continue
                if _SUSPICIOUS_VALUE_RE.search(value):
                    findings.setdefault(name, [])
                    if len(findings[name]) < 5:  # a handful of examples is enough to act on
                        findings[name].append((p.id, p.name[:50], value))
    return findings


def _audit_suspicious_chips(products):
    """Check 2 — static content red flags in already-stored sizes/colors."""
    findings = []
    for p in products:
        sizes = _load_sizes_colors(p.sizes)
        colors = _load_sizes_colors(p.colors)
        issues = []
        for s in sizes:
            if _CARAT_RE.search(s):
                issues.append(f'size "{s}" looks like a stone weight, not a physical size')
            if _TRAILING_PUNCT_RE.search(s):
                issues.append(f'size "{s}" has stray trailing punctuation')
        for c in colors:
            if _DIAMETER_LEAK_RE.search(c):
                issues.append(f'color "{c}" still carries a measurement-label fragment')
            if _BARE_MEASUREMENT_RE.search(c):
                issues.append(f'color "{c}" still carries a bare measurement')
            if _TRAILING_PUNCT_RE.search(c):
                issues.append(f'color "{c}" has stray trailing punctuation')
        if issues:
            findings.append((p.id, p.name[:50], issues))
    return findings


def _audit_stale_data(products):
    """
    Check 3 — stored sizes/colors vs what current code would produce right
    now, from _extract_variants() alone.

    Deliberately narrower than the real import pipeline: _to_standard() also
    (a) falls back to a description-parsed chain length when the variant
    options themselves have none, and (b) runs a final Rhodium->Silver/White
    Gold pass — both need the raw pre-sanitized Silverbene description text,
    which isn't stored on the Product row (only the cleaned, customer-facing
    description is), so this check can't replicate them. Approximates the
    Rhodium step with the same *default* mapping _normalize_color_final uses
    (Rhodium -> Silver) to avoid false positives on every Rhodium-plated
    product; the rarer per-product White Gold override is invisible to this
    check and won't be flagged if that's the actual live value. Only flags
    when the fresh result is non-empty and differs — an empty fresh result
    against a non-empty stored value is exactly the shape the unreplicated
    description-fallback produces legitimately, not a signal of real drift.
    """
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter, _RHODIUM_TOKEN_RE
    adapter = SilverbeneAdapter.__new__(SilverbeneAdapter)  # extraction needs no API state

    findings = []
    for p in products:
        try:
            options = json.loads(p.variants or "[]")
        except Exception:
            continue
        if not options:
            continue
        try:
            fresh_sizes, fresh_colors = adapter._extract_variants(options, category=p.category or "")
        except Exception as e:
            findings.append((p.id, p.name[:50], [f"extraction raised: {e}"]))
            continue
        stored_sizes = _load_sizes_colors(p.sizes)
        stored_colors = _load_sizes_colors(p.colors)
        fresh_sizes = fresh_sizes or []
        fresh_colors = [_RHODIUM_TOKEN_RE.sub("Silver", c) for c in (fresh_colors or [])]
        issues = []
        if fresh_sizes and sorted(stored_sizes) != sorted(fresh_sizes):
            issues.append(f"sizes stale: stored={stored_sizes} current_code_would_produce={fresh_sizes}")
        if fresh_colors and sorted(stored_colors) != sorted(fresh_colors):
            issues.append(f"colors stale: stored={stored_colors} current_code_would_produce={fresh_colors}")
        if issues:
            findings.append((p.id, p.name[:50], issues))
    return findings


def run_catalog_audit(verbose: bool = True) -> dict:
    """
    Runs all three checks against every active Silverbene product.
    Returns a dict report; also prints it when verbose (default — matches
    every other agent in this codebase, which report via print()).
    """
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.supplier_name == "Silverbene",
            )
        ).all()

    unknown_attrs = _audit_unknown_attributes(products)
    suspicious_chips = _audit_suspicious_chips(products)
    stale = _audit_stale_data(products)

    report = {
        "products_scanned": len(products),
        "unknown_attributes": unknown_attrs,
        "suspicious_chips": suspicious_chips,
        "stale_data": stale,
    }

    if verbose:
        print(f"[Catalog Audit] Scanned {len(products)} active Silverbene products")

        if unknown_attrs:
            print(f"[Catalog Audit] {len(unknown_attrs)} unrecognized attribute name(s) with suspicious values:")
            for name, examples in unknown_attrs.items():
                print(f"[Catalog Audit]   \"{name}\":")
                for pid, pname, val in examples:
                    print(f"[Catalog Audit]     #{pid} {pname} -> {val!r}")
        else:
            print("[Catalog Audit] No unrecognized attribute names look suspicious")

        if suspicious_chips:
            print(f"[Catalog Audit] {len(suspicious_chips)} product(s) with suspicious chip content:")
            for pid, pname, issues in suspicious_chips:
                for issue in issues:
                    print(f"[Catalog Audit]   #{pid} {pname}: {issue}")
        else:
            print("[Catalog Audit] No suspicious size/color chip content found")

        if stale:
            print(f"[Catalog Audit] {len(stale)} product(s) have stale sizes/colors vs current code:")
            for pid, pname, issues in stale:
                for issue in issues:
                    print(f"[Catalog Audit]   #{pid} {pname}: {issue}")
        else:
            print("[Catalog Audit] No stale sizes/colors — every product matches what current code would produce")

    return report


if __name__ == "__main__":
    run_catalog_audit()
