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
COLOR_ATTRIBUTE_NAMES = {"color", "colour", "metal color", "metal finish", "finish", "main stone", "stone", "stone color", "stone type", "birthstone"}


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
        # Normalize finish terms using Silverbene's customer-facing description language.
        # Silverbene API option attributes use "Rhodium" internally but their product pages
        # say "White Gold Color" — prefer the customer-facing term from desc.
        if colors:
            colors = self._normalize_finish_terms(colors, raw.get("description", "") or raw.get("desc", ""))
        # Chain length is always in the raw desc material-info section ("Chain Length: 45cm").
        # Always parse it and merge — don't skip just because variants already have sizes.
        desc_lengths = _parse_chain_length_from_desc(raw.get("description", "") or raw.get("desc", ""))
        if desc_lengths:
            if sizes:
                for l in desc_lengths:
                    if l not in sizes:
                        sizes.append(l)
            else:
                sizes = desc_lengths
        material = self._infer_material_from_desc(raw.get("description", "") or raw.get("desc", ""), colors)
        specs = self._extract_specs_from_desc(raw.get("description", "") or raw.get("desc", ""))

        return {
            **self.standard_product(
                supplier_product_id=raw.get("sku", ""),
                name=raw.get("title", ""),
                category="",
                description=raw.get("description", "") or raw.get("desc", ""),
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

    def _extract_specs_from_desc(self, desc: str) -> dict:  # noqa: C901
        """
        Parse all product specs from Silverbene's raw HTML <li> items.
        Must be called BEFORE description is rewritten — raw tags only exist at import time.
        Returns only fields with real data; never inserts placeholder values.
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
            'total weight': 'weight',
            'weight': 'weight',
            'bracelet total weight': 'weight',
            'anklet total weight': 'weight',
            'metal electroplating': 'plating',
            'earring size': 'earring_size',
            'main stone': 'stone',
            'accent stone': 'accent_stone',
            'main stone quantity': 'stone_qty',
            'stone quantity': 'stone_qty',
            'main stone size': 'stone_size',
            'stone size': 'stone_size',
            'accent stone size': 'accent_stone_size',
            'accent ston size': 'accent_stone_size',
            'main stone weight': 'stone_weight',
            'earring backs': 'earring_backs',
            'chain length': 'chain_length',
            'bracelet chain length': 'chain_length',
            'anklet chain length': 'chain_length',
            'single layer chain length': 'chain_length',
            'necklace a chain length': 'chain_length',
            'pendant size': 'pendant_size',
            'bead size': 'bead_size',
            'pearl size': 'pearl_size',
            'hoop size': 'hoop_size',
            'pin size': 'pin_size',
            'pin thickness': 'pin_size',
            'chain width': 'chain_width',
            'bangle width': 'width',
            'band width': 'width',
            'ring width': 'width',
            'width': 'width',
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
            'drop length': 'drop_length',
            'setting type': 'setting',
            'setting': 'setting',
            'closure': 'closure',
            'finish': 'finish',
            'surface': 'finish',
            'special craftsmanship': 'craftsmanship',
            'purity': 'purity',
            'size': 'size',
        }

        # Keys that are not useful product details for the customer
        SKIP_KEYS = {
            'metal material', 'metal color available', 'item type', 'gender',
            'occasion', 'style', 'feature', 'brand', 'new', 'color',
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

            val = _apply_spec_conversion(spec_key, val)
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

def parse_necklace_length(chain_length_str: str) -> list:
    """
    Convert a Silverbene chain length string into customer-facing inch chips.

    Inputs handled:
      "40cm+5cm"             -> ['Adjustable 16"-18"']   extender: both ends snap to standard
      "40cm+5cm adjustable"  -> ['Adjustable 16"-18"']
      "400mm - 450mm Adj."   -> ['Adjustable 16"-18"']   two-value adjustable range
      "45cm"                 -> ['18"']                   single fixed length
      "40cm - 60cm"          -> ['16"', '18"', '20"', '22"', '24"']  multi-length range
      "400mm"                -> ['16"']
    """
    s = chain_length_str.strip()
    is_adj = bool(re.search(r'adjustabl|extender|extension', s, re.I))

    # Extender pattern: "40cm+5cm" or "40+5cm" (Silverbene omits unit on base)
    ext_m = re.match(r'(\d+(?:\.\d+)?)\s*(cm|mm)?\s*\+\s*(\d+(?:\.\d+)?)\s*(cm|mm)', s, re.I)
    if ext_m:
        ext_unit = ext_m.group(4).lower()  # unit on the extension is authoritative
        base_unit = (ext_m.group(2) or ext_unit).lower()
        b_mm = int(round(float(ext_m.group(1)) * 10)) if base_unit == 'cm' else int(float(ext_m.group(1)))
        e_mm = int(round(float(ext_m.group(3)) * 10)) if ext_unit == 'cm' else int(float(ext_m.group(3)))
        lo, hi = _snap_inch(b_mm), _snap_inch(b_mm + e_mm)
        if lo == hi:
            return [lo]
        return [f'Adjustable {lo}-{hi}']

    # Normalise cm → mm
    def _to_mm(m): return str(int(round(float(m.group(1)) * 10))) + 'mm'
    s_mm = re.sub(r'(\d+(?:\.\d+)?)\s*cm', _to_mm, s, flags=re.I)

    nums = [int(n) for n in re.findall(r'\d+', s_mm) if 200 <= int(n) <= 900]
    if not nums:
        return []

    if len(nums) == 1:
        c = _snap_inch(nums[0])
        return [f'Adjustable {c}'] if is_adj else [c]

    lo_mm, hi_mm = min(nums), max(nums)

    # Two-value adjustable range: "400mm - 450mm Adjustable" → 'Adjustable 16"-18"'
    if is_adj and len(nums) == 2:
        lo_in, hi_in = _snap_inch(lo_mm), _snap_inch(hi_mm)
        if lo_in == hi_in:
            return [lo_in]
        return [f'Adjustable {lo_in}-{hi_in}']

    # Multi-length range: enumerate every standard length between lo and hi
    chips, seen = [], set()
    for mm in _STD_MM:
        if lo_mm <= mm <= hi_mm:
            c = MM_TO_INCHES[mm]
            if c not in seen:
                seen.add(c); chips.append(c)
    return chips or list(dict.fromkeys(_snap_inch(n) for n in nums))


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


def _apply_spec_conversion(spec_key: str, val: str) -> str:
    """
    Apply US jewelry unit conventions to a raw spec value.
    Chain/drop lengths → inches.  Sizes/weights → keep native units, clean whitespace.
    """
    # Chain-type lengths: convert mm or cm → inches using standard snap
    if spec_key in ('chain_length', 'drop_length', 'bangle_diameter'):
        chips = parse_necklace_length(val)
        if chips:
            return chips[0]
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
