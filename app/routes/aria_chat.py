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


def detect_intent(message, conversation_state={}):
    """
    Detect intent with conversation state awareness.
    ARIA knows what was searched last — resolves 'import 1, 2, 3' correctly.
    """
    last_search = conversation_state.get("last_search_results", [])
    last_search_summary = ""
    if last_search:
        last_search_summary = "Last search results:\n" + "\n".join([
            f"{i+1}. {p.get('name', '')} — PID: {p.get('pid', '')}"
            for i, p in enumerate(last_search[:5])
        ])

    prompt = f"""Analyze this message from Dennis and detect what he wants ARIA to do.

Message: {message}

{last_search_summary}

Categories:
- converse: just talking, asking questions, thinking together
- send_email: Dennis wants ARIA to send him an email
- find_products: Dennis wants ARIA to search CJ Dropshipping for beauty products
- import_product: Dennis wants to import a specific product
- assign_collection: Dennis wants to move or change a product to a different collection. Triggers on words like "change", "move", "assign", "put product X in collection Y"
- update_price: Dennis wants to change a product price
- delete_product: Dennis wants to remove a product
- execute: other business operations
- develop: change code, fix bugs, add features
- explain_code: understand how something in the codebase works

Important: If Dennis says "import 1" or "import the first one" or "import both" —
use the last search results above to resolve which PIDs he means.

Return JSON:
{{
    "intent": "converse/send_email/find_products/import_product/assign_collection/update_price/delete_product/execute/develop/explain_code",
    "action_description": "precise description of what needs to be done",
    "pids": ["pid1", "pid2"],
    "search_keyword": "keyword to search on CJ if finding products",
    "product_id": null,
    "collection_id": null,
    "collection_name": "the collection name mentioned if any",
    "new_price": null,
    "confidence": 0.9
}}

Return ONLY valid JSON."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        return parse_json_response(response.content[0].text)
    except:
        return {"intent": "converse", "action_description": ""}


def execute_action(intent, action_description, original_message,
                   conversation_context="", intent_data={}, conversation_id=""):
    """
    Routes to execution engine.
    Every action goes through ledger, policy check, verification.
    ARIA only says done when verified_success.
    """
    from app.agents.aria_execution import (
        execute_tool, update_conversation_state, get_conversation_state
    )

    # FIND PRODUCTS
    if intent == "find_products":
        keyword = intent_data.get("search_keyword", "beauty accessories")

        result = execute_tool(
            adapter_key="cj.search_products",
            params={"keyword": keyword},
            conversation_id=conversation_id,
            action_description=f"Search CJ for: {keyword}"
        )

        if result.get("success"):
            products = result.get("data", {}).get("products", [])
            update_conversation_state(
                conversation_id,
                last_search_results=products,
                current_intent="find_products",
                context_summary=f"Searched for: {keyword}, found {len(products)} products"
            )
            return {
                "executed": True,
                "result": result.get("response", "Found products."),
                "verified": result.get("verified", False),
                "new_capability_learned": False
            }

        return {
            "executed": True,
            "result": f"I searched CJ for '{keyword}' but found nothing suitable for Mikisi. Try a different keyword.",
            "new_capability_learned": False
        }

    # IMPORT PRODUCT — handles single and batch
    elif intent == "import_product":
        from app.agents.aria_execution import get_conversation_state

        pids = intent_data.get("pids", [])

        if not pids:
            raw_pid = None
            words = original_message.split()
            for word in words:
                if len(word) > 10 and "-" in word:
                    raw_pid = word
                    break

            if raw_pid:
                pids = [raw_pid]
            else:
                state = get_conversation_state(conversation_id)
                last_search = state.get("last_search_results", [])
                if last_search:
                    import re as re2
                    numbers = re2.findall(r'\b([1-5])\b', original_message)
                    for n in numbers:
                        idx = int(n) - 1
                        if 0 <= idx < len(last_search):
                            pids.append(last_search[idx].get("pid", ""))

        if not pids:
            state = get_conversation_state(conversation_id)
            last_search = state.get("last_search_results", [])
            if last_search:
                hint = "\n".join([
                    f"{i+1}. {p.get('name', '')} — say 'import {p.get('pid', '')}'"
                    for i, p in enumerate(last_search[:5])
                ])
                return {
                    "executed": False,
                    "result": f"Which product do you want to import? From your last search:\n{hint}",
                    "new_capability_learned": False
                }
            return {
                "executed": False,
                "result": "I need a product ID to import. Say 'find products [keyword]' first and I'll show you options.",
                "new_capability_learned": False
            }

        responses = []
        all_verified = True
        for pid in pids:
            if not pid:
                continue
            result = execute_tool(
                adapter_key="cj.import_product_by_pid",
                params={"pid": pid},
                conversation_id=conversation_id,
                action_description=f"Import product PID: {pid}"
            )
            responses.append(result.get("response", ""))
            if not result.get("verified"):
                all_verified = False

        return {
            "executed": True,
            "result": "\n".join(responses),
            "verified": all_verified,
            "new_capability_learned": False
        }

    # ASSIGN COLLECTION
    elif intent == "assign_collection":
        product_id = intent_data.get("product_id")
        collection_id = intent_data.get("collection_id")
        collection_name = intent_data.get("collection_name", "")

        # Resolve collection name to ID if needed
        if not collection_id and collection_name:
            try:
                from sqlmodel import Session, select
                from app.database import engine
                from app.models.collection import Collection
                with Session(engine) as session:
                    col = session.exec(
                        select(Collection).where(
                            Collection.name.ilike(f"%{collection_name}%"),
                            Collection.is_active == True
                        )
                    ).first()
                    if col:
                        collection_id = col.id
                        print(f"[ARIA] Resolved collection '{collection_name}' → ID {collection_id}")
            except Exception as e:
                print(f"[ARIA] Collection lookup error: {e}")

        if not product_id or not collection_id:
            return {
                "executed": False,
                "result": "I need both a product and a collection. Which product ID and which collection?",
                "new_capability_learned": False
            }

        result = execute_tool(
            adapter_key="store.assign_collection",
            params={"product_id": int(product_id), "collection_id": int(collection_id)},
            conversation_id=conversation_id,
            action_description=f"Move product {product_id} to collection {collection_id}"
        )

        return {
            "executed": result.get("success", False),
            "result": result.get("response", "Done."),
            "verified": result.get("verified", False),
            "new_capability_learned": False
        }

    # UPDATE PRICE
    elif intent == "update_price":
        product_id = intent_data.get("product_id")
        new_price = intent_data.get("new_price")

        if not product_id or not new_price:
            return {
                "executed": False,
                "result": "I need a product ID and new price. Which product and what price?",
                "new_capability_learned": False
            }

        result = execute_tool(
            adapter_key="store.update_price",
            params={"product_id": product_id, "final_price": new_price},
            conversation_id=conversation_id,
            action_description=f"Update product {product_id} price to ${new_price}"
        )

        return {
            "executed": result.get("success", False),
            "result": result.get("response", "Done."),
            "verified": result.get("verified", False),
            "new_capability_learned": False
        }

    # DELETE PRODUCT
    elif intent == "delete_product":
        product_id = intent_data.get("product_id")

        if not product_id:
            return {
                "executed": False,
                "result": "Which product do you want to remove? Give me the product ID.",
                "new_capability_learned": False
            }

        result = execute_tool(
            adapter_key="store.delete_product",
            params={"product_id": product_id},
            conversation_id=conversation_id,
            action_description=f"Delete product {product_id}"
        )

        return {
            "executed": result.get("success", False),
            "result": result.get("response", "Done."),
            "verified": result.get("verified", False),
            "new_capability_learned": False
        }

    # SEND EMAIL
    elif intent == "send_email":
        try:
            from app.agents.email_partner import send_email
            dennis_email = os.getenv("DENNIS_EMAIL")

            aria_result = aria_think(
                situation=f"{conversation_context}\n\nDennis wants ARIA to email him about: {action_description}",
                urgency="medium"
            )

            subject = aria_result.get("email_to_dennis", {}).get("subject", "Message from ARIA")
            body = aria_result.get("email_to_dennis", {}).get("body", "")
            if not body:
                body = aria_result.get("situation_assessment", action_description)

            result = execute_tool(
                adapter_key="email.send_to_dennis",
                params={"to": dennis_email, "subject": subject, "body": body},
                conversation_id=conversation_id,
                action_description=f"Send email: {subject}"
            )

            return {
                "executed": result.get("success", False),
                "result": result.get("response", "Email sent."),
                "verified": result.get("verified", False),
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

    # EXECUTE — requires explicit human approval, never auto-executes
    else:
        return {
            "executed": False,
            "result": None,
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

    # Load conversation state — ARIA's working memory
    from app.agents.aria_execution import get_conversation_state, update_conversation_state
    conversation_state = get_conversation_state(conversation_id)

    # Read live store state on every chat so ARIA always knows what's happening
    store_context_str = ""
    try:
        from app.agents.aria_intelligence import refresh_business_state
        snap = refresh_business_state()
        store_context_str = (
            f"LIVE MIKISI STATE: Revenue ${snap['total_revenue']:.2f} | "
            f"Orders {snap['total_orders']} | Active Products {snap['active_products']} | "
            f"Collections {snap['total_collections']} | Health {snap['system_health']} | "
            f"Products without collection: {snap['products_missing_collection']} | "
            f"Products missing images: {snap['products_missing_images']}"
        )
    except Exception as e:
        print(f"[ARIA Chat] Store snapshot error: {e}")

    # Build conversation context from memory
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

    # Detect intent with conversation state awareness
    intent_data = detect_intent(request.message, conversation_state)
    intent = intent_data.get("intent", "converse")
    action_description = intent_data.get("action_description", request.message)

    execution_result = None
    aria_response_clean = ""
    root_truth = ""
    verified = False

    action_context = (store_context_str + "\n" + conversation_context) if store_context_str else conversation_context

    if intent != "converse":
        execution_result = execute_action(
            intent,
            action_description,
            request.message,
            action_context,
            intent_data,
            conversation_id
        )

        if execution_result.get("executed"):
            aria_response_clean = execution_result.get("result", "Done.")
            verified = execution_result.get("verified", False)
        elif execution_result.get("pending"):
            aria_response_clean = execution_result.get("result", "Prepared — waiting for approval.")
        else:
            execution_result = None

    if not execution_result:
        from app.agents.aria_intelligence import ARIA_CORE

        prompt = f"""{ARIA_CORE}

{store_context_str}

{conversation_context}
Dennis: {request.message}

Reply as ARIA. Plain text only, no HTML.
If this is a question or analysis request, think thoroughly and give a complete answer.
If this is an action request you cannot execute, tell Dennis exactly what command to give.
Never claim to have done something unless you actually executed it through a tool."""

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        aria_response_clean = msg.content[0].text.strip()
        root_truth = ""

        if root_truth:
            store_knowledge(
                domain="business_intelligence",
                insight=root_truth,
                confidence=result.get("confidence", 0.8),
                source="aria_chat"
            )

    # Update Dennis model
    if len(request.message) > 50:
        update_dennis_model(
            observation=f"Dennis said: {request.message[:200]}",
            context="Real-time chat"
        )

    # Store episode in long term memory
    store_episode(
        event=f"Chat: {request.message[:80]}",
        context=f"Dennis: {request.message}",
        decision=f"ARIA: {aria_response_clean[:200]}",
        outcome="action_verified" if verified else "action_executed" if execution_result and execution_result.get("executed") else "conversation",
        significance="high" if verified else "medium" if execution_result else "low"
    )

    # Save to conversation memory
    memory_entry = {
        "user": request.message,
        "aria": aria_response_clean[:500],
        "timestamp": datetime.utcnow().isoformat(),
        "action_executed": intent if execution_result and execution_result.get("executed") else None,
        "verified": verified
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
        "verified": verified,
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
                "action_executed": data.get("action_executed"),
                "verified": data.get("verified", False)
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
        .verified-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.4); color: #22c55e; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 4px; }
        .unverified-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(234,179,8,0.1); border: 1px solid rgba(234,179,8,0.3); color: #eab308; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 4px; }
        .dev-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); color: #3b82f6; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 6px; }
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
        Mikisi Intelligence · Memory · Execution · Verified
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
        <button class="quick-prompt" onclick="sendQuick('find products skincare tools')">Find skincare</button>
        <button class="quick-prompt" onclick="sendQuick('find products jewelry')">Find jewelry</button>
        <button class="quick-prompt" onclick="sendQuick('Send me an email summary of Mikisi status')">Email me summary</button>
        <button class="quick-prompt" onclick="sendQuick('What should Mikisi focus on today?')">Today focus</button>
    </div>

    <div class="input-area">
        <textarea class="message-input" id="message-input"
            placeholder="Talk to ARIA... (say 'find products [keyword]' or 'import [pid]')"
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

    function addMessage(role, text, actionExecuted, verified, newCapability) {
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
                'send_email': '📧 Email sent',
                'find_products': '🔍 Products found',
                'import_product': '📦 Product imported',
                'assign_collection': '📁 Collection assigned',
                'update_price': '💰 Price updated',
                'delete_product': '🗑️ Product removed',
                'execute': '⚡ Executed'
            };
            badge.textContent = icons[actionExecuted] || '⚡ Executed';
            div.appendChild(badge);

            // Verification badge
            if (actionExecuted !== 'find_products') {
                const vBadge = document.createElement('div');
                vBadge.className = verified ? 'verified-badge' : 'unverified-badge';
                vBadge.textContent = verified ? '✓ Verified' : '⚠ Unverified';
                div.appendChild(vBadge);
            }
        }

        if (newCapability && role === 'aria') {
            const learnedBadge = document.createElement('div');
            learnedBadge.className = 'verified-badge';
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
        addMessage('user', text, null, false, false);

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
                addMessage('aria', data.response, data.action_executed, data.verified, data.new_capability_learned);
            } else {
                addMessage('aria', 'Something went wrong. Try again.', null, false, false);
            }
        } catch(e) {
            typing.style.display = 'none';
            addMessage('aria', 'Connection error. Check your backend.', null, false, false);
        }
    }
</script>
</body>
</html>"""