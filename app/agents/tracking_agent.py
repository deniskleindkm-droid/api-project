from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order, OrderTracking


def get_orders_needing_tracking():
    """Get all orders that need tracking updates."""
    with Session(engine) as session:
        trackings = session.exec(
            select(OrderTracking).where(
                OrderTracking.status.in_(["pending", "processing", "dispatched"])
            )
        ).all()
    return trackings


def create_tracking_entry(order_id, cj_order_id, customer_email,
                          customer_name, supplier_name="CJDropshipping",
                          supplier_product_cost=None, supplier_shipping_cost=None,
                          supplier_shipping_carrier=None, supplier_total_charged=None,
                          supplier_currency=None, supplier_raw_response=None):
    """
    Create a tracking entry when an order is forwarded to supplier.

    The supplier_* args are real per-order cost detail (see OrderTracking's
    docstring) — pass place_order()'s result fields straight through when
    available, for tax/bookkeeping. All optional so existing callers that
    don't have this data yet keep working unchanged.
    """
    with Session(engine) as session:
        existing = session.exec(
            select(OrderTracking).where(
                OrderTracking.order_id == order_id
            )
        ).first()

        if existing:
            print(f"[Tracking] Tracking already exists for order {order_id}")
            return existing

        tracking = OrderTracking(
            order_id=order_id,
            cj_order_id=cj_order_id,
            supplier_name=supplier_name,
            customer_email=customer_email,
            customer_name=customer_name,
            status="pending",
            created_at=datetime.utcnow(),
            supplier_product_cost=supplier_product_cost,
            supplier_shipping_cost=supplier_shipping_cost,
            supplier_shipping_carrier=supplier_shipping_carrier,
            supplier_total_charged=supplier_total_charged,
            supplier_currency=supplier_currency,
            supplier_raw_response=supplier_raw_response,
        )
        session.add(tracking)
        session.commit()
        session.refresh(tracking)
        print(f"[Tracking] ✅ Tracking created for order {order_id}")
        return tracking


def check_order_status(tracking):
    """
    Check order status from supplier.
    Uses supplier registry — works for any supplier.
    """
    try:
        from app.agents.suppliers.registry import get_supplier
        supplier = get_supplier(tracking.supplier_name)
        if not supplier:
            print(f"[Tracking] Supplier not found: {tracking.supplier_name}")
            return None

        result = supplier.get_tracking(tracking.cj_order_id)
        # "unknown" means the adapter has no real answer (Silverbene has no
        # tracking API at all; CJ falls back to it when auth fails) -- treat
        # it as "no new information" rather than letting the caller write it
        # over a real, already-confirmed status like "dispatched". This was
        # silently regressing order #21's status every 6 hours until fixed.
        if not result or result.get("status") == "unknown":
            return None
        return result

    except Exception as e:
        print(f"[Tracking] Error checking status for order {tracking.order_id}: {e}")
        return None


def _get_order_item_summary(order_id) -> str:
    """
    Looks up what was actually ordered so shipping/delivery emails can name
    the product instead of reading as a generic notice. Returns "" (and lets
    the caller omit the row) rather than raising if the order/product can't
    be found -- a missing product name shouldn't block a shipping email.
    """
    try:
        with Session(engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return ""
            from app.models.product import Product
            product = session.get(Product, order.product_id)
            if not product:
                return ""
            qty = f" (x{order.quantity})" if order.quantity and order.quantity > 1 else ""
            return f"{product.name}{qty}"
    except Exception as e:
        print(f"[Tracking] Could not look up order item for order {order_id}: {e}")
        return ""


def send_shipping_email(tracking):
    """Email customer when order ships."""
    try:
        from app.agents.email_partner import send_email

        item_summary = _get_order_item_summary(tracking.order_id)
        item_row = f"""
        <p style="font-size: 14px; color: #0e0e0e; margin-bottom: 4px;">
            <strong>Item:</strong> {item_summary}
        </p>""" if item_summary else ""

        # Order number in the subject survives into "Re:" replies, which is
        # how _match_delivery_preference_reply (customer_agent.py) correlates
        # a reply back to this specific OrderTracking record.
        subject = f"Your Mikisi order #{tracking.order_id} has shipped! 📦"
        body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: 'Georgia', serif; background: #fdf9f6; margin: 0; padding: 40px;">
<div style="max-width: 600px; margin: 0 auto; background: white; padding: 48px;">

    <div style="text-align: center; margin-bottom: 40px;">
        <h1 style="font-family: 'Georgia', serif; font-size: 28px; font-weight: 300;
                   letter-spacing: 6px; color: #0e0e0e; text-transform: uppercase;">
            Mik<em style="color: #d4849c; font-style: italic;">i</em>si
        </h1>
    </div>

    <h2 style="font-family: 'Georgia', serif; font-size: 24px; font-weight: 300;
               color: #0e0e0e; margin-bottom: 16px;">
        Your order is on its way, {tracking.customer_name.split()[0]}
    </h2>

    <p style="font-size: 14px; color: #6b6b6b; line-height: 1.8; margin-bottom: 24px;">
        Great news — your Mikisi order has been dispatched and is making its way to you.
    </p>

    <div style="background: #f7f2ed; padding: 24px; margin-bottom: 32px;">
        <p style="font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
                  color: #c9a96e; margin-bottom: 8px;">Order Information</p>{item_row}
        <p style="font-size: 14px; color: #0e0e0e;">
            <strong>Tracking Number:</strong> {tracking.tracking_number or 'Being updated'}
        </p>
    </div>

    <div style="background: #fdf6f8; border: 1px solid #f3dbe3; padding: 20px 24px; margin-bottom: 32px;">
        <p style="font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
                  color: #d4849c; margin-bottom: 8px;">Delivery Preferences</p>
        <p style="font-size: 14px; color: #0e0e0e; line-height: 1.7; margin: 0;">
            Want your package left somewhere specific, or don't need a signature?
            Just reply to this email and let us know — we'll pass it along to the courier for you.
        </p>
    </div>

    <p style="font-size: 13px; color: #6b6b6b; line-height: 1.8;">
        You'll receive another email once your order is delivered.
        Thank you for choosing Mikisi.
    </p>

    <div style="border-top: 1px solid #ece5dd; margin-top: 40px; padding-top: 24px;
                text-align: center;">
    </div>

</div>
</body>
</html>
"""
        sent = send_email(tracking.customer_email, subject, body, is_html=True)
        if sent:
            print(f"[Tracking] ✅ Shipping email sent to {tracking.customer_email}")
            with Session(engine) as session:
                t = session.get(OrderTracking, tracking.id)
                if t:
                    t.delivery_preference_requested = True
                    session.add(t)
                    session.commit()
        return sent

    except Exception as e:
        print(f"[Tracking] Shipping email error: {e}")
        return False


def send_delivery_email(tracking):
    """Email customer when order is delivered."""
    try:
        from app.agents.email_partner import send_email

        item_summary = _get_order_item_summary(tracking.order_id)
        item_block = f"""
    <div style="background: #f7f2ed; padding: 20px 24px; margin-bottom: 32px;">
        <p style="font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
                  color: #c9a96e; margin-bottom: 8px;">Delivered</p>
        <p style="font-size: 14px; color: #0e0e0e;"><strong>{item_summary}</strong></p>
    </div>""" if item_summary else ""

        subject = "Your Mikisi order has been delivered! ✨"
        body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: 'Georgia', serif; background: #fdf9f6; margin: 0; padding: 40px;">
<div style="max-width: 600px; margin: 0 auto; background: white; padding: 48px;">

    <div style="text-align: center; margin-bottom: 40px;">
        <h1 style="font-family: 'Georgia', serif; font-size: 28px; font-weight: 300;
                   letter-spacing: 6px; color: #0e0e0e; text-transform: uppercase;">
            Mik<em style="color: #d4849c; font-style: italic;">i</em>si
        </h1>
    </div>

    <h2 style="font-family: 'Georgia', serif; font-size: 24px; font-weight: 300;
               color: #0e0e0e; margin-bottom: 16px;">
        Your order has arrived, {tracking.customer_name.split()[0]} ✨
    </h2>

    <p style="font-size: 14px; color: #6b6b6b; line-height: 1.8; margin-bottom: 24px;">
        Your Mikisi order has been delivered. We hope you love it as much as
        we loved curating it for you.
    </p>
{item_block}
    <p style="font-size: 13px; color: #6b6b6b; line-height: 1.8;">
        If you have any questions about your order, simply reply to this email.
        We'd love to hear what you think.
    </p>

    <div style="border-top: 1px solid #ece5dd; margin-top: 40px; padding-top: 24px;
                text-align: center;">
        <p style="font-size: 11px; color: #d8d0c8; letter-spacing: 2px;
                  text-transform: uppercase;">Thank you for choosing Mikisi</p>
    </div>

</div>
</body>
</html>
"""
        sent = send_email(tracking.customer_email, subject, body, is_html=True)
        if sent:
            print(f"[Tracking] ✅ Delivery email sent to {tracking.customer_email}")
        return sent

    except Exception as e:
        print(f"[Tracking] Delivery email error: {e}")
        return False


def maybe_send_delivery_relay_alert(tracking_id):
    """
    Sends Dennis a one-click alert once BOTH halves of the delivery-relay
    loop exist for an order: the customer's stated delivery_preference
    (captured via customer_agent's reply parsing) and DHL's dhl_odd_link
    (captured via dhl_monitor). Neither piece alone is actionable -- there's
    nothing to relay without a preference, and no portal to relay it into
    without the link -- so this is called after either one is stored, and
    is a no-op until both are present. delivery_alert_sent guards against
    re-alerting every time either agent runs afterward.

    We deliberately don't auto-submit DHL's own portal form here -- that
    would mean scripting a bot against a third party's consumer-facing site
    we have no partnership with, likely fighting anti-bot protections. The
    click itself stays a human step; this just makes it a 10-second one.
    """
    with Session(engine) as session:
        t = session.get(OrderTracking, tracking_id)
        if not t or t.delivery_alert_sent:
            return
        if not (t.delivery_preference and t.dhl_odd_link):
            return

        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL", "hello@mikisi.co")
            sent = send_email(
                dennis_email,
                f"Apply delivery instructions — order #{t.order_id}",
                f"""<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#d4849c;">One click to apply — order #{t.order_id}</h2>
<p><strong>{t.customer_name or 'Customer'}</strong> asked us to pass this along to the courier:</p>
<p style="font-size:16px;color:#0e0e0e;font-style:italic;background:#f7f2ed;padding:16px;">"{t.delivery_preference}"</p>
<p>Open DHL's delivery page and enter it: <a href="{t.dhl_odd_link}">{t.dhl_odd_link}</a></p>
<p><strong>Waybill:</strong> {t.tracking_number or 'n/a'}</p>
</body></html>""",
                is_html=True,
            )
        except Exception as e:
            print(f"[Tracking] Delivery relay alert error: {e}")
            sent = False

        if sent:
            t.delivery_alert_sent = True
            session.add(t)
            session.commit()
            print(f"[Tracking] ✅ Delivery relay alert sent for order {t.order_id}")


def update_tracking_status(tracking_id, status, tracking_number=None,
                           carrier=None, shipped_at=None, delivered_at=None):
    """Update tracking record in database."""
    with Session(engine) as session:
        tracking = session.get(OrderTracking, tracking_id)
        if not tracking:
            return

        tracking.status = status
        tracking.last_checked = datetime.utcnow()

        if tracking_number:
            tracking.tracking_number = tracking_number
        if carrier:
            tracking.carrier = carrier
        if shipped_at:
            tracking.shipped_at = shipped_at
        if delivered_at:
            tracking.delivered_at = delivered_at

        session.add(tracking)
        session.commit()
        print(f"[Tracking] Updated order {tracking.order_id} → {status}")


def check_for_delays(tracking):
    """Check if order is delayed beyond acceptable threshold."""
    from app.agents.store_config import get_config
    max_days = int(get_config("max_shipping_days", default=30))

    if tracking.status in ["pending", "processing"]:
        days_since_order = (datetime.utcnow() - tracking.created_at).days
        if days_since_order > max_days:
            return True
    return False


def run_tracking_agent():
    """
    Main tracking agent loop.
    Checks all pending orders and updates their status.
    Runs every 6 hours from scheduler.
    """
    print(f"[Tracking] 🔍 Checking order tracking status...")

    trackings = get_orders_needing_tracking()

    if not trackings:
        print(f"[Tracking] No orders need tracking updates")
        return

    print(f"[Tracking] Checking {len(trackings)} orders")

    for tracking in trackings:
        try:
            # Check status from supplier
            result = check_order_status(tracking)

            if not result:
                # Check for delays even without status update
                if check_for_delays(tracking):
                    from app.agents.nervous_system import emit
                    emit(
                        signal_type="ORDER_DELAYED",
                        sender="tracking_agent",
                        payload={
                            "order_id": tracking.order_id,
                            "cj_order_id": tracking.cj_order_id,
                            "days_pending": (datetime.utcnow() - tracking.created_at).days,
                            "supplier": tracking.supplier_name
                        },
                        priority=2
                    )
                continue

            new_status = result.get("status", "pending").lower()
            tracking_number = result.get("tracking_number")
            carrier = result.get("carrier")

            # Map supplier status to our status
            if "transit" in new_status or "dispatched" in new_status:
                new_status = "dispatched"
            elif "delivered" in new_status:
                new_status = "delivered"
            elif "processing" in new_status:
                new_status = "processing"

            # Update database
            update_tracking_status(
                tracking.id,
                status=new_status,
                tracking_number=tracking_number,
                carrier=carrier,
                shipped_at=datetime.utcnow() if new_status == "dispatched" and not tracking.shipped_at else None,
                delivered_at=datetime.utcnow() if new_status == "delivered" and not tracking.delivered_at else None
            )

            # Reload tracking with updated data
            with Session(engine) as session:
                tracking = session.get(OrderTracking, tracking.id)

            # Send shipping email if not already sent
            if new_status == "dispatched" and not tracking.shipping_notified and tracking.customer_email:
                sent = send_shipping_email(tracking)
                if sent:
                    with Session(engine) as session:
                        t = session.get(OrderTracking, tracking.id)
                        t.shipping_notified = True
                        session.add(t)
                        session.commit()

                    from app.agents.nervous_system import emit
                    emit(
                        signal_type="ORDER_SHIPPED",
                        sender="tracking_agent",
                        payload={
                            "order_id": tracking.order_id,
                            "tracking_number": tracking_number,
                            "carrier": carrier
                        },
                        priority=5
                    )

            # Send delivery email if not already sent
            elif new_status == "delivered" and not tracking.delivery_notified and tracking.customer_email:
                sent = send_delivery_email(tracking)
                if sent:
                    with Session(engine) as session:
                        t = session.get(OrderTracking, tracking.id)
                        t.delivery_notified = True
                        session.add(t)
                        session.commit()

                    from app.agents.nervous_system import emit
                    emit(
                        signal_type="ORDER_DELIVERED",
                        sender="tracking_agent",
                        payload={
                            "order_id": tracking.order_id,
                            "customer_email": tracking.customer_email
                        },
                        priority=5
                    )

            # Check for delays
            if check_for_delays(tracking):
                from app.agents.nervous_system import emit
                emit(
                    signal_type="ORDER_DELAYED",
                    sender="tracking_agent",
                    payload={
                        "order_id": tracking.order_id,
                        "cj_order_id": tracking.cj_order_id,
                        "status": new_status,
                        "days_since_order": (datetime.utcnow() - tracking.created_at).days
                    },
                    priority=2
                )

        except Exception as e:
            print(f"[Tracking] Error processing order {tracking.order_id}: {e}")

    print(f"[Tracking] ✅ Tracking check complete")