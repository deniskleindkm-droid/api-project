from app.agents.suppliers.base import SupplierAdapter
from typing import Optional
import requests
import json
import os
import re

SILVERBENE_BASE = "https://s.silverbene.com"

# ── CONFIRMED ENDPOINTS ───────────────────────────────────────────────────────
# All verified against live API on 2026-06-02
ENDPOINT_PRODUCT_LIST      = "/api/dropshipping/product_list"           # GET — by SKU
ENDPOINT_PRODUCT_BY_DATE   = "/api/dropshipping/product_list_by_date"  # GET — browse + keyword search
ENDPOINT_OPTION_QTY        = "/api/dropshipping/option_qty"             # GET — stock by option_id
ENDPOINT_SHIPPING          = "/api/dropshipping/get_shipping_method"    # GET — shipping methods
ENDPOINT_CREATE_ORDER      = "/api/dropshipping/create_order"           # POST — place order
ENDPOINT_STORE_CREDIT      = "/api/dropshipping/store_credit"           # GET — account balance
# ─────────────────────────────────────────────────────────────────────────────

# Search keywords per Mikisi collection
CATEGORY_KEYWORDS = {
    "Rings":     ["ring", "925 ring", "adjustable ring", "silver statement ring",
                  "sterling silver band ring", "925 silver gemstone ring", "women ring size"],
    "Necklaces": ["necklace", "pendant", "chain", "lariat", "choker", "collar"],
    "Bracelets": ["bracelet", "chain bracelet", "link bracelet", "tennis bracelet",
                  "bangle", "bangle bracelet", "open bangle"],
    "Earrings":  ["earring", "stud earring", "drop earring"],
    "Anklets":   ["anklet"],
    "Ear Cuffs": ["ear cuff", "cartilage earring", "no piercing ear"],
}

# Values Silverbene puts in the Color attribute that are actually product-type descriptors.
# Strip these prefixes before storing as a display color.
_CATEGORY_PREFIXES = {"anklet", "bracelet", "necklace", "ring", "earring", "pendant", "chain"}

# A bangle is a rigid (or semi-rigid, cast-open) band — sized by inner diameter,
# not by a flexible wrist-length measurement. Silverbene's own title/description
# always says "bangle" outright when a bracelet is this style; never inferred
# from shape/material, since a wrong guess would apply the wrong size math
# (circumference-from-diameter vs. a direct wrist length) to a real chain bracelet.
_BANGLE_WORD_RE = re.compile(r'\bbangle\b', re.I)
_BRACELET_WORD_RE = re.compile(r'\bbracelet\b', re.I)


def is_bangle_product(title: str, desc: str = "") -> bool:
    """True if Silverbene's own title or raw description identifies this bracelet
    as a bangle. Ground truth only — never guessed from shape/material words."""
    return bool(_BANGLE_WORD_RE.search(title or "") or _BANGLE_WORD_RE.search(desc or ""))


def ensure_bangle_bracelet_naming(name: str, category: str, is_bangle: bool) -> str:
    """
    A bangle's display name must contain BOTH "Bangle" and "Bracelet" — the shape
    and the storefront category — never just one. Silverbene's raw titles and our
    own shortened names are inconsistent about including either word, so this is
    the single place that guarantees "... Bangle Bracelet" for every bangle,
    regardless of what ARIA's rewrite or the raw title happened to keep.
    """
    if category != "Bracelets" or not is_bangle or not name:
        return name
    has_bangle = bool(_BANGLE_WORD_RE.search(name))
    has_bracelet = bool(_BRACELET_WORD_RE.search(name))
    if has_bangle and has_bracelet:
        return name
    if has_bracelet:
        return _BRACELET_WORD_RE.sub("Bangle Bracelet", name, count=1)
    if has_bangle:
        return _BANGLE_WORD_RE.sub("Bangle Bracelet", name, count=1)
    return f"{name} Bangle Bracelet"

# Attribute names Silverbene uses per category type
SIZE_ATTRIBUTE_NAMES = {"size", "ring size", "length", "bracelet size", "anklet size", "chain length"}
BRACELET_SIZE_ATTR_NAMES = {"wrist size", "inner diameter", "bracelet size", "bracelet length"}
COLOR_ATTRIBUTE_NAMES = {"color", "colour", "metal color", "metal finish", "finish", "main stone", "stone", "stone color", "stone type", "birthstone"}
_METAL_ATTR_NAMES = {"color", "colour", "metal color", "metal finish", "finish"}

_SIZE_MEASURE_RE = re.compile(r'\d+\s*(mm|cm)', re.I)

# Matches a real length measurement buried inside Silverbene's overloaded
# "Purity" attribute (e.g. "925 Silver, Length 16.5CM") — deliberately keyed
# on the literal word "Length" next to the number, not on the attribute name
# alone, since "Purity" means different things on different products (see
# [[project_compound_variant_fix]]'s residual-gaps note) and must never be
# treated as a size source in general.
_PURITY_LENGTH_RE = re.compile(r'\blength\b\s*[:\-]?\s*\d+(?:\.\d+)?\s*(cm|mm)', re.I)

def sizes_are_variant_backed(variants_json) -> bool:
    """
    True only if at least one of this product's real, priced Silverbene
    options carries a genuine size-type attribute (Size, Ring Size, Chain
    Length, Bracelet Size, Wrist Size, Inner Diameter, ...) OR a Color-type
    attribute whose value bundles a real measurement (e.g. "18K Yellow Gold
    2.0x15mm") — the same two conditions /variant-prices (routes/products.py)
    and _extract_variants() (below) use to ever produce a non-null size for
    an option, so this always agrees with whether those endpoints actually
    can resolve a size. Deliberately checks the same preconditions rather
    than re-running the full split/parse — see _split_color_and_size's
    docstring: a matched measurement is never silently discarded, always
    becomes some size chip.

    False means any size text the product displays (p.sizes) was
    synthesized by parsing the free-text description as a fallback (see
    _extract_bracelet_info_from_desc / _parse_chain_length_from_desc below)
    because Silverbene's real options gave us nothing — real information,
    but never a distinct priced choice. A product like this has ONE priced
    option that varies only by color (or nothing at all), so its
    description-derived size can never correspond to a different
    option_id/price and must never be offered as a clickable/matchable
    selector — see _size_display_meta() in routes/products.py, the single
    place that decides selector vs. display-only badge, which calls this
    instead of guessing from the display text.
    """
    try:
        variants = json.loads(variants_json) if isinstance(variants_json, str) else (variants_json or [])
    except Exception:
        return False
    size_names = SIZE_ATTRIBUTE_NAMES | BRACELET_SIZE_ATTR_NAMES
    for v in (variants or []):
        for a in (v.get("attribute") or v.get("attributes") or []):
            name = (a.get("name") or "").lower().strip()
            val = (a.get("value") or "").strip()
            if name in size_names:
                return True
            if name in COLOR_ATTRIBUTE_NAMES and val and _SIZE_MEASURE_RE.search(val):
                return True
    return False


# Matches "Rhodium" wherever it appears, including Silverbene's typo'd raw-data
# variants that glue extra characters directly onto the word with no separator
# ("Rhodiumm Tone", "Rhodiumne") — \w* consumes those, stopping at the next
# real word boundary (space/punctuation), so "Rhodiumm Tone" -> "<target> Tone"
# and "Rhodiumne" -> "<target>". The single source of truth for every place
# that needs to detect-and-replace a Rhodium mention (see _normalize_color_final,
# _normalize_finish_terms, and _to_standard's Step 3 write-back) — they must all
# agree, or a customer's displayed chip stops matching the raw data at order time.
_RHODIUM_TOKEN_RE = re.compile(r'\bRhodium\w*', re.I)

# Maps Silverbene's internal/technical metal color names → customer-friendly display names.
# Only applied to metal-context attributes (not stone names like "Yellow Sapphire").
# "Pink" is the most common; others appear in compound variant names. Rhodium is
# deliberately NOT here — it's handled separately via _RHODIUM_TOKEN_RE in
# _normalize_color_final, since (unlike these) it needs a per-product, desc-aware
# decision between "Silver" and "White Gold" (see _rhodium_display_name).
_METAL_COLOR_NORMALIZE = {
    "pink":              "Rose Gold",
    "yellow":            "Yellow Gold",
    "white":             "White Gold",
    "18k gold":          "Gold",
    "18k rose gold":     "Rose Gold",
    "18k white gold":    "White Gold",
    "18k yellow gold":   "Yellow Gold",
    "no plating":        "Silver",
}

# Maps frontend display labels back to the raw Silverbene values they could represent.
# Safety net for existing DB data that was stored before _normalize_color_final existed.
# "white gold" includes "rhodium" because _normalize_finish_terms sometimes promotes
# "Rhodium" → "White Gold" in p.colors while p.variants still stores "Rhodium" raw.
_COLOR_LABEL_REVERSE: dict[str, list[str]] = {
    "gold":        ["gold", "18k gold"],
    "yellow gold": ["yellow gold", "yellow", "18k yellow gold"],
    "rose gold":   ["rose gold", "pink", "18k rose gold"],
    "white gold":  ["white gold", "white", "rhodium", "18k white gold"],
    "silver":      ["silver", "rhodium"],
    "platinum":    ["platinum"],
    "black":       ["black"],
}


def _normalize_color_final(value: str, attr_name: str = "color", normalize_rhodium: bool = True) -> str:
    """
    Convert technical Silverbene color names to customer-friendly display names.
    Called as a final pass after _clean_color_value and _normalize_finish_terms.
    Only normalizes metal-context attributes — stone colors (Yellow Sapphire, etc.)
    are left as-is.

    normalize_rhodium=False skips the Rhodium->Silver step (see _RHODIUM_TOKEN_RE)
    for callers upstream of _to_standard()'s Step 1 (_normalize_finish_terms), which
    needs the literal word "Rhodium" still present in the value to correctly decide,
    per-product, whether it should become "Silver" (default) or "White Gold" (when
    the product description explicitly advertises that finish name). Collapsing it
    to "Silver" here first would erase that information before Step 1 ever runs.
    """
    if not value:
        return value
    # Check the whole raw value against the dict first — "No plating" is a
    # dict entry in its own right, and the generic trailing-suffix strip
    # below would otherwise mangle it into "No" ("plating" reads as the
    # stripped suffix, not part of the phrase) before it ever reached the
    # lookup.
    raw_lower = value.strip().lower()
    if attr_name.lower() in _METAL_ATTR_NAMES and raw_lower in _METAL_COLOR_NORMALIZE:
        return _METAL_COLOR_NORMALIZE[raw_lower]
    # Strip technical suffixes: "White Gold Color" → "White Gold", "Gold Plated" → "Gold"
    cleaned = re.sub(r'\s+(color|plating|plated)\s*$', '', value, flags=re.I).strip()
    v_lower = cleaned.lower()
    if attr_name.lower() in _METAL_ATTR_NAMES:
        normalized = _METAL_COLOR_NORMALIZE.get(v_lower)
        if normalized:
            return normalized
    # Rhodium is never a gemstone name — normalize wherever it appears in the
    # value, regardless of attribute type, position, or typo (see _RHODIUM_TOKEN_RE).
    if normalize_rhodium and _RHODIUM_TOKEN_RE.search(cleaned):
        return _RHODIUM_TOKEN_RE.sub("Silver", cleaned)
    return cleaned


class SilverbeneAdapter(SupplierAdapter):
    """
    Silverbene primary supplier adapter for Mikisi.
    CJ Dropshipping is disabled — all imports run through here.

    Live response structure confirmed 2026-06-02:
    {
      "code": 0,
      "data": {
        "data": [
          {
            "title": "...",
            "sku": "HFH_827881713467",
            "desc": "<ul><li>Metal Color Available:Yellow Gold,Rhodium</li>...</ul>",
            "gallery": ["https://silverbene.com/media/...jpg", ...],
            "weight": 3,
            "created_time": "2025-01-02 15:28:59",
            "option": [
              {"attribute": [{"name": "Color", "value": "Rhodium"}], "qty": 48, "price": 18.5, "option_id": 51583},
              {"attribute": [{"name": "Color", "value": "Yellow Gold"}], "qty": 20, "price": 18.5, "option_id": 51584}
            ]
          }
        ]
      },
      "message": "success"
    }
    """

    def __init__(self):
        self.token = os.getenv("SILVERBENE_API_KEY", "")
        self.base = SILVERBENE_BASE
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: dict = None) -> dict:
        p = params or {}
        p["token"] = self.token
        try:
            r = self.session.get(f"{self.base}{endpoint}", params=p, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[Silverbene] GET {endpoint} error: {e}")
            return {}

    def _post(self, endpoint: str, payload: dict) -> dict:
        payload["token"] = self.token
        try:
            r = self.session.post(
                f"{self.base}{endpoint}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[Silverbene] POST {endpoint} error: {e}")
            return {}

    def _date_range(self, months_back: int = 2) -> tuple:
        """Return (start_date, end_date) strings covering the last N months."""
        end = datetime.utcnow()
        start = end - timedelta(days=months_back * 30)
        return start.strftime("%Y-%m"), end.strftime("%Y-%m")

    # ── CATALOG SEARCH ────────────────────────────────────────────────────────

    def search(self, keyword: str, limit: int = 20, category: str = "") -> list:
        """
        Search Silverbene catalog by keyword.
        Silverbene enforces a 2-month window per request, so we batch automatically
        across windows from oldest to newest until we have enough products.
        """
        from datetime import datetime
        result = []
        seen = set()

        # Walk 2-month windows from 3 years back to now
        # Zero-pad months — API rejects "2026-1", needs "2026-01"
        now = datetime.utcnow()
        windows = []
        year, month = now.year - 3, 1
        while (year, month) <= (now.year, now.month):
            if month + 2 <= 12:
                end_month, end_year = month + 2, year
            else:
                end_month, end_year = (month + 2) % 12 or 12, year + 1
            windows.append((f"{year}-{month:02d}", f"{end_year}-{end_month:02d}"))
            month += 2
            if month > 12:
                month -= 12
                year += 1

        for start_str, end_str in reversed(windows):  # newest first
            resp = self._get(ENDPOINT_PRODUCT_BY_DATE, {
                "start_date": start_str,
                "end_date": end_str,
                "keywords": keyword,
                "is_really_stock": 0,  # 0 = include all; stock checked live via option_qty
            })

            if not isinstance(resp, dict):
                continue
            if resp.get("code") != 0:
                continue

            data = resp.get("data", {})
            if isinstance(data, dict):
                items = data.get("data", [])
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                sku = item.get("sku", "")
                if sku and sku not in seen:
                    seen.add(sku)
                    result.append(self._to_standard(item, category=category))
                if len(result) >= limit:
                    break

            if len(result) >= limit:
                break

        print(f"[Silverbene] search '{keyword}': {len(result)} products across date windows")
        return result

    def search_by_category(self, category_name: str, limit: int = 50) -> list:
        """
        Search all keywords for a Mikisi collection, deduplicate, return up to limit.
        """
        keywords = CATEGORY_KEYWORDS.get(category_name, [category_name.lower()])
        seen_skus = set()
        results = []
        per_keyword = max(10, limit // len(keywords) + 5)

        for kw in keywords:
            products = self.search(keyword=kw, limit=per_keyword, category=category_name)
            for p in products:
                sku = p.get("supplier_product_id", "")
                if sku and sku not in seen_skus:
                    seen_skus.add(sku)
                    results.append(p)
            if len(results) >= limit:
                break

        print(f"[Silverbene] {collection_name_log(category_name)}: {len(results)} products found")
        return results[:limit]

    def get_by_sku(self, sku: str, category: str = "") -> Optional[dict]:
        """Fetch a specific product by its SKU."""
        resp = self._get(ENDPOINT_PRODUCT_LIST, {"sku": sku})
        if resp.get("code") == 0:
            data = resp.get("data", {})
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("data", [])
            else:
                items = []
            if items:
                return self._to_standard(items[0], category=category)
        return None

    def get_raw_desc_by_sku(self, sku: str) -> str:
        """Return the raw Silverbene HTML description for a SKU (for spec extraction)."""
        resp = self._get(ENDPOINT_PRODUCT_LIST, {"sku": sku})
        if resp.get("code") == 0:
            data = resp.get("data", {})
            items = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
            if items:
                return items[0].get("description", "") or items[0].get("desc", "") or ""
        return ""

    def get_product(self, product_id: str) -> Optional[dict]:
        return self.get_by_sku(product_id)

    def get_stock(self, option_id: str) -> int:
        """Get current stock for one or more option_ids (comma-separated)."""
        resp = self._get(ENDPOINT_OPTION_QTY, {"option_id": option_id})
        if resp.get("code") == 0:
            items = resp.get("data", [])
            if items and isinstance(items, list):
                return int(items[0].get("qty", 999))
        return 999

    # ── ORDERS ────────────────────────────────────────────────────────────────

    def get_shipping_methods(self, country_code: str = "US",
                             option_id: str = None, qty: int = 1,
                             postcode: str = "", city: str = "") -> list:
        """
        Get available shipping methods for a country + product.
        postcode and city are required by Silverbene for accurate rates.
        Returns list of dicts with: way, title, price, carrier_code, method_code.
        """
        payload = {
            "country_id": country_code,
            "postcode":   postcode,
            "city":       city,
            "products":   [{"option_id": str(option_id), "qty": qty}] if option_id else [],
        }
        for attempt in range(2):
            resp = self._post(ENDPOINT_SHIPPING, payload)
            print(f"[Silverbene] Shipping methods response (attempt {attempt + 1}): {resp}")
            if resp.get("code") == 0:
                raw = resp.get("data", [])
                if raw:
                    return [
                        {
                            **m,
                            "carrier_code": m.get("way", ""),
                            "method_code":  m.get("way", ""),
                        }
                        for m in raw
                    ]
            import time; time.sleep(2)

        # Silverbene intermittently returns empty methods — fall back to known US method
        print("[Silverbene] Shipping methods empty after retry — using fallback SUX")
        return [{"carrier_code": "SUX", "method_code": "SUX", "way": "SUX"}]

    def place_order(self, product_id: str, customer: dict, address: dict,
                    quantity: int = 1, option_id: str = None) -> dict:
        """
        Place a dropship order with Silverbene.
        product_id = Silverbene option_id (NOT sku — orders use option_id).
        use_credit: true charges our store credit balance automatically.

        IMPORTANT: We use our admin email (not customer email) in the Silverbene
        shipping address so any Silverbene payment/status emails go to us, never
        to the customer. Customers should never know Silverbene exists.
        """
        use_option = option_id or product_id
        methods = self.get_shipping_methods(
            address.get("country_code", "US"),
            option_id=use_option,
            qty=quantity,
            postcode=address.get("postal_code", ""),
            city=address.get("city", ""),
        )
        if not methods:
            print(f"[Silverbene] No shipping methods returned for option_id={use_option} — cannot place order")
            return self.standard_order(success=False, supplier_order_id="", reason="No shipping methods available")
        carrier_code = methods[0].get("carrier_code", "")

        order_option_id = option_id or product_id
        admin_email = "hello@mikisi.co"  # Silverbene must never have the customer's real email

        payload = {
            "products": [{"option_id": str(order_option_id), "qty": quantity}],
            "shipping_method": carrier_code,
            "use_credit": True,
            "shipping_address": {
                "firstname":  customer.get("first_name", ""),
                "lastname":   customer.get("last_name", ""),
                "email":      admin_email,   # never expose customer email to supplier
                "telephone":  customer.get("phone") or "0000000000",
                "street":     address.get("line1", ""),
                "city":       address.get("city", ""),
                "region":     address.get("state", ""),
                "postcode":   address.get("postal_code", ""),
                "country_id": address.get("country_code", "US"),
            },
        }

        result = self._post(ENDPOINT_CREATE_ORDER, payload)
        code = result.get("code")
        data = result.get("data", {}) or {}
        order_id = str(data.get("order_id", ""))
        payment_required = data.get("payment_required", False)

        print(f"[Silverbene] create_order response: code={code} order_id={order_id} payment_required={payment_required}")

        # Case 1 — credit covered the full amount, order is processing
        if code == 0 and order_id and not payment_required:
            return self.standard_order(success=True, supplier_order_id=order_id, reason="paid_from_credit")

        # Case 2 — order created but credit didn't fully cover it, Silverbene needs extra payment
        if code == 0 and order_id and payment_required:
            pay_url  = data.get("pay_url", "")
            amount   = data.get("amount_due") or data.get("total_price", "?")
            print(f"[Silverbene] ⚠️  Credit shortfall — order {order_id} needs ${amount} payment. URL: {pay_url}")
            self._alert_low_credit(
                subject=f"⚠️ Silverbene order {order_id} needs payment — credit shortfall",
                body=(
                    f"<p>Order <b>{order_id}</b> was created at Silverbene but your store credit "
                    f"didn't fully cover it.</p>"
                    f"<p><b>Amount due:</b> ${amount}</p>"
                    f"<p><b>Pay here:</b> <a href='{pay_url}'>{pay_url}</a></p>"
                    f"<p>Top up your Silverbene balance to avoid this in future orders.</p>"
                ),
            )
            # Return success=True so the order moves to 'processing' — it exists at Silverbene
            return self.standard_order(success=True, supplier_order_id=order_id, reason="pending_payment_shortfall")

        # Case 3 — insufficient credit, order was NOT created
        message = result.get("message", "unknown error")
        print(f"[Silverbene] ❌ Order failed: code={code} message={message}")
        self._alert_low_credit(
            subject="❌ Silverbene order FAILED — insufficient store credit",
            body=(
                f"<p>An order could not be placed at Silverbene because your store credit balance "
                f"is too low.</p>"
                f"<p><b>Error:</b> {message}</p>"
                f"<p>Top up your Silverbene balance immediately at "
                f"<a href='https://silverbene.com'>silverbene.com</a> or contact Jacky "
                f"(jackyli@silverbene.com).</p>"
            ),
        )
        return self.standard_order(success=False, supplier_order_id="", reason=f"insufficient_credit: {message}")

    def check_balance(self) -> float:
        """Returns the current Silverbene store credit balance in USD, or -1 on error."""
        result = self._get(ENDPOINT_STORE_CREDIT)
        if result.get("code") == 0:
            balance = result.get("data", {})
            if isinstance(balance, dict):
                amount = balance.get("amount") or balance.get("balance") or balance.get("credit", -1)
            else:
                amount = float(balance) if balance else -1
            try:
                return float(amount)
            except (TypeError, ValueError):
                pass
        print(f"[Silverbene] Balance check failed: {result}")
        return -1

    def _alert_low_credit(self, subject: str, body: str):
        """Email Dennis about a credit / payment issue."""
        try:
            from app.agents.email_partner import send_email
            dennis = os.getenv("DENNIS_EMAIL") or os.getenv("ADMIN_EMAIL")
            if dennis:
                send_email(to=dennis, subject=subject, body=f"<html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;'>{body}</body></html>", is_html=True)
        except Exception as e:
            print(f"[Silverbene] Alert email failed: {e}")

    def get_tracking(self, order_id: str) -> dict:
        """Tracking — endpoint to be added when Silverbene shares it."""
        return self.standard_tracking(order_id=order_id, status="unknown")

    # ── DATA NORMALISATION ────────────────────────────────────────────────────

    def _to_standard(self, raw: dict, category: str = "") -> dict:
        """
        Convert a live Silverbene product into Mikisi's standard format.
        Field names confirmed from live API response.
        Pass category="Bracelets" etc. to filter description-parsed lengths to the
        correct physical range (bracelets are 5"–9", necklaces 12"–36").
        """
        gallery = raw.get("gallery", [])
        image_url = gallery[0] if gallery else ""

        # Prefer the richer 'options' field (has base_price per variant).
        # Normalise to a single internal format so the rest of the pipeline
        # works regardless of which API call populated the dict.
        raw_options  = raw.get("options", [])   # new rich structure
        legacy_opts  = raw.get("option",  [])   # old structure (fallback)

        options = []
        if raw_options:
            for o in raw_options:
                # Normalise attributes: 'attributes' → 'attribute' for compat
                attrs = o.get("attributes") or o.get("attribute") or []
                options.append({
                    "option_id":  o.get("option_id"),
                    "attribute":  attrs,
                    "qty":        o.get("stock", o.get("qty", 0)),
                    "price":      o.get("base_price", o.get("price", 0)),
                    "base_price": o.get("base_price", o.get("price", 0)),
                })
        elif legacy_opts:
            for o in legacy_opts:
                attrs = o.get("attribute") or o.get("attributes") or []
                bp = o.get("price", 0)
                options.append({**o, "attribute": attrs, "base_price": bp})

        cost_price = float(options[0].get("base_price", options[0].get("price", 0))) if options else 0.0
        stock = sum(int(o.get("qty", 0)) for o in options) if options else 999

        sizes, colors = self._extract_variants(options, category=category)
        _desc_for_finish = raw.get("description", "") or raw.get("desc", "")
        # Rhodium plating normally displays as "Silver" (_normalize_color_final's
        # default), but some product descriptions explicitly advertise the same
        # plating as "White Gold" instead. Compute this once and apply it
        # everywhere Rhodium gets normalized below — the display colors list
        # (Step 1) AND the raw variant attributes (Step 3) — so a product's
        # customer-facing chip and its order-time raw-data lookup never
        # disagree on what "Rhodium" is called for this specific product.
        _rhodium_display = self._rhodium_display_name(_desc_for_finish)
        # Step 1: desc-based upgrade — replaces "Rhodium" with "White Gold" when the
        # product description explicitly uses that term (e.g. "Metal Color: White Gold Color").
        if colors:
            colors = self._normalize_finish_terms(colors, _rhodium_display)
        # Step 2: final friendly-name normalization for anything still technical
        # ("Rhodium" → "Silver", "Pink" → "Rose Gold", strip " Color"/" Plated" suffixes).
        if colors:
            colors = [_normalize_color_final(c) for c in colors]

        # Step 3: sync the same canonical metal name back into the stored variant
        # attributes so p.variants and p.colors always agree on plain color names
        # (e.g. "Rhodium" -> "Silver", or -> _rhodium_display when this product's
        # description overrides it). Only ever rewrites the metal/color part of
        # a raw attribute value — never the combined " · "-joined DISPLAY chip that
        # `colors` may contain (compound descriptors and/or a suffix folded in from
        # a *different* sibling attribute, e.g. "Silver · Pendant Only"). Writing
        # that combined chip into a single raw attribute would duplicate data that
        # still lives in the sibling attribute, and get detected and appended a
        # second time on the next read (see _detect_option_suffix).
        if colors:
            for opt in options:
                for attr in opt.get("attribute", []):
                    aname = attr.get("name", "").lower().strip()
                    aval  = attr.get("value", "").strip()
                    if aname not in COLOR_ATTRIBUTE_NAMES:
                        continue
                    if re.search(r'\d+\s*(mm|cm)', aval, re.I):
                        continue  # length disguised as color — _extract_variants put it in sizes
                    if _is_compound_color_candidate(aval):
                        parts = [p.strip() for p in aval.split(',') if p.strip()]
                        new_parts = []
                        for i, part in enumerate(parts):
                            if _RHODIUM_TOKEN_RE.search(part):
                                part = _RHODIUM_TOKEN_RE.sub(_rhodium_display, part)
                            elif i == 0:
                                part = _normalize_color_final(_clean_color_value(part), aname) or part
                            new_parts.append(part)
                        if new_parts:
                            attr["value"] = ', '.join(new_parts)
                    else:
                        cleaned = _clean_plain_color(aval)
                        if _RHODIUM_TOKEN_RE.search(cleaned):
                            canonical = _RHODIUM_TOKEN_RE.sub(_rhodium_display, cleaned)
                        else:
                            canonical = _normalize_color_final(cleaned, aname)
                        if canonical:
                            attr["value"] = canonical
        # Chain length / bracelet info from the description spec section.
        # For bracelets, use the full intelligent extractor which also returns width.
        _raw_desc_for_len = raw.get("description", "") or raw.get("desc", "")
        _bracelet_width = None
        _bangle_inner_diameter = None
        _is_bangle = category == "Bracelets" and is_bangle_product(raw.get("title", ""), _raw_desc_for_len)
        if category == "Bracelets":
            _binfo = _extract_bracelet_info_from_desc(_raw_desc_for_len, is_bangle=_is_bangle)
            desc_lengths = _binfo["sizes"]
            _bracelet_width = _binfo.get("width")
            _bangle_inner_diameter = _binfo.get("inner_diameter")
        else:
            desc_lengths = _parse_chain_length_from_desc(_raw_desc_for_len, category=category)
        # Only use the description-derived length as a fallback when variant
        # options gave us nothing at all. Real per-option data always wins and
        # is never topped up with extra description-parsed values — Silverbene
        # only prices one option per real size, so if the description mentions
        # a length that isn't backed by an actual priced variant, it has no
        # business becoming a selectable size (it can still show in specs/details).
        if desc_lengths and not sizes:
            sizes = desc_lengths
        raw_desc = raw.get("description", "") or raw.get("desc", "")
        # Last resort for Anklets/Bracelets with no real length anywhere —
        # neither a priced-option size nor a parseable number in the
        # description. If Silverbene's own text still confirms adjustability
        # somewhere (see _has_adjustable_language — catches "Extender"/
        # "Spring Ring" language embedded in an unrelated field, not just a
        # dedicated "Extension Chain: Yes" line), say so honestly instead of
        # showing nothing. Never fabricates a specific measurement — a bare
        # "Adjustable" is real, stated information, not a guessed number.
        if not sizes and category in ("Anklets", "Bracelets") and _has_adjustable_language(raw_desc):
            sizes = ["Adjustable"]
        material = self._infer_material_from_desc(raw_desc, colors)
        specs = self._extract_specs_from_desc(raw_desc, category=category)
        # For bracelets: inject width, remove any necklace-range chain_length
        if category == "Bracelets":
            if _bracelet_width:
                specs["width"] = specs.get("width") or _bracelet_width
            # chain_length from specs might be wrong (necklace range) — replace with
            # the bracelet-aware value already in `sizes`
            if "chain_length" in specs and sizes:
                specs["chain_length"] = sizes[0] if len(sizes) == 1 else " / ".join(sizes[:3])
            elif "chain_length" in specs and not sizes:
                del specs["chain_length"]
            # Bangles: show the real inner diameter as its own spec, never a
            # derived "Bracelet Length" — a rigid band's diameter and a chain's
            # wrist length are different measurements (see
            # _extract_bracelet_info_from_desc's docstring).
            if _bangle_inner_diameter:
                specs["inner_diameter"] = _bangle_inner_diameter
                specs.pop("chain_length", None)
        pendant_only = _is_pendant_only(raw_desc)
        if pendant_only:
            # Unconditional — a pendant-only listing must always show "Pendant Only"
            # regardless of whether a (possibly spurious, e.g. jump-ring wire
            # thickness) numeric size was extracted from a variant attribute.
            sizes = ["Pendant Only"]

        # Sanitize description: replace internal/technical plating terms with
        # customer-friendly equivalents so they never appear in product copy.
        clean_desc = _sanitize_description(raw_desc)

        return {
            **self.standard_product(
                supplier_product_id=raw.get("sku", ""),
                name=raw.get("title", ""),
                category="",
                description=clean_desc,
                cost_price=cost_price,
                image_url=image_url,
                stock=min(stock, 999),
                shipping_days=12,
                supplier_name="Silverbene",
                supplier_url=f"https://silverbene.com/product/{raw.get('sku', '')}",
                variants=options,
            ),
            "images": gallery,
            "material": material,
            "sizes": json.dumps(sizes) if sizes else None,
            "colors": json.dumps(colors) if colors else None,
            "specs": json.dumps(specs) if specs else None,
            # Scoring helpers
            "supplier_rating": 5.0,
            "material_name_en_set": [material] if material else [],
            "extra_text": f"{raw.get('title', '')} {raw.get('desc', '')} {material}",
            "product_image_set_count": len(gallery),
            # Keep raw options so bulk import can extract option_ids
            "_options": options,
            "is_pendant_only": pendant_only,
        }

    def _extract_variants(self, options: list, category: str = "") -> tuple:  # noqa: C901
        """
        Extract sizes and colors from Silverbene option attributes.
        Returns (sizes_list, colors_list).

        Live option structure:
        [{"attribute": [{"name": "Color", "value": "Rhodium"}], "qty": 48, "price": 18.5, "option_id": 51583}]
        """
        sizes = []
        colors = []
        seen_sizes = set()
        seen_colors = set()
        # Normally half-inch chips; escalates to quarter-inch only when two
        # genuinely different real sizes for THIS product would otherwise
        # collide into the same chip (see _bracelet_size_denom).
        _denom = _bracelet_size_denom(options)
        # A Color value that's an exact category word ("Anklet", "Necklace")
        # is usually just a redundant leftover tag — _clean_color_value()
        # discards it to "". But occasionally it's the ONLY thing that varies
        # between options and IS the real, differently-priced choice (e.g. a
        # chain sold configured either as a necklace or as an anklet). Track
        # what got discarded so it can be rescued below if nothing else was
        # ever captured as a color for this product.
        _bare_category_values = []
        _seen_bare = set()

        # A measurement bundled into a Color-type value (e.g. the "2mm" in
        # "Moissanite 1*2mm + 75 stones, with GRA certificate") is only a
        # real, price-differentiating size when this product has no OTHER,
        # dedicated size attribute already covering it — and even then, only
        # when the bundled measurement actually varies between options.
        # Silverbene sometimes repeats the exact same stone-size text
        # identically across every option of a ring that ALSO carries a real
        # "Size" attribute (US 5–9) — there the bundled text describes the
        # gem, not a second selectable dimension, so it must never sit
        # alongside the real sizes as a fake, unpriced chip (see
        # [[feedback_silverbene_price_backed_sizes]]). But some bracelets
        # carry NO dedicated size attribute at all — the chain length lives
        # only inside Color (e.g. "Pink_16+3cm") and is identical across
        # every color option simply because there's one length per product;
        # that's the ONLY size information available and must still be kept
        # even though it doesn't vary. Pre-scan every option first so both
        # checks can be decided once, before the per-option loop below ever
        # adds a chip.
        _measurement_chips_seen = set()
        _has_dedicated_size_attr = False
        for _opt in options:
            for _attr in _opt.get("attribute", []):
                _name = _attr.get("name", "").lower().strip()
                _value = _attr.get("value", "").strip()
                if not _value:
                    continue
                if _name in SIZE_ATTRIBUTE_NAMES or _name in BRACELET_SIZE_ATTR_NAMES:
                    _has_dedicated_size_attr = True
                elif _name == "purity" and _PURITY_LENGTH_RE.search(_value):
                    # Silverbene occasionally buries the real, price-differentiating
                    # bracelet length inside "Purity" alongside the material text
                    # (e.g. "925 Silver, Length 16.5CM") instead of a dedicated
                    # length attribute — found live on product 1138 (Cuban Link
                    # Moissanite Bracelet), which has 5 real distinct-priced
                    # lengths (16.5/18/19/20/21cm) all hidden this way. Counts as
                    # a real dedicated size source so the chain WIDTH bundled into
                    # Color (e.g. "8mm", identical across every option here) never
                    # gets wrongly promoted to the product's only "size" below.
                    _has_dedicated_size_attr = True
                elif _name in COLOR_ATTRIBUTE_NAMES and re.search(r'\d+\s*(mm|cm)', _value, re.I):
                    _, _chip = _split_color_and_size(_value, category)
                    if _chip:
                        _measurement_chips_seen.add(_chip)
        _measurement_chip_is_real = (
            len(_measurement_chips_seen) > 1 or
            (len(_measurement_chips_seen) == 1 and not _has_dedicated_size_attr)
        )

        # "Purity" is overloaded: sometimes it's just boilerplate material
        # description ("925 Sterling Silver") repeated identically on every
        # option regardless of which Color/finish was picked — not a real
        # second choice, and appending it to the color chip would tack a
        # redundant "· 925 Silver" onto products that never varied by it.
        # Only treat it as a genuine second selector when its own normalized
        # value actually differs across this product's options (e.g. "18k
        # gold" vs "No plating" — a real plating choice with nothing else to
        # distinguish the two).
        _purity_vals_seen = set()
        for _opt in options:
            for _attr in _opt.get("attribute", []):
                if (_attr.get("name") or "").lower().strip() != "purity":
                    continue
                _pval = (_attr.get("value") or "").strip()
                if _pval and re.search(r'\b(gold|silver|platinum|plating|plated|rhodium)\b', _pval, re.I):
                    _norm = _normalize_color_final(_clean_plain_color(_pval), "finish", normalize_rhodium=False)
                    if _norm:
                        _purity_vals_seen.add(_norm)
        _purity_is_real = len(_purity_vals_seen) > 1

        for opt in options:
            attrs = opt.get("attribute", [])
            _chain_style_suffix = _detect_option_suffix(attrs)
            # Some options carry TWO separate real color-type attributes at once
            # (e.g. "Color": "Silver" for the metal + "Main Stone": "Black" for the
            # gem — both names are in COLOR_ATTRIBUTE_NAMES). Silverbene prices
            # every metal+stone pairing as one distinct option, never as two
            # independent selectors, so collect every color-type attribute this
            # option carries and combine them into ONE chip below — never let a
            # later color-type attribute silently overwrite an earlier one.
            _color_parts_this_option: list = []
            for attr in attrs:
                name = attr.get("name", "").lower().strip()
                value = attr.get("value", "").strip()
                if not value:
                    continue

                if name in BRACELET_SIZE_ATTR_NAMES and re.search(r'\d+', value, re.I):
                    # Bracelet-specific attrs (wrist size, inner diameter, etc.)
                    for chip in parse_bracelet_size(value, _denom):
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in ("chain length", "length") and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    # Try bracelet range first; fall through to necklace parser
                    chips = parse_bracelet_size(value, _denom) or parse_necklace_length(value)
                    for chip in chips:
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name == "size" and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    chips = parse_bracelet_size(value, _denom) or parse_necklace_length(value)
                    for chip in chips:
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in COLOR_ATTRIBUTE_NAMES and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    # Measurement bundled into the Color attr (e.g. "16cm", "17+3",
                    # "Pink_16+3cm", "18K Yellow Gold 6mm" hoop diameter,
                    # "3mm wide, length: 16.5cm, weight:2g"). Split it into a clean
                    # color/finish name AND a size chip — a genuine chain-length range
                    # becomes the usual inch chip; anything else (hoop diameter, tube
                    # width) is kept as its own real, price-differentiating size chip
                    # rather than being discarded. Never drop the color half: Silverbene
                    # still prices color separately even when it shares an attribute
                    # with the size text.
                    _color_part, _size_chip = _split_color_and_size(value, category)
                    if _size_chip and _measurement_chip_is_real and _size_chip not in seen_sizes:
                        seen_sizes.add(_size_chip)
                        sizes.append(_size_chip)
                    if _color_part:
                        _color_parts_this_option.append(_color_part)
                elif name in SIZE_ATTRIBUTE_NAMES:
                    value = " ".join(value.split())
                    # A trailing comma is stray Silverbene data noise (e.g. "US 8,"),
                    # never a meaningful part of the size — strip it before it ends
                    # up as a customer-facing chip label.
                    value = value.rstrip(',').strip()
                    # Normalise any adjustable/open-ring variant to a single consistent label
                    _vl = value.lower()
                    # Silverbene sometimes puts an unrelated spec under the generic
                    # "Size" attribute name instead of a real physical dimension —
                    # seen with a stone's carat weight (e.g. "0.5 CT", "0.5CT/1CT").
                    # A carat value is never a length/diameter regardless of which
                    # attribute name it arrived under, and the real spec is already
                    # captured separately (_extract_specs_from_desc's stone_size) —
                    # trusting it here would mislabel it as the product's physical
                    # size (e.g. "Bracelet Length: 0.5 CT").
                    if re.search(r'\d\s*c\.?t\.?\b|\bcarat\b', _vl):
                        continue
                    if _vl in ('adjustable', 'one size', 'one size / adjustable',
                                'one size/adjustable', 'free size', 'all size',
                                'open ring', 'open size') or \
                       _vl.startswith('adjustable (') or \
                       re.match(r'^\d+\s*\(adjustable\)$', _vl):
                        # Bracelets always have a real physical length even when
                        # Silverbene's attribute just says "adjustable" with no
                        # dimension — "Open Size" would misrepresent them the way
                        # it doesn't for a genuinely open/stretchable ring band.
                        value = 'Adjustable' if category == 'Bracelets' else 'Open Size / Adjustable'
                    if value not in seen_sizes:
                        seen_sizes.add(value)
                        sizes.append(value)
                elif name in COLOR_ATTRIBUTE_NAMES:
                    # A comma-separated value with no measurement bundles a metal
                    # with a real second descriptor (stone color, grade, etc.) or
                    # pure noise ("Single Piece") — combine into one unique,
                    # matchable chip rather than a raw, unsplit compound string.
                    # A comma inside parentheses ("Rhodium (Pendant Only,)") is
                    # punctuation, not a second attribute — stays on the plain path.
                    # normalize_rhodium=False: leave a literal "Rhodium" as-is here
                    # so _to_standard()'s Step 1 (_normalize_finish_terms) can still
                    # see it and decide, per-product from the description, whether
                    # it becomes "Silver" or "White Gold" — collapsing it here first
                    # would erase that choice before Step 1 ever runs.
                    part = (_clean_compound_color(value) if _is_compound_color_candidate(value)
                            else _normalize_color_final(_clean_plain_color(value), name, normalize_rhodium=False))
                    if part:
                        _color_parts_this_option.append(part)
                    elif value.lower().strip() in _CATEGORY_PREFIXES and value not in _seen_bare:
                        _seen_bare.add(value)
                        _bare_category_values.append(value)
                elif name == "purity" and _PURITY_LENGTH_RE.search(value):
                    # The real per-option length hiding inside Purity text (see
                    # _PURITY_LENGTH_RE / pre-scan comment above). Extract just
                    # the number+unit and hand it to the same bracelet/necklace
                    # parsers every other length source uses, so this never
                    # disagrees with how "chain length"/"length" attributes are
                    # already handled elsewhere.
                    _len_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', value, re.I)
                    if _len_m:
                        _len_str = f"{_len_m.group(1)}{_len_m.group(2)}"
                        chips = parse_bracelet_size(_len_str, _denom) or parse_necklace_length(_len_str)
                        for chip in chips:
                            if chip not in seen_sizes:
                                seen_sizes.add(chip)
                                sizes.append(chip)
                elif name == "purity" and _purity_is_real and re.search(r'\b(gold|silver|platinum|plating|plated|rhodium)\b', value, re.I):
                    # "Purity" is overloaded — Silverbene also uses it for a
                    # pendant/chain-style choice ("Pendant Only" vs "Pendant +
                    # Necklace"), already handled by _detect_option_suffix, so
                    # "purity" is deliberately NOT in COLOR_ATTRIBUTE_NAMES.
                    # But sometimes it genuinely carries the plating/finish
                    # choice instead (e.g. "18k gold" vs "No plating") — a
                    # real, customer-facing selection that was previously
                    # invisible entirely (never became a color chip, never
                    # showed up in p.colors, both options collapsed into one
                    # indistinguishable listing). Only fires on a metal/plating
                    # -shaped value that actually varies (_purity_is_real), so
                    # it never collides with the pendant/chain-style case
                    # above, and never tacks redundant boilerplate material
                    # text onto every other product's color chip.
                    part = _normalize_color_final(_clean_plain_color(value), "finish", normalize_rhodium=False)
                    if part:
                        _color_parts_this_option.append(part)

            # Combine every real color-type attribute this option carries (e.g. a
            # separate metal "Color" + gem "Main Stone") into ONE display chip —
            # Silverbene prices the pairing as a single choice, never as two
            # independent selectors, so two options that differ only in stone must
            # never collapse into the same metal-only chip.
            # A suffix (post/gauge spec, pendant-style) only ever means anything
            # attached to a real color — an option with NO real color-type
            # attribute at all (e.g. a chain priced only by width/finish under a
            # nonstandard attribute name) must stay uncaptured here, exactly as
            # before _detect_option_suffix existed, not have the suffix text
            # itself masquerade as a fake color.
            display = ' · '.join(_color_parts_this_option)
            if _chain_style_suffix and display:
                display = f'{display} · {_chain_style_suffix}'
            if display and display not in seen_colors:
                seen_colors.add(display)
                colors.append(display)

        # Rescue: nothing else ever counted as a color, but this product's
        # Color attribute genuinely varies between real category words — that
        # variation IS the choice (see comment above), not noise to discard.
        if not colors and len(_bare_category_values) >= 2:
            colors = _bare_category_values

        return sizes or None, colors or None

    def _rhodium_display_name(self, desc: str) -> str:
        """
        Rhodium plating normally displays as "Silver" (_normalize_color_final's
        default), but Silverbene's product descriptions sometimes explicitly
        advertise the same plating as "White Gold" instead (via 'Metal Color
        Available' / 'Metal Electroplating'). Returns "White Gold" when this
        product's description says so, else "Silver" — the caller applies this
        consistently everywhere Rhodium gets normalized for this product (both
        the customer-facing colors list and the raw variant attributes), so
        display and order-time raw-data matching never disagree.
        """
        text = re.sub(r'<[^>]+>', ' ', desc or '')
        desc_finishes = []
        for pattern in [
            r'Metal\s+Color\s+Available\s*[:\-]\s*([^\n<]{2,100})',
            r'Metal\s+Electroplating\s*[:\-]\s*([^\n<]{2,80})',
        ]:
            m = re.search(pattern, text, re.I)
            if m:
                desc_finishes.extend(
                    c.strip() for c in re.split(r'[,/]', m.group(1)) if c.strip()
                )
        desc_lower = ' '.join(f.lower() for f in desc_finishes)
        return "White Gold" if 'white gold' in desc_lower else "Silver"

    def _normalize_finish_terms(self, colors: list, rhodium_display: str) -> list:
        """
        Silverbene's option attributes use the technical name 'Rhodium'; replace it
        with rhodium_display (see _rhodium_display_name) wherever it appears in the
        customer-facing colors list. Must run even when rhodium_display is the
        default "Silver" — _normalize_color_final only normalizes a color value
        that IS "Rhodium" outright, never a "Rhodium" buried as the 2nd+ part of a
        compound value (e.g. "Green Stone · Rhodium"; _clean_compound_color only
        normalizes the 1st part). Skipping this for the "Silver" case left compound
        colors permanently un-normalized in the display list while Step 3 below
        normalizes the exact same text in the raw attributes, so the two diverged
        and a customer's displayed chip stopped matching anything at order time.
        """
        return [
            _RHODIUM_TOKEN_RE.sub(rhodium_display, c) if _RHODIUM_TOKEN_RE.search(c) else c
            for c in colors
        ]

    def _extract_specs_from_desc(self, desc: str, category: str = "") -> dict:  # noqa: C901
        """
        Parse all product specs from Silverbene's raw HTML <li> items.
        Must be called BEFORE description is rewritten — raw tags only exist at import time.
        Returns only fields with real data; never inserts placeholder values.
        Pass category to enable category-aware length parsing.
        """
        specs = {}
        lis = re.findall(r'<li>(.*?)</li>', desc, re.I | re.S)

        # Skip lines that are internal Silverbene copy, not product specs
        SKIP_RE = re.compile(
            r'designed by silverbene|if out of stock|restock in|minimum order|'
            r'only \d+ pieces in stock|eligible to apply|pendant only|chain not included|'
            r'customize', re.I
        )

        # Map Silverbene field label → internal spec key
        FIELD_MAP = {
            # Weight
            'total weight': 'weight',
            'weight': 'weight',
            'bracelet total weight': 'weight',
            'anklet total weight': 'weight',
            'approximate weight': 'weight',
            'reference weight': 'weight',
            # Plating / finish
            'metal electroplating': 'plating',
            'electroplating': 'plating',
            'finish': 'finish',
            'surface': 'finish',
            'surface finish': 'finish',
            'special craftsmanship': 'craftsmanship',
            # Stone details
            'main stone': 'stone',
            'main stone type': 'stone',
            'stone type': 'stone',
            'gemstone': 'stone',
            'gemstone type': 'stone',
            'crystal type': 'stone',
            'accent stone': 'accent_stone',
            'secondary stone': 'accent_stone',
            'main stone quantity': 'stone_qty',
            'stone quantity': 'stone_qty',
            'number of stones': 'stone_qty',
            'main stone size': 'stone_size',
            'stone size': 'stone_size',
            'gemstone size': 'stone_size',
            'gem size': 'stone_size',
            'crystal size': 'stone_size',
            'zirconia size': 'stone_size',
            'cz size': 'stone_size',
            'moissanite size': 'stone_size',
            'stone shape': 'stone_shape',
            'main stone shape': 'stone_shape',
            'gemstone shape': 'stone_shape',
            'accent stone size': 'accent_stone_size',
            'accent ston size': 'accent_stone_size',
            'main stone weight': 'stone_weight',
            'stone setting': 'setting',
            'stone set': 'setting',
            'setting type': 'setting',
            'setting': 'setting',
            # Earring details
            'earring size': 'earring_size',
            'earring backs': 'earring_backs',
            'earring back': 'earring_backs',
            'back type': 'earring_backs',
            'hoop size': 'hoop_size',
            'hoop diameter': 'hoop_size',
            'hoop outer size': 'hoop_outer_size',
            'hoop inner diameter': 'hoop_inner_diameter',
            'hoop width': 'hoop_width',
            'post size': 'pin_size',
            'pin size': 'pin_size',
            'pin thickness': 'pin_size',
            'ear post material': 'post_material',
            'ear pin material': 'post_material',
            'post material': 'post_material',
            'earring post material': 'post_material',
            'ear needle material': 'post_material',
            'drop length': 'drop_length',
            'dangle length': 'drop_length',
            'total drop length': 'drop_length',
            'structure': 'structure',
            'pearl type': 'pearl_type',
            'stone width': 'stone_width',
            'craftsmanship': 'craftsmanship',
            'sold as': 'sold_as',
            'sales unit': 'sold_as',
            'back disc size': 'back_disc_size',
            'flat back disc size': 'back_disc_size',
            'stone color': 'stone_color_options',
            'stone color options': 'stone_color_options',
            'stone color available': 'stone_color_options',
            'main stone color': 'stone_color_options',
            'main stone colors': 'stone_color_options',
            'visible stone colors': 'stone_color_options',
            'available stone colors': 'stone_color_options',
            'design elements': 'design',
            # Chain / bracelet / anklet lengths
            'chain length': 'chain_length',
            'bracelet chain length': 'chain_length',
            'anklet chain length': 'chain_length',
            'single layer chain length': 'chain_length',
            'necklace a chain length': 'chain_length',
            'necklace length': 'chain_length',
            'bracelet length': 'chain_length',
            'bracelet size': 'chain_length',
            'wrist size': 'chain_length',
            'anklet length': 'chain_length',
            'chain length visible in image': 'chain_length',
            # Width
            'chain width': 'chain_width',
            'bracelet width': 'width',
            'bangle width': 'width',
            'band width': 'width',
            'ring width': 'width',
            'width': 'width',
            'width available': 'width',
            # Pendant / bead / pearl
            'pendant size': 'pendant_size',
            'pendant diameter': 'pendant_size',
            'charm size': 'pendant_size',
            'charm diameter': 'pendant_size',
            'pendant size visible in image': 'pendant_size',
            'letter options': 'letter_options',
            'bead size': 'bead_size',
            'bead diameter': 'bead_size',
            'pearl size': 'pearl_size',
            'pearl diameter': 'pearl_size',
            # Ring
            'bangle size': 'bangle_size',
            'bangle diameter': 'bangle_diameter',
            'ring top size': 'ring_top',
            'top width shown': 'ring_top',
            'ring diameter': 'ring_diameter',
            'ring inner diameter': 'inner_diameter',
            'inner diameter': 'inner_diameter',
            'internal diameter': 'inner_diameter',
            'inner ring diameter': 'inner_diameter',
            'ring size': 'ring_size_range',
            'ring size range': 'ring_size_range',
            # Closure
            'closure': 'closure',
            'closure type': 'closure',
            'clasp type': 'closure',
            'clasp': 'closure',
            # Design / details (customer-facing)
            'design detail': 'design',
            'design': 'design',
            'main design': 'design',
            'design element': 'design',
            'design style': 'design',
            'bracelet type': 'bracelet_type',
            'chain style': 'chain_style',
            'processing': 'plating',
            'purity': 'purity',
            'size': 'size',
        }

        # Keys that are not useful product details for the customer
        SKIP_KEYS = {
            'metal material', 'material', 'metal color available',
            'color available', 'item type', 'gender', 'occasion',
            'style', 'feature', 'brand', 'new', 'color', 'category',
            # Redundant with the name/badges already shown on the product page
            'suitable for', 'earring type', 'earrings type', 'main material',
            'applicable crowd', 'suitable occasion',
            # Static marketing text that can drift from the live variant selector —
            # the real color/size choices come from actual Silverbene option data,
            # never from description copy, to avoid showing a mismatch
            'color options', 'available sizes', 'available length',
        }

        # See usage below — Bracelets-only length-in-disguise labels.
        _BRACELET_SIZE_AS_LENGTH_KEYS = {
            'reference size', 'adjustable size', 'size options', 'available size options',
        }
        # See usage below — Rings-only size-in-disguise labels ("Reference Size:
        # US Size 6", "Adjustable Range: About 13-17", "Size Reference: US Size
        # 7", "Finger Circumference Reference: 54mm, 55mm, 56mm", "Inner Diameter
        # Reference: 17mm To 17.5mm") — consolidate into the existing
        # ring_size_range/inner_diameter keys rather than becoming their own
        # auto-keys, since "reference size" etc. mean something different for
        # other categories (already handled separately above for Bracelets).
        _RING_SIZE_AS_RANGE_KEYS = {
            'reference size': 'ring_size_range',
            'adjustable range': 'ring_size_range',
            'size reference': 'ring_size_range',
            'finger circumference reference': 'ring_size_range',
            'inner diameter reference': 'inner_diameter',
            'ring size options': 'ring_size_range',
            'sizes available': 'ring_size_range',
            'reference ring size': 'ring_size_range',
            'size type': 'ring_size_range',
            'referenced size option': 'ring_size_range',
            'available us sizes': 'ring_size_range',
            'available ring us sizes': 'ring_size_range',
            'available size': 'ring_size_range',
            'adjustable ring size': 'ring_size_range',
            'available inner diameter': 'inner_diameter',
            'ring inner diameter shown': 'inner_diameter',
            'inner diameter shown in image': 'inner_diameter',
            'available ring sizes': 'ring_size_range',
            'ring sizes available': 'ring_size_range',
            'size feature': 'ring_size_range',
        }

        for li in lis:
            text = re.sub(r'<[^>]+>', '', li).strip()
            if not text or ':' not in text:
                continue
            if SKIP_RE.search(text):
                continue
            key_raw, _, val = text.partition(':')
            key = key_raw.strip().lower()
            val = val.strip().rstrip('.,')
            if not val or len(val) > 120:
                continue
            if key in SKIP_KEYS:
                continue

            # Bracelets: several observed labels describe the wearable length
            # using "Size" instead of "Length" ("Reference Size", "Adjustable
            # Size", "Size Options", "Available Size Options") — consolidate
            # into the canonical chain_length key so the frontend's
            # length-hiding filter (which matches on "length") still catches
            # them. Scoped to Bracelets only — "Size Options" means something
            # different in other categories (e.g. ring sizes).
            if category == "Bracelets" and key in _BRACELET_SIZE_AS_LENGTH_KEYS:
                spec_key = "chain_length"
                val = _apply_spec_conversion(spec_key, val, category=category)
                if spec_key not in specs:
                    specs[spec_key] = val
                continue

            if category == "Rings" and key in _RING_SIZE_AS_RANGE_KEYS:
                spec_key = _RING_SIZE_AS_RANGE_KEYS[key]
                if spec_key not in specs:
                    specs[spec_key] = val
                continue

            spec_key = FIELD_MAP.get(key)
            if not spec_key:
                # Categories rolled out onto capture-everything (vs. the old fixed
                # allowlist) — extend this set as each category gets reviewed.
                if category in ("Earrings", "Necklaces", "Bracelets", "Rings", "Anklets", "Ear Cuffs"):
                    # Silverbene's label phrasing varies too much for a fixed allowlist
                    # to keep up with — capture it under an auto-generated key rather
                    # than silently dropping it. The frontend already renders unknown
                    # spec keys fine (auto-titled from the key name).
                    # Guard against a rarer rich-HTML description template (marketing
                    # bullets like "<li><strong>7 Selectable Stone Shapes:</strong>
                    # Choose from...</li>") that isn't real "field: value" data — a
                    # genuine spec label is short and doesn't start with a digit.
                    # Also guard against multi-design bundle listings that prefix
                    # labels with an internal product code (e.g. "DY110322 Size:",
                    # "DY150326 Chain Length:") — a real label's first word is never
                    # a mix of letters and digits like that.
                    key_words = key.split()
                    looks_like_marketing = (
                        (key_words and key_words[0][0].isdigit()) or
                        len(key_words) > 5 or
                        len(val) > 70 or
                        (key_words and re.search(r'[a-z]\d|\d[a-z]', key_words[0]))
                    )
                    if looks_like_marketing:
                        continue
                    # Strip possessive apostrophes before the alnum cleanup, else
                    # "Women's Ring Width" becomes the confusing "women_s_ring_width"
                    # instead of the readable "womens_ring_width".
                    spec_key = re.sub(r"'s\b", "s", key)
                    spec_key = re.sub(r'[^a-z0-9]+', '_', spec_key).strip('_')
                    if not spec_key:
                        continue
                else:
                    continue  # other categories: only store known, mapped fields for now

            val = _apply_spec_conversion(spec_key, val, category=category)
            # Dual-purpose listings (sold as either a bracelet or an anklet) state
            # both "Bracelet Chain Length" and "Anklet Chain Length" separately —
            # both map to chain_length, but whichever appears first in the raw
            # HTML would otherwise win by default. When processing as an Anklet,
            # the anklet-specific label is always the right one, even if the
            # bracelet-labeled line appeared earlier in the same description.
            is_anklet_override = (
                category == "Anklets" and spec_key == "chain_length" and key.startswith("anklet")
            )
            if spec_key not in specs or is_anklet_override:   # first value wins, except the override above
                specs[spec_key] = val

        # Legacy: also catch drop_length expressed as "Xg" pattern outside <li>
        if 'drop_length' not in specs:
            m = re.search(r'[Dd]rop\s+[Ll]ength\s*[:\-]\s*([\d.]+\s*cm)', desc)
            if m:
                cm_m = re.search(r'([\d.]+)', m.group(1))
                if cm_m:
                    specs['drop_length'] = f'{round(float(cm_m.group(1)) / 2.54, 1)}"'

        return specs

    def _infer_material_from_desc(self, desc: str, colors: list = None) -> str:
        """
        Silverbene's desc HTML contains material info.
        e.g. '<li>Metal Color Available:Yellow Gold,Rhodium</li>'
             '<li>Total Weight: 3g</li>'
        925/S925 is always the base metal — Silverbene is a 925 specialist.
        """
        # Silverbene is 100% 925 sterling silver — this is their brand promise
        if "925" in desc or "s925" in desc.lower() or "sterling" in desc.lower():
            base = "S925 Sterling Silver"
        else:
            base = "925 Sterling Silver"

        # Detect plating from colors or desc
        desc_lower = desc.lower()
        if colors:
            color_str = " ".join(colors).lower()
            if "gold" in color_str or "yellow gold" in color_str:
                return f"{base} (Gold Plated available)"
            if "rose gold" in color_str:
                return f"{base} (Rose Gold Plated available)"

        if "gold" in desc_lower:
            return f"{base} (Gold Plated available)"

        return base


def _normalize_size_for_match(raw: str) -> str:
    """
    Strip supplier prefixes from a raw size attribute value so it can be
    compared against the customer's selected_size (which came from the DB
    sizes array, already normalized at import time).

    Examples:
      "US 5"      → "5"
      "US  6"     → "6"     (double space)
      "Size 7"    → "7"
      "Ring Size 8" → "8"
      "No. 14"    → "14"
      "18\""      → "18\""  (inch — already final form)
    """
    v = raw.strip()
    # Trailing comma is stray Silverbene data noise (e.g. "US 8,"), never a
    # meaningful part of a size value — strip it before matching.
    v = v.rstrip(',').strip()
    for prefix in ("US-", "US  ", "US ", "Size ", "Ring Size ", "No. ", "No "):
        if v.upper().startswith(prefix.upper()):
            return v[len(prefix):].strip()
    return v


def resolve_option_id(variants_json: str, selected_size: str, selected_color: str,
                      return_meta: bool = False):
    """
    Return the Silverbene option_id whose attributes best match the customer's
    selected size and color.  Both selected_size and selected_color are the
    display values from the DB (e.g. "7", '18"', "Yellow Gold").

    Matching priority:
      1. Exact size + exact color match
      2. Exact size match (ignore color if color wasn't selected)
      3. Exact color match (ignore size if size wasn't selected)
      4. First variant (fallback — same as old cj_sku behaviour)
    """
    _none = (None, "no_variants") if return_meta else None
    if not variants_json:
        return _none
    try:
        variants = json.loads(variants_json)
    except Exception:
        return _none
    if not variants:
        return _none

    want_size  = (selected_size  or "").strip()
    want_color = (selected_color or "").strip()
    # Mirror _extract_variants(): normally half-inch chips, escalating to
    # quarter-inch only when this product's own real sizes would otherwise
    # collide into the same chip.
    _denom = _bracelet_size_denom(variants)

    def attr_size(attrs):
        for a in attrs:
            aname = a.get("name", "").lower()
            if aname in ("size", "ring size", "bracelet size", "anklet size") \
               or aname in BRACELET_SIZE_ATTR_NAMES:
                v = a.get("value", "").strip()
                normalized = _normalize_size_for_match(v)
                if re.search(r'\d+\s*(mm|cm)', v, re.I):
                    # Try bracelet range first, then necklace
                    chips = parse_bracelet_size(v, _denom) or parse_necklace_length(v)
                    if chips:
                        normalized = chips[0]
                return normalized
            if aname in ("chain length", "length") and re.search(r'\d+\s*(mm|cm)', a.get("value", ""), re.I):
                v = a.get("value", "").strip()
                chips = parse_bracelet_size(v, _denom) or parse_necklace_length(v)
                if chips:
                    return chips[0]
        # No dedicated size attribute — Silverbene sometimes bundles the real
        # size measurement into the Color attribute instead (hoop diameter,
        # tube width, bracelet extension). Mirror _extract_variants() exactly
        # so this matches whatever chip the customer actually saw and clicked.
        for a in attrs:
            if a.get("name", "").lower() in COLOR_ATTRIBUTE_NAMES:
                v = a.get("value", "").strip()
                if re.search(r'\d+\s*(mm|cm)', v, re.I):
                    _, size_chip = _split_color_and_size(v)
                    if size_chip:
                        return size_chip
        return None

    def attr_color(attrs):
        _suffix = _detect_option_suffix(attrs)
        parts = []
        for a in attrs:
            if a.get("name", "").lower() not in COLOR_ATTRIBUTE_NAMES:
                continue
            v = a.get("value", "").strip()
            if not v:
                continue
            if re.search(r'\d+\s*(mm|cm)', v, re.I):
                color_part, _ = _split_color_and_size(v)
            elif _is_compound_color_candidate(v):
                color_part = _clean_compound_color(v)
            else:
                cleaned = _clean_plain_color(v)
                # An exact category word ("Anklet", "Necklace") normally
                # cleans to "" as noise, but _extract_variants() rescues it
                # as the real color when it's the only thing that varies —
                # fall back to the raw word so this stays consistent with
                # whatever the customer actually selected in that case.
                color_part = cleaned or v
            if color_part:
                parts.append(color_part)
        # Combine every real color-type attribute this option carries (e.g. a
        # separate metal "Color" + gem "Main Stone") into ONE string, mirroring
        # _extract_variants() so a customer's exact selection always resolves.
        # A suffix only ever means anything attached to a real color — see
        # _extract_variants() for why a bare suffix must never stand in alone.
        display = ' · '.join(parts)
        if _suffix and display:
            display = f'{display} · {_suffix}'
        return display or None

    def color_matches(api_raw: str, want: str) -> bool:
        """
        True when api_raw (Silverbene raw value, e.g. 'Pink') equals want
        (display label stored in cart, e.g. 'Rose Gold').

        Handles three cases:
          1. Direct match: 'Silver' == 'Silver'
          2. Case-insensitive direct: 'gold' == 'Gold'
          3. Reverse label map: 'Pink' matches want='Rose Gold'
             because _COLOR_LABEL_REVERSE['rose gold'] = ['rose gold','pink']
        """
        if not api_raw or not want:
            return False
        if api_raw.lower() == want.lower():
            return True
        # Check if 'want' is a display label whose raw values include api_raw
        raw_candidates = _COLOR_LABEL_REVERSE.get(want.lower(), [])
        return api_raw.lower() in raw_candidates

    # Pass 1: exact size + exact color
    if want_size and want_color:
        for v in variants:
            attrs = v.get("attribute", [])
            if attr_size(attrs) == want_size and color_matches(attr_color(attrs) or "", want_color):
                return (str(v.get("option_id", "")), "exact") if return_meta else str(v.get("option_id", ""))

    # Pass 2: exact size only
    if want_size:
        for v in variants:
            attrs = v.get("attribute", [])
            if attr_size(attrs) == want_size:
                return (str(v.get("option_id", "")), "size_only") if return_meta else str(v.get("option_id", ""))

    # Pass 3: exact color only
    if want_color:
        for v in variants:
            attrs = v.get("attribute", [])
            if color_matches(attr_color(attrs) or "", want_color):
                return (str(v.get("option_id", "")), "color_only") if return_meta else str(v.get("option_id", ""))

    # Pass 4: fallback to first variant (cj_sku behaviour)
    return (str(variants[0].get("option_id", "")), "fallback") if return_meta else str(variants[0].get("option_id", ""))


_PENDANT_ONLY_RE = re.compile(
    r'pendant only|chain not included|without chain|no chain included|chain is not included',
    re.I,
)

def _is_pendant_only(desc: str) -> bool:
    """Return True if this is a pendant sold without a chain."""
    return bool(_PENDANT_ONLY_RE.search(desc or ''))


MM_TO_INCHES = {
    350: '14"', 380: '15"', 400: '16"', 410: '16"',
    420: '16.5"', 450: '18"', 460: '18"', 480: '19"',
    500: '20"', 550: '22"', 600: '24"', 650: '26"',
    700: '28"', 750: '30"',
}


_STD_MM = sorted(MM_TO_INCHES.keys())

def _snap_inch(mm: int) -> str:
    """Snap mm value to nearest standard necklace length, return clean inch string e.g. '16\"'."""
    best = min(_STD_MM, key=lambda s: abs(s - mm))
    return MM_TO_INCHES[best]  # already includes the " suffix


def _snap_bracelet_inch(mm: float, denom: int = 2) -> str:
    """
    Snap mm to the nearest 1/denom inch, return display string e.g. '7"'.
    denom=2 (default, half-inch) is the normal customer-facing granularity.
    denom=4 (quarter-inch) is used only when two genuinely different real
    Silverbene sizes for the same product would otherwise collide into the
    same half-inch label (see _bracelet_size_denom).
    """
    inches = mm / 25.4
    snapped = round(inches * denom) / denom
    whole = int(snapped)
    if denom <= 2:
        if snapped == whole:
            return f'{whole}"'
        return f'{snapped}"'
    quarters = round((snapped - whole) * 4) % 4
    if quarters == 0:
        return f'{whole}"'
    _QUARTER_SYMBOLS = {1: '¼', 2: '½', 3: '¾'}
    return f'{whole}{_QUARTER_SYMBOLS[quarters]}"'


def _bracelet_size_denom(variants: list) -> int:
    """
    Determine the finest 1/denom-inch granularity actually needed to keep every
    real, distinct Silverbene bracelet/anklet size value visually unique for
    this product. Defaults to the usual half-inch (denom=2); only escalates to
    quarter-inch (denom=4) when two genuinely different real sizes would
    otherwise collide into the same customer-facing chip (e.g. 160mm and
    170mm both round to "6.5\"" at half-inch precision but are two separate,
    differently-priced Silverbene options — confirmed against live Silverbene
    data for "Diamond Wheat Sheaf Bracelet", SKU SPZB_636352691391).
    Rare in practice (1 of 52 bracelet/anklet products in the catalog as of
    2026-07-12) — every other product keeps its normal half-inch chips.
    """
    mm_values = set()
    for v in variants or []:
        for a in v.get("attribute", []):
            name = a.get("name", "").lower().strip()
            val = a.get("value", "").strip()
            if name in BRACELET_SIZE_ATTR_NAMES or name in ("size", "chain length", "length"):
                m = re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm)', val, re.I)
                if m:
                    num, unit = float(m.group(1)), m.group(2).lower()
                    mm = num * 10 if unit == "cm" else num
                    if 100 <= mm <= 260:
                        mm_values.add(round(mm, 1))
    if len(mm_values) < 2:
        return 2
    for denom in (2, 4):
        if len({_snap_bracelet_inch(mm, denom) for mm in mm_values}) == len(mm_values):
            return denom
    return 4


# ── Ring size conversion (mm inner diameter → US size) ───────────────────────

_MM_TO_US_RING = [
    (14.0, 3), (14.9, 4), (15.7, 5), (16.5, 6),
    (17.3, 7), (18.1, 8), (18.9, 9),
]


def _mm_to_us_ring(mm: float) -> int:
    """Snap mm inner diameter to nearest US ring size."""
    return min(_MM_TO_US_RING, key=lambda x: abs(x[0] - mm))[1]


def _parse_ring_diameter_mm(text: str):
    """Return (min_mm, max_mm) from a diameter string, or None."""
    # Range first: "13–16.5mm", "13-16.5mm"
    m = re.search(r'([\d.]+)\s*[-–]\s*([\d.]+)\s*(mm|cm)', text, re.I)
    if m:
        lo, hi, unit = float(m.group(1)), float(m.group(2)), m.group(3).lower()
        if unit == 'cm':
            lo, hi = lo * 10, hi * 10
        return (lo, hi)
    # Single value: "16.4mm", "1.7cm"
    m = re.search(r'([\d.]+)\s*(mm|cm)', text, re.I)
    if m:
        val, unit = float(m.group(1)), m.group(2).lower()
        if unit == 'cm':
            val *= 10
        return (val, val)
    return None


def open_ring_size_text(specs: dict, desc: str = "") -> str:
    """Return the size badge text for an open/adjustable ring.

    Checks specs for ring_diameter or inner_diameter first.
    If a real mm measurement is found, converts to US range.
    Falls back to our standard open-ring range US 5-8.
    """
    dia_text = None
    for key in ('ring_diameter', 'inner_diameter'):
        val = specs.get(key, "")
        if val and re.search(r'\d', str(val)):
            dia_text = str(val)
            break

    # Try description if specs had nothing
    if not dia_text and desc:
        m = re.search(
            r'(?:ring\s+)?(?:inner|internal)?\s*diameter[:\s]+'
            r'([\d.]+(?:\s*[-–]\s*[\d.]+)?\s*(?:mm|cm))',
            desc, re.I
        )
        if m:
            dia_text = m.group(1)

    if dia_text:
        parsed = _parse_ring_diameter_mm(dia_text)
        if parsed:
            lo_us = _mm_to_us_ring(parsed[0])
            hi_us = _mm_to_us_ring(parsed[1])
            if lo_us == hi_us:
                return f"Adjustable · fits US {lo_us}"
            return f"Adjustable · fits US {min(lo_us, hi_us)}–{max(lo_us, hi_us)}"

    return "Adjustable · fits US 5-8"


def parse_bracelet_size(length_str: str, denom: int = 2) -> list:
    """
    Convert a Silverbene bracelet length/wrist-size string to US customer-facing inch chips.
    Handles cm and mm values in bracelet range (100–260mm / 10–26cm).
    Returns [] for values outside bracelet range so caller can try parse_necklace_length.

    Silverbene attribute names routed here: wrist size, inner diameter, bracelet size,
    bracelet length, and 'length'/'size'/'color' attrs whose value is in bracelet range.

    denom controls snapping granularity (2 = half-inch, the default; 4 = quarter-inch,
    only used when _bracelet_size_denom() detects that half-inch would collide two
    real, differently-priced sizes for the same product).

    Examples:
      "17cm"       → ['6.5"']
      "18 cm"      → ['7"']
      "19Cm"       → ['7.5"']
      "17+3"       → ['Adjustable 6.5"–8"']
      "17cm+3cm"   → ['Adjustable 6.5"–8"']
      "16cm-20cm"  → ['Adjustable 6.5"–8"']  (one item's span, not 4 separate sizes)
      "58mm" (ID)  → ['7"']  (inner diameter → circumference)
    """
    import math as _math
    s = length_str.strip()
    _BRACELET_RANGE_LO = 100   # mm — below this it's not a bracelet size
    _BRACELET_RANGE_HI = 260   # mm — above this hand off to necklace parser

    def _to_mm(val: str, unit: str) -> int:
        unit = (unit or "cm").lower()
        v = float(val)
        return int(round(v * 10)) if unit == "cm" else int(round(v))

    is_inner_diam = bool(re.search(r'inner\s*diam|i\.?d\.?', s, re.I))

    # Strip trailing descriptor words (e.g. "16+2cm Adjustable", "17cm Adjustable")
    s = re.sub(r'\s+(adjustable|adj\.?|extendable|extension)\s*$', '', s, flags=re.I).strip()

    # "17+3" or "17cm+3cm" — chain + one adjustor. Also handles Silverbene's
    # double-extension format "150mm + 15mm + 15mm" (two "+"-joined segments,
    # e.g. an extender chain on each side) — every segment after the base gets
    # summed into one total extension rather than only the first being read
    # and the rest silently dropped.
    ext_m = re.match(
        r'^(\d+(?:\.\d+)?)\s*(cm|mm)?((?:\s*\+\s*\d+(?:\.\d+)?\s*(?:cm|mm)?)+)$', s, re.I
    )
    if ext_m:
        b_unit = ext_m.group(2) or "cm"
        b_mm = _to_mm(ext_m.group(1), b_unit)
        ext_total_mm = 0
        last_unit = b_unit
        for num, unit in re.findall(r'\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)?', ext_m.group(3), re.I):
            last_unit = unit or last_unit
            ext_total_mm += _to_mm(num, last_unit)
        if _BRACELET_RANGE_LO <= b_mm <= _BRACELET_RANGE_HI:
            lo = _snap_bracelet_inch(b_mm, denom)
            hi = _snap_bracelet_inch(b_mm + ext_total_mm, denom)
            return [lo] if lo == hi else [f'Adjustable {lo}–{hi}']

    # "16cm-20cm" or "160mm-200mm" — a range named in a single text field never
    # justifies multiple selectable sizes: Silverbene only prices one option per
    # real size, so genuinely distinct sizes always show up as separate priced
    # variants (parsed one number at a time elsewhere). A range reaching here has
    # no per-length price behind it — it can only describe one adjustable item's
    # wearable span.
    range_m = re.search(
        r'(\d+(?:\.\d+)?)\s*(cm|mm)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I
    )
    if range_m:
        lo_mm = _to_mm(range_m.group(1), range_m.group(2))
        hi_mm = _to_mm(range_m.group(3), range_m.group(4))
        if _BRACELET_RANGE_LO <= lo_mm <= _BRACELET_RANGE_HI:
            lo, hi = _snap_bracelet_inch(lo_mm, denom), _snap_bracelet_inch(hi_mm, denom)
            return [lo] if lo == hi else [f'Adjustable {lo}–{hi}']

    # Inner diameter (bangle sizing) → wrist circumference
    if is_inner_diam:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
        if m:
            id_mm = _to_mm(m.group(1), m.group(2))
            circ_mm = _math.pi * id_mm
            if _BRACELET_RANGE_LO <= circ_mm <= _BRACELET_RANGE_HI:
                return [_snap_bracelet_inch(circ_mm, denom)]
        return []

    # Single value: "17cm", "18 CM", "180mm", "17Cm"
    single_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
    if single_m:
        mm = _to_mm(single_m.group(1), single_m.group(2))
        if _BRACELET_RANGE_LO <= mm <= _BRACELET_RANGE_HI:
            return [_snap_bracelet_inch(mm, denom)]

    return []


def parse_necklace_length(chain_length_str: str) -> list:
    """
    Convert a Silverbene chain length string into customer-facing inch chips.

    Inputs handled:
      "40cm+5cm"                           -> ['Adjustable 16"–18"']
      "Approximately 41cm + 5cm Adjustable"-> ['Adjustable 16"–18"']
      "400mm + 50mm Adjustable"            -> ['Adjustable 16"–18"']
      "43cm main chain with 5cm extension" -> ['Adjustable 17"–19"']
      "400mm - 450mm Adj."                 -> ['Adjustable 16"–18"']
      "45cm"                               -> ['18"']
      "40cm - 60cm"                        -> ['16"','18"','20"','22"','24"']
      "40cm, 45cm, 50cm, 55cm, 60cm"       -> ['16"','18"','20"','22"','24"'] (exact list, not expanded)
    """
    s = chain_length_str.strip()
    is_adj = bool(re.search(r'adjustabl|extender|extension', s, re.I))

    def _to_mm_val(val, unit):
        unit = unit.lower() if unit else ''
        return int(round(float(val) * 10)) if unit == 'cm' else int(float(val))

    # Pattern 1: "X(unit) + Y(unit)" — base + extender (use re.search not re.match).
    # Optional "Length"/"Chain" word tolerated between the base measurement and the
    # "+" sign — e.g. "45cm Length + 5cm Extension" (seen on real Silverbene copy).
    ext_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)?\s*(?:(?:length|chain)\s*)?\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
    if ext_m:
        ext_unit = ext_m.group(4).lower()
        base_unit = ext_m.group(2) or ext_unit
        b_mm = _to_mm_val(ext_m.group(1), base_unit)
        e_mm = _to_mm_val(ext_m.group(3), ext_unit)
        lo, hi = _snap_inch(b_mm), _snap_inch(b_mm + e_mm)
        if lo == hi:
            return [lo]
        return [f'Adjustable {lo}–{hi}']

    # Pattern 2: "Xcm main chain with Ycm" (no + sign)
    with_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)\s+(?:\w+\s+)?chain\s+with\s+(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
    if with_m:
        b_mm = _to_mm_val(with_m.group(1), with_m.group(2))
        e_mm = _to_mm_val(with_m.group(3), with_m.group(4))
        lo, hi = _snap_inch(b_mm), _snap_inch(b_mm + e_mm)
        if lo == hi:
            return [lo]
        return [f'Adjustable {lo}–{hi}']

    # Normalise cm → mm for remaining patterns
    def _to_mm(m): return str(int(round(float(m.group(1)) * 10))) + 'mm'
    s_mm = re.sub(r'(\d+(?:\.\d+)?)\s*cm', _to_mm, s, flags=re.I)

    nums = [int(n) for n in re.findall(r'\d+', s_mm) if 350 <= int(n) <= 900]
    if not nums:
        return []

    if len(nums) == 1:
        # Only one plausible in-range number survived (either the raw text only ever
        # had one, or a second number got filtered out as implausible — e.g. "200mm"
        # in "200mm - 415mm Adjustable" is below the 350mm necklace floor and likely
        # a data-entry error upstream). Never show it as "Adjustable X–X" — a range
        # with identical bounds isn't a range, it's confusing.
        c = _snap_inch(nums[0])
        return [f'Adjustable {c}'] if is_adj else [c]

    lo_mm, hi_mm = min(nums), max(nums)

    # A single text field naming 2+ plausible lengths (dash-range, "to"-range, or
    # comma-list — separator doesn't matter) never justifies claiming multiple
    # separately-purchasable sizes: Silverbene only ever prices one option per
    # real size, so genuinely distinct sizes always show up as separate priced
    # variants (each parsed individually, one number at a time, by the caller in
    # _extract_variants — never reaching this multi-number branch at all). A
    # multi-number string reaching this point has no per-length price behind it,
    # so it can only describe one adjustable item's wearable span.
    lo_in, hi_in = _snap_inch(lo_mm), _snap_inch(hi_mm)
    if lo_in == hi_in:
        return [lo_in]
    return [f'Adjustable {lo_in}–{hi_in}']


def _sanitize_description(desc: str) -> str:
    """
    Replace technical plating terms in product descriptions with customer-friendly names.
    Applied to every product on import so customers never see internal jargon.
    """
    if not desc:
        return desc
    # Rhodium → Silver (whole-word, case-preserving)
    desc = re.sub(r'\bRhodium\b', 'Silver', desc)
    desc = re.sub(r'\brhodium\b', 'silver', desc)
    desc = re.sub(r'\bRHODIUM\b', 'SILVER', desc)
    # "White Gold Color" / "Yellow Gold Color" → strip the redundant "Color" suffix
    desc = re.sub(r'\b(White Gold|Yellow Gold|Rose Gold|Gold|Silver|Platinum)\s+Color\b', r'\1', desc, flags=re.I)
    return desc


_SKU_PREFIX_RE = re.compile(r'^[A-Za-z]{1,4}\d+[-_\s]')
# Trailing catalog-reference remnants Silverbene sometimes leaves on a Color
# value after its own internal numbering: "Dark Blue Spinel 113#" (number+hash),
# "Rose Red#" (lone hash with nothing before it). Order matters — the numbered
# form must run first, or its own trailing "#" would already be gone by the
# time the lone-hash pattern runs, silently leaving the number behind instead.
_TRAILING_CATALOG_NUM_RE = re.compile(r'\s+\d+#?\s*$')
_TRAILING_HASH_RE = re.compile(r'#\s*$')


def _clean_color_value(value: str) -> str:
    """
    Strip Silverbene's own internal catalog-code prefixes, trailing catalog
    reference numbers, and category-word prefixes from a Color attribute value.
    e.g. "JZ210-Silver" → "Silver", "L874-Waterdrop CZ Bracelet" → "Waterdrop
    CZ Bracelet", "JZ1567 Silver" → "Silver", "Dark Blue Spinel 113#" → "Dark
    Blue Spinel", "Anklet Silver" → "Silver", "Anklet" → "" (discard).
    The SKU-prefix pattern requires a dash/underscore/space right after the
    digits, so it only ever matches a real letter+number catalog code, never a
    stone or color name that happens to start with a number-bearing word.
    """
    value = _SKU_PREFIX_RE.sub('', value)
    value = _TRAILING_CATALOG_NUM_RE.sub('', value)
    value = _TRAILING_HASH_RE.sub('', value)
    value = re.sub(r'\s{2,}', ' ', value).strip()
    lower = value.lower()
    for prefix in _CATEGORY_PREFIXES:
        if lower == prefix:
            return ""
        if lower.startswith(prefix + " "):
            return value[len(prefix):].strip()
    return value


_LABELED_LEN_RE = re.compile(r'\blength\s*[:\s]+(\d+(?:\.\d+)?)\s*(cm|mm)', re.I)
_EXT_LEN_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(cm|mm)?\s*\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)', re.I)
_TUBE_DIM_RE = re.compile(r'(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*(mm|cm)\b')
_BARE_DIM_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(mm|cm)\b', re.I)
_WEIGHT_FRAG_RE = re.compile(r'weight\s*[:\-]?\s*(approximately\s*)?[\d.]+\s*g\b', re.I)
_BARE_WEIGHT_RE = re.compile(r'\b[\d.]+\s*g\b', re.I)
_WIDE_DIM_RE = re.compile(r'\d+(?:\.\d+)?\s*(mm|cm)\s*wide\b', re.I)
_SINGLE_PAIR_RE = re.compile(r'\b(single(\s+piece)?|pair)\b', re.I)
# Known Silverbene typos seen in raw Color attribute text — corrected so they
# canonicalize to the same color bucket as the properly-spelled variants of
# the same product (otherwise a typo'd option silently becomes its own,
# unmatched color group).
_COLOR_TYPO_FIXES = [
    (re.compile(r'(?<!1)\b8K\b', re.I), '18K'),
    (re.compile(r'\bgolde\b', re.I), 'Gold'),
]


def _split_color_and_size(value: str, category: str = ""):
    """
    Split a Silverbene Color-attribute value that bundles a finish/metal name
    together with a measurement into a clean color name and a size chip.

    Silverbene sometimes puts the real, price-differentiating measurement
    inside the "Color" attribute instead of its own attribute, in all sorts of
    shapes: "18K Yellow Gold 6mm" (hoop diameter), "Pink_16+3cm" (bracelet
    extension), "3 mm wide, 18K gold, length: 16.5 cm, weight: 2 g" (chain),
    "1.0mm, 40cm" (width + length, no color/finish at all).

    Chain-length-range numbers (bracelet/necklace scale) are converted to the
    usual inch chip via parse_bracelet_size/parse_necklace_length — same as
    every other per-variant length. Anything else with a real measurement
    (hoop diameter, tube width, ring width) that doesn't fall in either range
    is kept as its own plain size chip (e.g. "6mm", "2.0x15mm") instead of
    being silently discarded — Silverbene still prices it as a distinct,
    selectable option even though it isn't a "length" in the bracelet/necklace
    sense. When a value bundles two measurements (a width alongside a length),
    every matched measurement token is stripped before what's left is treated
    as a color name — so a stray leftover number never becomes a fake "color".

    Returns (color_part: str, size_chip: str | None).
    """
    v = value.strip()
    size_chip = None
    remainder = v

    m = _LABELED_LEN_RE.search(v)
    if m:
        dim_str = f"{m.group(1)}{m.group(2)}"
        chips = parse_bracelet_size(dim_str) or parse_necklace_length(dim_str)
        size_chip = chips[0] if chips else None
        remainder = v[:m.start()] + v[m.end():]
    else:
        m = _EXT_LEN_RE.search(v)
        if m:
            dim_str = m.group(0).strip()
            chips = parse_bracelet_size(dim_str) or parse_necklace_length(dim_str)
            size_chip = chips[0] if chips else None
            remainder = v[:m.start()] + v[m.end():]
        else:
            m = _TUBE_DIM_RE.search(v)
            if m:
                size_chip = f"{m.group(1)}x{m.group(2)}{m.group(3).lower()}"
                remainder = v[:m.start()] + v[m.end():]
            else:
                matches = list(_BARE_DIM_RE.finditer(v))
                if matches:
                    chosen_chip = None
                    for cand in matches:
                        chips = parse_bracelet_size(cand.group(0)) or parse_necklace_length(cand.group(0))
                        if chips:
                            chosen_chip = chips[0]
                            break
                    first = matches[0]
                    size_chip = chosen_chip or f"{first.group(1)}{first.group(2).lower()}"
                    # Strip every matched token (not just the one used for the
                    # chip) — a second, unrelated measurement (e.g. a width
                    # alongside the length) must never leak into the color name.
                    for cand in reversed(matches):
                        remainder = remainder[:cand.start()] + remainder[cand.end():]

    color_part = remainder
    color_part = _WIDE_DIM_RE.sub('', color_part)
    color_part = _WEIGHT_FRAG_RE.sub('', color_part)
    color_part = _BARE_WEIGHT_RE.sub('', color_part)
    color_part = _BARE_DIM_RE.sub('', color_part)  # any other leftover measurement token
    color_part = re.sub(r'\bwide\b', '', color_part, flags=re.I)
    # A measurement's own label word ("12mm Outer Diameter", "8mm Inner
    # Diameter") describes what the number means, not the color — the number
    # itself is already stripped above, but the label word that follows it
    # is a separate token and survives unless removed here too (e.g. "18K
    # Gold, 12mm Outer Diameter" would otherwise clean to "18K Gold Outer
    # Diameter" instead of "18K Gold").
    color_part = re.sub(r'\b(outer|inner)?\s*diameter\b', '', color_part, flags=re.I)
    color_part = _SINGLE_PAIR_RE.sub('', color_part)
    for _typo_re, _fix in _COLOR_TYPO_FIXES:
        color_part = _typo_re.sub(_fix, color_part)
    color_part = re.sub(r'[,_&]+', ' ', color_part)
    color_part = re.sub(r'\s+', ' ', color_part).strip(' ,-')
    color_part = _clean_color_value(color_part)
    # A leftover with no letters at all isn't a real color/finish name.
    if color_part and not re.search(r'[A-Za-z]', color_part):
        color_part = ''
    return color_part, size_chip


_COLOR_NOISE_RE = re.compile(r'^(single(\s+piece)?|pair)$', re.I)
_TRAILING_NOISE_RE = re.compile(r'\s*\b(single(\s+piece)?|pair)\s*$', re.I)


def _is_compound_color_candidate(value: str) -> bool:
    """
    True when a comma in a Color value is a genuine separator between two
    distinct descriptors (e.g. "18K Yellow Gold, White Stone") rather than
    punctuation inside a parenthetical annotation (e.g. "Rhodium (Pendant
    Only,)"), which must stay on the plain single-color cleaning path.
    """
    return ',' in value and '(' not in value and ')' not in value


def _clean_compound_color(value: str) -> str:
    """
    Clean a Color attribute value that bundles multiple comma-separated
    descriptors with no measurement in it — e.g. "18K Yellow Gold, White
    Stone" (metal + stone color), "Rhodium, Single Piece" (metal + noise),
    "Platinum Color, D Color Moissanite, 0.5 Carat" (metal + grade + carat).

    Every real, non-noise part is kept and joined with " · " into ONE
    combined, display-ready color string — rather than trying to split it
    into two independent selectors (metal + stone) that can drift out of
    sync with which combinations Silverbene actually priced. This way each
    distinct priced option maps to exactly one unique, matchable chip.
    Pure noise words that never represent a real choice ("Single Piece")
    are dropped entirely.
    """
    parts = [p.strip() for p in value.split(',') if p.strip()]
    if not parts:
        return _clean_color_value(value)
    cleaned_parts = []
    for i, part in enumerate(parts):
        if i == 0:
            # Normalize the metal part the same way a plain (non-compound) value
            # would be ("18K Yellow Gold" -> "Yellow Gold" etc). normalize_rhodium=
            # False: a literal "Rhodium" here must survive uncollapsed so
            # _to_standard()'s Step 1 (_normalize_finish_terms) can still see it and
            # decide, per-product from the description, "Silver" vs "White Gold" —
            # by the time any other caller reads this (checkout, order tracker),
            # raw variants have already had Step 3's write-back applied, so a
            # literal "Rhodium" should never reach here again after that.
            part = _normalize_color_final(_clean_color_value(part), "color", normalize_rhodium=False)
        if not part or _COLOR_NOISE_RE.match(part):
            continue
        cleaned_parts.append(part)
    return ' · '.join(cleaned_parts)


def _clean_plain_color(value: str) -> str:
    """
    Clean a non-compound Color value — strips a trailing noise word Silverbene
    sometimes appends with no comma at all (e.g. "Rhodium Single" — the same
    "Single Piece" noise _clean_compound_color drops, just missing its comma)
    before the usual category-prefix strip. Friendly-name normalization
    ("Rhodium" -> "Silver") happens at the same outer layer as every other
    plain color value, not here.
    """
    return _clean_color_value(_TRAILING_NOISE_RE.sub('', value).strip())


_CHAIN_STYLE_ONLY_RE = re.compile(r'pendant\s+only|no\s+chain|without\s+chain', re.I)
_CHAIN_STYLE_WITH_RE = re.compile(
    r'pendant\s*[,+]?\s*(and\s+|\+\s*)?necklace|with\s+chain|includes?\s+chain|chain\s+included',
    re.I,
)
_SPEC_VALUE_RE = re.compile(r'\d+(\.\d+)?\s*mm', re.I)
_OPTION_SUFFIX_SKIP_NAMES = COLOR_ATTRIBUTE_NAMES | SIZE_ATTRIBUTE_NAMES | BRACELET_SIZE_ATTR_NAMES


def _detect_option_suffix(attrs: list) -> str | None:
    """
    Some options carry a second, real price-differentiating choice under an
    attribute name Silverbene never standardizes (never Color or Size):
      - necklaces: "pendant only, no chain" vs "pendant + full necklace"
        (e.g. under "Purity", "Style")
      - earrings/studs: a post or bar spec — gauge, post length, bar length —
        shared across options that otherwise have an identical Color value
        (e.g. "Post Size": "1.2mm x 6mm Post" vs "1.2mm x 8mm Post"; "Gauge
        And Length": "1.0mm Gauge, 6mm Bar" vs "1.0mm Gauge, 8mm Bar" —
        confirmed against live Silverbene data for products 1000, 1002, 1016,
        which otherwise collide two differently-priced options into one
        indistinguishable chip and silently resolve to the wrong option_id)
    Scan an option's other attributes for either and return a label to fold
    into the color chip so the options stay unique — or None if this option
    carries neither.
    """
    for a in attrs:
        name = (a.get("name") or "").lower().strip()
        val = (a.get("value") or "").strip()
        if not val or name in _OPTION_SUFFIX_SKIP_NAMES:
            continue
        if _CHAIN_STYLE_ONLY_RE.search(val):
            return "Pendant Only"
        if _CHAIN_STYLE_WITH_RE.search(val):
            return "With Necklace"
        if _SPEC_VALUE_RE.search(val):
            return ' · '.join(p.strip() for p in val.split(',') if p.strip())
    return None


def _parse_chain_length_from_desc(desc: str, category: str = "") -> list:
    """
    Extract chain length from Silverbene HTML description.
    Looks for patterns like:
      <li>Chain Length: 400mm - 450mm Adjustable</li>
      <li>Necklace Length Range: 41cm To 50cm</li>
      <li>Available Length: 40cm, 45cm, 50cm</li>
      <li>Length: 450mm</li>
      <li>Chain Style: Bead Chain with 45cm Length + 5cm Extension</li>

    For Anklets: ankle circumference is bracelet-scale (roughly 200-280mm),
    not necklace-scale — parse_necklace_length()'s snap table has no entry
    below 350mm, so every anklet-scale value was silently flooring to the
    same wrong "14 inch" regardless of its real length. Try the
    bracelet-scale parser first, matching the per-variant path in
    _extract_variants() which already does this correctly. Also prefer an
    explicit "Anklet Chain Length"/"Anklet Length" label over a generic
    "Chain Length" one — some listings are dual-purpose (sold as either a
    bracelet or an anklet) and state both lengths separately.
    Returns parsed chips list, or empty list if nothing found.
    """
    def _parse_len(text: str) -> list:
        if category == "Anklets":
            return parse_bracelet_size(text) or parse_necklace_length(text)
        return parse_necklace_length(text)

    if category == "Anklets":
        m = re.search(r'[Aa]nklet\s+(?:[Cc]hain\s+)?[Ll]ength(?:\s+[Rr]ange)?[:\s]+([^<\n]{3,60})', desc)
        if m:
            return _parse_len(m.group(1))

    m = re.search(r'(?:[Cc]hain|[Nn]ecklace)\s+[Ll]ength(?:\s+[Rr]ange)?[:\s]+([^<\n]{3,60})', desc)
    if not m:
        m = re.search(r'[Aa]vailable\s+[Ll]ength(?:\s+[Oo]ptions)?[:\s]+([^<\n]{3,60})', desc)
    if not m:
        # Bare "Length:" with no "Chain"/"Necklace"/"Available" prefix — Silverbene
        # writes this in both mm ("450mm") and cm ("40cm + 5cm Adjustable") forms,
        # so require a real cm/mm unit rather than assuming mm and a fixed digit count.
        m = re.search(r'\bLength[:\s]+(\d+(?:\.\d+)?\s*(?:mm|cm)[^<\n]{0,40})', desc)
    if m:
        return _parse_len(m.group(1))
    # Some Silverbene listings put real length data under "Chain Style" instead
    # of "Chain Length" (e.g. "Bead Chain with 45cm Length + 5cm Extension").
    # Only trust it here if the value actually contains a cm/mm measurement, so
    # a plain style description with no dimensions ("Chain Style: Box Chain")
    # isn't misread as a length.
    m = re.search(r'[Cc]hain\s+[Ss]tyle[:\s]+([^<\n]{3,80})', desc)
    if m and re.search(r'\d+\s*(cm|mm)', m.group(1), re.I):
        chips = _parse_len(m.group(1))
        if chips:
            return chips
    return []


_ADJUSTABLE_LANGUAGE_RE = re.compile(
    r'\badjustable\b|\bextender\b|\bextension\s+chain\b|\bextending\s+chain\b|'
    r'\bspring\s+ring\b|\bspring\s+clasp\b',
    re.I,
)


def _has_adjustable_language(desc: str) -> bool:
    """
    True if the raw description mentions adjustability anywhere at all —
    not just in a dedicated "Extension Chain: Yes" field (that's already
    captured as its own spec key by _extract_specs_from_desc), but also
    when the exact same real information is embedded inside a different
    field's value, e.g. "Closure: Spring Ring Clasp With Extender Chain".
    A spring-ring/spring-clasp closure is included deliberately (per
    Dennis) — in this catalog's anklet/bracelet listings it consistently
    co-occurs with a genuinely adjustable extender, even on the listings
    that never say "adjustable" or "extender" outright.

    Used only as the last-resort fallback for Anklets/Bracelets that have
    NO real length anywhere (no priced-option size, no parseable number in
    the description — see _parse_chain_length_from_desc) — surfaces an
    honest "Adjustable" note instead of showing nothing, but never invents
    a specific measurement. If this text isn't present, the gap is real
    and nothing is shown, same as before.
    """
    return bool(_ADJUSTABLE_LANGUAGE_RE.search(desc or ""))


def _parse_chain_length_from_desc_bracelet(desc: str) -> list:
    """Thin wrapper — delegates to _extract_bracelet_info_from_desc for backward compat."""
    return _extract_bracelet_info_from_desc(desc)["sizes"]


def _raw_mm_text(val: str):
    """Extract a clean 'Xmm' string from a raw cm/mm value, converting cm→mm.
    Returns None if no measurement is found."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm)', val, re.I)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2).lower()
    mm = num * 10 if unit == "cm" else num
    return f'{int(mm)}mm' if mm == int(mm) else f'{mm}mm'


def _extract_bracelet_info_from_desc(desc: str, is_bangle: bool = False) -> dict:
    """
    Intelligently extract bracelet size and width from Silverbene HTML description.

    Handles every spec pattern Silverbene uses:
      • "Bracelet Length: 16+3cm Adjustable"  → Adjustable 6.5"–7.5"
      • "Chain Length: 16+2cm Adjustable"     → Adjustable 6.5"–7"
      • "Available Lengths: 16.5cm, 18cm, …"  → [6.5", 7", …]
      • "Wrist Size: 17cm"                    → [6.5"]
      • "Bracelet Length: Adjustable"         → ["Adjustable"]
      • "Bracelet Type: Adjustable Sliding …" → ["Adjustable"]
      • "Closure: … Extension Chain …"        → ["Adjustable"]
      • "Bangle Diameter: 60mm"               → inner_diameter="60mm" (never a
        wrist-length chip — see rationale below)
      • "Bangle Size: Open Size/Adjustable"   → ["Adjustable"] (cuff — flexes open)
      • Width: "Bracelet Width: 3mm", "Width: 3.7mm", "Chain Width: 3mm"

    Returns {"sizes": [...], "width": "Xmm", "inner_diameter": "Xmm"|None}.
    sizes == [] means no wrist-length data found. A rigid bangle's diameter is a
    fundamentally different measurement from a bracelet's wrist length (across
    the inside of a rigid band vs. around the wrist) — converting it to a
    derived "Bracelet Length" circumference misrepresents the product, so it's
    surfaced separately as inner_diameter and never mixed into sizes.
    """
    text = re.sub(r'<[^>]+>', ' ', desc)  # strip HTML tags for plain-text matching

    # "adjustable" phrased loosely, with no dimension attached — cuffs and
    # sliding-clasp bracelets are described this way ("Open Size/Adjustable",
    # "One Size", "Free Size") rather than a plain "Adjustable" label.
    def _is_adjustable_no_dim(val: str) -> bool:
        vl = re.sub(r'\s+', ' ', val).strip().lower()
        return bool(re.match(
            r'^(adjustable|one size(\s*/\s*adjustable)?|open size(\s*/\s*adjustable)?|free size|all size)$',
            vl
        ))

    # ── 0. Rigid bangle diameter (highest confidence, distinct math) ─────────
    # A bangle doesn't stretch — its diameter is measured across the inside of
    # the rigid band. Surfaced as its own inner_diameter spec, never converted
    # into a "Bracelet Length" wrist-circumference chip (see docstring).
    m = re.search(r'[Bb]angle\s+[Dd]iameter[:\s]+([^<\n]{2,40})', desc, re.I)
    if m:
        val = m.group(1).strip()
        if _is_adjustable_no_dim(val):
            return {"sizes": ["Adjustable"], "width": _extract_bracelet_width(text), "inner_diameter": None}
        dia_mm = _raw_mm_text(val)
        if dia_mm:
            return {"sizes": [], "width": _extract_bracelet_width(text), "inner_diameter": dia_mm}

    m = re.search(r'[Bb]angle\s+[Ss]ize[:\s]+([^<\n]{2,40})', desc, re.I)
    if m:
        val = m.group(1).strip()
        if _is_adjustable_no_dim(val):
            return {"sizes": ["Adjustable"], "width": _extract_bracelet_width(text), "inner_diameter": None}
        dia_mm = _raw_mm_text(val)
        if dia_mm:
            return {"sizes": [], "width": _extract_bracelet_width(text), "inner_diameter": dia_mm}

    # "Adjustable Size: Approximately 60mm" — ambiguous label Silverbene uses
    # for both stretchy chains (a real wrist-range value) and rigid bangles (an
    # inner diameter too small to be a wrist circumference). A real wrist-range
    # value (>= bracelet range) is trusted directly. Below that range: when this
    # product's title/description says "bangle" elsewhere, treat it as an inner
    # diameter (its own spec, not a derived length); otherwise fall back to the
    # old circumference conversion for genuinely adjustable non-bangle cuffs.
    m = re.search(r'[Aa]djustable\s+[Ss]ize[:\s]+([^<\n]{2,60})', desc, re.I)
    if m:
        val = m.group(1).strip()
        if _is_adjustable_no_dim(val):
            return {"sizes": ["Adjustable"], "width": _extract_bracelet_width(text), "inner_diameter": None}
        chips = parse_bracelet_size(val)
        if chips:
            return {"sizes": chips, "width": _extract_bracelet_width(text), "inner_diameter": None}
        if is_bangle:
            dia_mm = _raw_mm_text(val)
            if dia_mm:
                return {"sizes": [], "width": _extract_bracelet_width(text), "inner_diameter": dia_mm}
        chips = parse_bracelet_size(val + " inner diameter")
        if chips:
            return {"sizes": chips, "width": _extract_bracelet_width(text), "inner_diameter": None}

    # ── 1. Explicit length fields (highest confidence) ────────────────────────
    LENGTH_KEYS = (
        r'[Bb]racelet\s+[Ll]ength',
        r'[Bb]racelet\s+[Ss]ize',
        r'[Cc]hain\s+[Ll]ength',
        r'[Ww]rist\s+[Ss]ize',
    )
    for key_pat in LENGTH_KEYS:
        m = re.search(key_pat + r'[:\s]+([^<\n]{3,80})', desc, re.I)
        if not m:
            continue
        val = m.group(1).strip()

        # "Adjustable" with no dimension → plain label
        if _is_adjustable_no_dim(val):
            return {"sizes": ["Adjustable"], "width": _extract_bracelet_width(text)}

        # Has a cm/mm dimension → parse to inch chips
        chips = parse_bracelet_size(val)
        if chips:
            return {"sizes": chips, "width": _extract_bracelet_width(text)}

        # e.g. "14 inch" — explicitly in inches already, trust it only if bracelet-range
        inch_m = re.match(r'(\d+(?:\.\d+)?)\s*(?:inch|")', val, re.I)
        if inch_m:
            v = float(inch_m.group(1))
            if 5 <= v <= 10:
                chip = f'{int(v)}"' if v == int(v) else f'{v}"'
                return {"sizes": [chip], "width": _extract_bracelet_width(text)}

    # ── 2. "Available Lengths: X, Y, Z" CSV ──────────────────────────────────
    av_m = re.search(r'[Aa]vailable\s+[Ll]engths?[:\s]+([^<\n]{5,120})', desc)
    if av_m:
        chips, seen = [], set()
        for v, u in re.findall(r'(\d+(?:\.\d+)?)\s*(cm|mm)', av_m.group(1), re.I):
            for c in parse_bracelet_size(v + u):
                if c not in seen:
                    seen.add(c); chips.append(c)
        if chips:
            return {"sizes": chips, "width": _extract_bracelet_width(text)}

    # ── 3. Adjustable by type or closure (no exact dimension) ────────────────
    _ADJ_PATTERNS = [
        r'[Bb]racelet\s+[Tt]ype[:\s]+[^<\n]*[Aa]djustable',
        r'[Cc]losure[:\s]+[^<\n]*(?:[Ee]xtension\s+[Cc]hain|[Aa]djustable\s+[Ff]it)',
        r'[Cc]lasp[:\s]+[^<\n]*[Aa]djustable',
    ]
    for pat in _ADJ_PATTERNS:
        if re.search(pat, desc, re.I):
            return {"sizes": ["Adjustable"], "width": _extract_bracelet_width(text)}

    # ── 4. Plain "Length: Xcm" fallback ──────────────────────────────────────
    # Tolerate a leading "Approx."/"Approximately" hedge word before the number
    # (e.g. "Length: Approx. 16cm + 3cm Extension") — without this, the digit
    # requirement right after "Length:" fails to match and the length is lost.
    m = re.search(r'\bLength[:\s]+(?:[Aa]pprox(?:imately)?\.?\s*)?(\d{2,3}\s*(?:mm|cm)[^<\n]{0,40})', desc, re.I)
    if m:
        chips = parse_bracelet_size(m.group(1))
        if chips:
            return {"sizes": chips, "width": _extract_bracelet_width(text)}

    return {"sizes": [], "width": _extract_bracelet_width(text)}


def _extract_bracelet_width(text: str) -> str | None:
    """
    Extract bracelet/chain width from plain text (HTML tags already stripped).
    Handles: "Bracelet Width: 3mm", "Width: 3.7mm", "Chain Width: 3mm",
             "Width Available: 2.2mm, 3.2mm"
    Returns the first width found as a clean string e.g. "3mm", or None.
    """
    WIDTH_KEYS = (
        r'[Bb]racelet\s+[Ww]idth',
        r'[Cc]hain\s+[Ww]idth',
        r'[Ww]idth\s+[Aa]vailable',
        r'(?<!\w)[Ww]idth',   # standalone "Width:" — only if not part of another word
    )
    for key_pat in WIDTH_KEYS:
        m = re.search(key_pat + r'[:\s]+([^<\n]{2,40})', text, re.I)
        if not m:
            continue
        w_m = re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm)', m.group(1), re.I)
        if w_m:
            val = float(w_m.group(1))
            unit = w_m.group(2).lower()
            # Convert cm to mm for display consistency
            if unit == "cm":
                val = round(val * 10, 1)
                unit = "mm"
            display = f"{int(val)}mm" if val == int(val) else f"{val}mm"
            return display
    return None


# Hong Kong → US ring size lookup table.
# Source: Chow Sang Sang's official HK ring-size guide
# (cdn.chowsangsang.com/hkeshop/images/web/Ring_Size_Eng.pdf), one of Hong Kong's
# largest jewelers — cross-checked against Wills Jewellery and Diamond Collection
# HK's published charts, which agree closely (e.g. all three put HK14 at US 6.25-6.5).
# The previous table here was off by roughly a full US size across the board
# (e.g. it mapped HK14 -> US7.5 instead of the correct US6.5).
# Sizes 1-4 are below Chow Sang Sang's published range (they start at 5) and are
# extrapolated from the same diameter progression + the mm-to-US formula used
# elsewhere in this file — noted as approximate; adult rings rarely go this low.
_HK_TO_US = {
    1:1, 2:1.5, 3:2, 4:2.5,
    5:2.75, 6:3, 7:3.5, 8:3.75, 9:4.25, 10:4.75,
    11:5.25, 12:5.5, 13:6, 14:6.5, 15:7,
    16:7.5, 17:7.75, 18:8.25, 19:8.75, 20:9,
    21:9.5, 22:10, 23:10.25, 24:10.75, 25:11.25,
}

def _hk_to_us(n: int) -> str:
    us = _HK_TO_US.get(n)
    if us is None:
        return str(n)
    return str(int(us)) if us == int(us) else str(us)

def _convert_ring_size_to_us(val: str) -> str:
    """
    Convert ring size specs containing HK / Hong Kong / Asian sizes to US equivalents.
    Examples:
      "Hong Kong Size 13-15"     → "US 6 - 7"
      "HK Size 12"               → "US 5.5"
      "Asian Size 13"            → "US 6"
      "US 7"                     → "US 7"      (already US, leave as-is)
      "Inner Diameter 17.5mm"    → "US 7"      (explicit mm measurement, not HK size 17)
    """
    v = val.strip()
    # Already a US size — return as-is
    if re.match(r'^US\s*[\d.]+', v, re.I):
        return v
    # An explicit mm/cm diameter is unambiguous — prefer it over any bare number
    # in the same text. "Inner Diameter 17.5mm" is a measurement, not HK size 17;
    # a phrase like "Approximately 14/16.9mm" pairs a matching HK number with its
    # own diameter, so either interpretation agrees there anyway.
    parsed_mm = _parse_ring_diameter_mm(v)
    if parsed_mm:
        lo_mm, hi_mm = parsed_mm
        lo_us, hi_us = _mm_to_us_ring(lo_mm), _mm_to_us_ring(hi_mm)
        return f"US {lo_us}" if lo_us == hi_us else f"US {lo_us} - {hi_us}"
    # Extract numeric range or single number — whole numbers only. HK sizes are
    # always whole per the official Chow Sang Sang chart, so a decimal like the
    # "16.5" in "13 to 16.5" is never a valid HK size; excluding it here avoids
    # splitting it into spurious extra matches ("16" and "5") that corrupt the range.
    nums = [int(n) for n in re.findall(r'(?<![.\d])(\d{1,2})(?!\.\d)\b', v) if 1 <= int(n) <= 25]
    if not nums:
        return v  # nothing parseable — keep original
    lo, hi = min(nums), max(nums)
    lo_us = _hk_to_us(lo)
    if lo == hi:
        return f"US {lo_us}"
    hi_us = _hk_to_us(hi)
    return f"US {lo_us} - {hi_us}"


def _apply_spec_conversion(spec_key: str, val: str, category: str = "") -> str:
    """
    Apply US jewelry unit conventions to a raw spec value.
    Chain/drop lengths → inches.  Sizes/weights → keep native units, clean whitespace.
    """
    # Chain-type lengths: convert mm or cm → inches
    if spec_key in ('chain_length', 'drop_length', 'bangle_diameter'):
        # Bracelets and Anklets: ankle circumference is bracelet-scale
        # (roughly 200-280mm), not necklace-scale — parse_necklace_length()'s
        # snap table has no entry below 350mm, so anklet values were silently
        # flooring to the same wrong "14 inch" regardless of their real length.
        if category in ("Bracelets", "Anklets") or spec_key == "chain_length" and re.search(r'bracelet|wrist', val, re.I):
            chips = parse_bracelet_size(val)
            if chips:
                return chips[0] if len(chips) == 1 else " / ".join(chips)
        chips = parse_necklace_length(val)
        if chips:
            return chips[0] if len(chips) == 1 else " / ".join(chips)
        # Fallback: direct cm→in or mm→in
        m = re.search(r'([\d.]+)\s*cm', val, re.I)
        if m:
            return f'{round(float(m.group(1)) / 2.54, 1)}"'
        m = re.search(r'([\d.]+)\s*mm', val, re.I)
        if m:
            return f'{round(float(m.group(1)) / 25.4, 1)}"'
        return val

    # Weight: clean spacing ("3 g" → "3g")
    if spec_key == 'weight':
        return re.sub(r'\s*(g)\b', r'\1', val, flags=re.I)

    # Ring size range: convert Hong Kong / Asian sizes to US
    if spec_key == 'ring_size_range':
        return _convert_ring_size_to_us(val)

    # Sizes, widths, stone dimensions — keep mm but normalise spacing
    return re.sub(r'\s+', ' ', val).strip()


def collection_name_log(name: str) -> str:
    return f"[{name}]"
