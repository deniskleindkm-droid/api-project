from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta


def _recently_ran(job_id: str, min_minutes: float) -> bool:
    """
    True if job_id completed within the last min_minutes. Several jobs below
    are registered with next_run_time=utcnow() so they don't get perpetually
    reset if the host restarts more often than their real interval (see each
    job's registration comment) -- but that means EVERY deploy re-fires them
    immediately, regardless of how recently they last actually ran. Found
    live 2026-07-21: with 10+ deploys in one session, this silently re-ran
    the full Silverbene-catalog stock sync and bulk-import pipeline (real
    Silverbene + Anthropic API calls) on every single one, burning through
    both APIs' usage far faster than the real "every N hours" cadence
    implies. This is the shared guard -- call at the top of any job that
    shouldn't just blindly re-run because the process restarted.
    """
    from app.agents.store_config import get_config
    last = get_config(f"_last_run_{job_id}", default="")
    if not last:
        return False
    try:
        return datetime.utcnow() - datetime.fromisoformat(last) < timedelta(minutes=min_minutes)
    except Exception:
        return False


def _mark_ran(job_id: str):
    from app.agents.store_config import set_config
    set_config(f"_last_run_{job_id}", datetime.utcnow().isoformat())


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
    if _recently_ran("silverbene_stock_sync", min_minutes=300):
        print("[Scheduler] Skipping silverbene_stock_sync — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.silverbene_stock_agent import run_silverbene_stock_agent
        run_silverbene_stock_agent()
        _mark_ran("silverbene_stock_sync")
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

            # Bulk import runs in the last 24h — the daily digest previously
            # had zero visibility into this agent's actual results at all
            # (only last_product_imported's single product NAME, no counts).
            # Found live 2026-07-21 when Dennis asked why ARIA always
            # reported "0 imports" despite real imports sometimes happening —
            # she genuinely had no real data to answer from.
            import_runs_24h = session.exec(
                select(AgentMemory)
                .where(AgentMemory.agent_name == "bulk_import_agent", AgentMemory.memory_type == "import_run")
                .where(AgentMemory.created_at >= datetime.utcnow() - timedelta(hours=24))
                .order_by(AgentMemory.id.desc())
            ).all()

        last_sync_ts = "never"
        if last_sync:
            try:
                last_sync_ts = json.loads(last_sync.content).get("timestamp", "")[:16] + " UTC"
            except Exception:
                pass

        imports_24h = 0
        rejects_24h = 0
        for run in import_runs_24h:
            try:
                c = json.loads(run.content)
                imports_24h += c.get("total_imported", 0)
                rejects_24h += c.get("total_rejected", 0)
            except Exception:
                pass
        import_summary = f"{imports_24h} imported, {rejects_24h} rejected across {len(import_runs_24h)} run(s)" if import_runs_24h else "no runs recorded"

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
            f"  Last stock sync: {last_sync_ts}\n"
            f"  Bulk imports (last 24h): {import_summary}\n\n"
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
        result = _monitor()
        # Previously always heartbeat("inbox scan complete") regardless of
        # outcome -- a failed IMAP connection (bad/missing credentials) and
        # a real successful scan looked identical in the logs, so a silent
        # credential failure could run forever with no visible sign anything
        # was wrong. Report what actually happened instead.
        if not result.get("connected"):
            _heartbeat("silverbene_shipping_monitor", "IMAP connection failed — check GMAIL_ADDRESS/GMAIL_APP_PASSWORD")
        else:
            _heartbeat(
                "silverbene_shipping_monitor",
                f"scanned {result.get('processed', 0)} email(s) — "
                f"{len(result.get('matched', []))} matched, "
                f"{len(result.get('unmatched', []))} unmatched, "
                f"{len(result.get('skipped', []))} skipped"
            )
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
    # Redundant with bulk_import_agent.py's own concurrency lock (which only
    # guards against overlap), but that lock clears as soon as one run
    # finishes -- this stops a second, non-overlapping full run from firing
    # on a deploy that lands minutes after the last one completed.
    if _recently_ran("bulk_import", min_minutes=1200):
        print("[Scheduler] Skipping bulk_import — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.bulk_import_agent import run_bulk_import_agent
        run_bulk_import_agent()
        _mark_ran("bulk_import")
    except Exception as e:
        print(f"[Scheduler] Bulk import error: {e}")


def run_specs_backfill():
    if _recently_ran("specs_backfill", min_minutes=1200):
        print("[Scheduler] Skipping specs_backfill — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.specs_backfill_agent import run_specs_backfill
        run_specs_backfill()
        _mark_ran("specs_backfill")
    except Exception as e:
        print(f"[Scheduler] Specs backfill error: {e}")


def run_catalog_audit():
    if _recently_ran("catalog_audit", min_minutes=1200):
        print("[Scheduler] Skipping catalog_audit — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.catalog_audit_agent import run_catalog_audit as _audit
        _audit()
        _mark_ran("catalog_audit")
    except Exception as e:
        print(f"[Scheduler] Catalog audit error: {e}")


def run_db_cleanup():
    if _recently_ran("db_cleanup", min_minutes=1200):
        print("[Scheduler] Skipping db_cleanup — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.db_cleanup_agent import run_db_cleanup as _cleanup
        _cleanup()
        _mark_ran("db_cleanup")
    except Exception as e:
        print(f"[Scheduler] DB cleanup error: {e}")


def run_balance_check():
    """
    Daily check: if Silverbene store credit drops below $50, email Dennis.
    Runs at 09:05 UTC (just after the daily digest).
    """
    if _recently_ran("balance_check", min_minutes=1200):
        print("[Scheduler] Skipping balance_check — ran recently (deploy re-fire guard)")
        return
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.agents.email_partner import send_email
        import os

        sb = SilverbeneAdapter()
        balance = sb.check_balance()
        _mark_ran("balance_check")

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


def run_instagram_catchup():
    """Hourly: posts the next item in Dennis's 12-item manual catch-up queue, if any remain."""
    try:
        from app.agents.instagram_agent import run_instagram_catchup_queue
        run_instagram_catchup_queue()
    except Exception as e:
        print(f"[Scheduler] Instagram catchup queue error: {e}")


def run_instagram_posting():
    """Daily 16:00 UTC (10:00 AM CST): post one piece of content to Instagram."""
    try:
        from app.agents.instagram_agent import run_instagram_agent
        run_instagram_agent()
        _heartbeat("instagram_agent", "posting cycle complete")
    except Exception as e:
        _heartbeat("instagram_agent", f"error: {str(e)[:80]}")
        print(f"[Scheduler] Instagram agent error: {e}")


def run_instagram_engagement_pull():
    """Daily 17:00 UTC: pull engagement metrics for posts that are 24h+ old."""
    try:
        from app.agents.instagram_agent import pull_engagement
        pull_engagement()
        _heartbeat("instagram_agent", "engagement pull complete")
    except Exception as e:
        _heartbeat("instagram_agent", f"engagement pull error: {str(e)[:80]}")
        print(f"[Scheduler] Instagram engagement pull error: {e}")


def run_order_recovery():
    if _recently_ran("order_recovery", min_minutes=25):
        return
    try:
        from app.agents.order_recovery_agent import run_order_recovery_agent
        run_order_recovery_agent()
        _heartbeat("order_recovery_agent", "order recovery cycle")
        _mark_ran("order_recovery")
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
    # IntervalTrigger(hours=24) computed "24h from whenever this job was last
    # (re)registered" — since the in-memory job store has no persistence across
    # restarts, every app restart reset the countdown back to a full 24h out.
    # On a host that redeploys/restarts more often than once a day, the job
    # could perpetually get reset and never actually fire. CronTrigger anchors
    # to a fixed wall-clock time instead, so it survives restarts — same
    # pattern already used for every other daily job in this file.
    trigger=CronTrigger(hour=4, minute=0),
    id='bulk_import',
    name='Bulk Product Import Agent — Daily 4:00 AM UTC',
    next_run_time=datetime.utcnow(),   # catch up the current backlog immediately on this deploy
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
        run_catalog_audit,
        trigger=IntervalTrigger(hours=24),
        id='catalog_audit',
        name='Catalog Audit — flag unrecognized attributes, suspicious chips, stale size/color data',
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

    # fal.ai + Runway video generation disabled — Silverbene images used directly
    # run_daily_content job removed

    scheduler.add_job(
        run_instagram_posting,
        trigger=CronTrigger(hour=16, minute=0),
        id='instagram_posting',
        name='Instagram Content Agent — Daily Post (10:00 AM CST)',
        replace_existing=True
    )

    # TEMPORARY — Dennis's 12-item manual catch-up batch, 2026-07-21. Posts
    # one item per hour, unattended; self-terminates (no-ops) once all 12
    # are done (see run_instagram_catchup_queue's docstring). Safe to remove
    # this job once the queue is confirmed complete (check
    # instagram_catchup_index in StoreConfig — done when it reaches 12).
    scheduler.add_job(
        run_instagram_catchup,
        trigger=IntervalTrigger(hours=1),
        id='instagram_catchup',
        name='Instagram Manual Catch-Up Queue — 12 items, ~1/hour (TEMPORARY, 2026-07-21)',
        next_run_time=datetime.utcnow(),   # post item 1 immediately on this deploy
        replace_existing=True
    )

    scheduler.add_job(
        run_instagram_engagement_pull,
        trigger=CronTrigger(hour=17, minute=0),
        id='instagram_engagement_pull',
        name='Instagram Engagement Pull — 24h metrics',
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
    print("[Scheduler]   → Instagram posting: daily at 16:00 UTC (10:00 AM CST)")
    print("[Scheduler]   → Instagram engagement pull: daily at 17:00 UTC")
    print("[Scheduler]   → Pinterest analytics: daily at 00:05 UTC")
    print("[Scheduler]   → Daily digest email: every day at 08:00 UTC")
    print("[Scheduler]   → TikTok token refresh: every day at 06:00 UTC")
    print("[Scheduler]   → Order recovery agent: every 30 minutes")
    print("[Scheduler]   → Silverbene shipping monitor: every 2 hours")