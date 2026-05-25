from app.agents.suppliers.base import SupplierAdapter
from typing import Optional
import requests
import json
import os
import time

CJ_API_BASE = "https://developers.cjdropshipping.com/api2.0/v1"

_token_cache = {"token": None, "expires_at": 0}


class CJAdapter(SupplierAdapter):
    """
    CJ Dropshipping adapter.
    Translates CJ's API into Mikisi's standard supplier interface.
    """

    def __init__(self):
        self.email = os.getenv("CJ_EMAIL")
        self.api_key = os.getenv("CJ_API_KEY")

    def _get_token(self):
        global _token_cache
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expires_at"]:
            return _token_cache["token"]
        try:
            response = requests.post(
                f"{CJ_API_BASE}/authentication/getAccessToken",
                json={"email": self.email, "password": self.api_key},
                timeout=30
            )
            data = response.json()
            if data.get("result"):
                token = data["data"]["accessToken"]
                _token_cache["token"] = token
                _token_cache["expires_at"] = now + 3600
                return token
            print(f"[CJ Adapter] Auth failed: {data.get('message')}")
            return None
        except Exception as e:
            print(f"[CJ Adapter] Auth error: {e}")
            return None

    def _extract_image(self, cj_product):
        raw = (
            cj_product.get("productImage") or
            cj_product.get("bigImage") or
            ""
        )
        if isinstance(raw, list):
            return raw[0] if raw else ""
        if isinstance(raw, str) and raw.strip().startswith("["):
            try:
                parsed = json.loads(raw)
                return parsed[0] if parsed else ""
            except:
                return raw
        return raw

    def _parse_price(self, raw_price):
        try:
            if isinstance(raw_price, str) and "-" in raw_price:
                return float(raw_price.split("-")[0].strip())
            return float(raw_price) if raw_price else 0.0
        except:
            return 0.0

    def search(self, keyword: str, limit: int = 20) -> list:
        token = self._get_token()
        if not token:
            return []
        try:
            response = requests.get(
                f"{CJ_API_BASE}/product/list",
                headers={"CJ-Access-Token": token},
                params={"productNameEn": keyword, "pageNum": 1, "pageSize": limit},
                timeout=30
            )
            data = response.json()
            if not data.get("result"):
                return []

            products = data.get("data", {}).get("list", [])
            result = []
            for p in products:
                variants = p.get("variants", [])
                result.append(self.standard_product(
                    supplier_product_id=p.get("pid", ""),
                    supplier_variant_id=variants[0].get("vid", "") if variants else "",
                    name=p.get("productNameEn", ""),
                    category=p.get("categoryName", ""),
                    description=p.get("description", ""),
                    cost_price=self._parse_price(p.get("sellPrice", 0)),
                    image_url=self._extract_image(p),
                    stock=999,
                    shipping_days=15,
                    supplier_name="CJDropshipping",
                    supplier_url=f"https://cjdropshipping.com/product/{p.get('pid', '')}",
                    variants=variants
                ))
            return result
        except Exception as e:
            print(f"[CJ Adapter] Search error: {e}")
            return []

    def get_product(self, product_id: str) -> Optional[dict]:
        token = self._get_token()
        if not token:
            return None
        try:
            response = requests.get(
                f"{CJ_API_BASE}/product/query",
                headers={"CJ-Access-Token": token},
                params={"pid": product_id},
                timeout=30
            )
            data = response.json()
            if not data.get("result"):
                return None

            p = data.get("data")
            variants = p.get("variants", [])
            return self.standard_product(
                supplier_product_id=p.get("pid", ""),
                supplier_variant_id=variants[0].get("vid", "") if variants else "",
                name=p.get("productNameEn", ""),
                category=p.get("categoryName", ""),
                description=p.get("description", ""),
                cost_price=self._parse_price(p.get("sellPrice", 0)),
                image_url=self._extract_image(p),
                stock=999,
                shipping_days=15,
                supplier_name="CJDropshipping",
                supplier_url=f"https://cjdropshipping.com/product/{p.get('pid', '')}",
                variants=variants
            )
        except Exception as e:
            print(f"[CJ Adapter] Get product error: {e}")
            return None

    def get_shipping_methods(self, variant_id: str, country_code: str = "US") -> list:
        token = self._get_token()
        if not token:
            return []
        try:
            time.sleep(1)
            response = requests.post(
                f"{CJ_API_BASE}/logistic/freightCalculate",
                headers={
                    "CJ-Access-Token": token,
                    "Content-Type": "application/json"
                },
                json={
                    "startCountryCode": "CN",
                    "endCountryCode": country_code,
                    "products": [{"vid": variant_id, "quantity": 1}]
                },
                timeout=30
            )
            data = response.json()
            if data.get("result"):
                return data.get("data", [])
            return []
        except Exception as e:
            print(f"[CJ Adapter] Shipping methods error: {e}")
            return []

    def place_order(self, product_id: str, customer: dict, address: dict, quantity: int = 1) -> dict:
        token = self._get_token()
        if not token:
            return self.standard_order(success=False, reason="CJ auth failed")

        try:
            # Get shipping method
            variant_id = product_id  # For CJ, product_id here is the variant vid
            country_code = address.get("country_code", "US")
            methods = self.get_shipping_methods(variant_id, country_code)
            logistic_name = methods[0].get("logisticName", "CJPacket Ordinary") if methods else "CJPacket Ordinary"

            time.sleep(1)

            payload = {
                "orderNumber": f"MIKISI-{int(time.time())}",
                "fromCountryCode": "CN",
                "shippingCountry": country_code,
                "shippingCountryCode": country_code,
                "shippingCustomerName": customer.get("full_name", ""),
                "shippingFirstName": customer.get("first_name", ""),
                "shippingLastName": customer.get("last_name", ""),
                "shippingAddress": address.get("street", ""),
                "shippingCity": address.get("city", ""),
                "shippingProvince": address.get("state", ""),
                "shippingZip": address.get("zip", ""),
                "shippingPhone": customer.get("phone", "0000000000"),
                "logisticName": logistic_name,
                "products": [{"vid": variant_id, "quantity": quantity}]
            }

            response = requests.post(
                f"{CJ_API_BASE}/shopping/order/createOrder",
                headers={
                    "CJ-Access-Token": token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30
            )
            data = response.json()

            if data.get("result"):
                order_id = data.get("data", "")
                if isinstance(order_id, dict):
                    order_id = order_id.get("orderId", "")
                print(f"[CJ Adapter] ✅ Order placed: {order_id}")
                return self.standard_order(
                    success=True,
                    supplier_order_id=order_id
                )
            else:
                reason = data.get("message", "Unknown error")
                print(f"[CJ Adapter] Order failed: {reason}")
                return self.standard_order(success=False, reason=reason)

        except Exception as e:
            print(f"[CJ Adapter] Place order error: {e}")
            return self.standard_order(success=False, reason=str(e))

    def get_tracking(self, order_id: str) -> dict:
        token = self._get_token()
        if not token:
            return self.standard_tracking(order_id=order_id, status="unknown")
        try:
            response = requests.get(
                f"{CJ_API_BASE}/logistic/trackInfo",
                headers={"CJ-Access-Token": token},
                params={"trackNumber": order_id},
                timeout=30
            )
            data = response.json()
            if data.get("result"):
                info = data.get("data", [{}])[0]
                return self.standard_tracking(
                    order_id=order_id,
                    status=info.get("trackingStatus", "unknown"),
                    tracking_number=info.get("trackingNumber", ""),
                    carrier=info.get("lastMileCarrier", ""),
                    estimated_delivery=info.get("deliveryTime", ""),
                    last_update=info.get("deliveryTime", "")
                )
            return self.standard_tracking(order_id=order_id, status="unknown")
        except Exception as e:
            print(f"[CJ Adapter] Tracking error: {e}")
            return self.standard_tracking(order_id=order_id, status="error")