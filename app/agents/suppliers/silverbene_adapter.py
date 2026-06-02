from app.agents.suppliers.base import SupplierAdapter
from typing import Optional
import requests
import json
import os

SILVERBENE_BASE = "https://s.silverbene.com"

# ── ENDPOINT PATHS ────────────────────────────────────────────────────────────
# These will be confirmed and filled in once the API portal docs are shared.
# The adapter is fully wired — only these paths need updating.
ENDPOINT_PRODUCT_LIST  = "/api/product/list"     # GET/POST — returns paginated catalog
ENDPOINT_PRODUCT_STOCK = "/api/product/stock"    # GET/POST — returns stock for option_id
ENDPOINT_SHIPPING      = "/api/order/shipping"   # GET/POST — returns shipping methods
ENDPOINT_ORDER_CREATE  = "/api/order/create"     # POST — places a dropship order
ENDPOINT_ORDER_STATUS  = "/api/order/status"     # GET/POST — gets order status/tracking
# ─────────────────────────────────────────────────────────────────────────────

# Category keyword mapping for Mikisi's 7 collections
CATEGORY_KEYWORDS = {
    "Rings":        ["sterling silver ring", "925 silver ring", "gold ring women"],
    "Necklaces":    ["925 silver necklace", "gold necklace women", "sterling pendant necklace"],
    "Bracelets":    ["925 silver bracelet", "gold bracelet women", "sterling charm bracelet"],
    "Earrings":     ["925 silver earrings", "gold stud earrings", "drop earrings women"],
    "Anklets":      ["925 silver anklet", "gold anklet women", "sterling ankle bracelet"],
    "Ear Cuffs":    ["ear cuff no piercing", "925 silver ear cuff", "gold ear cuff women"],
    "Jewelry Sets": ["925 silver jewelry set", "necklace earring set", "matching jewelry set women"],
}

# Size label per category — mirrors the frontend CATEGORY_SIZE_LABEL
SIZE_LABEL = {
    "Rings":        "Ring Size",
    "Necklaces":    "Chain Length",
    "Bracelets":    "Bracelet Length",
    "Anklets":      "Anklet Length",
    "Earrings":     "Size",
    "Ear Cuffs":    "Size",
    "Jewelry Sets": "Size",
}


class SilverbeneAdapter(SupplierAdapter):
    """
    Silverbene adapter — primary supplier for Mikisi's jewelry store.
    Translates Silverbene's API into Mikisi's standard supplier interface.
    CJ Dropshipping is disabled; all imports run through this adapter.
    """

    def __init__(self):
        self.token = os.getenv("SILVERBENE_API_KEY", "")
        self.base = SILVERBENE_BASE
        self.session = requests.Session()
        self.session.headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _post(self, endpoint: str, payload: dict) -> dict:
        payload["token"] = self.token
        try:
            r = self.session.post(f"{self.base}{endpoint}", json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[Silverbene] POST {endpoint} error: {e}")
            return {}

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

    # ── CATALOG SEARCH ────────────────────────────────────────────────────────

    def search(self, keyword: str, limit: int = 20, page: int = 1) -> list:
        """
        Search Silverbene catalog by keyword.
        Returns list of products in Mikisi standard format.
        """
        data = self._post(ENDPOINT_PRODUCT_LIST, {
            "sku": keyword,
            "page": page,
            "page_size": limit,
        })

        items = data.get("data", data.get("items", data.get("products", [])))
        if not isinstance(items, list):
            print(f"[Silverbene] search: unexpected response shape — {list(data.keys())}")
            return []

        return [self._to_standard(p) for p in items]

    def search_by_category(self, category_name: str, limit: int = 50, page: int = 1) -> list:
        """
        Search all keywords for a given Mikisi collection category.
        Returns deduplicated list of products.
        """
        keywords = CATEGORY_KEYWORDS.get(category_name, [category_name.lower()])
        seen_skus = set()
        results = []

        for kw in keywords:
            products = self.search(keyword=kw, limit=limit // len(keywords) + 5, page=page)
            for p in products:
                sku = p.get("supplier_product_id", "")
                if sku and sku not in seen_skus:
                    seen_skus.add(sku)
                    results.append(p)

        return results[:limit]

    # ── PRODUCT DETAIL ────────────────────────────────────────────────────────

    def get_product(self, product_id: str) -> Optional[dict]:
        """
        Get full product details by SKU/product_id.
        Returns product in Mikisi standard format.
        """
        data = self._post(ENDPOINT_PRODUCT_LIST, {"sku": product_id, "page": 1, "page_size": 1})
        items = data.get("data", data.get("items", data.get("products", [])))
        if items:
            return self._to_standard(items[0])
        return None

    def get_stock(self, option_id: str) -> int:
        """Get current stock for a specific product option/variant."""
        data = self._post(ENDPOINT_PRODUCT_STOCK, {"option_id": option_id})
        return int(data.get("qty", data.get("stock", data.get("quantity", 999))))

    # ── ORDERS ────────────────────────────────────────────────────────────────

    def place_order(self, product_id: str, customer: dict, address: dict, quantity: int = 1) -> dict:
        """Place a dropship order with Silverbene."""
        shipping_methods = self._post(ENDPOINT_SHIPPING, {
            "country_id": address.get("country_code", "US")
        })
        methods = shipping_methods.get("data", shipping_methods.get("methods", []))
        carrier_code = methods[0].get("carrier_code", "") if methods else ""
        method_code = methods[0].get("method_code", "") if methods else ""

        result = self._post(ENDPOINT_ORDER_CREATE, {
            "options": [{"sku": product_id, "qty": quantity}],
            "shipping_address": {
                "firstname":  customer.get("first_name", ""),
                "lastname":   customer.get("last_name", ""),
                "email":      customer.get("email", ""),
                "telephone":  customer.get("phone", ""),
                "street":     [address.get("line1", ""), address.get("line2", "")],
                "city":       address.get("city", ""),
                "region":     address.get("state", ""),
                "postcode":   address.get("postal_code", ""),
                "country_id": address.get("country_code", "US"),
            },
            "shipping_carrier_code": carrier_code,
            "shipping_method_code":  method_code,
        })

        order_id = result.get("order_id", result.get("increment_id", ""))
        return self.standard_order(
            success=bool(order_id),
            supplier_order_id=str(order_id),
            reason=result.get("message", ""),
        )

    def get_tracking(self, order_id: str) -> dict:
        """Get tracking status for a placed order."""
        data = self._post(ENDPOINT_ORDER_STATUS, {"order_id": order_id})
        return self.standard_tracking(
            order_id=order_id,
            status=data.get("status", "unknown"),
            tracking_number=data.get("tracking_number", data.get("track_number", "")),
            carrier=data.get("carrier", data.get("shipping_carrier", "")),
            estimated_delivery=data.get("estimated_delivery", ""),
            last_update=data.get("updated_at", ""),
        )

    # ── DATA NORMALISATION ────────────────────────────────────────────────────

    def _to_standard(self, raw: dict) -> dict:
        """
        Convert a raw Silverbene product dict into Mikisi's standard format.
        Field names will be confirmed once API docs are shared.
        """
        # Primary image — Silverbene typically sends a list or a single URL
        images_raw = raw.get("images", raw.get("media_gallery_entries", []))
        if isinstance(images_raw, list):
            image_list = [
                img.get("url", img.get("file", img)) if isinstance(img, dict) else img
                for img in images_raw
            ]
        elif isinstance(images_raw, str) and images_raw.startswith("["):
            try:
                image_list = json.loads(images_raw)
            except Exception:
                image_list = [images_raw] if images_raw else []
        else:
            image_list = [images_raw] if images_raw else []

        image_url = (
            raw.get("image_url", raw.get("image", raw.get("thumbnail", "")))
            or (image_list[0] if image_list else "")
        )

        # Variants — sizes and colors extracted separately for the storefront
        options = raw.get("options", raw.get("configurable_options", raw.get("variants", [])))
        sizes, colors = self._extract_variants(options)

        # Material — Silverbene specifies 925, 18k gold plated, etc.
        material = (
            raw.get("material", "")
            or raw.get("metal_type", "")
            or raw.get("custom_attributes_material", "")
            or self._infer_material(raw.get("name", "") + " " + raw.get("description", ""))
        )

        cost_price = float(
            raw.get("price", raw.get("cost", raw.get("wholesale_price", 0))) or 0
        )

        return {
            **self.standard_product(
                supplier_product_id=str(raw.get("sku", raw.get("id", raw.get("product_id", "")))),
                name=raw.get("name", raw.get("product_name", "")),
                category=raw.get("category", ""),
                description=raw.get("description", raw.get("short_description", "")),
                cost_price=cost_price,
                image_url=image_url,
                stock=int(raw.get("qty", raw.get("stock", raw.get("quantity", 999))) or 999),
                shipping_days=int(raw.get("shipping_days", 12)),
                supplier_name="Silverbene",
                supplier_url=f"https://silverbene.com/product/{raw.get('sku', '')}",
                variants=options,
            ),
            "images": image_list,
            "material": material,
            "sizes": sizes,
            "colors": colors,
            "supplier_rating": float(raw.get("rating", raw.get("review_count", 0)) or 0),
            "material_raw": raw.get("material", ""),
        }

    def _extract_variants(self, options) -> tuple:
        """
        Extract sizes and colors from Silverbene's variant/option structure.
        Returns (sizes_json_str, colors_json_str).
        """
        sizes = []
        colors = []

        if not options:
            return None, None

        if not isinstance(options, list):
            return None, None

        color_keywords = {"gold", "rose gold", "silver", "white gold", "yellow gold",
                          "rhodium", "platinum", "tanzanite", "black gold"}

        for opt in options:
            label = (opt.get("label", "") or opt.get("name", "") or "").lower()
            values = opt.get("values", opt.get("options", opt.get("choices", [])))
            if not isinstance(values, list):
                continue

            val_labels = [
                str(v.get("label", v.get("value", v)) if isinstance(v, dict) else v)
                for v in values
            ]

            if any(kw in label for kw in ("size", "ring", "length", "bracelet", "anklet", "chain")):
                sizes = val_labels
            elif any(kw in label for kw in ("color", "colour", "metal", "finish", "tone")):
                colors = [v for v in val_labels if v.lower() in color_keywords] or val_labels

        return (json.dumps(sizes) if sizes else None,
                json.dumps(colors) if colors else None)

    def _infer_material(self, text: str) -> str:
        """Fallback material detection from product name/description text."""
        t = text.lower()
        if "925" in t or "sterling" in t:
            return "925 Sterling Silver"
        if "18k" in t:
            return "18k Gold Plated"
        if "14k" in t:
            return "14k Gold Plated"
        if "stainless" in t:
            return "Stainless Steel"
        if "titanium" in t:
            return "Titanium"
        return "Fine Sterling Silver"
