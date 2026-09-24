"""
Stripe TEST-MODE qualification for the international checkout. Refuses to run with a live key.
Creates Checkout Sessions only (nothing is charged, no real card involved) and reports what
Stripe says each session would offer, for both the legacy card-only config and dynamic methods.

    python scripts/qualify_stripe_test_mode.py

Output: artifacts/stripe_test_mode_qualification.json

What this can and cannot prove:
  - CAN: sessions create with the exact parameters checkout uses; which payment_method_types
    Stripe resolves for dynamic mode; the account's payment-method-configuration flags for
    card / link / apple_pay / google_pay.
  - CANNOT: render Apple Pay / Google Pay buttons. Wallets need a real browser + device
    wallet on a domain verified with Stripe; those are checked by hand (see report).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import stripe  # noqa: E402

key = os.getenv("STRIPE_SECRET_KEY", "")
if not key.startswith("sk_test_"):
    sys.exit("refusing to run: STRIPE_SECRET_KEY is not a test-mode key")
stripe.api_key = key

LINE = [{"price_data": {"currency": "usd", "product_data": {"name": "Mikisi test ring"}, "unit_amount": 29800},
         "quantity": 1}]
COMMON = dict(line_items=LINE, mode="payment", success_url="https://mikisi.co/?payment=success",
              cancel_url="https://mikisi.co/", customer_email="qa@example.com",
              metadata={"checkout_id": "qualification"})
out = {}

for label, extra in (("legacy_card_only", {"payment_method_types": ["card"]}),
                     ("dynamic_methods", {})):
    s = stripe.checkout.Session.create(**COMMON, **extra)
    out[label] = {"id": s.id, "livemode": s.livemode, "payment_method_types_resolved": list(s.payment_method_types),
                  "url_host": s.url.split("/")[2], "currency": s.currency, "amount_total": s.amount_total}
    stripe.checkout.Session.expire(s.id)             # leave nothing dangling

# Capability evidence per Wave-1 presentment currency (test sessions only; production stays USD).
out["dynamic_methods_by_currency"] = {}
for cur in ("usd", "gbp", "eur", "aud", "cad"):
    line = [{"price_data": {"currency": cur, "product_data": {"name": "Mikisi test ring"}, "unit_amount": 29800},
             "quantity": 1}]
    try:
        s = stripe.checkout.Session.create(**{**COMMON, "line_items": line})
        out["dynamic_methods_by_currency"][cur] = list(s.payment_method_types)
        stripe.checkout.Session.expire(s.id)
    except Exception as e:  # noqa: BLE001
        out["dynamic_methods_by_currency"][cur] = f"ERR {type(e).__name__}: {e}"

try:
    cfgs = stripe.PaymentMethodConfiguration.list(limit=5)
    out["payment_method_configurations"] = []
    for c in cfgs.data:
        d = c.to_dict()
        out["payment_method_configurations"].append({
            "id": d.get("id"), "name": d.get("name"), "is_default": d.get("is_default"),
            **{m: ((d.get(m) or {}).get("display_preference") or {}).get("value")
               for m in ("card", "link", "apple_pay", "google_pay", "paypal", "klarna", "ideal", "bancontact")}})
except Exception as e:  # noqa: BLE001
    out["payment_method_configurations_error"] = f"{type(e).__name__}: {e}"

os.makedirs(os.path.join(os.path.dirname(__file__), "..", "artifacts"), exist_ok=True)
with open(os.path.join(os.path.dirname(__file__), "..", "artifacts", "stripe_test_mode_qualification.json"),
          "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out, indent=1))
