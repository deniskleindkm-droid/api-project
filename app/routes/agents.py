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