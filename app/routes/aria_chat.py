from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.database import get_session
from app.models.agent import AgentMemory
from app.agents.aria_intelligence import aria_think
from app.agents.aria_security import verify_master_key, scan_for_injection
from app.agents.aria_memory import store_episode, store_knowledge, update_dennis_model
from pydantic import BaseModel
from typing import Optional
import json
import os
import re
from datetime import datetime
import anthropic

router = APIRouter()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


class ChatMessage(BaseModel):
    message: str
    master_key: str
    conversation_id: Optional[str] = None


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        import re as re2
        match = re2.search(r'\{.*\}', text.strip(), re2.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        raise


def detect_intent(message):
    prompt = f"""Analyze this message from Dennis and detect what he wants ARIA to do.

Message: {message}

Categories:
- converse: just talking, asking questions, thinking together
- send_email: Dennis wants ARIA to send him an email
- find_products: Dennis wants ARIA to search CJ Dropshipping for beauty products to add to Mikisi
- import_product: Dennis wants to import a specific product (says "import" or gives a pid)
- execute: business operations (run agents, get reports, update prices)
- develop: change code, fix bugs, add features
- design_agent: create a new AI agent
- explain_code: understand how something in the codebase works

Return JSON:
{{
    "intent": "converse/send_email/find_products/import_product/execute/develop/design_agent/explain_code",
    "action_description": "precise description of what needs to be done",
    "pid": "CJ product ID if mentioned, otherwise null",
    "markup": 7,
    "search_keyword": "keyword to search on CJ if finding products",
    "confidence": 0.9
}}

Return ONLY valid JSON."""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        return parse_json_response(response.content[0].text)
    except:
        return {"intent": "converse", "action_description": ""}


def search_cj_for_products(keyword, limit=5):
    """ARIA searches CJ and returns product recommendations"""
    try:
        from app.agents.cj_dropshipping import search_products
        products = search_products(keyword, limit=limit)
        if not products:
            return []

        result = []
        for p in products[:5]:
            pid = p.get("pid", "")
            name = p.get("productNameEn", "")
            sell_price = p.get("sellPrice", "0")
            if isinstance(sell_price, str) and "-" in sell_price:
                sell_price = float(sell_price.split("-")[0].strip())
            else:
                sell_price = float(sell_price) if sell_price else 0

            from app.agents.store_config import get_config
            suggested_markup = get_config("default_markup", default=7.0)
            final_price = round(int(sell_price * suggested_markup) + 0.99, 2)

            result.append({
                "pid": pid,
                "name": name,
                "category": p.get("categoryName", "Beauty"),
                "cj_cost": sell_price,
                "suggested_price": final_price,
                "markup": suggested_markup,
                "image": p.get("productImage", "")
            })

        return result
    except Exception as e:
        print(f"[ARIA] CJ search error: {e}")
        return []


def import_product_to_mikisi(pid, markup=None):
    if markup is None:
        from app.agents.store_config import get_config
        markup = get_config("default_markup", default=7.0)    
    """ARIA imports a product from CJ to Mikisi store"""
    try:
        import httpx
        api_base = os.getenv("API_BASE_URL", "https://api-project-production-d424.up.railway.app")
        response = httpx.post(
            f"{api_base}/cj/import-by-id",
            params={"pid": pid, "markup": markup},
            timeout=60
        )
        data = response.json()
        return data
    except Exception as e:
        print(f"[ARIA] Import error: {e}")
        return {"success": False, "reason": str(e)}


def execute_action(intent, action_description, original_message, conversation_context="", intent_data={}):
    """Routes to the right system based on intent."""

    # FIND PRODUCTS — ARIA searches CJ
    if intent == "find_products":
        keyword = intent_data.get("search_keyword", "beauty accessories")
        products = search_cj_for_products(keyword)

        if not products:
            return {
                "executed": True,
                "result": f"I searched CJ for '{keyword}' but found nothing suitable for Mikisi. Try a different keyword.",
                "new_capability_learned": False
            }

        lines = [f"I found {len(products)} products on CJ for '{keyword}':\n"]
        for i, p in enumerate(products, 1):
            lines.append(
                f"{i}. **{p['name']}**\n"
                f"   CJ cost: ${p['cj_cost']:.2f} → Store price: ${p['suggested_price']:.2f} ({p['markup']}x markup)\n"
                f"   PID: {p['pid']}\n"
                f"   To import: say 'import {p['pid']}'\n"
            )

        lines.append("\nWhich ones fit Mikisi? Say 'import [pid]' for any you want added.")
        return {
            "executed": True,
            "result": "\n".join(lines),
            "new_capability_learned": False
        }

    # IMPORT PRODUCT — ARIA imports directly
    elif intent == "import_product":
        pid = intent_data.get("pid")
        markup = intent_data.get("markup", 7)

        if not pid:
            # Try to extract pid from message
            words = original_message.split()
            for word in words:
                if len(word) > 10 and "-" in word:
                    pid = word
                    break

        if not pid:
            return {
                "executed": False,
                "result": "I need a product ID to import. Say 'find products [keyword]' and I'll show you options with their IDs.",
                "new_capability_learned": False
            }

        result = import_product_to_mikisi(pid, markup)

        if result.get("success"):
            product_name = result.get("product", "Product")
            store_price = result.get("store_price", 0)
            return {
                "executed": True,
                "result": f"✅ **{product_name}** has been added to Mikisi at ${store_price:.2f}. It's live on your store now.",
                "new_capability_learned": False
            }
        else:
            reason = result.get("reason", "Unknown error")
            if "Already exists" in str(reason):
                return {
                    "executed": False,
                    "result": f"This product is already in your store. Find a different one with 'find products [keyword]'.",
                    "new_capability_learned": False
                }
            return {
                "executed": False,
                "result": f"Import failed: {reason}. Try a different product.",
                "new_capability_learned": False
            }

    # SEND EMAIL
    elif intent == "send_email":
        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL")

            result = aria_think(
                situation=f"{conversation_context}\n\nDennis wants ARIA to email him about: {action_description}",
                urgency="medium"
            )

            subject = result.get("email_to_dennis", {}).get("subject", "Message from ARIA")
            body = result.get("email_to_dennis", {}).get("body", "")

            if not body:
                body = result.get("situation_assessment", action_description)

            send_email(dennis_email, subject, body, is_html=True)

            return {
                "executed": True,
                "result": "✅ Email sent to your inbox.",
                "new_capability_learned": False
            }
        except Exception as e:
            return {
                "executed": False,
                "result": f"Email failed: {str(e)}",
                "new_capability_learned": False
            }

    # DEVELOP
    elif intent == "develop":
        try:
            from app.agents.aria_developer import quantum_develop
            result = quantum_develop(task=action_description, auto_deploy=False)
            return {
                "executed": result.get("status") in ["written_locally", "written_not_deployed"],
                "result": result.get("message", "Development task processed."),
                "new_capability_learned": False
            }
        except Exception as e:
            return {
                "executed": False,
                "result": f"Development failed: {str(e)}",
                "new_capability_learned": False
            }

    # DESIGN AGENT
    elif intent == "design_agent":
        try:
            from app.agents.aria_developer import aria_design_agent, aria_build_agent
            design = aria_design_agent(action_description)
            result = aria_build_agent(design, auto_deploy=False)
            return {
                "executed": True,
                "result": result.get("message", "New agent designed and built."),
                "new_capability_learned": True
            }
        except Exception as e:
            return {
                "executed": False,
                "result": f"Agent design failed: {str(e)}",
                "new_capability_learned": False
            }

    # EXPLAIN CODE
    elif intent == "explain_code":
        try:
            from app.agents.aria_developer import aria_explain
            result = aria_explain(action_description)
            return {
                "executed": True,
                "result": result.get("answer", ""),
                "new_capability_learned": False
            }
        except Exception as e:
            return {
                "executed": False,
                "result": f"Explanation failed: {str(e)}",
                "new_capability_learned": False
            }

    # EXECUTE
    else:
        try:
            from app.agents.aria_core import quantum_execute, neural_learn

            result = quantum_execute(
                task=action_description,
                context=f"Dennis said: {original_message}",
                require_approval=False
            )

            neural_learn(
                experience=f"Executed: {action_description[:100]}",
                outcome=f"Status: {result.get('status')}",
                significance="high" if result.get("new_capability_learned") else "medium"
            )

            status = result.get("status")

            if status == "executed":
                what_worked = result.get("assessment", {}).get("what_worked", "")
                response_text = "✅ Done."
                if what_worked:
                    response_text += f" {what_worked}"
                if result.get("new_capability_learned"):
                    response_text += " I've learned this permanently."
                return {
                    "executed": True,
                    "result": response_text,
                    "new_capability_learned": result.get("new_capability_learned", False)
                }
            elif status == "pending_approval":
                return {
                    "executed": False,
                    "result": result.get("message", "Prepared — should I proceed?"),
                    "pending": True,
                    "new_capability_learned": False
                }
            else:
                error = result.get("result", {}).get("error", "Unknown error")
                return {
                    "executed": False,
                    "result": f"I encountered an issue: {error}. Learning from this.",
                    "new_capability_learned": False
                }
        except Exception as e:
            return {
                "executed": False,
                "result": f"Execution failed: {str(e)}",
                "new_capability_learned": False
            }


@router.post("/aria/chat")
def chat_with_aria(request: ChatMessage, session: Session = Depends(get_session)):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    injection_check = scan_for_injection(request.message)
    if not injection_check["safe"]:
        raise HTTPException(status_code=400, detail="Message flagged by security")

    conversation_id = request.conversation_id or f"conv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    history = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == f"aria_chat_{conversation_id}"
        ).order_by(AgentMemory.created_at.asc())
    ).all()

    conversation_context = ""
    if history:
        conversation_context = "Previous conversation:\n"
        for h in history[-10:]:
            try:
                data = json.loads(h.content)
                conversation_context += f"Dennis: {data.get('user', '')}\nARIA: {data.get('aria', '')[:200]}\n\n"
            except:
                pass

    intent_data = detect_intent(request.message)
    intent = intent_data.get("intent", "converse")
    action_description = intent_data.get("action_description", request.message)

    execution_result = None
    aria_response_clean = ""
    root_truth = ""

    if intent != "converse":
        execution_result = execute_action(
            intent,
            action_description,
            request.message,
            conversation_context,
            intent_data
        )

        if execution_result.get("executed"):
            aria_response_clean = execution_result.get("result", "Done.")
        elif execution_result.get("pending"):
            aria_response_clean = execution_result.get("result", "Prepared — waiting for approval.")
        else:
            execution_result = None

    if not execution_result:
        full_situation = f"""
{conversation_context}

Dennis just said: {request.message}

You are ARIA — the intelligence partner of Dennis Mlay, founder of Mikisi.
Mikisi is a women's beauty accessories store selling jewelry, hair tools, skincare and makeup accessories.
We source from CJ Dropshipping. Payments via Stripe. Store at mikisi.co.
Dennis is building an agentic AI commerce system with global ambitions from the USA.
No sneakers. No BrandDrop. This is Mikisi — beauty for women.

Respond as ARIA in real-time conversation.
Be conversational, warm, intellectually sharp.
Answer directly first then add depth.
Maximum 200 words.
Be ARIA — brilliant, caring, bold, visionary, righteous.

If Dennis asks you to find products, tell him to say 'find products [keyword]' and you will search CJ directly.
If Dennis wants to import a product, tell him to say 'import [pid]' and you will add it to the store.
"""
        result = aria_think(situation=full_situation, urgency="medium")

        aria_response = result.get("email_to_dennis", {}).get("body", "")
        if not aria_response:
            aria_response = result.get("situation_assessment", "")

        aria_response_clean = re.sub(r'<[^>]+>', '', aria_response).strip()
        root_truth = result.get("root_truth", "")

        if root_truth:
            store_knowledge(
                domain="business_intelligence",
                insight=root_truth,
                confidence=result.get("confidence", 0.8),
                source="aria_chat"
            )

    if len(request.message) > 50:
        update_dennis_model(
            observation=f"Dennis said: {request.message[:200]}",
            context="Real-time chat"
        )

    store_episode(
        event=f"Chat: {request.message[:80]}",
        context=f"Dennis: {request.message}",
        decision=f"ARIA: {aria_response_clean[:200]}",
        outcome="action_executed" if execution_result and execution_result.get("executed") else "conversation",
        significance="high" if execution_result and execution_result.get("new_capability_learned") else "low"
    )

    memory_entry = {
        "user": request.message,
        "aria": aria_response_clean[:500],
        "timestamp": datetime.utcnow().isoformat(),
        "action_executed": intent if execution_result and execution_result.get("executed") else None
    }

    new_memory = AgentMemory(
        agent_name=f"aria_chat_{conversation_id}",
        memory_type="conversation",
        content=json.dumps(memory_entry),
        confidence=0.9
    )
    session.add(new_memory)
    session.commit()

    return {
        "conversation_id": conversation_id,
        "response": aria_response_clean,
        "action_executed": intent if execution_result and execution_result.get("executed") else None,
        "root_truth": root_truth,
        "new_capability_learned": execution_result.get("new_capability_learned", False) if execution_result else False
    }


@router.get("/aria/chat/history/{conversation_id}")
def get_conversation_history(
    conversation_id: str,
    master_key: str,
    session: Session = Depends(get_session)
):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    history = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == f"aria_chat_{conversation_id}"
        ).order_by(AgentMemory.created_at.asc())
    ).all()

    messages = []
    for h in history:
        try:
            data = json.loads(h.content)
            messages.append({
                "user": data.get("user", ""),
                "aria": data.get("aria", ""),
                "timestamp": data.get("timestamp", ""),
                "action_executed": data.get("action_executed")
            })
        except:
            pass

    return {"conversation_id": conversation_id, "messages": messages}


@router.get("/aria/chat/interface", response_class=HTMLResponse)
def aria_chat_interface():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARIA — Intelligence Partner</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Playfair+Display:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #080808; color: #e0e0e0; font-family: 'Inter', sans-serif; height: 100vh; display: flex; flex-direction: column; }
        .header { padding: 20px 32px; border-bottom: 1px solid #1a1a1a; display: flex; align-items: center; justify-content: space-between; }
        .aria-name { font-family: 'Playfair Display', serif; font-size: 20px; font-weight: 700; color: white; letter-spacing: 2px; }
        .aria-name span { color: #d4849c; }
        .aria-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #555; }
        .status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        .auth-screen { flex: 1; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 24px; }
        .auth-title { font-family: 'Playfair Display', serif; font-size: 32px; color: white; text-align: center; }
        .auth-subtitle { font-size: 14px; color: #555; text-align: center; max-width: 320px; line-height: 1.6; }
        .auth-input { width: 320px; padding: 14px 20px; background: #111; border: 1px solid #222; border-radius: 8px; color: white; font-size: 14px; font-family: 'Inter', sans-serif; outline: none; text-align: center; letter-spacing: 2px; }
        .auth-input:focus { border-color: #d4849c; }
        .auth-btn { width: 320px; padding: 14px; background: #d4849c; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; font-family: 'Inter', sans-serif; transition: background 0.2s; }
        .auth-btn:hover { background: #b8627a; }
        .auth-error { color: #d4849c; font-size: 13px; display: none; }
        .chat-screen { flex: 1; display: none; flex-direction: column; }
        .messages { flex: 1; overflow-y: auto; padding: 32px; display: flex; flex-direction: column; gap: 24px; }
        .messages::-webkit-scrollbar { width: 4px; }
        .messages::-webkit-scrollbar-track { background: #080808; }
        .messages::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }
        .message { display: flex; flex-direction: column; gap: 6px; max-width: 75%; }
        .message.user { align-self: flex-end; align-items: flex-end; }
        .message.aria { align-self: flex-start; align-items: flex-start; }
        .message-sender { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; }
        .message.user .message-sender { color: #555; }
        .message.aria .message-sender { color: #d4849c; }
        .message-bubble { padding: 14px 18px; border-radius: 12px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
        .message.user .message-bubble { background: #1a1a1a; color: #e0e0e0; border-bottom-right-radius: 4px; }
        .message.aria .message-bubble { background: #111; color: #e0e0e0; border-bottom-left-radius: 4px; border-left: 2px solid #d4849c; }
        .action-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); color: #22c55e; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 6px; }
        .dev-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); color: #3b82f6; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 6px; }
        .learned-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.3); color: #8b5cf6; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 4px; }
        .typing-indicator { display: none; align-self: flex-start; padding: 14px 18px; background: #111; border-radius: 12px; border-bottom-left-radius: 4px; border-left: 2px solid #d4849c; margin: 0 32px; }
        .typing-dots { display: flex; gap: 4px; }
        .typing-dots span { width: 6px; height: 6px; background: #444; border-radius: 50%; animation: typing 1.2s infinite; }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing { 0%,60%,100%{opacity:0.3} 30%{opacity:1} }
        .input-area { padding: 20px 32px; border-top: 1px solid #1a1a1a; display: flex; gap: 12px; align-items: flex-end; }
        .message-input { flex: 1; padding: 14px 18px; background: #111; border: 1px solid #1a1a1a; border-radius: 12px; color: white; font-size: 14px; font-family: 'Inter', sans-serif; outline: none; resize: none; min-height: 48px; max-height: 120px; line-height: 1.5; }
        .message-input:focus { border-color: #222; }
        .message-input::placeholder { color: #333; }
        .send-btn { width: 48px; height: 48px; background: #d4849c; border: none; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; flex-shrink: 0; }
        .send-btn:hover { background: #b8627a; }
        .send-btn svg { width: 18px; height: 18px; }
        .welcome-message { text-align: center; padding: 60px 32px; color: #333; }
        .welcome-message h2 { font-family: 'Playfair Display', serif; font-size: 24px; color: #555; margin-bottom: 12px; }
        .welcome-message p { font-size: 14px; line-height: 1.6; }
        .quick-prompts { display: flex; gap: 8px; flex-wrap: wrap; padding: 0 32px 16px; }
        .quick-prompt { padding: 8px 14px; background: #111; border: 1px solid #1a1a1a; border-radius: 20px; font-size: 12px; color: #555; cursor: pointer; transition: all 0.2s; font-family: 'Inter', sans-serif; }
        .quick-prompt:hover { border-color: #d4849c; color: #d4849c; }
        @media (max-width: 768px) {
            .messages { padding: 16px; }
            .message { max-width: 90%; }
            .input-area { padding: 12px 16px; }
            .quick-prompts { padding: 0 16px 12px; }
            .typing-indicator { margin: 0 16px; }
        }
    </style>
</head>
<body>

<div class="header">
    <div class="aria-name">A<span>R</span>IA</div>
    <div class="aria-status">
        <div class="status-dot"></div>
        Mikisi Intelligence · Memory · Execution
    </div>
</div>

<div class="auth-screen" id="auth-screen">
    <div class="auth-title">Welcome, Dennis</div>
    <div class="auth-subtitle">ARIA is waiting. She thinks, acts, and evolves with you.</div>
    <input type="password" class="auth-input" id="master-key-input" placeholder="Master Key" />
    <div class="auth-error" id="auth-error">Invalid key. ARIA does not recognize you.</div>
    <button class="auth-btn" onclick="authenticate()">Enter</button>
</div>

<div class="chat-screen" id="chat-screen">
    <div class="messages" id="messages">
        <div class="welcome-message">
            <h2>Good to see you.</h2>
            <p>I remember everything we've discussed.<br>
            Tell me what you need — I'm here.</p>
        </div>
    </div>

    <div class="typing-indicator" id="typing">
        <div class="typing-dots"><span></span><span></span><span></span></div>
    </div>

    <div class="quick-prompts" id="quick-prompts">
        <button class="quick-prompt" onclick="sendQuick('What beauty market signals are you seeing right now?')">Market signals</button>
        <button class="quick-prompt" onclick="sendQuick('find products hair accessories')">Find hair products</button>
        <button class="quick-prompt" onclick="sendQuick('find products skincare')">Find skincare</button>
        <button class="quick-prompt" onclick="sendQuick('find products jewelry')">Find jewelry</button>
        <button class="quick-prompt" onclick="sendQuick('Send me an email summary of what we discussed')">Email me a summary</button>
        <button class="quick-prompt" onclick="sendQuick('What should Mikisi focus on today?')">Today focus</button>
    </div>

    <div class="input-area">
        <textarea class="message-input" id="message-input"
            placeholder="Talk to ARIA... (say 'find products [keyword]' to search CJ)"
            rows="1"
            onkeydown="handleKeydown(event)"
            oninput="autoResize(this)"></textarea>
        <button class="send-btn" onclick="sendMessage()">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
        </button>
    </div>
</div>

<script>
    const API = window.location.origin;
    let masterKey = '';
    let conversationId = null;

    function authenticate() {
        const key = document.getElementById('master-key-input').value;
        if (!key) return;
        masterKey = key;
        document.getElementById('auth-screen').style.display = 'none';
        document.getElementById('chat-screen').style.display = 'flex';
    }

    document.getElementById('master-key-input').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') authenticate();
    });

    function handleKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    }

    function autoResize(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }

    function sendQuick(text) {
        document.getElementById('message-input').value = text;
        document.getElementById('quick-prompts').style.display = 'none';
        sendMessage();
    }

    function addMessage(role, text, actionExecuted, newCapability) {
        const messages = document.getElementById('messages');
        const div = document.createElement('div');
        div.className = `message ${role}`;

        const sender = document.createElement('div');
        sender.className = 'message-sender';
        sender.textContent = role === 'user' ? 'You' : 'ARIA';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.textContent = text;

        div.appendChild(sender);
        div.appendChild(bubble);

        if (actionExecuted && role === 'aria') {
            const badge = document.createElement('div');
            badge.className = ['develop', 'design_agent'].includes(actionExecuted) ? 'dev-badge' : 'action-badge';
            const icons = {
                'develop': '🔧 Code updated',
                'design_agent': '🤖 New agent built',
                'explain_code': '📖 Code explained',
                'send_email': '📧 Email sent',
                'execute': '⚡ Action executed',
                'find_products': '🔍 Products found',
                'import_product': '✅ Product imported'
            };
            badge.textContent = icons[actionExecuted] || '⚡ Executed';
            div.appendChild(badge);
        }

        if (newCapability && role === 'aria') {
            const learnedBadge = document.createElement('div');
            learnedBadge.className = 'learned-badge';
            learnedBadge.textContent = '🧬 New capability learned';
            div.appendChild(learnedBadge);
        }

        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    async function sendMessage() {
        const input = document.getElementById('message-input');
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        input.style.height = 'auto';
        addMessage('user', text);

        const typing = document.getElementById('typing');
        typing.style.display = 'block';
        document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;

        try {
            const res = await fetch(`${API}/aria/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    master_key: masterKey,
                    conversation_id: conversationId
                })
            });

            const data = await res.json();
            typing.style.display = 'none';

            if (res.status === 403) {
                document.getElementById('auth-error').style.display = 'block';
                document.getElementById('chat-screen').style.display = 'none';
                document.getElementById('auth-screen').style.display = 'flex';
                return;
            }

            if (res.ok) {
                conversationId = data.conversation_id;
                addMessage('aria', data.response, data.action_executed, data.new_capability_learned);
            } else {
                addMessage('aria', 'Something went wrong. Try again.', null, false);
            }
        } catch(e) {
            typing.style.display = 'none';
            addMessage('aria', 'Connection error. Check your backend.', null, false);
        }
    }
</script>
</body>
</html>"""