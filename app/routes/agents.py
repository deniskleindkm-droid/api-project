from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision
from app.agents.orchestrator import run_full_cycle, set_monthly_vision, get_agent_status
from app.agents.goal_engine import set_goal, update_goal_progress, reflect_and_learn, get_active_goal, generate_improvement_plan
from app.agents.email_partner import send_opportunity_alert, send_sales_alert, check_inbox_for_replies, get_gmail_service
from app.agents.customer_service import run_customer_service
from app.agents.aria_intelligence import why_engine, quantum_possibilities, challenge_assumptions, aria_think, aria_analyze_market, aria_morning_briefing
from app.agents.aria_security import verify_master_key, scan_for_injection, scan_for_data_poisoning, devils_advocate, get_security_report, check_immutable_core_violation
from app.agents.market_data import run_market_data_collection, get_latest_market_data
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter()

class VisionRequest(BaseModel):
    vision: str
    target_market: str
    target_products: str
    target_locations: str

class MarketRequest(BaseModel):
    topic: str
    platform: str
    content: str

class CustomerQuestion(BaseModel):
    question: str
    customer_email: Optional[str] = None

@router.post("/agents/vision")
def set_vision(request: VisionRequest):
    set_monthly_vision(
        vision=request.vision,
        target_market=request.target_market,
        target_products=request.target_products,
        target_locations=request.target_locations
    )
    return {"message": "Vision set successfully"}

@router.post("/agents/run")
def run_agents(request: Optional[MarketRequest] = None):
    try:
        if request:
            report = run_full_cycle(
                market_topic=request.topic,
                market_platform=request.platform,
                market_content=request.content
            )
        else:
            report = run_full_cycle()
        return {"message": "Agent cycle complete", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/status")
def agent_status():
    return get_agent_status()

@router.get("/agents/memories")
def get_memories(session: Session = Depends(get_session)):
    memories = session.exec(
        select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(50)
    ).all()
    return memories

@router.get("/agents/tasks")
def get_tasks(session: Session = Depends(get_session)):
    tasks = session.exec(
        select(AgentTask).order_by(AgentTask.created_at.desc()).limit(50)
    ).all()
    return tasks

@router.get("/agents/insights")
def get_insights(session: Session = Depends(get_session)):
    insights = session.exec(
        select(MarketInsight).order_by(MarketInsight.created_at.desc()).limit(20)
    ).all()
    return insights

@router.get("/agents/report")
def get_latest_report(session: Session = Depends(get_session)):
    memory = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == "analytics",
            AgentMemory.memory_type == "report"
        ).order_by(AgentMemory.created_at.desc())
    ).first()
    if not memory:
        return {"message": "No report yet"}
    return json.loads(memory.content)

@router.post("/agents/ask")
def ask_customer_service(question: CustomerQuestion):
    result = run_customer_service(
        question=question.question,
        customer_email=question.customer_email
    )
    return result

@router.get("/agents/vision")
def get_vision(session: Session = Depends(get_session)):
    vision = session.exec(
        select(MonthlyVision).where(MonthlyVision.is_active == True)
    ).first()
    if not vision:
        return {"message": "No active vision"}
    return vision

class GoalRequest(BaseModel):
    goal: str
    deadline: str
    metric: str
    target_value: float

class LearningRequest(BaseModel):
    agent_name: str
    action: str
    outcome: str
    lesson: str
    metric: Optional[str] = None
    metric_value: Optional[float] = None

@router.post("/agents/goal")
def set_agent_goal(request: GoalRequest):
    try:
        goal, breakdown = set_goal(
            goal=request.goal,
            deadline=request.deadline,
            metric=request.metric,
            target_value=request.target_value
        )
        return {"message": "Goal set successfully", "breakdown": breakdown}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/goal")
def get_goal():
    goal = get_active_goal()
    if not goal:
        return {"message": "No active goal"}
    return goal

@router.post("/agents/goal/progress")
def check_progress():
    goal = update_goal_progress()
    if not goal:
        return {"message": "No active goal"}
    return {"goal": goal.goal, "current": goal.current_value, "target": goal.target_value, "status": goal.status}

@router.post("/agents/reflect")
def add_learning(request: LearningRequest):
    reflect_and_learn(
        agent_name=request.agent_name,
        action=request.action,
        outcome=request.outcome,
        lesson=request.lesson,
        metric=request.metric,
        metric_value=request.metric_value
    )
    return {"message": "Learning recorded"}

@router.post("/agents/improve")
def improve():
    try:
        plan = generate_improvement_plan()
        if not plan:
            return {"message": "Set a goal first using POST /agents/goal"}
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
class AlertRequest(BaseModel):
    opportunity: str
    platform: str
    data: str

class SalesAlertRequest(BaseModel):
    metric: str
    value: str
    context: str

@router.post("/agents/email/opportunity")
def send_opportunity(request: AlertRequest):
    try:
        result = send_opportunity_alert(
            opportunity=request.opportunity,
            platform=request.platform,
            data=request.data
        )
        return {"message": "Alert sent", "email": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agents/email/sales-alert")
def send_sales(request: SalesAlertRequest):
    try:
        result = send_sales_alert(
            metric=request.metric,
            value=request.value,
            context=request.context
        )
        return {"message": "Sales alert sent", "email": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/email/check-inbox")
def check_inbox():
    try:
        reply = check_inbox_for_replies()
        if reply:
            return {"found": True, "reply": reply}
        return {"found": False, "message": "No new replies"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/email/setup")
def setup_gmail():
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        return {"message": "Gmail connected", "email": profile.get('emailAddress')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
class AriaThinkRequest(BaseModel):
    situation: str
    urgency: Optional[str] = "medium"

class AriaMarketRequest(BaseModel):
    platform: str
    content: str
    topic: str

class WhyRequest(BaseModel):
    observation: str
    context: Optional[str] = ""

class AssumptionRequest(BaseModel):
    belief: str
    evidence: Optional[str] = ""

class QuantumRequest(BaseModel):
    situation: str
    constraints: Optional[str] = ""

@router.post("/aria/think")
def aria_think_route(request: AriaThinkRequest):
    try:
        result = aria_think(
            situation=request.situation,
            urgency=request.urgency
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/why")
def aria_why_route(request: WhyRequest):
    try:
        result = why_engine(
            observation=request.observation,
            context=request.context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/quantum")
def aria_quantum_route(request: QuantumRequest):
    try:
        result = quantum_possibilities(
            situation=request.situation,
            constraints=request.constraints
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/challenge")
def aria_challenge_route(request: AssumptionRequest):
    try:
        result = challenge_assumptions(
            belief=request.belief,
            evidence=request.evidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/market")
def aria_market_route(request: AriaMarketRequest):
    try:
        result = aria_analyze_market(
            platform=request.platform,
            content=request.content,
            topic=request.topic
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/aria/briefing")
def aria_briefing_route():
    try:
        result = aria_morning_briefing()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
class MasterKeyRequest(BaseModel):
    master_key: str

class SecurityScanRequest(BaseModel):
    master_key: str
    content: str
    source: Optional[str] = "unknown"

class DevilsAdvocateRequest(BaseModel):
    master_key: str
    recommendation: str
    context: Optional[str] = ""

class ImmutableCoreCheckRequest(BaseModel):
    master_key: str
    recommendation: str

@router.get("/aria/security/report")
def security_report(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized — invalid master key")
    return get_security_report()

@router.post("/aria/security/scan")
def security_scan(request: SecurityScanRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized — invalid master key")
    injection_check = scan_for_injection(request.content)
    data_check = scan_for_data_poisoning(request.content, request.source)
    return {
        "injection_scan": injection_check,
        "data_poisoning_scan": data_check,
        "overall_safe": injection_check["safe"] and data_check["safe"]
    }

@router.post("/aria/security/devils-advocate")
def devils_advocate_route(request: DevilsAdvocateRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized — invalid master key")
    try:
        result = devils_advocate(request.recommendation, request.context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/security/check-core")
def check_core_route(request: ImmutableCoreCheckRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized — invalid master key")
    return check_immutable_core_violation(request.recommendation)

@router.post("/aria/think")
def aria_think_protected(request: AriaThinkRequest, master_key: str = ""):
    if master_key and not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        result = aria_think(request.situation, request.urgency)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))  
    
@router.post("/market/fetch")
def fetch_market_data():
    try:
        result = run_market_data_collection()
        if result:
            return {"message": "Market data fetched", "data": result}
        return {"message": "No data retrieved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/market/latest")
def get_market_data():
    try:
        data = get_latest_market_data()
        if data:
            return data
        return {"message": "No market data yet — run POST /market/fetch first"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))    