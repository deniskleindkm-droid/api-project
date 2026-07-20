from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order
from app.models.product import Product


def run_order_recovery_agent():
    """
    Runs every 30 minutes. Finds every paid order whose Silverbene
    forwarding failed or never ran, and retries it automatically.

    Logic:
    - Orders with status='paid' and supplier_notified=False
      that are at least 5 minutes old (avoids racing the webhook)
    - Retries Silverbene place_order for each
    - On success: status → 'processing', supplier_notified = True, tracking entry created
    - On failure: if order is >2 hours old, emails Dennis so he's aware
    """
    print(f"[Order Recovery] Starting scan — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.agents.tracking_agent import create_tracking_entry

        cutoff_recent = datetime.utcnow() - timedelta(minutes=5)
        cutoff_old = datetime.utcnow() - timedelta(hours=2)

        with Session(engine) as session:
            pending = session.exec(
                select(Order).where(
                    (Order.status == "paid") | (Order.status == "pending_credit"),
                    Order.supplier_notified == False,
                    Order.created_at < cutoff_recent,
                )
            ).all()

        if not pending:
            print("[Order Recovery] No unforwarded orders found")
            return

        print(f"[Order Recovery] Found {len(pending)} order(s) to retry")

        sb = SilverbeneAdapter()
        recovered = []
        failed = []

        # Check balance before retrying — if still critically low, skip pending_credit orders
        sb_balance = sb.check_balance()
        balance_ok = sb_balance < 0 or sb_balance >= 20
        if not balance_ok:
            print(f"[Order Recovery] Silverbene balance ${sb_balance:.2f} still too low — skipping pending_credit orders")

        for order in pending:
            try:
                with Session(engine) as session:
                    product = session.get(Product, order.product_id)

                if order.status == "pending_credit" and not balance_ok:
                    print(f"[Order Recovery] Order {order.id} skipped — still pending_credit and balance too low")
                    continue

                if not product or not product.cj_sku:
                    print(f"[Order Recovery] Order {order.id}: no Silverbene option_id — skipping")
                    failed.append({"order_id": order.id, "reason": "no option_id on product"})
                    continue

                # The customer's actual selected variant (see app.models.
                # product_variant.ProductVariant) — falls back to product.cj_sku
                # (the product's default/first option) only for orders placed
                # before Order.variant_id existed. Without this, every recovered
                # order silently shipped whichever variant happened to be first,
                # regardless of what the customer actually bought and paid for.
                option_id = product.cj_sku
                if order.variant_id:
                    from app.models.product_variant import ProductVariant
                    with Session(engine) as vsession:
                        variant = vsession.get(ProductVariant, order.variant_id)
                    if variant and variant.product_id == order.product_id:
                        option_id = variant.supplier_option_id

                parts = order.user_id.split("@")[0].split(".")
                customer = {
                    "first_name": parts[0].capitalize(),
                    "last_name":  parts[1].capitalize() if len(parts) > 1 else "Customer",
                    "email":      order.user_id,
                    "phone":      "",
                }

                addr_parts = [p.strip() for p in order.shipping_address.split(",")]
                address = {
                    "line1":        addr_parts[0] if len(addr_parts) > 0 else "",
                    "city":         addr_parts[1] if len(addr_parts) > 1 else "",
                    "state":        addr_parts[2] if len(addr_parts) > 2 else "",
                    "state_code":   addr_parts[2][:2].upper() if len(addr_parts) > 2 else "",
                    "postal_code":  addr_parts[3] if len(addr_parts) > 3 else "",
                    "country_code": addr_parts[4].upper() if len(addr_parts) > 4 else "US",
                }

                result = sb.place_order(
                    product_id=str(option_id),
                    customer=customer,
                    address=address,
                    quantity=order.quantity,
                    option_id=str(option_id),
                )

                if result.get("success"):
                    create_tracking_entry(
                        order_id=order.id,
                        cj_order_id=result.get("supplier_order_id", ""),
                        customer_email=order.user_id,
                        customer_name=f"{customer['first_name']} {customer['last_name']}",
                        supplier_name="Silverbene"
                    )
                    with Session(engine) as session:
                        o = session.get(Order, order.id)
                        if o:
                            o.status = "processing"
                            o.supplier_notified = True
                            session.add(o)
                            session.commit()
                    print(f"[Order Recovery] ✅ Order {order.id} forwarded — supplier_order_id={result.get('supplier_order_id')}")
                    recovered.append(order.id)
                else:
                    reason = result.get("reason", "unknown")
                    print(f"[Order Recovery] ❌ Order {order.id} failed: {reason}")
                    failed.append({"order_id": order.id, "reason": reason})

            except Exception as e:
                print(f"[Order Recovery] Order {order.id} exception: {e}")
                failed.append({"order_id": order.id, "reason": str(e)})

        # Email Dennis about persistently stuck orders (>2h old, still failing)
        stuck = [
            f for f in failed
            if any(o.id == f["order_id"] and o.created_at < cutoff_old for o in pending)
        ]
        if stuck:
            _alert_dennis(stuck)

        print(f"[Order Recovery] Done — recovered={len(recovered)} failed={len(failed)}")

    except Exception as e:
        import traceback
        print(f"[Order Recovery] Agent error: {e}")
        traceback.print_exc()


def _alert_dennis(stuck_orders: list):
    try:
        from app.agents.email_partner import send_email
        import os

        rows = "".join(
            f"<tr><td style='padding:8px;border-bottom:1px solid #eee;'>Order #{o['order_id']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;color:#c0392b;'>{o['reason']}</td></tr>"
            for o in stuck_orders
        )

        body = f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#c0392b;">⚠️ Orders Stuck — Silverbene Forwarding Failed</h2>
<p>The order recovery agent has been unable to forward the following orders to Silverbene
for over 2 hours. These require your attention.</p>
<table style="width:100%;border-collapse:collapse;margin-top:16px;">
<tr style="background:#f5f5f5;">
  <th style="padding:8px;text-align:left;">Order</th>
  <th style="padding:8px;text-align:left;">Reason</th>
</tr>
{rows}
</table>
<p style="margin-top:20px;color:#666;font-size:13px;">
The recovery agent will keep retrying every 30 minutes.
</p>
</body></html>"""

        dennis_email = os.getenv("DENNIS_EMAIL")
        if dennis_email:
            send_email(
                to=dennis_email,
                subject=f"⚠️ {len(stuck_orders)} Mikisi order(s) stuck — Silverbene forwarding failed",
                body=body,
                is_html=True,
            )
            print(f"[Order Recovery] Alert sent to Dennis — {len(stuck_orders)} stuck order(s)")
    except Exception as e:
        print(f"[Order Recovery] Alert email failed: {e}")
