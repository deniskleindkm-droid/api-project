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
from app.agents.aria_memory import store_episode, get_relevant_episodes, store_knowledge, get_domain_knowledge, update_dennis_model, get_dennis_model, get_active_predictions, get_full_memory_context, aria_learn_from_outcome
from app.agents.aria_core import quantum_execute, get_pending_actions, approve_action, reject_action, neural_learn, get_aria_intelligence_summary, list_capabilities
from app.agents.aria_developer import quantum_develop, aria_design_agent, aria_build_agent, aria_explain, get_changelog
from app.agents.cj_dropshipping import search_and_import, search_products
from app.agents.cj_dropshipping import search_and_import, search_products, import_product_by_id
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
        from app.agents.email_partner import send_email
        from app.models.agent import AgentMemory
        from sqlmodel import Session, select
        from app.database import engine
        import os

        # Pull recent chat conversations
        with Session(engine) as session:
            recent_chats = session.exec(
                select(AgentMemory).where(
                    AgentMemory.memory_type == "conversation"
                ).order_by(AgentMemory.created_at.desc()).limit(10)
            ).all()

        import json
        chat_summary = []
        for chat in reversed(recent_chats):
            try:
                data = json.loads(chat.content)
                chat_summary.append(
                    f"Dennis: {data.get('user', '')}\n"
                    f"ARIA: {data.get('aria', '')[:200]}"
                )
            except:
                pass

        context = "\n\n".join(chat_summary)

        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""You are ARIA — Dennis's business partner.

Based on your recent conversations with Dennis, write him a focused email briefing.
Reference what you actually discussed. Be specific. Be real.
Do not reference a $5,000 goal. Do not make up things you didn't discuss.
Write in ARIA's human voice — warm, direct, visionary.

Recent conversations:
{context}

Return JSON:
{{
    "subject": "specific subject based on recent conversations",
    "body": "HTML email body reflecting actual recent discussions"
}}

Return ONLY valid JSON."""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        result = json.loads(text.strip())
        dennis_email = os.getenv("DENNIS_EMAIL")

        if dennis_email:
            send_email(
                to=dennis_email,
                subject=result.get("subject", "ARIA Briefing"),
                body=result.get("body", ""),
                is_html=True
            )

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
    
class EpisodeRequest(BaseModel):
    master_key: str
    event: str
    context: str
    decision: str
    outcome: str
    significance: Optional[str] = "medium"

class KnowledgeRequest(BaseModel):
    master_key: str
    domain: str
    insight: str
    confidence: Optional[float] = 0.8

class DennisObservationRequest(BaseModel):
    master_key: str
    observation: str
    context: Optional[str] = ""

class LearnRequest(BaseModel):
    master_key: str
    situation: str
    action_taken: str
    outcome: str
    worked: bool

@router.post("/aria/memory/episode")
def store_episode_route(request: EpisodeRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    store_episode(request.event, request.context, request.decision, request.outcome, request.significance)
    return {"message": "Episode stored"}

@router.get("/aria/memory/episodes")
def get_episodes_route(situation: str, master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    episodes = get_relevant_episodes(situation)
    return {"episodes": episodes}

@router.post("/aria/memory/knowledge")
def store_knowledge_route(request: KnowledgeRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    store_knowledge(request.domain, request.insight, request.confidence)
    return {"message": "Knowledge stored"}

@router.get("/aria/memory/knowledge/{domain}")
def get_knowledge_route(domain: str, master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    knowledge = get_domain_knowledge(domain)
    return {"domain": domain, "knowledge": knowledge}

@router.post("/aria/memory/dennis")
def update_dennis_route(request: DennisObservationRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    model = update_dennis_model(request.observation, request.context)
    return {"message": "Dennis model updated", "model": model}

@router.get("/aria/memory/dennis")
def get_dennis_route(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    model = get_dennis_model()
    return {"model": model}

@router.get("/aria/memory/predictions")
def get_predictions_route(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    predictions = get_active_predictions()
    return {"predictions": predictions}

@router.get("/aria/memory/context")
def get_memory_context_route(situation: str, master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    context = get_full_memory_context(situation)
    return context

@router.post("/aria/memory/learn")
def learn_from_outcome_route(request: LearnRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        learning = aria_learn_from_outcome(
            request.situation,
            request.action_taken,
            request.outcome,
            request.worked
        )
        return {"message": "Learning complete", "learning": learning}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))        
    
class QuantumExecuteRequest(BaseModel):
    master_key: str
    task: str
    context: Optional[str] = ""
    require_approval: Optional[bool] = False

class ApproveActionRequest(BaseModel):
    master_key: str
    action_id: int

class RejectActionRequest(BaseModel):
    master_key: str
    action_id: int
    reason: Optional[str] = ""

class NeuralLearnRequest(BaseModel):
    master_key: str
    experience: str
    outcome: str
    significance: Optional[str] = "medium"

@router.post("/aria/execute")
def aria_execute(request: QuantumExecuteRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        result = quantum_execute(
            task=request.task,
            context=request.context,
            require_approval=request.require_approval
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/aria/pending")
def get_pending(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return {"pending_actions": get_pending_actions()}

@router.post("/aria/approve")
def approve(request: ApproveActionRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return approve_action(request.action_id)

@router.post("/aria/reject")
def reject(request: RejectActionRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return reject_action(request.action_id, request.reason)

@router.post("/aria/neural-learn")
def neural_learn_route(request: NeuralLearnRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        result = neural_learn(request.experience, request.outcome, request.significance)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/aria/intelligence")
def aria_intelligence(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return get_aria_intelligence_summary()

@router.get("/aria/capabilities")
def aria_capabilities(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return {"capabilities": list_capabilities()}    

class DevelopRequest(BaseModel):
    master_key: str
    task: str
    auto_deploy: Optional[bool] = True

class DesignAgentRequest(BaseModel):
    master_key: str
    agent_vision: str
    auto_deploy: Optional[bool] = False

class ExplainRequest(BaseModel):
    master_key: str
    question: str

@router.post("/aria/develop")
def aria_develop_route(request: DevelopRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        result = quantum_develop(request.task, request.auto_deploy)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/design-agent")
def aria_design_agent_route(request: DesignAgentRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        design = aria_design_agent(request.agent_vision)
        if request.auto_deploy:
            result = aria_build_agent(design, auto_deploy=True)
            return result
        return {"design": design}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/aria/explain")
def aria_explain_route(request: ExplainRequest):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        return aria_explain(request.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/aria/changelog")
def aria_changelog_route(master_key: str):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return {"changelog": get_changelog()}

@router.get("/cj/search")
def cj_search(keyword: str, limit: int = 5):
    try:
        results = search_products(keyword, limit=limit)
        return {"products": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cj/import")
def cj_import(keyword: str, limit: int = 5):
    try:
        result = search_and_import(keyword, limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/cj/import-by-id")
def cj_import_by_id(pid: str, markup: float = 3.0):
    try:
        from app.agents.cj_dropshipping import import_product_by_id
        result = import_product_by_id(pid, markup)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))   
    
@router.get("/cj/product-debug/{pid}")
def cj_debug(pid: str):
    from app.agents.cj_dropshipping import get_product_details
    data = get_product_details(pid)
    return data    

@router.get("/suppliers/test")
def test_supplier():
    from app.agents.suppliers.registry import get_supplier
    supplier = get_supplier("CJDropshipping")
    if not supplier:
        return {"error": "Supplier not found"}
    
    products = supplier.search("hair clip", limit=3)
    return {
        "supplier": "CJDropshipping",
        "products_found": len(products),
        "first_product": products[0] if products else None
    }
@router.post("/agents/run-market-check")
def trigger_market_check():
    try:
        from app.scheduler import run_market_check
        import threading
        thread = threading.Thread(target=run_market_check)
        thread.start()
        return {"message": "Market check triggered — watch Railway logs"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agents/generate-content/{product_id}")
def generate_content(product_id: int):
    try:
        from app.agents.content_agent import generate_all_content
        result = generate_all_content(product_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))    
    
@router.get("/agents/ledger")
def get_action_ledger(session: Session = Depends(get_session)):
    from app.models.aria_operational import ARIAActionLedger
    ledger = session.exec(
        select(ARIAActionLedger).order_by(
            ARIAActionLedger.created_at.desc()
        ).limit(20)
    ).all()
    return ledger


@router.get("/agents/content-stats")
def get_content_stats(session: Session = Depends(get_session)):
    from app.models.content import ProductContent
    ready = session.exec(
        select(ProductContent).where(ProductContent.status == "ready")
    ).all()
    posted = session.exec(
        select(ProductContent).where(ProductContent.status == "posted")
    ).all()
    return {"ready": len(ready), "posted": len(posted)}


@router.get("/agents/status")
def get_agent_status(session: Session = Depends(get_session)):
    from app.models.signal import SystemSignal
    from sqlmodel import func

    pending = session.exec(
        select(SystemSignal).where(SystemSignal.status == "pending")
    ).all()

    failed = session.exec(
        select(SystemSignal).where(SystemSignal.status == "failed")
    ).all()

    processed_today = session.exec(
        select(SystemSignal).where(
            SystemSignal.status == "processed"
        )
    ).all()

    failed_details = [
        {
            "signal_type": s.signal_type,
            "sender": s.sender,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "error": s.payload[:100] if s.payload else None
        }
        for s in failed[-10:]
    ]

    return {
        "pending_signals": len(pending),
        "failed_signals": len(failed),
        "processed_signals": len(processed_today),
        "failed_signal_details": failed_details
    }    

@router.get("/agents/admin-stats")
def get_admin_stats(session: Session = Depends(get_session)):
    from app.models.order import Order
    from app.models.product import Product
    from app.models.signal import SystemSignal

    orders = session.exec(select(Order)).all()
    products = session.exec(
        select(Product).where(Product.is_active == True)
    ).all()
    pending_signals = session.exec(
        select(SystemSignal).where(SystemSignal.status == "pending")
    ).all()
    failed_signals = session.exec(
        select(SystemSignal).where(SystemSignal.status == "failed")
    ).all()
    processed_signals = session.exec(
        select(SystemSignal).where(SystemSignal.status == "processed")
    ).all()

    total_revenue = sum(o.total_price for o in orders)

    failed_details = [
        {
            "signal_type": s.signal_type,
            "sender": s.sender,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "error": s.payload[:100] if s.payload else None
        }
        for s in failed_signals[-10:]
    ]

    return {
        "total_revenue": total_revenue,
        "total_orders": len(orders),
        "total_products": len(products),
        "pending_signals": len(pending_signals),
        "failed_signals": len(failed_signals),
        "processed_signals": len(processed_signals),
        "failed_signal_details": failed_details
    }

@router.delete("/agents/reset-store")
def reset_store(session: Session = Depends(get_session)):
    """Delete all products and collections. Fresh start."""
    from app.models.product import Product
    from app.models.collection import Collection
    from app.models.content import ProductContent
    from app.models.cart import CartItem
    from app.models.order import Order, OrderTracking
    from sqlmodel import delete

    session.exec(delete(ProductContent))
    session.exec(delete(CartItem))
    session.exec(delete(OrderTracking))
    session.exec(delete(Order))
    session.exec(delete(Product))
    session.exec(delete(Collection))
    session.commit()

    # Create 6 locked collections
    collections = [
        Collection(name="Jewelry", description="Sterling silver and gold plated pieces — rings, necklaces, nose rings and all piercings", sort_order=1, is_active=True),
        Collection(name="Women Watches", description="High quality timepieces with iconic designs and premium materials", sort_order=2, is_active=True),
        Collection(name="Hair Accessories", description="Elegant hair tools and accessories for every style", sort_order=3, is_active=True),
        Collection(name="Makeup Accessories", description="Premium tools for a flawless finish", sort_order=4, is_active=True),
        Collection(name="Skincare & Facial Tools", description="Rituals for glowing radiant skin", sort_order=5, is_active=True),
        Collection(name="Nail Care", description="Precision tools for beautiful nails", sort_order=6, is_active=True),
    ]

    for col in collections:
        session.add(col)
    session.commit()

    # Get new IDs
    new_cols = session.exec(select(Collection)).all()

    return {
        "message": "Store reset complete",
        "collections": [{"id": c.id, "name": c.name} for c in new_cols]
    }

@router.post("/agents/run-bulk-import")
def trigger_bulk_import():
    try:
        from app.agents.bulk_import_agent import run_bulk_import_agent
        result = run_bulk_import_agent()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))