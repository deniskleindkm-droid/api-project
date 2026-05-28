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

        report = run_analytics()

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

    scheduler.start()
    print("[Scheduler] ✅ ARIA scheduler started — checking every 6 hours with real beauty market data")
    return scheduler