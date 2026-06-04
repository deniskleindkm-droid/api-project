# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from app.agents.email_partner import send_email

dennis_email  = os.getenv("DENNIS_EMAIL")
customer_email = dennis_email  # send test to Dennis inbox for both

product_name  = "Ocean Mermaid Tail Earrings"
qty           = 1
price         = 39.00
total         = 39.00
shipping_addr = "123 Test Street, New York, NY 10001, US"

items_html = f"<tr><td>{product_name}</td><td>{qty}</td><td>${price:.2f}</td><td>${total:.2f}</td></tr>"
items_html_customer = (
    f"<tr><td style='padding:10px 0;font-size:14px;font-weight:300;color:#0e0e0e;"
    f"border-bottom:1px solid #ece5dd;'>{product_name}</td>"
    f"<td style='text-align:center;padding:10px 0;font-size:14px;font-weight:300;"
    f"color:#6b6b6b;border-bottom:1px solid #ece5dd;'>{qty}</td>"
    f"<td style='text-align:right;padding:10px 0;font-family:Georgia,serif;font-size:16px;"
    f"color:#0e0e0e;border-bottom:1px solid #ece5dd;'>${total:.2f}</td></tr>"
)

# ── Dennis notification ───────────────────────────────────────
print("Sending Dennis notification...")
ok1 = send_email(
    to=dennis_email,
    subject=f"[TEST] New Mikisi Order — ${total:.2f}",
    body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#d4849c;">New Order Received! (TEST)</h2>
<p><strong>Customer:</strong> test@customer.com</p>
<p><strong>Shipping Address:</strong> {shipping_addr}</p>
<h3>Order Details:</h3>
<table border="1" cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;">
<tr style="background:#f5f5f5;">
    <th>Product</th><th>Qty</th><th>Price</th><th>Subtotal</th>
</tr>
{items_html}
<tr style="background:#fff5f7;">
    <td colspan="3"><strong>Total</strong></td>
    <td><strong>${total:.2f}</strong></td>
</tr>
</table>
<br>
<p style="color:#d4849c;font-weight:bold;">Silverbene order forwarding will be attempted automatically.</p>
<p>Ship to: {shipping_addr}</p>
</body></html>""",
    is_html=True
)
print(f"  Dennis email: {'SENT' if ok1 else 'FAILED'}")

# ── Customer confirmation ─────────────────────────────────────
print("Sending customer confirmation...")
ok2 = send_email(
    to=customer_email,
    subject="[TEST] Your Mikisi Order is Confirmed",
    body=f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#fdf9f6;">
<div style="text-align:center;padding:32px 0;">
    <h1 style="font-family:Georgia,serif;color:#0e0e0e;letter-spacing:4px;text-transform:uppercase;font-size:28px;font-weight:300;">Mik<em style="color:#d4849c;">i</em>si</h1>
    <p style="font-size:11px;color:#888;letter-spacing:3px;text-transform:uppercase;">Look Elegant and Polished</p>
</div>
<div style="background:white;padding:32px;border:1px solid #ece5dd;">
    <h2 style="font-family:Georgia,serif;font-weight:300;font-size:24px;color:#0e0e0e;margin-bottom:8px;">Your order is confirmed.</h2>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">Thank you for your purchase. We are preparing your order and it will be on its way soon.</p>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:16px;">Order Summary</h3>
    <table style="width:100%;border-collapse:collapse;">
        <tr style="border-bottom:1px solid #ece5dd;">
            <th style="text-align:left;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Product</th>
            <th style="text-align:center;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Qty</th>
            <th style="text-align:right;padding:10px 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;">Price</th>
        </tr>
        {items_html_customer}
        <tr>
            <td colspan="2" style="padding:16px 0 8px;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#888;">Total</td>
            <td style="padding:16px 0 8px;text-align:right;font-family:Georgia,serif;font-size:20px;color:#0e0e0e;">${total:.2f}</td>
        </tr>
    </table>
    <hr style="border:none;border-top:1px solid #ece5dd;margin:24px 0;">
    <h3 style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;font-weight:400;margin-bottom:12px;">Shipping To</h3>
    <p style="color:#6b6b6b;font-size:14px;font-weight:300;line-height:1.8;">{shipping_addr}</p>
    <p style="color:#6b6b6b;font-size:13px;font-weight:300;margin-top:16px;">Estimated delivery: 8-10 business days</p>
</div>
<div style="text-align:center;padding:32px 0;">
    <p style="font-size:11px;color:#bbb;letter-spacing:1px;">Questions? Contact us at hello@mikisi.co</p>
    <p style="font-size:10px;color:#ccc;margin-top:8px;letter-spacing:1px;">2026 Mikisi - Look Elegant and Polished</p>
</div>
</body></html>""",
    is_html=True
)
print(f"  Customer email: {'SENT' if ok2 else 'FAILED'}")

print()
if ok1 and ok2:
    print("RESULT: BOTH EMAILS DELIVERED — check your inbox at", dennis_email)
else:
    print("RESULT: ONE OR MORE EMAILS FAILED")
