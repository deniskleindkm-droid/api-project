from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.signal import SystemSignal
import json


def emit(signal_type, sender, payload=None, receiver=None, priority=5):
    """
    Any agent calls this to send a signal through the nervous system.
    """
    try:
        with Session(engine) as session:
            signal = SystemSignal(
                signal_type=signal_type,
                sender=sender,
                receiver=receiver,
                payload=json.dumps(payload) if payload else None,
                priority=priority,
                status="pending",
                created_at=datetime.utcnow()
            )
            session.add(signal)
            session.commit()
            session.refresh(signal)
            print(f"[Nervous System] 📡 Signal emitted: {signal_type} from {sender} (priority {priority})")
            return signal.id
    except Exception as e:
        print(f"[Nervous System] ❌ Failed to emit signal: {e}")
        return None


def get_pending_signals(receiver=None, limit=50):
    with Session(engine) as session:
        query = select(SystemSignal).where(
            SystemSignal.status == "pending"
        )
        if receiver:
            from sqlmodel import or_
            query = query.where(
                or_(
                    SystemSignal.receiver == receiver,
                    SystemSignal.receiver == None
                )
            )
        query = query.order_by(
            SystemSignal.priority.asc(),
            SystemSignal.created_at.asc()
        ).limit(limit)
        return session.exec(query).all()


def mark_processed(signal_id):
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "processed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()


def mark_failed(signal_id, reason=""):
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "failed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()
            print(f"[Nervous System] ❌ Signal {signal_id} failed: {reason}")


def get_signal_payload(signal):
    try:
        return json.loads(signal.payload) if signal.payload else {}
    except:
        return {}


def process_signals():
    """
    Signal processor — routes pending signals to correct agents.
    Runs every 30 seconds from scheduler.
    """
    signals = get_pending_signals(limit=20)

    if not signals:
        return

    print(f"[Nervous System] 🔄 Processing {len(signals)} pending signals")

    for signal in signals:
        try:
            payload = get_signal_payload(signal)
            print(f"[Nervous System] → {signal.signal_type} from {signal.sender}")

            if signal.signal_type == "PRODUCT_IMPORTED":
                _handle_product_imported(payload)

            elif signal.signal_type == "PRODUCT_AUTO_IMPORTED":
                _handle_product_auto_imported(payload)

            elif signal.signal_type == "PRODUCT_APPROVED":
                _handle_product_approved(payload)

            elif signal.signal_type == "PRODUCT_NEEDS_REVIEW":
                _handle_product_needs_review(payload)

            elif signal.signal_type == "PRODUCT_NEEDS_COLLECTION":
                _handle_product_needs_collection(payload)

            elif signal.signal_type == "TREND_DETECTED":
                _handle_trend_detected(payload)

            elif signal.signal_type == "ORDER_FAILED":
                _handle_order_failed(payload)

            elif signal.signal_type == "ORDER_SHIPPED":
                _handle_order_shipped(payload)

            elif signal.signal_type == "ORDER_DELIVERED":
                _handle_order_delivered(payload)

            elif signal.signal_type == "ORDER_DELAYED":
                _handle_order_delayed(payload)

            elif signal.signal_type == "CONTENT_READY":
                _handle_content_ready(payload)

            elif signal.signal_type == "CONTENT_BATCH_COMPLETE":
                _handle_content_batch_complete(payload)

            elif signal.signal_type == "CONTENT_NEEDS_REVIEW":
                _handle_content_needs_review(payload)

            elif signal.signal_type == "CONTENT_POSTED":
                _handle_content_posted(payload)

            elif signal.signal_type == "STOCK_LOW":
                _handle_stock_low(payload)

            elif signal.signal_type == "STOCK_OUT":
                _handle_stock_out(payload)

            elif signal.signal_type == "STOCK_RESTORED":
                _handle_stock_restored(payload)

            elif signal.signal_type == "STOCK_SYNC_COMPLETE":
                _handle_stock_sync_complete(payload)

            elif signal.signal_type == "BULK_IMPORT_COMPLETE":
                payload_data = payload
                print(f"[Nervous System] 📥 Bulk import done: {payload_data.get('total_imported',0)} products across {payload_data.get('collections',0)} collections")

            elif signal.signal_type == "COLLECTION_ASSIGNED":
                pass

            elif signal.signal_type == "ORDER_PLACED":
                pass

            elif signal.signal_type == "COMPLAINT_RECEIVED":
                _handle_complaint_received(payload)

            elif signal.signal_type == "CUSTOMER_CONTACTED":
                _handle_customer_contacted(payload)

            elif signal.signal_type == "PERFORMANCE_REPORT":
                _handle_performance_report(payload)    

            else:
                print(f"[Nervous System] ⚠️ Unknown signal type: {signal.signal_type}")

            mark_processed(signal.id)

        except Exception as e:
            print(f"[Nervous System] ❌ Error processing signal {signal.id}: {e}")
            mark_failed(signal.id, str(e))


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def _handle_product_imported(payload):
    product_id = payload.get("product_id")
    product_name = payload.get("name")
    collection_id = payload.get("collection_id")
    print(f"[Nervous System] ✅ Product imported: {product_name} (ID: {product_id}) → Collection {collection_id}")

    # Trigger content generation automatically
    try:
        from app.agents.content_agent import generate_all_content
        generate_all_content(product_id)
    except Exception as e:
        print(f"[Nervous System] Content generation failed: {e}")


def _handle_product_auto_imported(payload):
    name = payload.get("name")
    store_price = payload.get("store_price")
    score = payload.get("score")
    supplier = payload.get("supplier")
    print(f"[Nervous System] 🤖 Auto-imported: {name} at ${store_price} (score: {score}, supplier: {supplier})")


def _handle_product_approved(payload):
    name = payload.get("name")
    score = payload.get("total_score")
    supplier_product_id = payload.get("supplier_product_id")
    supplier_name = payload.get("supplier_name", "CJDropshipping")
    print(f"[Nervous System] ✅ Auto-importing approved product: {name} (score: {score})")

    try:
        from app.agents.suppliers.registry import get_supplier
        from app.agents.store_manager import import_product_from_supplier

        supplier = get_supplier(supplier_name)
        if not supplier:
            print(f"[Nervous System] Supplier not found: {supplier_name}")
            return

        product = supplier.get_product(supplier_product_id)
        if not product:
            print(f"[Nervous System] Product not found: {supplier_product_id}")
            return

        result = import_product_from_supplier(product, markup=None)

        if result.get("success"):
            print(f"[Nervous System] ✅ Auto-imported: {name} at ${result.get('store_price')}")
            emit(
                signal_type="PRODUCT_AUTO_IMPORTED",
                sender="autonomy_engine",
                payload={
                    "name": name,
                    "store_price": result.get("store_price"),
                    "score": score,
                    "supplier": supplier_name,
                    "auto_imported": True
                },
                priority=5
            )
        else:
            reason = result.get("reason", "Unknown")
            if "Already exists" in str(reason):
                print(f"[Nervous System] Product already in store: {name}")
            else:
                print(f"[Nervous System] Auto-import failed: {reason}")

    except Exception as e:
        print(f"[Nervous System] Auto-import error: {e}")


def _handle_product_needs_review(payload):
    name = payload.get("name")
    score = payload.get("total_score")
    reason = payload.get("reason")
    print(f"[Nervous System] 📋 Product needs review: {name} (score: {score}) — {reason}")


def _handle_product_needs_collection(payload):
    product_name = payload.get("product_name")
    category = payload.get("category")
    print(f"[Nervous System] 📋 Product needs collection review: {product_name} — {category}")


def _handle_trend_detected(payload):
    keyword = payload.get("keyword")
    trend = payload.get("trend")
    change = payload.get("change_percent", 0)
    print(f"[Nervous System] 📈 Trend detected: {keyword} is {trend} ({change:+.1f}%)")

    try:
        from app.agents.suppliers.registry import get_supplier
        from app.agents.product_scoring import score_and_decide

        supplier = get_supplier("CJDropshipping")
        if not supplier:
            print(f"[Nervous System] No supplier available for trend: {keyword}")
            return

        products = supplier.search(keyword, limit=5)
        print(f"[Nervous System] Found {len(products)} products for trend: {keyword}")

        for product in products[:3]:
            result = score_and_decide(product)
            print(f"[Nervous System] Scored {product.get('name', '')[:40]} → {result['action']}")

    except Exception as e:
        print(f"[Nervous System] Trend handler error: {e}")


def _handle_order_failed(payload):
    order_id = payload.get("order_id")
    reason = payload.get("reason")
    print(f"[Nervous System] 🚨 Order failed: {order_id} — {reason}")


def _handle_order_shipped(payload):
    order_id = payload.get("order_id")
    tracking = payload.get("tracking_number")
    carrier = payload.get("carrier")
    print(f"[Nervous System] 📦 Order {order_id} shipped — tracking: {tracking} via {carrier}")


def _handle_order_delivered(payload):
    order_id = payload.get("order_id")
    customer_email = payload.get("customer_email")
    print(f"[Nervous System] ✅ Order {order_id} delivered to {customer_email}")

    # Trigger follow up email
    try:
        from app.agents.customer_agent import handle_post_delivery_followup
        handle_post_delivery_followup(
            order_id=order_id,
            customer_email=customer_email,
            customer_name=customer_email.split("@")[0] if customer_email else "Customer"
        )
    except Exception as e:
        print(f"[Nervous System] Follow up failed: {e}")


def _handle_order_delayed(payload):
    order_id = payload.get("order_id")
    days = payload.get("days_since_order")
    print(f"[Nervous System] ⚠️ Order {order_id} delayed — {days} days since order")


def _handle_content_ready(payload):
    product_id   = payload.get("product_id")
    product_name = payload.get("product_name", "")
    asset_type   = payload.get("asset_type", "")
    total_cost   = payload.get("total_cost", 0.0)
    images_done  = payload.get("images_done", 0)
    videos_done  = payload.get("videos_done", 0)

    print(f"[Nervous System] Content ready: {product_name} — {images_done} images, {videos_done} videos (${total_cost:.2f})")


def _handle_content_batch_complete(payload):
    """Fired after a full batch run — ARIA reports to Dennis."""
    images_generated = payload.get("images_generated", 0)
    videos_generated = payload.get("videos_generated", 0)
    total_cost       = payload.get("total_cost", 0.0)
    batch_type       = payload.get("batch_type", "batch")

    print(f"[Nervous System] Content batch done: {images_generated} images, {videos_generated} videos — ${total_cost:.2f}")

    try:
        import os
        from app.agents.aria_intelligence import aria_think
        from app.agents.email_partner import send_email

        situation = (
            f"Mikisi content agent just completed a {batch_type}. "
            f"{images_generated} product images and {videos_generated} videos were generated and saved to Cloudinary. "
            f"Total generation cost: ${total_cost:.2f}. "
            f"Dennis needs a brief update on what content was produced and what the store looks like now."
        )
        result = aria_think(situation=situation, urgency="low")
        email_data = result.get("email_to_dennis", {}) if result else {}
        body    = email_data.get("body", "")
        subject = email_data.get("subject", f"Mikisi Content Update — {images_generated} images, {videos_generated} videos")
        dennis  = os.getenv("DENNIS_EMAIL")
        if body and dennis:
            send_email(dennis, subject, body, is_html=True)
            print(f"[Nervous System] ARIA content report sent to Dennis")
    except Exception as e:
        print(f"[Nervous System] ARIA content report error: {e}")


def _handle_content_needs_review(payload):
    content_id = payload.get("content_id")
    platform = payload.get("platform")
    score = payload.get("score")
    print(f"[Nervous System] 📋 Content needs review: ID {content_id} for {platform} (score: {score})")


def _handle_stock_low(payload):
    product_id = payload.get("product_id")
    stock = payload.get("stock")
    print(f"[Nervous System] ⚠️ Stock low: Product {product_id} has {stock} units remaining")


def _handle_stock_out(payload):
    name = payload.get("product_name", "Unknown product")
    print(f"[Nervous System] 🔴 Out of stock — hidden from store: {name}")


def _handle_stock_restored(payload):
    name = payload.get("product_name", "Unknown product")
    print(f"[Nervous System] 🟢 Back in stock — visible again: {name}")


def _handle_stock_sync_complete(payload):
    checked = payload.get("checked", 0)
    updated = payload.get("updated", 0)
    deactivated = payload.get("deactivated", 0)
    reactivated = payload.get("reactivated", 0)
    print(f"[Nervous System] 📦 Silverbene stock sync: {checked} checked | {updated} updated | {deactivated} out | {reactivated} restocked")

def _handle_content_posted(payload):
    content_id = payload.get("content_id")
    platform = payload.get("platform")
    product_name = payload.get("product_name")
    print(f"[Nervous System] 🌍 Content posted: {product_name} on {platform} (ID: {content_id})")
    # Future: analytics agent tracks engagement    

def _handle_complaint_received(payload):
    customer_email = payload.get("customer_email")
    summary = payload.get("summary")
    urgency = payload.get("urgency")
    print(f"[Nervous System] 🚨 Complaint received from {customer_email} — {summary} (urgency: {urgency})")
    # ARIA reviews and decides action


def _handle_customer_contacted(payload):
    customer_email = payload.get("customer_email")
    category = payload.get("category")
    auto_responded = payload.get("auto_responded", False)
    print(f"[Nervous System] 📧 Customer contacted: {customer_email} — {category} (auto: {auto_responded})") 

def _handle_performance_report(payload):
    report_type = payload.get("type")
    performance = payload.get("performance")
    alert_level = payload.get("alert_level")
    insight = payload.get("top_insight")
    revenue = payload.get("revenue", 0)
    print(f"[Nervous System] 📊 Performance report: {performance} | Alert: {alert_level} | Revenue: ${revenue:.2f}")
    if alert_level == "red":
        print(f"[Nervous System] 🚨 Red alert — {insight}")
        # Future: ARIA sends email to Dennis       