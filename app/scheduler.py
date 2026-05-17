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

        # Step 1 - Collect real market data
        print("[Scheduler] Fetching real market data...")
        market_data = run_market_data_collection()

        # Step 2 - Update goal progress
        update_goal_progress()

        # Step 3 - Run analytics
        report = run_analytics()

        # Step 4 - ARIA analyzes everything with real data
        market_context = ""
        if market_data:
            trends = market_data.get("trends", {}).get("trends", {})
            rising = [k for k, v in trends.items() if v.get("trend") == "rising"]
            market_context = f"Real Google Trends data shows these rising: {rising}"

        aria_result = aria_think(
            situation=f"Weekly market check. {market_context}. Analytics report: {json.dumps(report)[:500] if report else 'No report'}",
            urgency="medium"
        )

        # Step 5 - Send email if important
        if aria_result:
            urgency = aria_result.get("urgency_level", "low")
            if urgency in ["high", "medium"]:
                dennis_email = os.getenv("DENNIS_EMAIL")
                email_data = aria_result.get("email_to_dennis", {})
                subject = email_data.get("subject", "ARIA Intelligence Update")
                body = email_data.get("body", "")
                if body and dennis_email:
                    send_email(dennis_email, subject, body, is_html=True)
                    print(f"[Scheduler] ✅ ARIA sent intelligence email")

    except Exception as e:
        print(f"[Scheduler] Error: {e}")
        import traceback
        traceback.print_exc()

def start_scheduler():
    scheduler = BackgroundScheduler()
    
    scheduler.add_job(
        run_market_check,
        trigger=IntervalTrigger(hours=6),
        id='market_check',
        name='ARIA Market Intelligence Check',
        replace_existing=True
    )
    
    scheduler.start()
    print("[Scheduler] ✅ ARIA scheduler started — checking every 6 hours with real market data")
    return scheduler