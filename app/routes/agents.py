from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision
from app.agents.orchestrator import run_full_cycle, set_monthly_vision, get_agent_status
from app.agents.goal_engine import set_goal, update_goal_progress, reflect_and_learn, get_active_goal, generate_improvement_plan
from app.agents.email_partner import send_opportunity_alert, send_sales_alert, check_inbox_for_replies, get_gmail_service
from app.agents.customer_service import run_customer_service
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