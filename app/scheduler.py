from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
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

        _heartbeat("market_data", "market intelligence cycle complete")
        _heartbeat("goal_engine", "goal progress updated")

    except Exception as e:
        print(f"[Scheduler] Error: {e}")
        import traceback
        traceback.print_exc()


def _heartbeat(agent_name: str, note: str = ""):
    """Write a heartbeat to AgentMemory so the command center shows the agent as active."""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.agent import AgentMemory
        import json
        from datetime import datetime
        with Session(engine) as session:
            session.add(AgentMemory(
                agent_name=agent_name,
                memory_type="heartbeat",
                content=json.dumps({"timestamp": datetime.utcnow().isoformat(), "note": note}),
                confidence=0.9
            ))
            session.commit()
    except Exception as e:
        print(f"[Scheduler] Heartbeat error for {agent_name}: {e}")


def run_silverbene_stock_sync():
    """Delegates to the dedicated Silverbene Stock Agent."""
    try:
        from app.agents.silverbene_stock_agent import run_silverbene_stock_agent
        run_silverbene_stock_agent()
    except Exception as e:
        print(f"[Scheduler] Silverbene stock agent error: {e}")


def run_pinterest_analytics():
    """Daily midnight: pull Pinterest pin metrics into analytics table."""
    try:
        from app.agents.pinterest_agent import pull_analytics
        result = pull_analytics()
        _heartbeat("pinterest_agent", f"analytics pulled: {result.get('pins_synced',0)} pins")
    except Exception as e:
        _heartbeat("pinterest_agent", f"analytics error: {str(e)[:80]}")
        print(f"[Scheduler] Pinterest analytics error: {e}")


def run_daily_digest():
    """
    Daily 08:00 UTC: email Dennis a store health summary regardless of changes.
    Covers stock sync status, product counts, flagged items, system health.
    """
    try:
        from sqlmodel import Session, select, func
        from app.database import engine
        from app.models.product import Product
        from app.models.order import Order
        from app.models.agent import AgentMemory
        from app.agents.aria_intelligence import aria_think
        from app.agents.email_partner import send_email
        from app.agents.store_config import get_config
        import json, os
        from datetime import datetime, timedelta

        with Session(engine) as session:
            total_active   = session.exec(select(func.count()).select_from(Product).where(Product.is_active == True)).one()
            out_of_stock   = session.exec(select(func.count()).select_from(Product).where(Product.is_active == True, Product.stock == 0)).one()
            low_stock      = session.exec(select(func.count()).select_from(Product).where(Product.is_active == True, Product.stock > 0, Product.stock <= 10)).one()
            no_image       = session.exec(select(func.count()).select_from(Product).where(Product.is_active == True, Product.content_image_url == None)).one()
            pinned         = session.exec(select(func.count()).select_from(Product).where(Product.pinterest_pin_id != None)).one()
            needs_review   = session.exec(select(func.count()).select_from(Product).where(Product.needs_length_review == True)).one()
            orders_today   = session.exec(select(func.count()).select_from(Order).where(
                Order.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
            )).one()

            # Last stock sync
            last_sync = session.exec(
                select(AgentMemory)
                .where(AgentMemory.agent_name == "silverbene_stock_agent", AgentMemory.memory_type == "sync_run")
                .order_by(AgentMemory.id.desc()).limit(1)
            ).first()

        last_sync_ts = "never"
        if last_sync:
            try:
                last_sync_ts = json.loads(last_sync.content).get("timestamp", "")[:16] + " UTC"
            except Exception:
                pass

        situation = (
            f"Daily Mikisi store digest for Dennis — {datetime.utcnow().strftime('%A %d %B %Y')}.\n\n"
            f"Store snapshot:\n"
            f"  Active products: {total_active}\n"
            f"  Out of stock: {out_of_stock}\n"
            f"  Low stock (≤10 units): {low_stock}\n"
            f"  Missing AI images: {no_image}\n"
            f"  Pinterest pinned: {pinned}/{total_active}\n"
            f"  Products flagged for review: {needs_review}\n"
            f"  Orders today: {orders_today}\n"
            f"  Last stock sync: {last_sync_ts}\n\n"
            f"Write Dennis a clean, confident daily store digest. Mikisi tone — elegant and direct. "
            f"Highlight anything that needs attention. If everything looks good, say so clearly. "
            f"Keep it under 200 words."
        )

        result = aria_think(situation=situation, urgency="low")
        dennis_email = os.getenv("DENNIS_EMAIL")
        if dennis_email and result:
            email_data = result.get("email_to_dennis", {})
            subject = email_data.get("subject", f"Mikisi Daily Digest — {datetime.utcnow().strftime('%d %b %Y')}")
            body    = email_data.get("body", "")
            if body:
                send_email(dennis_email, subject, body, is_html=True)
                print(f"[Scheduler] Daily digest sent to Dennis")

        _heartbeat("aria", "daily digest sent")

    except Exception as e:
        print(f"[Scheduler] Daily digest error: {e}")


def run_signal_processor():
    try:
        from app.agents.nervous_system import process_signals
        process_signals()
        _heartbeat("nervous_system_processor", "signal processing cycle")
    except Exception as e:
        print(f"[Scheduler] Signal processor error: {e}")


def run_tracking_check():
    try:
        from app.agents.tracking_agent import run_tracking_agent
        run_tracking_agent()
        _heartbeat("tracking_agent", "order tracking cycle")
    except Exception as e:
        _heartbeat("tracking_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Tracking check error: {e}")


def run_silverbene_shipping_monitor():
    """Every 2 hours: scan hello@mikisi.co for Silverbene shipping emails and auto-notify customers."""
    try:
        from app.agents.silverbene_shipping_monitor import run_silverbene_shipping_monitor as _monitor
        _monitor()
        _heartbeat("silverbene_shipping_monitor", "inbox scan complete")
    except Exception as e:
        _heartbeat("silverbene_shipping_monitor", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Silverbene shipping monitor error: {e}")


def run_tiktok_token_refresh():
    """
    Daily refresh of the TikTok access token using the stored refresh token.
    Runs at 06:00 UTC — well within the 24h access token lifetime.
    If refresh fails (refresh token itself expired/revoked), email Dennis
    with a link to re-authorize, since that step requires human OAuth consent.
    """
    try:
        from app.agents.tiktok_token import refresh
        refresh()
        _heartbeat("tiktok_token_refresh", "TikTok token refreshed")
    except Exception as e:
        _heartbeat("tiktok_token_refresh", f"error: {str(e)[:80]}")
        print(f"[Scheduler] TikTok token refresh error: {e}")
        try:
            from app.agents.email_partner import send_email
            import os
            dennis = os.getenv("DENNIS_EMAIL")
            if dennis:
                send_email(
                    to=dennis,
                    subject="ACTION REQUIRED — TikTok token refresh failed",
                    body="""<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#c0392b;">ACTION REQUIRED — TikTok token refresh failed</h2>
<p>Your TikTok access token could not be refreshed automatically. You need to re-authorize once by clicking this link:</p>
<p><a href="https://api-project-production-d424.up.railway.app/auth/tiktok/login">https://api-project-production-d424.up.railway.app/auth/tiktok/login</a></p>
<p>This takes 30 seconds and will restore automatic posting to @mikisiproducts.</p>
</body></html>""",
                    is_html=True,
                )
        except Exception as email_err:
            print(f"[Scheduler] Failed to send TikTok refresh alert email: {email_err}")


def run_posting_check():
    try:
        from app.agents.posting_agent import run_posting_agent
        run_posting_agent()
        _heartbeat("posting_agent", "social posting cycle")
    except Exception as e:
        _heartbeat("posting_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Posting agent error: {e}")


def run_customer_check():
    try:
        from app.agents.customer_agent import run_customer_agent
        run_customer_agent()
        _heartbeat("customer_agent", "customer inbox cycle")
    except Exception as e:
        _heartbeat("customer_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Customer agent error: {e}")


def run_analytics_check():
    try:
        from app.agents.analytics_agent import run_analytics_agent
        run_analytics_agent()
        _heartbeat("analytics_agent", "analytics cycle")
    except Exception as e:
        _heartbeat("analytics_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Analytics agent error: {e}")


def run_bulk_import():
    try:
        from app.agents.bulk_import_agent import run_bulk_import_agent
        run_bulk_import_agent()
    except Exception as e:
        print(f"[Scheduler] Bulk import error: {e}")


def run_specs_backfill():
    try:
        from app.agents.specs_backfill_agent import run_specs_backfill
        run_specs_backfill()
    except Exception as e:
        print(f"[Scheduler] Specs backfill error: {e}")


def run_db_cleanup():
    try:
        from app.agents.db_cleanup_agent import run_db_cleanup as _cleanup
        _cleanup()
    except Exception as e:
        print(f"[Scheduler] DB cleanup error: {e}")


def run_balance_check():
    """
    Daily check: if Silverbene store credit drops below $50, email Dennis.
    Runs at 09:05 UTC (just after the daily digest).
    """
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.agents.email_partner import send_email
        import os

        sb = SilverbeneAdapter()
        balance = sb.check_balance()

        if balance < 0:
            print("[Balance Check] Could not retrieve Silverbene balance — endpoint may not exist yet")
            return

        print(f"[Balance Check] Silverbene store credit: ${balance:.2f}")

        LOW_BALANCE_THRESHOLD = 50.0
        if balance < LOW_BALANCE_THRESHOLD:
            dennis = os.getenv("DENNIS_EMAIL")
            if dennis:
                send_email(
                    to=dennis,
                    subject=f"⚠️ Silverbene balance low: ${balance:.2f} remaining",
                    body=f"""<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#c0392b;">⚠️ Silverbene Store Credit Low</h2>
<p>Your Silverbene dropshipping balance has dropped below ${LOW_BALANCE_THRESHOLD:.0f}.</p>
<p><b>Current balance: ${balance:.2f}</b></p>
<p>Top up now to avoid order failures:</p>
<ul>
  <li>Contact Jacky: <a href="mailto:jackyli@silverbene.com">jackyli@silverbene.com</a></li>
  <li>WhatsApp: +86 180 2239 4913</li>
</ul>
<p style="color:#666;font-size:13px;">This alert fires daily when balance is below ${LOW_BALANCE_THRESHOLD:.0f}.</p>
</body></html>""",
                    is_html=True,
                )
                print(f"[Balance Check] Low balance alert sent to Dennis (${balance:.2f})")
    except Exception as e:
        print(f"[Scheduler] Balance check error: {e}")


def run_daily_content():
    """
    Daily content job: generate 2 videos per category for newest products.
    Runs at 09:00 UTC — generates up to 12 videos/day.
    Images are generated at import time, not here.
    """
    try:
        from app.agents.content_agent import run_daily_video_batch
        run_daily_video_batch()
        _heartbeat("content_agent", "daily video batch complete")
    except Exception as e:
        _heartbeat("content_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Content agent error: {e}")            


def run_order_recovery():
    try:
        from app.agents.order_recovery_agent import run_order_recovery_agent
        run_order_recovery_agent()
        _heartbeat("order_recovery_agent", "order recovery cycle")
    except Exception as e:
        print(f"[Scheduler] Order recovery error: {e}")


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
        run_specs_backfill,
        trigger=IntervalTrigger(hours=24),
        id='specs_backfill',
        name='Specs Backfill — populate product details from Silverbene',
        next_run_time=datetime.utcnow(),
        replace_existing=True
    )

    scheduler.add_job(
        run_order_recovery,
        trigger=IntervalTrigger(minutes=30),
        id='order_recovery',
        name='Order Recovery Agent — Auto-retry failed Silverbene orders',
        next_run_time=datetime.utcnow(),
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
        run_daily_content,
        trigger=IntervalTrigger(hours=24),
        id='daily_content',
        name='Content Agent — Daily Video Batch',
        replace_existing=True
    )

    scheduler.add_job(
        run_silverbene_stock_sync,
        trigger=IntervalTrigger(hours=6),
        id='silverbene_stock_sync',
        name='Silverbene Live Stock Sync',
        next_run_time=datetime.utcnow(),   # run immediately on startup, then every 6h
        replace_existing=True
    )

    scheduler.add_job(
        run_pinterest_analytics,
        trigger=CronTrigger(hour=0, minute=5),
        id='pinterest_analytics',
        name='Pinterest Daily Analytics Pull',
        replace_existing=True
    )

    scheduler.add_job(
        run_daily_digest,
        trigger=CronTrigger(hour=8, minute=0),
        id='daily_digest',
        name='ARIA Daily Store Digest Email',
        replace_existing=True
    )

    scheduler.add_job(
        run_balance_check,
        trigger=CronTrigger(hour=9, minute=5),
        id='balance_check',
        name='Silverbene Store Credit Balance Monitor',
        next_run_time=datetime.utcnow(),
        replace_existing=True
    )

    scheduler.add_job(
        run_db_cleanup,
        trigger=CronTrigger(hour=3, minute=0),
        id='db_cleanup',
        name='DB Cleanup — hard-delete dead non-Silverbene products',
        next_run_time=datetime.utcnow(),   # run immediately on startup to clear existing junk
        replace_existing=True
    )

    scheduler.add_job(
        run_tiktok_token_refresh,
        trigger=CronTrigger(hour=6, minute=0),
        id='tiktok_token_refresh',
        name='TikTok Access Token Auto-Refresh',
        replace_existing=True
    )

    scheduler.add_job(
        run_silverbene_shipping_monitor,
        trigger=IntervalTrigger(hours=2),
        id='silverbene_shipping_monitor',
        name='Silverbene Shipping Email Monitor — Auto-notify customers',
        next_run_time=datetime.utcnow(),
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
    print("[Scheduler]   → Content agent (daily videos): every 24 hours")
    print("[Scheduler]   → Pinterest analytics: daily at 00:05 UTC")
    print("[Scheduler]   → Daily digest email: every day at 08:00 UTC")
    print("[Scheduler]   → TikTok token refresh: every day at 06:00 UTC")
    print("[Scheduler]   → Order recovery agent: every 30 minutes")
    print("[Scheduler]   → Silverbene shipping monitor: every 2 hours")