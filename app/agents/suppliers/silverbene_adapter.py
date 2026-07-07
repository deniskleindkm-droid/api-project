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
    "Bracelets": ["bracelet", "chain bracelet", "link bracelet", "tennis bracelet"],
    "Earrings":  ["earring", "stud earring", "drop earring"],
    "Anklets":   ["anklet"],
    "Ear Cuffs": ["ear cuff", "cartilage earring", "no piercing ear"],
}

# Values Silverbene puts in the Color attribute that are actually product-type descriptors.
# Strip these prefixes before storing as a display color.
_CATEGORY_PREFIXES = {"anklet", "bracelet", "necklace", "ring", "earring", "pendant", "chain"}

# Attribute names Silverbene uses per category type
SIZE_ATTRIBUTE_NAMES = {"size", "ring size", "length", "bracelet size", "anklet size", "chain length"}
BRACELET_SIZE_ATTR_NAMES = {"wrist size", "inner diameter", "bracelet size", "bracelet length"}
COLOR_ATTRIBUTE_NAMES = {"color", "colour", "metal color", "metal finish", "finish", "main stone", "stone", "stone color", "stone type", "birthstone"}
_METAL_ATTR_NAMES = {"color", "colour", "metal color", "metal finish", "finish"}

# Maps Silverbene's internal/technical metal color names → customer-friendly display names.
# Only applied to metal-context attributes (not stone names like "Yellow Sapphire").
# "Rhodium" and "Pink" are the most common; others appear in compound variant names.
_METAL_COLOR_NORMALIZE = {
    "rhodium":           "Silver",
    "pink":              "Rose Gold",
    "yellow":            "Yellow Gold",
    "white":             "White Gold",
    "18k gold":          "Gold",
    "18k rose gold":     "Rose Gold",
    "18k white gold":    "White Gold",
    "18k yellow gold":   "Yellow Gold",
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


def _normalize_color_final(value: str, attr_name: str = "color") -> str:
    """
    Convert technical Silverbene color names to customer-friendly display names.
    Called as a final pass after _clean_color_value and _normalize_finish_terms.
    Only normalizes metal-context attributes — stone colors (Yellow Sapphire, etc.)
    are left as-is.
    """
    if not value:
        return value
    # Strip technical suffixes: "White Gold Color" → "White Gold", "Gold Plated" → "Gold"
    cleaned = re.sub(r'\s+(color|plating|plated)\s*$', '', value, flags=re.I).strip()
    v_lower = cleaned.lower()
    if attr_name.lower() in _METAL_ATTR_NAMES:
        normalized = _METAL_COLOR_NORMALIZE.get(v_lower)
        if normalized:
            return normalized
    # Rhodium is never a gemstone name — normalize regardless of attribute type
    if v_lower == "rhodium":
        return "Silver"
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

    def search(self, keyword: str, limit: int = 20) -> list:
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
                    result.append(self._to_standard(item))
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
            products = self.search(keyword=kw, limit=per_keyword)
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

        sizes, colors = self._extract_variants(options)
        # Step 1: desc-based upgrade — replaces "Rhodium" with "White Gold" when the
        # product description explicitly uses that term (e.g. "Metal Color: White Gold Color").
        if colors:
            colors = self._normalize_finish_terms(colors, raw.get("description", "") or raw.get("desc", ""))
        # Step 2: final friendly-name normalization for anything still technical
        # ("Rhodium" → "Silver", "Pink" → "Rose Gold", strip " Color"/" Plated" suffixes).
        if colors:
            colors = [_normalize_color_final(c) for c in colors]

        # Step 3: sync the same canonical names back into the stored variant attributes
        # so p.variants and p.colors always agree on color names.
        # Mirror exactly the filtering _extract_variants applies (skip length-valued color
        # attrs) so the zip index stays aligned with the colors list.
        if colors:
            raw_cleaned_colors: list[str] = []
            seen_rc: set[str] = set()
            for opt in options:
                for attr in opt.get("attribute", []):
                    aname = attr.get("name", "").lower().strip()
                    aval  = attr.get("value", "").strip()
                    if aname not in COLOR_ATTRIBUTE_NAMES:
                        continue
                    if re.search(r'\d+\s*cm', aval, re.I):
                        continue  # length disguised as color — _extract_variants put it in sizes
                    rc = _clean_color_value(aval).strip()
                    if rc and rc not in seen_rc:
                        seen_rc.add(rc)
                        raw_cleaned_colors.append(rc)
            color_remap = {rc.lower(): cc for rc, cc in zip(raw_cleaned_colors, colors)}
            for opt in options:
                for attr in opt.get("attribute", []):
                    aname = attr.get("name", "").lower().strip()
                    aval  = attr.get("value", "").strip()
                    if aname not in COLOR_ATTRIBUTE_NAMES:
                        continue
                    if re.search(r'\d+\s*cm', aval, re.I):
                        continue  # leave length-in-color attrs untouched
                    rc = _clean_color_value(aval).strip()
                    # Prefer the remap (desc-aware); fall back to direct normalization
                    canonical = color_remap.get(rc.lower()) or _normalize_color_final(rc, aname)
                    if canonical:
                        attr["value"] = canonical
        # Chain length / bracelet info from the description spec section.
        # For bracelets, use the full intelligent extractor which also returns width.
        _raw_desc_for_len = raw.get("description", "") or raw.get("desc", "")
        _bracelet_width = None
        if category == "Bracelets":
            _binfo = _extract_bracelet_info_from_desc(_raw_desc_for_len)
            desc_lengths = _binfo["sizes"]
            _bracelet_width = _binfo.get("width")
        else:
            desc_lengths = _parse_chain_length_from_desc(_raw_desc_for_len)
        if desc_lengths:
            if sizes:
                for l in desc_lengths:
                    if l not in sizes:
                        sizes.append(l)
            else:
                sizes = desc_lengths
        raw_desc = raw.get("description", "") or raw.get("desc", "")
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
        pendant_only = _is_pendant_only(raw_desc)
        if pendant_only and sizes:
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

    def _extract_variants(self, options: list) -> tuple:  # noqa: C901
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

        for opt in options:
            attrs = opt.get("attribute", [])
            for attr in attrs:
                name = attr.get("name", "").lower().strip()
                value = attr.get("value", "").strip()
                if not value:
                    continue

                if name in BRACELET_SIZE_ATTR_NAMES and re.search(r'\d+', value, re.I):
                    # Bracelet-specific attrs (wrist size, inner diameter, etc.)
                    for chip in parse_bracelet_size(value):
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in ("chain length", "length") and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    # Try bracelet range first; fall through to necklace parser
                    chips = parse_bracelet_size(value) or parse_necklace_length(value)
                    for chip in chips:
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name == "size" and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    chips = parse_bracelet_size(value) or parse_necklace_length(value)
                    for chip in chips:
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in COLOR_ATTRIBUTE_NAMES and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    # Length hidden in Color attr (e.g. "16cm", "17+3", "160mm Bracelet",
                    # "Pink_16+3cm", "3mm wide, length: 16.5cm, weight:2g").
                    # Prefer explicit "length: X cm/mm" over the first dimension match,
                    # which may be a chain width (3mm) not the wrist size.
                    _len_m = re.search(r'\blength[:\s]+(\d+(?:\.\d+)?)\s*(cm|mm)', value, re.I)
                    if _len_m:
                        _dim_str = _len_m.group(1) + _len_m.group(2)
                    else:
                        _ext_m = re.search(
                            r'(\d+(?:\.\d+)?)\s*(cm|mm)?\s*\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)',
                            value, re.I
                        )
                        _sing_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', value, re.I)
                        if _ext_m:
                            _dim_str = _ext_m.group(0).strip()
                        elif _sing_m:
                            _dim_str = _sing_m.group(0).strip()
                        else:
                            _dim_str = value
                    chips = parse_bracelet_size(_dim_str) or parse_necklace_length(_dim_str)
                    for chip in chips:
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in SIZE_ATTRIBUTE_NAMES:
                    value = " ".join(value.split())
                    # Normalise any adjustable/open-ring variant to a single consistent label
                    _vl = value.lower()
                    if _vl in ('adjustable', 'one size', 'one size / adjustable',
                                'one size/adjustable', 'free size', 'all size',
                                'open ring', 'open size') or \
                       _vl.startswith('adjustable (') or \
                       re.match(r'^\d+\s*\(adjustable\)$', _vl):
                        value = 'Open Size / Adjustable'
                    if value not in seen_sizes:
                        seen_sizes.add(value)
                        sizes.append(value)
                elif name in COLOR_ATTRIBUTE_NAMES:
                    display = _clean_color_value(value)
                    if display and display not in seen_colors:
                        seen_colors.add(display)
                        colors.append(display)

        return sizes or None, colors or None

    def _normalize_finish_terms(self, colors: list, desc: str) -> list:
        """
        Silverbene's option attributes use technical names ('Rhodium') but their product
        descriptions use customer-facing names ('White Gold Color'). Read 'Metal Color
        Available' and 'Metal Electroplating' from the raw desc to prefer the term
        Silverbene actually shows to customers.
        """
        text = re.sub(r'<[^>]+>', ' ', desc)

        # Extract customer-facing finish list from desc
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

        if not desc_finishes:
            return colors  # no desc data — keep option attribute terms as-is

        # Check if desc says "White Gold" where we stored "Rhodium"
        desc_lower = ' '.join(f.lower() for f in desc_finishes)
        has_white_gold_in_desc = 'white gold' in desc_lower

        return [
            # Replace "Rhodium" with "White Gold" when desc explicitly uses "White Gold"
            re.sub(r'\bRhodium\b', 'White Gold', c) if has_white_gold_in_desc and re.search(r'\bRhodium\b', c) else c
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
            'post size': 'pin_size',
            'pin size': 'pin_size',
            'pin thickness': 'pin_size',
            'drop length': 'drop_length',
            'dangle length': 'drop_length',
            # Chain / bracelet / anklet lengths
            'chain length': 'chain_length',
            'bracelet chain length': 'chain_length',
            'anklet chain length': 'chain_length',
            'single layer chain length': 'chain_length',
            'necklace a chain length': 'chain_length',
            'bracelet length': 'chain_length',
            'anklet length': 'chain_length',
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
            'bead size': 'bead_size',
            'bead diameter': 'bead_size',
            'pearl size': 'pearl_size',
            'pearl diameter': 'pearl_size',
            # Ring
            'bangle size': 'bangle_size',
            'bangle diameter': 'bangle_diameter',
            'ring top size': 'ring_top',
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
            'bracelet type': 'bracelet_type',
            'chain style': 'chain_style',
            'purity': 'purity',
            'size': 'size',
        }

        # Keys that are not useful product details for the customer
        SKIP_KEYS = {
            'metal material', 'material', 'metal color available',
            'color available', 'item type', 'gender', 'occasion',
            'style', 'feature', 'brand', 'new', 'color', 'category',
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

            spec_key = FIELD_MAP.get(key)
            if not spec_key:
                continue  # only store known, mapped fields

            val = _apply_spec_conversion(spec_key, val, category=category)
            if spec_key not in specs:   # first value wins
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

    def attr_size(attrs):
        for a in attrs:
            aname = a.get("name", "").lower()
            if aname in ("size", "ring size", "bracelet size", "anklet size") \
               or aname in BRACELET_SIZE_ATTR_NAMES:
                v = a.get("value", "").strip()
                normalized = _normalize_size_for_match(v)
                if re.search(r'\d+\s*(mm|cm)', v, re.I):
                    # Try bracelet range first, then necklace
                    chips = parse_bracelet_size(v) or parse_necklace_length(v)
                    if chips:
                        normalized = chips[0]
                return normalized
            if aname in ("chain length", "length") and re.search(r'\d+\s*(mm|cm)', a.get("value", ""), re.I):
                v = a.get("value", "").strip()
                chips = parse_bracelet_size(v) or parse_necklace_length(v)
                if chips:
                    return chips[0]
        return None

    def attr_color(attrs):
        for a in attrs:
            if a.get("name", "").lower() in COLOR_ATTRIBUTE_NAMES:
                return _clean_color_value(a.get("value", "").strip())
        return None

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


def _snap_bracelet_inch(mm: float) -> str:
    """Snap mm to nearest 0.5-inch, return display string e.g. '7\"'."""
    inches = mm / 25.4
    snapped = round(inches * 2) / 2
    if snapped == int(snapped):
        return f'{int(snapped)}"'
    return f'{snapped}"'


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
    Falls back to the industry-standard open-ring range US 5–9.
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

    return "Adjustable · fits US 5–9"


def parse_bracelet_size(length_str: str) -> list:
    """
    Convert a Silverbene bracelet length/wrist-size string to US customer-facing inch chips.
    Handles cm and mm values in bracelet range (100–260mm / 10–26cm).
    Returns [] for values outside bracelet range so caller can try parse_necklace_length.

    Silverbene attribute names routed here: wrist size, inner diameter, bracelet size,
    bracelet length, and 'length'/'size'/'color' attrs whose value is in bracelet range.

    Examples:
      "17cm"       → ['6.5"']
      "18 cm"      → ['7"']
      "19Cm"       → ['7.5"']
      "17+3"       → ['Adjustable 6.5"–8"']
      "17cm+3cm"   → ['Adjustable 6.5"–8"']
      "16cm-20cm"  → ['6.5"', '7"', '7.5"', '8"']
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

    # "17+3" or "17cm+3cm" — chain + adjustor
    ext_m = re.match(
        r'^(\d+(?:\.\d+)?)\s*(cm|mm)?\s*\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)?$', s, re.I
    )
    if ext_m:
        b_unit = ext_m.group(2) or "cm"
        e_unit = ext_m.group(4) or b_unit
        b_mm = _to_mm(ext_m.group(1), b_unit)
        e_mm = _to_mm(ext_m.group(3), e_unit)
        if _BRACELET_RANGE_LO <= b_mm <= _BRACELET_RANGE_HI:
            lo = _snap_bracelet_inch(b_mm)
            hi = _snap_bracelet_inch(b_mm + e_mm)
            return [lo] if lo == hi else [f'Adjustable {lo}–{hi}']

    # "16cm-20cm" or "160mm-200mm" — range
    range_m = re.search(
        r'(\d+(?:\.\d+)?)\s*(cm|mm)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I
    )
    if range_m:
        lo_mm = _to_mm(range_m.group(1), range_m.group(2))
        hi_mm = _to_mm(range_m.group(3), range_m.group(4))
        if _BRACELET_RANGE_LO <= lo_mm <= _BRACELET_RANGE_HI:
            chips, seen = [], set()
            step = 5
            mm = lo_mm
            while mm <= hi_mm + step // 2:
                c = _snap_bracelet_inch(mm)
                if c not in seen:
                    seen.add(c)
                    chips.append(c)
                mm += step
            return chips

    # Inner diameter (bangle sizing) → wrist circumference
    if is_inner_diam:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
        if m:
            id_mm = _to_mm(m.group(1), m.group(2))
            circ_mm = _math.pi * id_mm
            if _BRACELET_RANGE_LO <= circ_mm <= _BRACELET_RANGE_HI:
                return [_snap_bracelet_inch(circ_mm)]
        return []

    # Single value: "17cm", "18 CM", "180mm", "17Cm"
    single_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
    if single_m:
        mm = _to_mm(single_m.group(1), single_m.group(2))
        if _BRACELET_RANGE_LO <= mm <= _BRACELET_RANGE_HI:
            return [_snap_bracelet_inch(mm)]

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
    """
    s = chain_length_str.strip()
    is_adj = bool(re.search(r'adjustabl|extender|extension', s, re.I))

    def _to_mm_val(val, unit):
        unit = unit.lower() if unit else ''
        return int(round(float(val) * 10)) if unit == 'cm' else int(float(val))

    # Pattern 1: "X(unit) + Y(unit)" — base + extender (use re.search not re.match)
    ext_m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm)?\s*\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
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
        c = _snap_inch(nums[0])
        return [f'Adjustable {c}–{c}'] if is_adj else [c]

    lo_mm, hi_mm = min(nums), max(nums)

    # Two-value adjustable range: "400mm - 450mm Adjustable"
    if is_adj and len(nums) == 2:
        lo_in, hi_in = _snap_inch(lo_mm), _snap_inch(hi_mm)
        if lo_in == hi_in:
            return [lo_in]
        return [f'Adjustable {lo_in}–{hi_in}']

    # Multi-length range: enumerate every standard length between lo and hi
    chips, seen = [], set()
    for mm in _STD_MM:
        if lo_mm <= mm <= hi_mm:
            c = MM_TO_INCHES[mm]
            if c not in seen:
                seen.add(c); chips.append(c)
    return chips or list(dict.fromkeys(_snap_inch(n) for n in nums))


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


def _clean_color_value(value: str) -> str:
    """
    Strip category-word prefixes Silverbene puts in Color attribute values.
    e.g. "Anklet Silver" → "Silver", "Anklet" → "" (discard), "Gold" → "Gold"
    """
    lower = value.lower()
    for prefix in _CATEGORY_PREFIXES:
        if lower == prefix:
            return ""
        if lower.startswith(prefix + " "):
            return value[len(prefix):].strip()
    return value


def _parse_chain_length_from_desc(desc: str) -> list:
    """
    Extract chain length from Silverbene HTML description.
    Looks for patterns like:
      <li>Chain Length: 400mm - 450mm Adjustable</li>
      <li>Length: 450mm</li>
    Returns parsed chips list, or empty list if nothing found.
    """
    m = re.search(r'[Cc]hain\s+[Ll]ength[:\s]+([^<\n]{3,60})', desc)
    if not m:
        m = re.search(r'\bLength[:\s]+(\d{3,4}\s*mm[^<\n]{0,40})', desc)
    if m:
        return parse_necklace_length(m.group(1))
    return []


def _parse_chain_length_from_desc_bracelet(desc: str) -> list:
    """Thin wrapper — delegates to _extract_bracelet_info_from_desc for backward compat."""
    return _extract_bracelet_info_from_desc(desc)["sizes"]


def _extract_bracelet_info_from_desc(desc: str) -> dict:
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
      • Width: "Bracelet Width: 3mm", "Width: 3.7mm", "Chain Width: 3mm"

    Returns {"sizes": [...], "width": "Xmm"}.
    sizes == [] means no data found.
    """
    text = re.sub(r'<[^>]+>', ' ', desc)  # strip HTML tags for plain-text matching

    # ── 1. Explicit length fields (highest confidence) ────────────────────────
    LENGTH_KEYS = (
        r'[Bb]racelet\s+[Ll]ength',
        r'[Cc]hain\s+[Ll]ength',
        r'[Ww]rist\s+[Ss]ize',
    )
    for key_pat in LENGTH_KEYS:
        m = re.search(key_pat + r'[:\s]+([^<\n]{3,80})', desc, re.I)
        if not m:
            continue
        val = m.group(1).strip()

        # "Adjustable" with no dimension → plain label
        if re.match(r'^[Aa]djustable\s*$', val.strip()):
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
    m = re.search(r'\bLength[:\s]+(\d{2,3}\s*(?:mm|cm)[^<\n]{0,40})', desc, re.I)
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


# Hong Kong → US ring size lookup table (standard international conversion)
_HK_TO_US = {
    1:1, 2:1.5, 3:2, 4:2.5, 5:3, 6:3.5, 7:4, 8:4.5, 9:5, 10:5.5,
    11:6, 12:6.5, 13:7, 14:7.5, 15:8, 16:8.5, 17:9, 18:9.5, 19:10,
    20:10.5, 21:11, 22:11.5, 23:12, 24:12.5, 25:13,
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
      "Hong Kong Size 13-15"  → "US 7 - 8"
      "HK Size 12"            → "US 6.5"
      "Asian Size 13"         → "US 7"
      "US 7"                  → "US 7"  (already US, leave as-is)
    """
    v = val.strip()
    # Already a US size — return as-is
    if re.match(r'^US\s*[\d.]+', v, re.I):
        return v
    # Extract numeric range or single number
    nums = [int(n) for n in re.findall(r'\b(\d{1,2})\b', v) if 1 <= int(n) <= 25]
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
        # Bracelets: use bracelet range parser first
        if category == "Bracelets" or spec_key == "chain_length" and re.search(r'bracelet|wrist', val, re.I):
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
