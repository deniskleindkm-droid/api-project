from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os

def run_market_check():
    print(f"[Scheduler] Running market check at {datetime.utcnow()}")
    try:
        from app.agents.analytics import run_analytics
        from app.agents.goal_engine import update_goal_progress, generate_improvement_plan
        from app.agents.email_partner import send_opportunity_alert
        import os

        # Update goal progress
        update_goal_progress()

        # Run analytics
        report = run_analytics()

        if report:
            alert_level = report.get("alert_level", "green")
            
            # Send alert if yellow or red
            if alert_level in ["yellow", "red"]:
                send_opportunity_alert(
                    opportunity=report.get("top_insight", "Business intelligence update"),
                    platform="BrandDrop Analytics",
                    data=f"Performance: {report.get('performance')} | Alert: {report.get('alert_reason')} | Recommendations: {report.get('recommendations', [])}"
                )
                print(f"[Scheduler] ✅ Alert sent to Dennis — Level: {alert_level}")
            else:
                print(f"[Scheduler] ✅ All green — no alert needed")

    except Exception as e:
        print(f"[Scheduler] Error: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    
    # Run market check every 6 hours
    scheduler.add_job(
        run_market_check,
        trigger=IntervalTrigger(hours=6),
        id='market_check',
        name='Market Check',
        replace_existing=True
    )
    
    scheduler.start()
    print("[Scheduler] ✅ ARIA scheduler started — checking every 6 hours")
    return scheduler