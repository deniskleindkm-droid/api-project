from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.signal import SystemSignal
import json


def emit(signal_type, sender, payload=None, receiver=None, priority=5):
    """
    Any agent calls this to send a signal through the nervous system.
    
    Examples:
    emit("PRODUCT_IMPORTED", "product_agent", {"product_id": 16, "name": "Jade Roller"})
    emit("ORDER_FAILED", "order_agent", {"order_id": 123}, priority=1)
    emit("TREND_DETECTED", "market_agent", {"keyword": "gua sha", "trend": "rising"}, receiver="product_agent")
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
    """
    Get pending signals for a specific receiver or all broadcasts.
    Ordered by priority (1=critical first) then by created_at.
    """
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
    """Mark a signal as processed."""
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "processed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()


def mark_failed(signal_id, reason=""):
    """Mark a signal as failed."""
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "failed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()
            print(f"[Nervous System] ❌ Signal {signal_id} failed: {reason}")


def get_signal_payload(signal):
    """Safely parse signal payload."""
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
            
            # Route to correct handler
            if signal.signal_type == "PRODUCT_IMPORTED":
                _handle_product_imported(payload)

            elif signal.signal_type == "TREND_DETECTED":
                _handle_trend_detected(payload)

            elif signal.signal_type == "ORDER_FAILED":
                _handle_order_failed(payload)

            elif signal.signal_type == "STOCK_LOW":
                _handle_stock_low(payload)

            elif signal.signal_type == "COLLECTION_ASSIGNED":
                pass  # No action needed — logged only

            elif signal.signal_type == "ORDER_PLACED":
                pass  # Handled by payments webhook already

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
    """When a product is imported — notify ARIA and log"""
    product_id = payload.get("product_id")
    product_name = payload.get("name")
    collection_id = payload.get("collection_id")
    print(f"[Nervous System] ✅ Product imported: {product_name} (ID: {product_id}) → Collection {collection_id}")
    # Future: trigger content agent


def _handle_trend_detected(payload):
    """When a trend is detected — trigger product search"""
    keyword = payload.get("keyword")
    trend = payload.get("trend")
    print(f"[Nervous System] 📈 Trend detected: {keyword} is {trend}")
    # Future: trigger product agent to search and score


def _handle_order_failed(payload):
    """When an order fails — signal ARIA immediately"""
    order_id = payload.get("order_id")
    reason = payload.get("reason")
    print(f"[Nervous System] 🚨 Order failed: {order_id} — {reason}")
    # Future: ARIA decides whether to retry or notify Dennis


def _handle_stock_low(payload):
    """When stock is low — signal ARIA"""
    product_id = payload.get("product_id")
    stock = payload.get("stock")
    print(f"[Nervous System] ⚠️ Stock low: Product {product_id} has {stock} units remaining")
    # Future: ARIA decides whether to restock or remove product    

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
    """
    Get pending signals for a specific receiver or all broadcasts.
    Ordered by priority then by created_at.
    """
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
    """Mark a signal as processed."""
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "processed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()


def mark_failed(signal_id, reason=""):
    """Mark a signal as failed."""
    with Session(engine) as session:
        signal = session.get(SystemSignal, signal_id)
        if signal:
            signal.status = "failed"
            signal.processed_at = datetime.utcnow()
            session.add(signal)
            session.commit()
            print(f"[Nervous System] ❌ Signal {signal_id} failed: {reason}")


def get_signal_payload(signal):
    """Safely parse signal payload."""
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

            elif signal.signal_type == "STOCK_LOW":
                _handle_stock_low(payload)

            elif signal.signal_type == "COLLECTION_ASSIGNED":
                pass

            elif signal.signal_type == "ORDER_PLACED":
                pass

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
    """When a product is imported — notify ARIA and log"""
    product_id = payload.get("product_id")
    product_name = payload.get("name")
    collection_id = payload.get("collection_id")
    print(f"[Nervous System] ✅ Product imported: {product_name} (ID: {product_id}) → Collection {collection_id}")
    # Future: trigger content agent


def _handle_product_approved(payload):
    """Product scored above threshold — auto import it"""
    name = payload.get("name")
    score = payload.get("total_score")
    print(f"[Nervous System] ✅ Auto-importing approved product: {name} (score: {score})")
    # Future: trigger actual import through supplier interface


def _handle_product_needs_review(payload):
    """Product scored below threshold — needs review"""
    name = payload.get("name")
    score = payload.get("total_score")
    reason = payload.get("reason")
    print(f"[Nervous System] 📋 Product needs review: {name} (score: {score}) — {reason}")
    # Future: ARIA reviews and decides


def _handle_product_needs_collection(payload):
    """Product landed in Uncategorized — signal ARIA to review"""
    product_name = payload.get("product_name")
    category = payload.get("category")
    print(f"[Nervous System] 📋 Product needs collection review: {product_name} — {category}")
    # Future: ARIA reviews and assigns correct collection


def _handle_trend_detected(payload):
    """When a trend is detected — search and score products"""
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
    """When an order fails — signal ARIA immediately"""
    order_id = payload.get("order_id")
    reason = payload.get("reason")
    print(f"[Nervous System] 🚨 Order failed: {order_id} — {reason}")
    # Future: ARIA decides whether to retry or notify Dennis


def _handle_stock_low(payload):
    """When stock is low — signal ARIA"""
    product_id = payload.get("product_id")
    stock = payload.get("stock")
    print(f"[Nervous System] ⚠️ Stock low: Product {product_id} has {stock} units remaining")
    # Future: ARIA decides whether to restock or remove product