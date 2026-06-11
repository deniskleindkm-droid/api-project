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
COLOR_ATTRIBUTE_NAMES = {"color", "colour", "metal color", "metal finish", "finish"}


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

    def get_by_sku(self, sku: str) -> Optional[dict]:
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
                return self._to_standard(items[0])
        return None

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
                             option_id: str = None, qty: int = 1) -> list:
        """
        Get available shipping methods for a country + product.
        Silverbene requires POST JSON with products array to return methods.
        Returns list of dicts with: way, title, price, carrier_code, method_code.
        """
        payload = {
            "country_id": country_code,
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
        """
        use_option = option_id or product_id
        methods = self.get_shipping_methods(
            address.get("country_code", "US"),
            option_id=use_option,
            qty=quantity
        )
        if not methods:
            print(f"[Silverbene] No shipping methods returned for option_id={use_option} — cannot place order")
            return self.standard_order(success=False, supplier_order_id="", reason="No shipping methods available")
        carrier_code = methods[0].get("carrier_code", "")
        method_code = methods[0].get("method_code", "")

        order_option_id = option_id or product_id

        payload = {
            "products": [{"option_id": str(order_option_id), "qty": quantity}],
            "shipping_address": {
                "firstname":   customer.get("first_name", ""),
                "lastname":    customer.get("last_name", ""),
                "email":       customer.get("email", ""),
                "telephone":   customer.get("phone", ""),
                "street":      address.get("line1", ""),
                "city":        address.get("city", ""),
                "region":      address.get("state", ""),
                "region_code": address.get("state_code", None),
                "region_id":   address.get("region_id", None),
                "postcode":    address.get("postal_code", ""),
                "country_id":  address.get("country_code", "US"),
            },
            "shipping_method": carrier_code,
        }

        result = self._post(ENDPOINT_CREATE_ORDER, payload)
        order_id = result.get("data", {}).get("order_id", "") if result.get("code") == 0 else ""

        return self.standard_order(
            success=bool(order_id),
            supplier_order_id=str(order_id),
            reason=result.get("message", ""),
        )

    def get_tracking(self, order_id: str) -> dict:
        """Tracking — endpoint to be added when Silverbene shares it."""
        return self.standard_tracking(order_id=order_id, status="unknown")

    # ── DATA NORMALISATION ────────────────────────────────────────────────────

    def _to_standard(self, raw: dict) -> dict:
        """
        Convert a live Silverbene product into Mikisi's standard format.
        Field names confirmed from live API response.
        """
        gallery = raw.get("gallery", [])
        image_url = gallery[0] if gallery else ""

        # Options contain price, stock, and attributes (Color / Size)
        options = raw.get("option", [])
        cost_price = float(options[0].get("price", 0)) if options else 0.0
        stock = sum(int(o.get("qty", 0)) for o in options) if options else 999

        sizes, colors = self._extract_variants(options)
        if not sizes:
            sizes = _parse_chain_length_from_desc(raw.get("desc", "")) or None
        material = self._infer_material_from_desc(raw.get("desc", ""), colors)

        return {
            **self.standard_product(
                supplier_product_id=raw.get("sku", ""),
                name=raw.get("title", ""),
                category="",
                description=raw.get("desc", ""),
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
            # Scoring helpers
            "supplier_rating": 5.0,
            "material_name_en_set": [material] if material else [],
            "extra_text": f"{raw.get('title', '')} {raw.get('desc', '')} {material}",
            "product_image_set_count": len(gallery),
            # Keep raw options so bulk import can extract option_ids
            "_options": options,
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

                if name in ("chain length", "length") and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    for chip in parse_necklace_length(value):
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name == "size" and re.search(r'\d+\s*(mm|cm)', value, re.I):
                    # Size attribute with a length value (e.g. "45cm", "450mm")
                    for chip in parse_necklace_length(value):
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in COLOR_ATTRIBUTE_NAMES and re.search(r'\d+\s*cm', value, re.I):
                    # Length hidden in Color attribute (e.g. "1.0mm, 40cm")
                    for chip in parse_necklace_length(value):
                        if chip not in seen_sizes:
                            seen_sizes.add(chip)
                            sizes.append(chip)
                elif name in SIZE_ATTRIBUTE_NAMES:
                    value = " ".join(value.split())
                    if value not in seen_sizes:
                        seen_sizes.add(value)
                        sizes.append(value)
                elif name in COLOR_ATTRIBUTE_NAMES:
                    display = _clean_color_value(value)
                    if display and display not in seen_colors:
                        seen_colors.add(display)
                        colors.append(display)

        return sizes or None, colors or None

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


MM_TO_INCHES = {
    350: '14"', 380: '15"', 400: '16"', 410: '16"',
    420: '16.5"', 450: '18"', 460: '18"', 480: '19"',
    500: '20"', 550: '22"', 600: '24"', 650: '26"',
    700: '28"', 750: '30"',
}


def parse_necklace_length(chain_length_str: str) -> list:
    """
    Convert a Silverbene chain length string into display chips.

    Handles mm and cm inputs:
      "400mm - 450mm Adjustable" -> ["400mm / 16\"", "450mm / 18\"", "Adjustable"]
      "45cm"                     -> ["450mm / 18\""]
      "1.0mm, 40cm"              -> ["400mm / 16\""]
      "40cm - 50cm"              -> ["400mm / 16\"", "450mm / 18\"", "500mm / 20\""]

    For ranges, every standard length between lo and hi is included.
    """
    s = chain_length_str.strip()
    is_adjustable = "adjustable" in s.lower()

    # Normalise: convert any cm values to mm before extracting numbers
    def _cm_to_mm(match):
        val = float(match.group(1))
        return str(int(round(val * 10))) + "mm"

    s_mm = re.sub(r'(\d+(?:\.\d+)?)\s*cm', _cm_to_mm, s, flags=re.I)

    nums = [int(m) for m in re.findall(r'\d+', s_mm) if 200 <= int(m) <= 1000]
    if not nums:
        return []

    if len(nums) >= 2:
        lo, hi = min(nums), max(nums)
        mm_values = sorted(k for k in MM_TO_INCHES if lo <= k <= hi)
        if not mm_values:
            mm_values = sorted({lo, hi})
    else:
        mm_values = [nums[0]]

    chips = []
    seen = set()
    for mm in mm_values:
        if mm in MM_TO_INCHES:
            chip = f'{mm}mm / {MM_TO_INCHES[mm]}'
        else:
            chip = f'{mm}mm / {round(mm / 25.4, 1)}"'
        if chip not in seen:
            seen.add(chip)
            chips.append(chip)

    if is_adjustable:
        chips.append("Adjustable")

    return chips


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


def collection_name_log(name: str) -> str:
    return f"[{name}]"
