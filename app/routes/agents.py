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

@router.get("/agents/sync-report")
def get_sync_report(session: Session = Depends(get_session)):
    """Recent Silverbene sync/discontinuation activity — replaces the emails Dennis used to get per run."""
    stock_syncs = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == "silverbene_stock_agent",
            AgentMemory.memory_type == "sync_run",
        ).order_by(AgentMemory.created_at.desc()).limit(10)
    ).all()
    discontinuation_checks = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == "silverbene_discontinuation_agent",
        ).order_by(AgentMemory.created_at.desc()).limit(10)
    ).all()
    return {"stock_syncs": stock_syncs, "discontinuation_checks": discontinuation_checks}

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


@router.get("/agents/email/test-imap")
def test_imap_connection(master_key: str):
    """Test IMAP connection to hello@mikisi.co without reading any emails."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    import imaplib
    import os
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_address:
        return {"success": False, "error": "GMAIL_ADDRESS not set in environment"}
    if not gmail_password:
        return {"success": False, "error": "GMAIL_APP_PASSWORD not set in environment"}
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, gmail_password)
        mail.logout()
        return {"success": True, "connected_as": gmail_address}
    except imaplib.IMAP4.error as e:
        return {"success": False, "gmail_address": gmail_address, "error": str(e)}
    except Exception as e:
        return {"success": False, "gmail_address": gmail_address, "error": str(e)}
    
    
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
            model="claude-opus-4-8",
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

@router.get("/cj/categories")
def cj_categories(parent_id: Optional[str] = None):
    try:
        from app.agents.cj_dropshipping import get_categories
        results = get_categories(parent_id=parent_id)
        return {"categories": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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


@router.post("/agents/silverbene/retry-order/{order_id}")
def silverbene_retry_order(order_id: int, master_key: str, session: Session = Depends(get_session)):
    """
    Retry Silverbene forwarding for an order that is already paid in the DB
    but whose supplier placement failed or was never attempted.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.models.order import Order
    from app.models.product import Product
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    from app.agents.tracking_agent import create_tracking_entry
    from app.database import engine
    from sqlmodel import Session as DBSession

    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    if order.status not in ("paid", "processing"):
        raise HTTPException(status_code=400, detail=f"Order status is '{order.status}' — only paid/processing orders can be retried")

    product = session.get(Product, order.product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {order.product_id} not found")

    # The customer's actual selected variant (see app.models.product_variant.
    # ProductVariant) — falls back to product.cj_sku (the product's default/
    # first option) only for orders placed before Order.variant_id existed.
    option_id = product.cj_sku
    if order.variant_id:
        from app.models.product_variant import ProductVariant
        variant = session.get(ProductVariant, order.variant_id)
        if variant and variant.product_id == order.product_id:
            option_id = variant.supplier_option_id
    if not option_id:
        raise HTTPException(status_code=400, detail=f"Product has no Silverbene option_id (cj_sku)")

    # Build customer from user_id (email)
    parts = order.user_id.split("@")[0].split(".")
    customer = {
        "first_name": parts[0].capitalize(),
        "last_name":  parts[1].capitalize() if len(parts) > 1 else "Customer",
        "email":      "hello@mikisi.co",  # never send real customer email to supplier — matches payments.py's checkout path
        "phone":      "",
    }

    # Parse stored shipping address string
    addr_parts = [p.strip() for p in order.shipping_address.split(",")]
    address = {
        "line1":        addr_parts[0] if len(addr_parts) > 0 else "",
        "city":         addr_parts[1] if len(addr_parts) > 1 else "",
        "state":        addr_parts[2] if len(addr_parts) > 2 else "",
        "state_code":   addr_parts[2][:2].upper() if len(addr_parts) > 2 else "",
        "postal_code":  addr_parts[3] if len(addr_parts) > 3 else "",
        "country_code": addr_parts[4].upper() if len(addr_parts) > 4 else "US",
    }

    sb = SilverbeneAdapter()
    result = sb.place_order(
        product_id=str(option_id),
        customer=customer,
        address=address,
        quantity=order.quantity,
        option_id=str(option_id),
    )

    print(f"[Silverbene Retry] order_id={order_id} result={result}")

    if result.get("success"):
        create_tracking_entry(
            order_id=order_id,
            cj_order_id=result.get("supplier_order_id", ""),
            customer_email=order.user_id,
            customer_name=f"{customer['first_name']} {customer['last_name']}",
            supplier_name="Silverbene"
        )
        with DBSession(engine) as s:
            o = s.get(Order, order_id)
            if o:
                o.status = "processing"
                o.supplier_notified = True
                s.add(o)
                s.commit()
        return {
            "success": True,
            "order_id": order_id,
            "supplier_order_id": result.get("supplier_order_id"),
            "message": "Order forwarded to Silverbene and status set to processing",
        }
    else:
        return {
            "success": False,
            "order_id": order_id,
            "reason": result.get("reason", "Unknown error"),
        }

@router.get("/suppliers/test")
def test_supplier():
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    sb = SilverbeneAdapter()
    products = sb.search("ring", limit=3)
    return {
        "supplier": "Silverbene",
        "products_found": len(products),
        "first_product": products[0] if products else None
    }

@router.get("/silverbene/check-stock")
def silverbene_check_stock_raw(option_ids: str, master_key: str):
    """Debug — query Silverbene option_qty directly for a comma-separated list of option_ids."""
    from app.agents.aria_security import verify_master_key
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        sb = SilverbeneAdapter()
        resp = sb._get("/api/dropshipping/option_qty", {"option_id": option_ids})
        return {"raw_response": resp, "queried": option_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/silverbene/sync-stock")
def silverbene_sync_stock_now():
    """Trigger an immediate run of the Silverbene Stock Agent outside the 6-hour schedule."""
    import threading
    try:
        from app.agents.silverbene_stock_agent import run_silverbene_stock_agent
        thread = threading.Thread(target=run_silverbene_stock_agent)
        thread.start()
        return {
            "message": "Silverbene Stock Agent triggered — checking live inventory for all products",
            "auto_schedule": "Also runs automatically every 6 hours",
            "what_happens": "Stock updated, out-of-stock products hidden, restocked products made visible, ARIA emails Dennis if changes found"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/silverbene/backfill-specs")
def silverbene_backfill_specs():
    """
    One-shot backfill: re-fetches raw Silverbene descriptions for all products
    and extracts inner_diameter (rings) and refreshes weight into specs JSON.
    Safe to re-run — only overwrites inner_diameter and weight, leaves other specs untouched.
    """
    import json, threading
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    from app.database import engine
    from sqlmodel import Session, select
    from app.models.product import Product

    def _run():
        sb = SilverbeneAdapter()
        updated = 0
        skipped = 0
        with Session(engine) as session:
            products = session.exec(
                select(Product).where(
                    Product.supplier_name == "Silverbene",
                    Product.cj_product_id.isnot(None),
                )
            ).all()
            for p in products:
                try:
                    desc = sb.get_raw_desc_by_sku(p.cj_product_id)
                    if not desc:
                        skipped += 1
                        continue
                    new_specs = sb._extract_specs_from_desc(desc)
                    if not new_specs:
                        skipped += 1
                        continue
                    existing = json.loads(p.specs or "{}")
                    changed = False
                    for key in ("inner_diameter", "weight"):
                        if key in new_specs and new_specs[key] != existing.get(key):
                            existing[key] = new_specs[key]
                            changed = True
                    if changed:
                        p.specs = json.dumps(existing)
                        session.add(p)
                        updated += 1
                except Exception:
                    skipped += 1
                    continue
            session.commit()
        print(f"[Spec Backfill] Done — updated={updated} skipped={skipped}")

    threading.Thread(target=_run).start()
    return {"message": "Spec backfill started in background — updates inner_diameter and weight for all Silverbene products", "check": "Watch Railway logs for completion"}


@router.get("/silverbene/ping")
def silverbene_ping():
    """Diagnose Silverbene API connection — shows token status and raw response."""
    import traceback, os, requests
    token = os.getenv("SILVERBENE_API_KEY", "")
    try:
        url = "https://s.silverbene.com/api/dropshipping/product_list_by_date"
        # Show raw response for diagnosis
        # Test different combinations to find what returns products
        results = {}
        import requests as req2
        combos = [
            ("2024-1", "2024-3", "ring", 1),
            ("2024-1", "2024-3", "ring", 0),
            ("2024-1", "2024-3", "", 0),
            ("2023-1", "2023-3", "ring", 0),
            ("2025-1", "2025-3", "ring", 0),
            ("2025-1", "2025-3", "necklace", 0),
        ]
        for start, end, kw, stock in combos:
            p = {"token": token, "start_date": start, "end_date": end, "is_really_stock": stock}
            if kw:
                p["keywords"] = kw
            r2 = req2.get(url, params=p, timeout=15)
            try:
                j = r2.json()
                count = len(j.get("data", {}).get("data", [])) if isinstance(j.get("data"), dict) else 0
                results[f"{start}_{end}_{kw or 'nokw'}_stock{stock}"] = f"code={j.get('code')} count={count}"
            except Exception:
                results[f"{start}_{end}_{kw or 'nokw'}_stock{stock}"] = r2.text[:100]
        params = {
            "token": token,
            "start_date": "2024-1",
            "end_date": "2024-3",
            "is_really_stock": 0,
        }
        r = requests.get(url, params=params, timeout=30)
        raw_text = r.text[:500]
        return {
            "token_set": bool(token),
            "http_status": r.status_code,
            "range_tests": results,
            "last_raw": raw_text,
        }
    except Exception as e:
        return {
            "token_set": bool(token),
            "token_preview": token[:8] + "..." if token else "EMPTY",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@router.get("/silverbene/score-test")
def silverbene_score_test():
    """Step 2: Does scoring pass for a real Silverbene product?"""
    import traceback
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.agents.jewelry_scoring import score_jewelry_product
        from datetime import datetime, timedelta
        sb = SilverbeneAdapter()
        end = datetime.utcnow()
        start = end - timedelta(days=60)
        resp = sb._get("/api/dropshipping/product_list_by_date", {
            "start_date": f"{start.year}-{start.month}",
            "end_date": f"{end.year}-{end.month}",
            "keywords": "ring",
            "is_really_stock": 1,
        })
        items = resp.get("data", {}).get("data", [])
        if not items:
            return {"error": "No products returned from Silverbene"}
        raw = items[0]
        std = sb._to_standard(raw)
        score = score_jewelry_product(std)
        return {
            "product_name": std.get("name", "")[:60],
            "cost_price": std.get("cost_price"),
            "images_count": len(std.get("images", [])),
            "material": std.get("material"),
            "sizes": std.get("sizes"),
            "colors": std.get("colors"),
            "score_result": score,
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.post("/silverbene/save-one")
def silverbene_save_one(collection: str = "Rings"):
    """Step 3: Score, rewrite, and save exactly ONE product. Fast enough to not timeout."""
    import traceback, json as _json
    try:
        from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
        from app.agents.jewelry_pricing import calculate_jewelry_price
        from app.agents.jewelry_scoring import score_jewelry_product
        from app.agents.shipping_agent import get_best_shipping
        from app.agents.bulk_import_agent import batch_rewrite_products, COLLECTION_STRATEGIES
        from app.agents.store_manager import add_product_to_store
        from app.agents.store_config import get_config

        sb = SilverbeneAdapter()
        strategy = COLLECTION_STRATEGIES.get(collection, {})

        # Use the adapter's full search (handles date windows + is_really_stock=0)
        products = sb.search_by_category(collection, limit=3)
        if not products:
            return {"error": f"No products from Silverbene for collection={collection}"}

        std = products[0]
        score = score_jewelry_product(std)
        if score["rejected"]:
            return {"error": "Product rejected by scorer", "reason": score["rejection_reason"],
                    "product": std.get("name", "")[:60], "score": score}

        collection_id = int(get_config(strategy.get("config_key", "collection_rings"), default="0"))
        rewritten = batch_rewrite_products([std], collection, collection_id)
        if not rewritten:
            return {"error": "ARIA rejected the product in rewrite step"}

        product = rewritten[0]
        shipping = get_best_shipping("Silverbene", "")
        pricing = calculate_jewelry_price({**std, "supplier_name": "Silverbene"}, score, shipping_cost=shipping["cost"])

        options = std.get("_options", [])
        option_id = str(options[0].get("option_id", "")) if options else ""

        product_data = {
            "name": product["mikisi_name"],
            "brand": "Mikisi",
            "category": collection,
            "description": product.get("mikisi_description", "") or std.get("name", ""),
            "original_price": pricing["original_price"],
            "discount_percent": pricing["discount_percent"],
            "final_price": pricing["final_price"],
            "image_url": std.get("image_url", ""),
            "images": _json.dumps(std.get("images", [])) if std.get("images") else None,
            "stock": std.get("stock", 999),
            "shipping_days": shipping["days_max"],
            "supplier_name": "Silverbene",
            "supplier_url": "",
            "cj_product_id": std.get("supplier_product_id", ""),
            "cj_sku": option_id,
            "collection_id": collection_id,
            "variants": _json.dumps(options) if options else None,
            "material": std.get("material", ""),
            "sizes": std.get("sizes"),
            "colors": std.get("colors"),
        }

        p_obj, status = add_product_to_store(product_data)
        return {
            "status": status,
            "product_id": p_obj.id if p_obj else None,
            "name": product_data["name"],
            "price": product_data["final_price"],
            "collection_id": collection_id,
            "images": len(std.get("images", [])),
            "material": product_data["material"],
            "score": score["score"],
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.post("/silverbene/test-import")
def silverbene_test_import(collection: str = "Rings", max_products: int = 5):
    """
    Run a small test import from Silverbene for one collection.
    Use this to verify products look correct before running the full bulk import.
    """
    try:
        from app.agents.bulk_import_agent import import_for_collection, COLLECTION_STRATEGIES
        import threading

        collection = collection.strip().title()
        if collection not in COLLECTION_STRATEGIES:
            available = list(COLLECTION_STRATEGIES.keys())
            raise HTTPException(status_code=400, detail=f"Unknown collection. Choose from: {available}")

        strategy = {**COLLECTION_STRATEGIES[collection], "max_per_run": max_products}

        def run():
            import_for_collection(collection, strategy)

        thread = threading.Thread(target=run)
        thread.start()

        return {
            "message": f"Test import started — importing up to {max_products} products into '{collection}'",
            "collection": collection,
            "max_products": max_products,
            "watch": "Check Railway logs for progress. Visit your store to see results."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/silverbene/bulk-import")
def silverbene_bulk_import(max_per_collection: int = 20):
    """Run full bulk import across all 7 collections from Silverbene."""
    try:
        import threading
        from app.agents.bulk_import_agent import run_bulk_import_agent

        def run():
            run_bulk_import_agent(max_per_collection=max_per_collection)

        thread = threading.Thread(target=run)
        thread.start()

        return {
            "message": f"Full Silverbene bulk import started — up to {max_per_collection} products per collection",
            "collections": 7,
            "watch": "Monitor Railway logs for real-time progress"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
def generate_content(product_id: int, with_video: bool = False, session: Session = Depends(get_session)):
    """Generate images (and optionally video) for a single product."""
    try:
        from app.agents.content_agent import generate_product_content
        product = session.get(__import__('app.models.product', fromlist=['Product']).Product, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        result = generate_product_content(product, with_video=with_video)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/content/run-images")
def run_image_pipeline(limit: int = None):
    """Generate images for all products that don't have content yet. Runs in background."""
    import threading
    def _run():
        from app.agents.content_agent import run_image_pipeline
        run_image_pipeline(limit=limit)
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": f"Image pipeline started — check content-stats for progress"}


@router.post("/agents/content/run-videos-initial")
def run_initial_videos():
    """One-time: generate videos for top 20 products + all collection tiles + hero."""
    import threading
    def _run():
        from app.agents.content_agent import run_video_pipeline_initial
        run_video_pipeline_initial()
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "Initial video pipeline started (top 20 + collections + hero)"}


@router.post("/agents/content/run-hero")
def run_hero():
    """Generate the hero banner video."""
    import threading
    def _run():
        from app.agents.content_agent import generate_hero_content
        generate_hero_content()
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "Hero banner generation started"}
    
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
    from app.models.product import Product
    from app.models.agent import AgentMemory
    import json as _json

    total   = session.exec(select(Product).where(Product.is_active == True)).all()
    with_img = [p for p in total if p.content_image_url]
    with_vid = [p for p in total if p.video_url]

    # Last 10 generation log entries
    logs = session.exec(
        select(AgentMemory)
        .where(AgentMemory.agent_name == "content_agent",
               AgentMemory.memory_type == "generation_log")
        .order_by(AgentMemory.id.desc())
        .limit(10)
    ).all()
    recent = []
    for l in logs:
        try:
            recent.append(_json.loads(l.content))
        except Exception:
            pass

    total_cost = sum(r.get("cost_usd", 0) for r in recent)
    return {
        "total_products":      len(total),
        "with_content_image":  len(with_img),
        "with_video":          len(with_vid),
        "pending_images":      len(total) - len(with_img),
        "pending_videos":      len(total) - len(with_vid),
        "recent_generations":  recent,
        "recent_cost_usd":     round(total_cost, 4),
    }


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

    # Create 7 locked jewelry collections
    collections = [
        Collection(name="Rings", description="Sterling silver and gold rings for every occasion", sort_order=1, is_active=True),
        Collection(name="Necklaces", description="Pendants, chains and layering pieces", sort_order=2, is_active=True),
        Collection(name="Bracelets", description="Bangles, cuffs and charm bracelets", sort_order=3, is_active=True),
        Collection(name="Earrings", description="Studs, hoops and statement drops", sort_order=4, is_active=True),
        Collection(name="Anklets", description="Delicate chains for graceful steps", sort_order=5, is_active=True),
        Collection(name="Ear Cuffs", description="No piercing required — bold and elegant", sort_order=6, is_active=True),
        Collection(name="Jewelry Sets", description="Matching pieces curated as one", sort_order=7, is_active=True),
    ]

    for col in collections:
        session.add(col)
    session.commit()

    # Sync collection IDs into store config so agents use the real DB IDs
    new_cols = session.exec(select(Collection).order_by(Collection.sort_order)).all()
    collection_map = {
        "Rings": "collection_rings",
        "Necklaces": "collection_necklaces",
        "Bracelets": "collection_bracelets",
        "Earrings": "collection_earrings",
        "Anklets": "collection_anklets",
        "Ear Cuffs": "collection_ear_cuffs",
        "Jewelry Sets": "collection_jewelry_sets"
    }
    from app.agents.store_config import set_config as _sc
    locked_ids = []
    for col in new_cols:
        key = collection_map.get(col.name)
        if key:
            _sc(key, str(col.id), f"{col.name} collection ID")
            locked_ids.append(str(col.id))
    _sc("locked_collection_ids", ",".join(locked_ids), "The 7 locked jewelry collection IDs")

    return {
        "message": "Store reset complete — 7 jewelry collections created",
        "collections": [{"id": c.id, "name": c.name} for c in new_cols]
    }

@router.post("/agents/run-bulk-import")
def trigger_bulk_import(max_per_collection: int = 100):
    """Start bulk import in background — returns immediately. Poll /agents/bulk-import-result."""
    try:
        import threading
        from app.agents.bulk_import_agent import run_bulk_import_agent
        thread = threading.Thread(
            target=run_bulk_import_agent,
            kwargs={"max_per_collection": max_per_collection},
            daemon=True
        )
        thread.start()
        return {"message": "Bulk import started in background", "poll": "/agents/bulk-import-result", "max_per_collection": max_per_collection}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/bulk-import-result")
def get_bulk_import_result(session: Session = Depends(get_session)):
    """Return the most recent bulk import run result from agent memory."""
    memory = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == "bulk_import_agent",
            AgentMemory.memory_type == "import_run"
        ).order_by(AgentMemory.created_at.desc())
    ).first()
    if not memory:
        return {"status": "no_result", "message": "Import not complete yet or never run"}
    import json as _json
    return {"status": "complete", **_json.loads(memory.content)}


@router.post("/agents/reprice-products")
def reprice_products(session: Session = Depends(get_session)):
    """
    Recalculate final_price and original_price for every active product
    using the current pricing engine and ceiling configs.
    Explicitly writes the correct ceiling values to StoreConfig first
    so this is safe to call before the next full app restart.
    """
    import json as _json
    from app.models.product import Product
    from app.agents.store_config import set_config as _sc
    from app.agents.jewelry_pricing import calculate_jewelry_price

    # Force ceiling values into DB right now (don't wait for next restart)
    _sc("pricing_ceiling_fashion",     "80.00",   "Max price for fashion tier")
    _sc("pricing_ceiling_premium",     "150.00",  "Max price for premium tier")
    _sc("pricing_ceiling_luxury",      "500.00",  "Max price for luxury tier")
    _sc("pricing_ceiling_ultra_luxury","2000.00", "Max price for ultra luxury tier")

    products = session.exec(select(Product).where(Product.is_active == True)).all()

    updated = 0
    skipped = 0
    repriced = []
    errors = []

    def _infer_tier_and_score(name: str, description: str):
        """Detect quality tier and a representative score from product text."""
        text = f"{name} {description}".lower()
        stone = None
        if "moissanite" in text:
            stone = "moissanite"
        elif "diamond" in text:
            stone = "diamond"

        if "925" in text or "sterling" in text or "999" in text:
            metal = "925_silver"
        elif "18k" in text:
            metal = "18k_gold"
        elif "14k" in text:
            metal = "14k_gold"
        elif "stainless" in text:
            metal = "stainless_steel"
        elif "titanium" in text:
            metal = "titanium"
        elif "surgical" in text:
            metal = "surgical_steel"
        elif "gold filled" in text:
            metal = "gold_filled"
        elif "gold plated" in text:
            metal = "gold_plated"
        else:
            metal = "unknown"

        if stone in ("moissanite", "diamond"):
            tier, score = "ultra_luxury", 87
        elif metal in ("925_silver", "18k_gold", "14k_gold"):
            tier, score = "luxury", 72
        elif metal in ("gold_plated", "stainless_steel", "surgical_steel", "titanium", "gold_filled"):
            tier, score = "premium", 62
        else:
            tier, score = "fashion", 55

        return tier, score, metal, stone

    for product in products:
        try:
            # Extract cost price from variant data
            cost_price = None
            if product.variants:
                try:
                    variants = _json.loads(product.variants)
                    if variants and isinstance(variants, list):
                        sp = variants[0].get("variantSellPrice")
                        if sp and float(sp) > 0:
                            cost_price = float(sp)
                except Exception:
                    pass

            if not cost_price:
                skipped += 1
                continue

            quality_tier, score_val, detected_metal, detected_stone = _infer_tier_and_score(
                product.name, product.description or ""
            )

            score_dict = {
                "score": score_val,
                "quality_tier": quality_tier,
                "detected_metal": detected_metal,
                "detected_stone": detected_stone,
                "auto_import": score_val >= 70,
                "needs_review": 50 <= score_val < 70,
                "rejected": False,
            }

            pricing = calculate_jewelry_price(
                {"name": product.name, "cost_price": cost_price,
                 "supplier_name": product.supplier_name or "CJDropshipping"},
                score_dict,
                shipping_cost=4.50,
            )

            old_price = product.final_price
            product.final_price    = pricing["final_price"]
            product.original_price = pricing["original_price"]
            product.discount_percent = pricing["discount_percent"]
            session.add(product)
            updated += 1
            repriced.append({
                "id": product.id,
                "name": product.name[:45],
                "tier": quality_tier,
                "cost": round(cost_price, 2),
                "old_price": old_price,
                "new_price": pricing["final_price"],
            })

        except Exception as e:
            errors.append({"id": product.id, "name": product.name[:40], "error": str(e)[:80]})

    session.commit()
    return {
        "updated": updated,
        "skipped_no_cost": skipped,
        "errors": errors,
        "repriced": repriced,
    }


@router.post("/agents/backfill-variants")
def backfill_variants(session: Session = Depends(get_session)):
    """
    One-time migration: fetch real variant data from CJ for every product
    that has a cj_product_id but no variants saved yet.
    Safe to re-run — skips products that already have variants.
    """
    import json as _json
    import time
    from app.models.product import Product
    from app.agents.cj_dropshipping import get_product_details

    # Only touch products missing variant data
    products = session.exec(
        select(Product).where(
            Product.cj_product_id != None,
            Product.cj_product_id != "",
            Product.variants == None
        )
    ).all()

    total = len(products)
    updated = 0
    failed = 0
    skipped = 0
    errors = []

    print(f"[Backfill Variants] Starting — {total} products to process")

    for i, product in enumerate(products):
        pid = product.cj_product_id
        try:
            details = get_product_details(pid)

            if not details:
                print(f"[Backfill Variants] [{i+1}/{total}] No data for pid={pid} — skipping")
                skipped += 1
                time.sleep(0.3)
                continue

            variants = details.get("variants", [])

            if not variants:
                print(f"[Backfill Variants] [{i+1}/{total}] No variants for '{product.name[:40]}' — skipping")
                skipped += 1
                time.sleep(0.3)
                continue

            product.variants = _json.dumps(variants)
            session.add(product)
            session.commit()
            updated += 1
            print(f"[Backfill Variants] [{i+1}/{total}] ✅ {product.name[:40]} — {len(variants)} variants saved")

        except Exception as e:
            failed += 1
            err = f"pid={pid}: {str(e)[:80]}"
            errors.append(err)
            print(f"[Backfill Variants] [{i+1}/{total}] ❌ {err}")
            session.rollback()

        # Respect CJ rate limits
        time.sleep(0.4)

    print(f"[Backfill Variants] Done — {updated} updated, {skipped} skipped, {failed} failed")
    return {
        "total_products": total,
        "updated": updated,
        "skipped_no_variants": skipped,
        "failed": failed,
        "errors": errors[:20]
    }


@router.post("/agents/backfill-product-variants")
def backfill_product_variants(master_key: str, published_only: bool = True, session: Session = Depends(get_session)):
    """
    One-time migration: populate ProductVariant rows (the new first-class
    internal variant identity — see app.models.product_variant) from each
    product's existing Silverbene `variants` JSON.

    Uses _extract_variant_rows() — the exact same per-option parser that
    already produces Product.sizes/Product.colors — so a ProductVariant row
    can never disagree with what the storefront already shows for that
    option. Idempotent: skips any (product_id, supplier_option_id) already
    present, safe to re-run.

    published_only=True (default): scope the first pass to live products —
    verify those, then call again with published_only=false to pick up the
    rest of the (mostly staged/unpublished) catalog.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.models.product import Product
    from app.models.product_variant import ProductVariant
    from app.agents.suppliers.silverbene_adapter import SilverbeneAdapter
    from app.agents.jewelry_pricing import calculate_mikisi_price

    adapter = SilverbeneAdapter()

    query = select(Product).where(Product.variants != None, Product.variants != "")
    if published_only:
        query = query.where(Product.is_published == True)
    products = session.exec(query).all()

    total = len(products)
    products_touched = 0
    rows_inserted = 0
    errors = []

    print(f"[Backfill ProductVariant] Starting — {total} products in scope (published_only={published_only})")

    for product in products:
        try:
            existing_option_ids = {
                v.supplier_option_id for v in session.exec(
                    select(ProductVariant).where(
                        ProductVariant.product_id == product.id,
                        ProductVariant.supplier_name == "Silverbene",
                    )
                ).all()
            }
            options = json.loads(product.variants)
            variant_rows = adapter._extract_variant_rows(options, product.category or "")

            inserted_this_product = 0
            for row in variant_rows:
                option_id = str(row["option_id"]) if row["option_id"] is not None else None
                if not option_id or option_id in existing_option_ids:
                    continue
                # Mirrors get_variant_prices()'s existing rule — only variants
                # with a known base_price are real, orderable options.
                base_price = float(row["base_price"] or 0)
                if not base_price:
                    continue
                session.add(ProductVariant(
                    product_id=product.id,
                    supplier_name="Silverbene",
                    supplier_option_id=option_id,
                    size=row["size"],
                    color=adapter._finalize_variant_color(row["color"], product.description or ""),
                    raw_attributes=json.dumps(row["raw_attributes"]),
                    base_price=base_price,
                    final_price=calculate_mikisi_price(base_price)["final_price"],
                    stock=int(row["qty"] or 0),
                    available=bool(row["available"]),
                    sort_order=row["sort_order"],
                ))
                inserted_this_product += 1

            if inserted_this_product:
                session.commit()
                rows_inserted += inserted_this_product
                products_touched += 1
                print(f"[Backfill ProductVariant] {product.name[:40]} — {inserted_this_product} rows")

        except Exception as e:
            session.rollback()
            err = f"product {product.id}: {str(e)[:120]}"
            errors.append(err)
            print(f"[Backfill ProductVariant] ❌ {err}")

    print(f"[Backfill ProductVariant] Done — {products_touched} products touched, {rows_inserted} rows inserted")
    return {
        "scope": "published_only" if published_only else "all_products",
        "products_scanned": total,
        "products_touched": products_touched,
        "rows_inserted": rows_inserted,
        "errors": errors[:20],
    }


# ── CONNECTION CHECKER ────────────────────────────────────────────────────────

@router.get("/agents/check-connections")
def check_connections():
    """
    Test every integration and return a live status report.
    Green = working. Red = missing token or API error.
    Safe to call any time — read-only, no posts are made.
    """
    import os, requests as _req

    def _ok(name, detail=""):
        return {"name": name, "status": "connected", "detail": detail}

    def _missing(name, detail=""):
        return {"name": name, "status": "missing_token", "detail": detail}

    def _error(name, detail=""):
        return {"name": name, "status": "error", "detail": detail}

    results = []

    # ── Core infrastructure ───────────────────────────────────────────────────
    results.append(
        _ok("Silverbene API", "key configured")
        if os.getenv("SILVERBENE_API_KEY") else
        _missing("Silverbene API", "Set SILVERBENE_API_KEY in Railway")
    )

    results.append(
        _ok("fal.ai", "key configured")
        if os.getenv("FAL_KEY") else
        _missing("fal.ai", "Set FAL_KEY in Railway")
    )

    results.append(
        _ok("Runway", "key configured")
        if os.getenv("RUNWAY_API_KEY") else
        _missing("Runway", "Set RUNWAY_API_KEY in Railway")
    )

    results.append(
        _ok("Cloudinary", "key configured")
        if os.getenv("CLOUDINARY_API_KEY") else
        _missing("Cloudinary", "Set CLOUDINARY_API_KEY in Railway")
    )

    results.append(
        _ok("Anthropic / ARIA", "key configured")
        if os.getenv("ANTHROPIC_API_KEY") else
        _missing("Anthropic / ARIA", "Set ANTHROPIC_API_KEY in Railway")
    )

    results.append(
        _ok("Stripe", "key configured")
        if os.getenv("STRIPE_SECRET_KEY") else
        _missing("Stripe", "Set STRIPE_SECRET_KEY in Railway — payments won't work without this")
    )

    # ── Social platforms ──────────────────────────────────────────────────────
    ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    ig_account = os.getenv("INSTAGRAM_ACCOUNT_ID")
    if ig_token and ig_account:
        try:
            r = _req.get(
                f"https://graph.facebook.com/v18.0/{ig_account}",
                params={"fields": "id,username", "access_token": ig_token},
                timeout=8
            )
            d = r.json()
            if "id" in d:
                results.append(_ok("Instagram", f"@{d.get('username', ig_account)}"))
            else:
                results.append(_error("Instagram", d.get("error", {}).get("message", "Token invalid")))
        except Exception as e:
            results.append(_error("Instagram", str(e)[:80]))
    elif ig_token or ig_account:
        results.append(_missing("Instagram", "Have token but missing INSTAGRAM_ACCOUNT_ID (or vice versa)"))
    else:
        results.append(_missing("Instagram",
            "Need INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_ACCOUNT_ID — "
            "get from Meta Business > Settings > Instagram > Generate Token"))

    fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
    fb_page = os.getenv("FACEBOOK_PAGE_ID")
    if fb_token and fb_page:
        try:
            r = _req.get(
                f"https://graph.facebook.com/v18.0/{fb_page}",
                params={"fields": "id,name", "access_token": fb_token},
                timeout=8
            )
            d = r.json()
            if "id" in d:
                results.append(_ok("Facebook", d.get("name", fb_page)))
            else:
                results.append(_error("Facebook", d.get("error", {}).get("message", "Token invalid")))
        except Exception as e:
            results.append(_error("Facebook", str(e)[:80]))
    elif fb_token or fb_page:
        results.append(_missing("Facebook", "Have token but missing FACEBOOK_PAGE_ID (or vice versa)"))
    else:
        results.append(_missing("Facebook",
            "Need FACEBOOK_ACCESS_TOKEN + FACEBOOK_PAGE_ID — "
            "get from Meta Business > Settings > Page > Generate Token"))

    from app.agents.tiktok_token import get_access_token as _get_tiktok_token
    tt_token = _get_tiktok_token()
    if tt_token:
        try:
            r = _req.get(
                "https://open.tiktokapis.com/v2/user/info/",
                headers={"Authorization": f"Bearer {tt_token}"},
                params={"fields": "open_id,display_name"},
                timeout=8
            )
            d = r.json()
            if d.get("data"):
                name = d["data"].get("user", {}).get("display_name", "connected")
                results.append(_ok("TikTok", name))
            else:
                results.append(_error("TikTok", d.get("error", {}).get("message", "Token invalid")))
        except Exception as e:
            results.append(_error("TikTok", str(e)[:80]))
    else:
        results.append(_missing("TikTok",
            "Need TIKTOK_ACCESS_TOKEN — "
            "get from TikTok Developers > My Apps > your app > Keys & Token"))

    pin_token = os.getenv("PINTEREST_ACCESS_TOKEN")
    if pin_token:
        try:
            # Check account access
            r = _req.get(
                "https://api.pinterest.com/v5/user_account",
                headers={"Authorization": f"Bearer {pin_token}"},
                timeout=8
            )
            d = r.json()
            if "username" in d:
                username = d["username"]
                # Also probe boards:write scope
                probe = _req.post(
                    "https://api.pinterest.com/v5/boards",
                    headers={"Authorization": f"Bearer {pin_token}",
                             "Content-Type": "application/json"},
                    json={"name": "_scope_probe_", "privacy": "SECRET"},
                    timeout=8
                )
                pd = probe.json()
                if pd.get("code") == 3:  # missing scope
                    missing_scopes = pd.get("message", "")
                    results.append(_error(
                        "Pinterest",
                        f"@{username} connected but token missing scopes: {missing_scopes} — "
                        f"regenerate token with boards:write + pins:write + catalogs:write"
                    ))
                else:
                    # Real board was created — delete it immediately
                    probe_id = pd.get("id", "")
                    if probe_id:
                        _req.delete(
                            f"https://api.pinterest.com/v5/boards/{probe_id}",
                            headers={"Authorization": f"Bearer {pin_token}"},
                            timeout=8
                        )
                    results.append(_ok("Pinterest", f"@{username} — all scopes verified"))
            else:
                results.append(_error("Pinterest", d.get("message", "Token invalid or expired")))
        except Exception as e:
            results.append(_error("Pinterest", str(e)[:80]))
    else:
        results.append(_missing("Pinterest",
            "Need PINTEREST_ACCESS_TOKEN — "
            "get from Pinterest Developers > My Apps > your app > Generate token"))

    # ── Auto-posting status ───────────────────────────────────────────────────
    from app.agents.store_config import get_config
    auto = get_config("auto_posting_enabled", default="false")
    social_ready = sum(
        1 for r in results
        if r["name"] in ("Instagram", "Facebook", "TikTok", "Pinterest")
        and r["status"] == "connected"
    )
    results.append({
        "name": "Auto-posting",
        "status": "enabled" if auto == "true" else "disabled",
        "detail": (
            f"{social_ready} platform(s) connected. Auto-posting is ON." if auto == "true"
            else f"{social_ready} platform(s) connected. Call POST /agents/enable-auto-posting to turn on."
        )
    })

    connected = sum(1 for r in results if r["status"] in ("connected", "enabled"))
    total = len(results)
    return {
        "summary": f"{connected}/{total} integrations connected",
        "integrations": results
    }


# ── PINTEREST ─────────────────────────────────────────────────────────────────

@router.post("/agents/pinterest/create-boards")
def pinterest_create_boards():
    """Run once — creates the 6 Mikisi Pinterest boards and saves their IDs."""
    try:
        from app.agents.pinterest_agent import ensure_boards_exist
        board_ids = ensure_boards_exist()
        return {"status": "done", "boards": board_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/pinterest/sync-product/{product_id}")
def pinterest_sync_product(product_id: int, session: Session = Depends(get_session)):
    """Manually sync a single product to Pinterest (catalog + pin)."""
    try:
        from app.models.product import Product
        from app.agents.pinterest_agent import sync_product
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        result = sync_product(product)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/pinterest/sync-all")
def pinterest_sync_all():
    """
    Backfill: sync all active products without a pin_id to Pinterest.
    Runs in background — returns immediately.
    """
    import threading

    def _run():
        from sqlmodel import Session, select
        from app.database import engine
        from app.models.product import Product
        from app.agents.pinterest_agent import sync_product

        with Session(engine) as s:
            products = s.exec(
                select(Product).where(
                    Product.is_active == True,
                    Product.pinterest_pin_id == None,
                )
            ).all()

        print(f"[Pinterest] Backfill: syncing {len(products)} products")
        done = 0
        for p in products:
            result = sync_product(p)
            if result.get("pin_id"):
                done += 1
        print(f"[Pinterest] Backfill complete: {done}/{len(products)} pinned")

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "Pinterest backfill running in background"}


@router.get("/agents/pinterest/analytics")
def pinterest_analytics():
    """Pull today's Pinterest analytics for all pinned products."""
    try:
        from app.agents.pinterest_agent import pull_analytics
        result = pull_analytics()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/pinterest/status")
def pinterest_status(session: Session = Depends(get_session)):
    """Overview: boards created, products pinned, analytics entries."""
    from sqlmodel import func
    from app.models.product import Product
    from app.models.platform_analytics import PlatformAnalytics
    from app.agents.store_config import get_config

    total     = session.exec(select(func.count()).select_from(Product).where(Product.is_active == True)).one()
    pinned    = session.exec(select(func.count()).select_from(Product).where(Product.pinterest_pin_id != None)).one()
    analytics = session.exec(select(func.count()).select_from(PlatformAnalytics).where(PlatformAnalytics.platform == "pinterest")).one()

    boards = {}
    for cat in ["Necklaces","Earrings","Rings","Bracelets","Anklets","Ear Cuffs"]:
        key = f"pinterest_board_{cat.lower().replace(' ','_')}"
        boards[cat] = get_config(key, default="") or "not created"

    return {
        "boards": boards,
        "products_total": total,
        "products_pinned": pinned,
        "products_not_pinned": total - pinned,
        "analytics_entries": analytics,
    }


@router.post("/agents/enable-auto-posting")
def enable_auto_posting():
    """Turn on automatic scheduled posting to all connected social platforms."""
    from app.agents.store_config import set_config, get_config
    from app.agents.aria_security import verify_master_key
    set_config("auto_posting_enabled", "true", "Automatic social media posting")
    return {"status": "enabled", "message": "Auto-posting is now ON. ARIA will post on schedule."}


@router.post("/agents/disable-auto-posting")
def disable_auto_posting():
    """Turn off automatic social media posting."""
    from app.agents.store_config import set_config
    set_config("auto_posting_enabled", "false", "Automatic social media posting")
    return {"status": "disabled", "message": "Auto-posting is now OFF."}


@router.post("/admin/instagram/queue-campaign")
def queue_campaign_product(product_id: int, master_key: str, session: Session = Depends(get_session)):
    """
    Admin — manually choose which product's photoshoot goes out on the
    NEXT campaign post (see instagram_agent.py's _pick_campaign_product).
    Consumed exactly once, cleared automatically after that post succeeds.
    Pass product_id=0 to clear a queued pick without replacing it.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.agents.store_config import set_config
    from app.models.product import Product

    if product_id:
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        if not (product.content_lifestyle_url or product.image_url):
            raise HTTPException(status_code=400, detail="Product has no image to post")

    set_config("instagram_manual_campaign_product_id", str(product_id))
    return {
        "queued_product_id": product_id,
        "message": f"Next campaign post will use product #{product_id}" if product_id else "Manual queue cleared",
    }


@router.get("/admin/instagram/env-check")
def instagram_env_check(master_key: str):
    """
    Admin — reports which social/commerce env vars are actually set on
    THIS deployment, presence only (never the value) — a claim like
    "X is already in Railway" made in a different session/tool should
    always be verified here before code is built assuming it's true.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    import os
    keys = [
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID",
        "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_PAGE_ID", "FACEBOOK_CATALOG_ID",
        "FACEBOOK_CATALOG_TOKEN", "FACEBOOK_APP_SECRET", "FACEBOOK_APP_ID",
    ]
    return {k: bool(os.getenv(k)) for k in keys}


@router.get("/admin/instagram/shop-eligibility")
def instagram_shop_eligibility(master_key: str):
    """
    Admin — checks shopping_product_tag_eligibility directly on the
    Instagram account. Hit a generic "(#100) Invalid parameter" trying to
    tag a real post despite a valid token with instagram_shopping_tag_products
    permission and a confirmed-real catalog product ID — research (Meta's
    own product-tagging docs) points to Shop/Checkout-on-Instagram approval
    status (a separate Commerce Manager review, not a token scope) as the
    most likely cause. This field says so directly instead of guessing
    from a vague error on a real post.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    import os, requests
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
    if not access_token or not account_id:
        return {"error": "INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID not set"}

    r = requests.get(
        f"https://graph.facebook.com/v18.0/{account_id}",
        params={"fields": "shopping_product_tag_eligibility,username", "access_token": access_token},
        timeout=15,
    )
    return r.json()


@router.get("/admin/instagram/catalog-product-search")
def instagram_catalog_product_search(q: str, master_key: str):
    """
    Admin — calls the exact endpoint Instagram itself uses to search for
    taggable products (catalog_product_search) rather than inferring
    eligibility from review_status, which came back blank for all 125
    products and proved uninformative. Only products that pass Meta's own
    internal tagging-eligibility check are returned here, so results are
    a direct list of what's actually postable right now — as opposed to
    guessing product IDs against post-now and hitting subcode 2207037
    one at a time.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    import os, requests
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
    catalog_id = os.getenv("FACEBOOK_CATALOG_ID")
    if not access_token or not account_id or not catalog_id:
        return {"error": "INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID, or FACEBOOK_CATALOG_ID not set"}

    r = requests.get(
        f"https://graph.facebook.com/v18.0/{account_id}/catalog_product_search",
        params={"catalog_id": catalog_id, "q": q, "access_token": access_token},
        timeout=15,
    )
    return r.json()


@router.get("/admin/instagram/meta-catalog-test")
def meta_catalog_test(product_id: int, master_key: str, session: Session = Depends(get_session)):
    """
    Admin — verifies a Mikisi product actually resolves in the Meta
    catalog BEFORE trusting that mapping in a real post. Bypasses the
    cache (always does a fresh Graph API lookup) so this reflects the
    catalog's real current state, not a previously cached miss/hit. Uses
    the exact same token preference as meta_catalog.py's real lookup
    (FACEBOOK_CATALOG_TOKEN first, FACEBOOK_ACCESS_TOKEN as fallback) so
    this test reflects what a real post will actually use.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.models.product import Product
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    import os, requests
    catalog_id = os.getenv("FACEBOOK_CATALOG_ID")
    access_token = os.getenv("FACEBOOK_CATALOG_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN")
    token_source = "FACEBOOK_CATALOG_TOKEN" if os.getenv("FACEBOOK_CATALOG_TOKEN") else "FACEBOOK_ACCESS_TOKEN"
    if not catalog_id or not access_token:
        return {"product_id": product_id, "resolved": False, "reason": "FACEBOOK_CATALOG_ID or a catalog-capable token not set"}

    r = requests.get(
        f"https://graph.facebook.com/v18.0/{catalog_id}/products",
        params={
            "filter": f'{{"retailer_id":{{"eq":"{product_id}"}}}}',
            # review_status/availability/visibility: catalog membership alone
            # (what this endpoint originally checked) isn't the same as
            # being individually approved for shopping tags — a product can
            # be "in the catalog" but still pending/rejected review, which
            # is a per-product status separate from the account-level
            # shopping_product_tag_eligibility check.
            "fields": "id,retailer_id,name,review_status,availability,visibility",
            "access_token": access_token,
        },
        timeout=15,
    )
    data = r.json()
    items = data.get("data", [])
    return {
        "product_id": product_id,
        "product_name": product.name,
        "token_used": token_source,
        "resolved": bool(items),
        "meta_product": items[0] if items else None,
        "raw_response": data if not items else None,
    }


@router.get("/admin/instagram/meta-catalog-variants-test")
def meta_catalog_variants_test(product_id: int, master_key: str, session: Session = Depends(get_session)):
    """
    Admin — like meta-catalog-test, but for the multi-variant retailer_id
    scheme (see meta_feed.py's _items_for()): "{product_id}-{variant_id}".
    Checks review_status/availability/visibility per matched entry — used
    right after switching that scheme from Silverbene's option_id to the
    internal ProductVariant id (see [[refactored-wobbling-rabin]]), to watch
    whether Meta treats the new-id entries as needing re-review.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.models.product import Product
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    import os, requests
    catalog_id = os.getenv("FACEBOOK_CATALOG_ID")
    access_token = os.getenv("FACEBOOK_CATALOG_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN")
    if not catalog_id or not access_token:
        return {"product_id": product_id, "resolved": False, "reason": "FACEBOOK_CATALOG_ID or a catalog-capable token not set"}

    r = requests.get(
        f"https://graph.facebook.com/v18.0/{catalog_id}/products",
        params={
            "filter": f'{{"retailer_id":{{"i_contains":"{product_id}-"}}}}',
            "fields": "id,retailer_id,name,review_status,availability,visibility",
            "access_token": access_token,
        },
        timeout=15,
    )
    data = r.json()
    items = data.get("data", [])
    return {
        "product_id": product_id,
        "product_name": product.name,
        "variant_entries_found": len(items),
        "entries": items,
        "raw_response": data if not items else None,
    }


@router.post("/admin/meta-capi-test")
def meta_capi_test(master_key: str, test_event_code: str):
    """
    Admin — sends one synthetic Purchase event through the server-side Meta
    Conversions API path (_send_meta_capi_event in payments.py), tagged with
    a Test Events code from Events Manager's "Test Events" tab so it shows
    up there instantly instead of polluting real Purchase reporting with a
    fake order. Used to verify META_PIXEL_ID/META_CONVERSIONS_API_TOKEN are
    both live and correct right after they're set in Railway, without
    waiting for (or faking) a real checkout.
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    import time
    from app.routes.payments import _send_meta_capi_event
    resp = _send_meta_capi_event(
        "Purchase", 1.00, ["TEST-PRODUCT"],
        email="capi-test@mikisi.co",
        event_id=f"capi-test-{int(time.time())}",
        test_event_code=test_event_code,
    )
    if resp is None:
        return {"sent": False, "reason": "META_PIXEL_ID or META_CONVERSIONS_API_TOKEN not set, or the request raised — check Railway logs for '[Meta CAPI]'"}
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    return {"sent": resp.ok, "status_code": resp.status_code, "response": body}


@router.post("/admin/instagram/exchange-facebook-token")
def exchange_facebook_token(short_lived_token: str, master_key: str):
    """
    Admin — exchanges a short-lived Graph API Explorer user token for the
    long-lived Page access token FACEBOOK_ACCESS_TOKEN /
    INSTAGRAM_ACCESS_TOKEN actually need (the previous one expired
    2026-06-23 — short-lived user tokens are NOT what should be stored
    long-term). FACEBOOK_APP_ID/FACEBOOK_APP_SECRET never leave this
    server — only the resulting page token is returned, for pasting into
    Railway by hand (no Railway write access from here).

    Two-step exchange per Meta's own docs: short-lived user token ->
    long-lived user token -> that user's page tokens (which, for a Page
    token obtained this way, don't expire on their own).
    """
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    import os, requests
    app_id = os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("FACEBOOK_APP_SECRET")
    page_id = os.getenv("FACEBOOK_PAGE_ID")
    if not app_id or not app_secret:
        raise HTTPException(status_code=400, detail="FACEBOOK_APP_ID or FACEBOOK_APP_SECRET not set in Railway")
    if not page_id:
        raise HTTPException(status_code=400, detail="FACEBOOK_PAGE_ID not set in Railway")

    r1 = requests.get(
        "https://graph.facebook.com/v18.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_token,
        },
        timeout=15,
    )
    data1 = r1.json()
    long_lived_user_token = data1.get("access_token")
    if not long_lived_user_token:
        return {"step": "exchange_user_token", "success": False, "error": data1}

    r2 = requests.get(
        "https://graph.facebook.com/v18.0/me/accounts",
        params={"access_token": long_lived_user_token},
        timeout=15,
    )
    data2 = r2.json()
    pages = data2.get("data", [])
    target = next((p for p in pages if p.get("id") == page_id), None)
    if not target:
        return {
            "step": "get_page_token", "success": False,
            "reason": f"page {page_id} not found among this user's pages",
            "page_ids_found": [p.get("id") for p in pages],
        }

    return {
        "success": True,
        "page_id": target["id"],
        "page_name": target.get("name"),
        "page_access_token": target["access_token"],
        "message": "Paste this value into Railway as BOTH FACEBOOK_ACCESS_TOKEN and INSTAGRAM_ACCESS_TOKEN",
    }


class ManualPostRequest(BaseModel):
    product_id: int
    post_type: str  # "product" or "campaign"
    master_key: str
    image_count: Optional[int] = None   # first N images from the product's gallery
    image_urls: Optional[list] = None   # explicit list, overrides image_count entirely
    dry_run: bool = True                # default True — preview before any real post
    skip_catalog_tag: bool = False      # post without the Shopping tag attempt at all


@router.post("/admin/instagram/post-now")
def instagram_post_now(data: ManualPostRequest):
    """
    Admin — manually post one specific product, on command. Never touches
    the automatic scheduler/counter (see instagram_agent.py's
    post_manually docstring) — Dennis is posting by hand for now.
    dry_run defaults True: generates the real caption/hashtags/catalog tag
    and returns exactly what would be posted without calling the Graph
    API. Pass dry_run=false only once you've reviewed that preview.
    """
    if not verify_master_key(data.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    from app.agents.instagram_agent import post_manually
    return post_manually(
        product_id=data.product_id,
        post_type=data.post_type,
        image_count=data.image_count,
        image_urls=data.image_urls,
        dry_run=data.dry_run,
        skip_catalog_tag=data.skip_catalog_tag,
    )