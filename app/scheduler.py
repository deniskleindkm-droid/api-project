from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime


def run_market_check():
    print(f"[Scheduler] Running market check at {datetime.utcnow()}")
    try:
        from app.agents.market_data import run_market_data_collection, get_latest_market_data
        from app.agents.aria_intelligence import aria_think
        from app.agents.analytics import run_analytics
        from app.agents.goal_engine import update_goal_progress
        from app.agents.email_partner import send_email
        import os
        import json

        print("[Scheduler] Fetching real beauty market data...")
        market_data = run_market_data_collection()

        update_goal_progress()

        from app.agents.analytics_agent import run_analytics_agent
        report = run_analytics_agent()

        market_context = ""
        if market_data:
            trends = market_data.get("trends", {}).get("trends", {})
            rising = [k for k, v in trends.items() if v.get("trend") == "rising"]
            beauty_trending = market_data.get("trending", {}).get("beauty_relevant", [])
            market_context = f"""
Mikisi is a women's beauty accessories store selling hair tools, skincare, jewelry and makeup accessories.
Google Trends beauty signals currently rising: {rising}.
Beauty trends spotted in general searches: {beauty_trending}.
Focus analysis on beauty market opportunities, not sneakers or streetwear.
"""

        aria_result = aria_think(
            situation=f"Weekly beauty market check for Mikisi. {market_context}. Analytics report: {json.dumps(report)[:500] if report else 'No report'}",
            urgency="medium"
        )

        if aria_result:
            urgency = aria_result.get("urgency_level", "low")
            if urgency in ["high", "medium"]:
                dennis_email = os.getenv("DENNIS_EMAIL")
                email_data = aria_result.get("email_to_dennis", {})
                subject = email_data.get("subject", "ARIA Beauty Market Update")
                body = email_data.get("body", "")
                if body and dennis_email:
                    send_email(dennis_email, subject, body, is_html=True)
                    print(f"[Scheduler] ✅ ARIA sent beauty intelligence email")

    except Exception as e:
        print(f"[Scheduler] Error: {e}")
        import traceback
        traceback.print_exc()


def run_silverbene_stock_sync():
    """
    Live stock sync — checks every Silverbene product's option_id against
    Silverbene's stock API and updates qty in our store.
    If stock hits 0, marks product inactive. Runs every 6 hours.
    """
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.models.product import Product
        from sqlmodel import Session, select
        from app.database import engine
        import json

        sb = SilverbeneAdapter()

        with Session(engine) as session:
            products = session.exec(
                select(Product).where(
                    Product.supplier_name == "Silverbene",
                    Product.is_active == True
                )
            ).all()

        if not products:
            print("[Silverbene Sync] No Silverbene products to check")
            return

        # Collect all option_ids (stored in cj_sku field)
        id_map = {}
        for p in products:
            option_id = p.cj_sku
            if option_id:
                id_map[str(option_id)] = p.id

        if not id_map:
            print("[Silverbene Sync] No option_ids found on products")
            return

        # Batch check stock — comma-separated option_ids
        batch_size = 50
        option_ids = list(id_map.keys())
        updated = 0
        deactivated = 0

        for i in range(0, len(option_ids), batch_size):
            batch = option_ids[i:i + batch_size]
            resp = sb._get("/api/dropshipping/option_qty", {
                "option_id": ",".join(batch)
            })

            if resp.get("code") != 0:
                print(f"[Silverbene Sync] Stock check error: {resp.get('message')}")
                continue

            stock_data = resp.get("data", [])
            if not isinstance(stock_data, list):
                continue

            with Session(engine) as session:
                for item in stock_data:
                    option_id = str(item.get("option_id", ""))
                    qty = int(item.get("qty", 0))
                    product_id = id_map.get(option_id)
                    if not product_id:
                        continue

                    product = session.get(Product, product_id)
                    if not product:
                        continue

                    if qty == 0 and product.is_active:
                        product.is_active = False
                        session.add(product)
                        deactivated += 1
                        print(f"[Silverbene Sync] ⚠ Out of stock — deactivated: {product.name[:50]}")
                    elif qty > 0 and product.stock != qty:
                        product.stock = qty
                        if not product.is_active:
                            product.is_active = True
                        session.add(product)
                        updated += 1

                session.commit()

        print(f"[Silverbene Sync] ✅ Done — {updated} updated, {deactivated} deactivated out of {len(products)} products")

    except Exception as e:
        import traceback
        print(f"[Silverbene Sync] Error: {e}")
        traceback.print_exc()


def run_signal_processor():
    try:
        from app.agents.nervous_system import process_signals
        process_signals()
    except Exception as e:
        print(f"[Scheduler] Signal processor error: {e}")


def run_tracking_check():
    try:
        from app.agents.tracking_agent import run_tracking_agent
        run_tracking_agent()
    except Exception as e:
        print(f"[Scheduler] Tracking check error: {e}")


def run_posting_check():
    try:
        from app.agents.posting_agent import run_posting_agent
        run_posting_agent()
    except Exception as e:
        print(f"[Scheduler] Posting agent error: {e}")


def run_customer_check():
    try:
        from app.agents.customer_agent import run_customer_agent
        run_customer_agent()
    except Exception as e:
        print(f"[Scheduler] Customer agent error: {e}")

def run_analytics_check():
    try:
        from app.agents.analytics_agent import run_analytics_agent
        run_analytics_agent()
    except Exception as e:
        print(f"[Scheduler] Analytics agent error: {e}")   

def run_bulk_import():
    try:
        from app.agents.bulk_import_agent import run_bulk_import_agent
        run_bulk_import_agent()
    except Exception as e:
        print(f"[Scheduler] Bulk import error: {e}")            


def run_aria_self_check():
    """ARIA proactively reads the store every 30 min and alerts Dennis if anything needs attention."""
    try:
        from app.agents.aria_intelligence import refresh_business_state, aria_think
        from app.agents.email_partner import send_email
        import os

        snap = refresh_business_state()
        print(f"[Scheduler] ARIA self-check: {snap['active_products']} products, ${snap['total_revenue']:.2f} revenue, health={snap['system_health']}")

        alerts = []
        if snap.get("products_missing_collection", 0) > 3:
            alerts.append(f"{snap['products_missing_collection']} products have no collection assigned")
        if snap.get("products_missing_images", 0) > 3:
            alerts.append(f"{snap['products_missing_images']} products are missing images")

        if alerts:
            situation = (
                f"ARIA self-check found issues: {'. '.join(alerts)}. "
                f"Store: {snap['active_products']} products, ${snap['total_revenue']:.2f} revenue, {snap['total_orders']} orders."
            )
            result = aria_think(situation=situation, urgency="high")
            email_data = result.get("email_to_dennis", {})
            body = email_data.get("body", "")
            subject = email_data.get("subject", "ARIA Store Alert")
            dennis_email = os.getenv("DENNIS_EMAIL")
            if body and dennis_email:
                send_email(dennis_email, subject, body, is_html=True)
                print(f"[Scheduler] ✅ ARIA self-check alert sent to Dennis")

    except Exception as e:
        print(f"[Scheduler] ARIA self-check error: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        run_market_check,
        trigger=IntervalTrigger(hours=6),
        id='market_check',
        name='ARIA Beauty Market Intelligence Check',
        replace_existing=True
    )

    scheduler.add_job(
        run_signal_processor,
        trigger=IntervalTrigger(seconds=30),
        id='signal_processor',
        name='Nervous System Signal Processor',
        replace_existing=True
    )

    scheduler.add_job(
        run_tracking_check,
        trigger=IntervalTrigger(hours=6),
        id='tracking_check',
        name='Order Tracking Agent',
        replace_existing=True
    )

    scheduler.add_job(
        run_posting_check,
        trigger=IntervalTrigger(hours=1),
        id='posting_check',
        name='Social Media Posting Agent',
        replace_existing=True
    )

    scheduler.add_job(
        run_customer_check,
        trigger=IntervalTrigger(hours=1),
        id='customer_check',
        name='Customer Agent Inbox Monitor',
        replace_existing=True
    )

    scheduler.add_job(
    run_analytics_check,
    trigger=IntervalTrigger(hours=6),
    id='analytics_check',
    name='Analytics Agent',
    replace_existing=True
    )

    scheduler.add_job(
    run_bulk_import,
    trigger=IntervalTrigger(hours=24),
    id='bulk_import',
    name='Bulk Product Import Agent',
    replace_existing=True
    )

    scheduler.add_job(
        run_aria_self_check,
        trigger=IntervalTrigger(minutes=30),
        id='aria_self_check',
        name='ARIA Self-Update & Proactive Store Monitor',
        replace_existing=True
    )

    scheduler.add_job(
        run_silverbene_stock_sync,
        trigger=IntervalTrigger(hours=6),
        id='silverbene_stock_sync',
        name='Silverbene Live Stock Sync',
        replace_existing=True
    )

    scheduler.start()
    print("[Scheduler] ✅ ARIA scheduler started with jobs:")
    print("[Scheduler]   → Market check: every 6 hours")
    print("[Scheduler]   → Signal processor: every 30 seconds")
    print("[Scheduler]   → Tracking agent: every 6 hours")
    print("[Scheduler]   → Posting agent: every 1 hour")
    print("[Scheduler]   → Customer agent: every 1 hour")
    print("[Scheduler]   → Analytics agent: every 6 hours")
    print("[Scheduler]   → Bulk import: every 24 hours")
    print("[Scheduler]   → ARIA self-check: every 30 minutes")
    print("[Scheduler]   → Silverbene stock sync: every 6 hours")