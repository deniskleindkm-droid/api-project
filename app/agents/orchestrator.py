import json
import os
import time
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import MonthlyVision, AgentMemory
from app.agents.market_intelligence import run_market_intelligence
from app.agents.product_scout import run_product_scout
from app.agents.store_manager import run_store_manager
from app.agents.marketing import run_marketing
from app.agents.analytics import run_analytics

def set_monthly_vision(vision, target_market, target_products, target_locations):
    with Session(engine) as session:
        existing = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).all()
        for v in existing:
            v.is_active = False
            session.add(v)
        
        month = datetime.utcnow().strftime("%Y-%m")
        new_vision = MonthlyVision(
            month=month,
            vision=vision,
            target_market=target_market,
            target_products=target_products,
            target_locations=target_locations,
            is_active=True
        )
        session.add(new_vision)
        session.commit()
        print(f"[Orchestrator] ✅ Vision set for {month}: {vision}")

def get_agent_status():
    with Session(engine) as session:
        memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()
        
        status = {}
        for memory in memories:
            if memory.agent_name not in status:
                status[memory.agent_name] = {
                    "last_active": memory.created_at.isoformat(),
                    "last_action": memory.content[:100]
                }
        return status

def run_full_cycle(market_topic=None, market_platform=None, market_content=None):
    print("\n" + "="*60)
    print(f"[Orchestrator] Starting agent cycle at {datetime.utcnow()}")
    print("="*60)
    
    # Step 1 - Market Intelligence
    if market_topic and market_content:
        print("\n[Orchestrator] Step 1: Market Intelligence")
        run_market_intelligence(
            topic=market_topic,
            platform=market_platform or "web",
            raw_content=market_content
        )
    
    # Step 2 - Product Scout
    print("\n[Orchestrator] Step 2: Product Scout")
    run_product_scout()
    
    # Step 3 - Store Manager
    print("\n[Orchestrator] Step 3: Store Manager")
    run_store_manager()
    
    # Step 4 - Marketing
    print("\n[Orchestrator] Step 4: Marketing Agent")
    run_marketing()
    
    # Step 5 - Analytics
    print("\n[Orchestrator] Step 5: Analytics Agent")
    report = run_analytics()
    
    print("\n" + "="*60)
    print("[Orchestrator] Cycle complete")
    print("="*60 + "\n")
    
    return report