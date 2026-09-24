"""
PayPal (Orders v2) provider -- behind the INTL_PAYPAL flag, sandbox by default.

Flow:  create order (intent=CAPTURE)  ->  customer approves at PayPal
       ->  we capture (return route OR CHECKOUT.ORDER.APPROVED webhook)
       ->  order fulfillment (same idempotent path Stripe uses)

Idempotency: every mutating PayPal call carries a deterministic PayPal-Request-Id
(create: per checkout+attempt; capture: per PayPal order; refund: per capture), so a
retry/replay returns the original result instead of a second charge. On the Mikisi
side the PayPal order id (prefixed "pp_") is the same idempotency key
process_order_background already uses for Stripe sessions.

All HTTP goes through `PayPalClient._request`, so tests substitute a fake and the
real sandbox can be exercised by exporting credentials (see docs in STAGE1B report):
    PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WEBHOOK_ID, PAYPAL_MODE=sandbox|live
Production activation is a separate, explicit step; live mode is refused unless
PAYPAL_ALLOW_LIVE=1.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

SANDBOX = "https://api-m.sandbox.paypal.com"
LIVE = "https://api-m.paypal.com"


class PayPalError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


def paypal_enabled() -> bool:
    return os.getenv("INTL_PAYPAL", "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class CaptureResult:
    order_id: str
    status: str                 # COMPLETED | PENDING | DECLINED | ...
    capture_id: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    already_captured: bool = False


class PayPalClient:
    def __init__(self, client_id=None, client_secret=None, mode=None, http: Optional[Callable] = None):
        self.client_id = client_id or os.getenv("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("PAYPAL_CLIENT_SECRET", "")
        self.mode = (mode or os.getenv("PAYPAL_MODE", "sandbox")).lower()
        if self.mode == "live" and os.getenv("PAYPAL_ALLOW_LIVE") != "1":
            raise PayPalError("PayPal live mode is not activated (PAYPAL_ALLOW_LIVE)")
        self.base = LIVE if self.mode == "live" else SANDBOX
        self._http = http
        self._token: Optional[str] = None
        self._token_exp = 0.0

    # single choke point for network I/O ---------------------------------------
    def _request(self, method, path, *, json=None, data=None, headers=None, auth=None):
        if self._http is not None:
            return self._http(method, self.base + path, json=json, data=data, headers=headers or {}, auth=auth)
        import requests
        r = requests.request(method, self.base + path, json=json, data=data, headers=headers or {},
                             auth=auth, timeout=30)
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {"_raw": r.text[:300]}
        return r.status_code, body

    def _bearer(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        if not (self.client_id and self.client_secret):
            raise PayPalError("PayPal credentials are not configured")
        status, body = self._request("POST", "/v1/oauth2/token", data={"grant_type": "client_credentials"},
                                     auth=(self.client_id, self.client_secret),
                                     headers={"Accept": "application/json"})
        if status != 200 or "access_token" not in body:
            raise PayPalError("PayPal auth failed", status, body)
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 300))
        return self._token

    def _call(self, method, path, *, json=None, request_id=None, ok=(200, 201)):
        headers = {"Authorization": f"Bearer {self._bearer()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        # SANDBOX-ONLY negative testing (PayPal's documented PayPal-Mock-Response header), e.g.
        # PAYPAL_SANDBOX_MOCK=INSTRUMENT_DECLINED makes the next captures fail like a declined payment.
        mock = os.getenv("PAYPAL_SANDBOX_MOCK")
        if mock and self.mode == "sandbox" and path.endswith("/capture"):
            headers["PayPal-Mock-Response"] = '{"mock_application_codes":"%s"}' % mock
        status, body = self._request(method, path, json=json, headers=headers)
        if status not in ok:
            raise PayPalError(f"PayPal {method} {path} -> {status}", status, body)
        return status, body

    # operations -----------------------------------------------------------------
    def create_order(self, *, checkout_id: str, items: List[dict], currency: str, return_url: str,
                     cancel_url: str, attempt: int = 0) -> dict:
        """items: [{"name", "unit_amount": Decimal-string, "quantity"}]. Returns {"id", "approve_url", "status"}."""
        total = sum(float(i["unit_amount"]) * int(i["quantity"]) for i in items)
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": checkout_id, "custom_id": checkout_id,
                "amount": {"currency_code": currency, "value": f"{total:.2f}",
                           "breakdown": {"item_total": {"currency_code": currency, "value": f"{total:.2f}"}}},
                "items": [{"name": i["name"][:127], "quantity": str(i["quantity"]),
                           "unit_amount": {"currency_code": currency, "value": f"{float(i['unit_amount']):.2f}"}}
                          for i in items],
            }],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": return_url, "cancel_url": cancel_url, "user_action": "PAY_NOW",
                "shipping_preference": "NO_SHIPPING", "brand_name": "Mikisi"}}},
        }
        _, body = self._call("POST", "/v2/checkout/orders", json=payload,
                             request_id=f"mikisi-create-{checkout_id}-{attempt}")
        link = next((l["href"] for l in body.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
        if not link:
            raise PayPalError("PayPal order has no approval link", body=body)
        return {"id": body["id"], "approve_url": link, "status": body.get("status")}

    def get_order(self, order_id: str) -> dict:
        return self._call("GET", f"/v2/checkout/orders/{order_id}")[1]

    def capture_order(self, order_id: str) -> CaptureResult:
        try:
            _, body = self._call("POST", f"/v2/checkout/orders/{order_id}/capture",
                                 json={}, request_id=f"mikisi-capture-{order_id}")
            already = False
        except PayPalError as e:
            issues = [d.get("issue") for d in (e.body.get("details") or [])]
            if e.status == 422 and "ORDER_ALREADY_CAPTURED" in issues:
                body, already = self.get_order(order_id), True     # replay: report the original capture
            else:
                raise
        cap = ((body.get("purchase_units") or [{}])[0].get("payments") or {}).get("captures") or [{}]
        cap = cap[0]
        amt = cap.get("amount") or {}
        return CaptureResult(
            order_id=order_id, status=cap.get("status") or body.get("status", ""),
            capture_id=cap.get("id"),
            amount=float(amt["value"]) if amt.get("value") else None, currency=amt.get("currency_code"),
            already_captured=already)

    def refund_capture(self, capture_id: str, *, amount: Optional[float] = None, currency: str = "USD",
                       note: str = "") -> dict:
        payload = {}
        if amount is not None:
            payload["amount"] = {"value": f"{amount:.2f}", "currency_code": currency}
        if note:
            payload["note_to_payer"] = note[:255]
        _, body = self._call("POST", f"/v2/payments/captures/{capture_id}/refund", json=payload,
                             request_id=f"mikisi-refund-{capture_id}-{'full' if amount is None else f'{amount:.2f}'}")
        return body

    def verify_webhook(self, headers: dict, event: dict, webhook_id: Optional[str] = None) -> bool:
        webhook_id = webhook_id or os.getenv("PAYPAL_WEBHOOK_ID", "")
        if not webhook_id:
            return False                       # never accept an unverifiable webhook
        h = {k.lower(): v for k, v in headers.items()}
        need = ("paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig",
                "paypal-cert-url", "paypal-auth-algo")
        if any(k not in h for k in need):
            return False
        payload = {
            "auth_algo": h["paypal-auth-algo"], "cert_url": h["paypal-cert-url"],
            "transmission_id": h["paypal-transmission-id"], "transmission_sig": h["paypal-transmission-sig"],
            "transmission_time": h["paypal-transmission-time"], "webhook_id": webhook_id, "webhook_event": event,
        }
        try:
            _, body = self._call("POST", "/v1/notifications/verify-webhook-signature", json=payload)
        except PayPalError:
            return False
        return body.get("verification_status") == "SUCCESS"


class PayPalProvider:
    """PaymentProvider adapter. create_session mirrors the Stripe signature and returns .id/.url."""
    def __init__(self, client: Optional[PayPalClient] = None):
        self._client = client

    @property
    def client(self) -> PayPalClient:
        if self._client is None:
            self._client = PayPalClient()
        return self._client

    def create_session(self, *, line_items, success_url, cancel_url, customer_email, metadata):
        from types import SimpleNamespace
        items = [{"name": li["price_data"]["product_data"]["name"],
                  "unit_amount": f"{li['price_data']['unit_amount'] / 100:.2f}",
                  "quantity": li["quantity"]} for li in line_items]
        order = self.client.create_order(
            checkout_id=metadata["checkout_id"], items=items,
            currency=line_items[0]["price_data"]["currency"].upper(),
            return_url=success_url, cancel_url=cancel_url,
            attempt=int(metadata.get("attempt", 0)))
        return SimpleNamespace(id=f"pp_{order['id']}", url=order["approve_url"], paypal_order_id=order["id"])
