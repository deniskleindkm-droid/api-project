import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.aria_operational import (
    ARIAActionLedger, ARIATool, ARIAConversationState, ARIAPolicy
)


# ============================================================
# SAFE ADAPTER REGISTRY
# Maps adapter_key → real function
# ARIA discovers tools from database but executes through this safe map
# New tools get added here when registered in database
# ============================================================

def _get_adapter_registry():
    return {
        "cj.search_products": _adapter_search_products,
        "cj.import_product_by_pid": _adapter_import_product,
        "store.assign_collection": _adapter_assign_collection,
        "store.update_price": _adapter_update_price,
        "store.delete_product": _adapter_delete_product,
        "email.send_to_dennis": _adapter_send_email,
        "scoring.score_product": _adapter_score_product,
    }


# ============================================================
# TOOL DISCOVERY
# ARIA reads this — discovers what she can do from database
# ============================================================

def discover_tools(agent: str = None) -> list:
    """ARIA discovers her available tools dynamically from database."""
    with Session(engine) as session:
        query = select(ARIATool).where(ARIATool.is_active == True)
        if agent:
            query = query.where(ARIATool.agent == agent)
        tools = session.exec(query).all()

    result = []
    for t in tools:
        result.append({
            "name": t.name,
            "description": t.description,
            "adapter_key": t.adapter_key,
            "risk_level": t.risk_level,
            "requires_confirmation": t.requires_confirmation,
            "agent": t.agent
        })

    print(f"[Execution] 🔍 ARIA discovered {len(result)} tools")
    return result


# ============================================================
# POLICY CHECK
# ============================================================

def check_policy(action_type: str, requesting_agent: str = "aria") -> dict:
    """Check if an action is allowed under current policy."""
    with Session(engine) as session:
        policy = session.exec(
            select(ARIAPolicy).where(
                ARIAPolicy.action_type == action_type,
                ARIAPolicy.is_active == True
            )
        ).first()

    if not policy:
        return {
            "allowed": True,
            "requires_human_approval": False,
            "requires_aria_approval": False,
            "reason": "No policy found — defaulting to allowed"
        }

    allowed_agents = [a.strip() for a in policy.allowed_agents.split(",")]
    if "none" in allowed_agents:
        return {
            "allowed": False,
            "requires_human_approval": True,
            "reason": f"Action '{action_type}' is forbidden for all agents"
        }

    return {
        "allowed": True,
        "requires_human_approval": policy.requires_human_approval,
        "requires_aria_approval": policy.requires_aria_approval,
        "rollback_required": policy.rollback_required,
        "risk_level": policy.risk_level,
        "reason": policy.description
    }


# ============================================================
# ACTION LEDGER
# ============================================================

def create_ledger_entry(conversation_id, action_type, input_summary, assigned_agent="aria") -> int:
    """Create a new action in the ledger — status starts as planned."""
    with Session(engine) as session:
        entry = ARIAActionLedger(
            conversation_id=conversation_id,
            assigned_agent=assigned_agent,
            action_type=action_type,
            input_summary=input_summary[:500],
            status="planned",
            created_at=datetime.utcnow()
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        print(f"[Ledger] 📋 Action planned: {action_type} (ID: {entry.id})")
        return entry.id


def update_ledger(ledger_id: int, status: str, result_summary: str = None,
                  error: str = None, verification_evidence: str = None,
                  tool_calls: list = None):
    """Update action ledger status."""
    with Session(engine) as session:
        entry = session.get(ARIAActionLedger, ledger_id)
        if not entry:
            return

        entry.status = status
        if result_summary:
            entry.result_summary = result_summary[:500]
        if error:
            entry.error_message = error[:500]
        if verification_evidence:
            entry.verification_status = "verified" if "success" in status else "failed"
            entry.verification_evidence = verification_evidence[:500]
        if tool_calls:
            entry.tool_calls_used = json.dumps(tool_calls)
        if status in ["verified_success", "failed", "blocked"]:
            entry.completed_at = datetime.utcnow()

        session.add(entry)
        session.commit()
        print(f"[Ledger] 📊 Action {ledger_id} → {status}")


# ============================================================
# CONVERSATION STATE
# ============================================================

def get_conversation_state(conversation_id: str) -> dict:
    """Get current conversation working memory."""
    with Session(engine) as session:
        state = session.exec(
            select(ARIAConversationState).where(
                ARIAConversationState.conversation_id == conversation_id
            )
        ).first()

    if not state:
        return {}

    return {
        "last_search_results": json.loads(state.last_search_results) if state.last_search_results else [],
        "last_action_taken": state.last_action_taken,
        "last_tool_called": state.last_tool_called,
        "pending_actions": json.loads(state.pending_actions) if state.pending_actions else [],
        "commitments_made": json.loads(state.commitments_made) if state.commitments_made else [],
        "current_intent": state.current_intent,
        "context_summary": state.context_summary
    }


def update_conversation_state(conversation_id: str, **kwargs):
    """Update conversation working memory."""
    with Session(engine) as session:
        state = session.exec(
            select(ARIAConversationState).where(
                ARIAConversationState.conversation_id == conversation_id
            )
        ).first()

        if not state:
            state = ARIAConversationState(
                conversation_id=conversation_id
            )

        if "last_search_results" in kwargs:
            state.last_search_results = json.dumps(kwargs["last_search_results"])
        if "last_action_taken" in kwargs:
            state.last_action_taken = kwargs["last_action_taken"]
        if "last_tool_called" in kwargs:
            state.last_tool_called = kwargs["last_tool_called"]
        if "pending_actions" in kwargs:
            state.pending_actions = json.dumps(kwargs["pending_actions"])
        if "commitments_made" in kwargs:
            state.commitments_made = json.dumps(kwargs["commitments_made"])
        if "current_intent" in kwargs:
            state.current_intent = kwargs["current_intent"]
        if "context_summary" in kwargs:
            state.context_summary = kwargs["context_summary"]

        state.updated_at = datetime.utcnow()
        session.add(state)
        session.commit()


# ============================================================
# MAIN EXECUTION ENGINE
# ============================================================

def execute_tool(adapter_key: str, params: dict, conversation_id: str,
                 action_description: str) -> dict:
    """
    Central execution function.
    Every tool call goes through here.
    Logs to ledger, checks policy, executes safely, verifies result.
    ARIA only says done when verified_success.
    """
    registry = _get_adapter_registry()

    # Check tool exists
    if adapter_key not in registry:
        print(f"[Execution] ❌ Unknown adapter key: {adapter_key}")
        return {
            "success": False,
            "status": "failed",
            "response": f"I don't have a tool for that yet. Available tools: {list(registry.keys())}",
            "verified": False
        }

    # Extract action type from adapter key
    action_type = adapter_key.split(".")[-1]

    # Check policy
    policy = check_policy(action_type)
    if not policy["allowed"]:
        return {
            "success": False,
            "status": "blocked",
            "response": f"This action is not permitted: {policy['reason']}",
            "verified": False
        }

    if policy.get("requires_human_approval"):
        return {
            "success": False,
            "status": "needs_approval",
            "response": f"This action requires your approval Dennis. Shall I proceed with: {action_description}?",
            "verified": False,
            "pending": True
        }

    # Create ledger entry
    ledger_id = create_ledger_entry(
        conversation_id=conversation_id,
        action_type=action_type,
        input_summary=action_description,
        assigned_agent="aria"
    )

    # Update ledger to executing
    update_ledger(ledger_id, "executing")

    # Execute through safe adapter
    try:
        adapter_fn = registry[adapter_key]
        result = adapter_fn(params)

        if result.get("success"):
            # Verify the action
            verified, evidence = _verify_action(adapter_key, params, result)

            if verified:
                update_ledger(
                    ledger_id, "verified_success",
                    result_summary=result.get("summary", str(result)[:200]),
                    verification_evidence=evidence,
                    tool_calls=[adapter_key]
                )
                # Update conversation state
                update_conversation_state(
                    conversation_id,
                    last_action_taken=action_description,
                    last_tool_called=adapter_key
                )
                return {
                    "success": True,
                    "status": "verified_success",
                    "response": result.get("response", "Done."),
                    "verified": True,
                    "evidence": evidence,
                    "data": result
                }
            else:
                update_ledger(
                    ledger_id, "executed_unverified",
                    result_summary="Executed but verification failed",
                    verification_evidence=evidence
                )
                return {
                    "success": True,
                    "status": "executed_unverified",
                    "response": f"I ran the action but could not fully verify it yet. {evidence}",
                    "verified": False
                }
        else:
            error = result.get("reason", "Unknown error")
            update_ledger(ledger_id, "failed", error=error)
            return {
                "success": False,
                "status": "failed",
                "response": f"The action failed: {error}",
                "verified": False
            }

    except Exception as e:
        update_ledger(ledger_id, "failed", error=str(e))
        print(f"[Execution] ❌ Error: {e}")
        return {
            "success": False,
            "status": "failed",
            "response": f"Something went wrong: {str(e)}",
            "verified": False
        }


# ============================================================
# VERIFICATION ENGINE
# ============================================================

def _verify_action(adapter_key: str, params: dict, result: dict) -> tuple:
    """Verify an action was actually completed. Returns (verified, evidence)."""

    if adapter_key == "cj.import_product_by_pid":
        return _verify_product_imported(params, result)

    elif adapter_key == "store.assign_collection":
        return _verify_collection_assigned(params, result)

    elif adapter_key == "store.update_price":
        return _verify_price_updated(params, result)

    elif adapter_key == "cj.search_products":
        products = result.get("products", [])
        if products:
            return True, f"Search returned {len(products)} products"
        return False, "Search returned no results"

    elif adapter_key == "email.send_to_dennis":
        sent = result.get("sent", False)
        return sent, "Email sent successfully" if sent else "Email sending failed"

    # Default — trust the result
    return result.get("success", False), "Action reported success"


def _verify_product_imported(params: dict, result: dict) -> tuple:
    """Verify product actually exists in database after import."""
    from sqlmodel import Session, select
    from app.models.product import Product

    product_name = result.get("product", "")
    if not product_name:
        return False, "No product name in result"

    with Session(engine) as session:
        product = session.exec(
            select(Product).where(
                Product.name == product_name,
                Product.is_active == True
            )
        ).first()

    if product:
        evidence = f"Product '{product_name}' verified in database as ID {product.id}"
        if product.collection_id:
            evidence += f" in collection {product.collection_id}"
        return True, evidence

    return False, f"Product '{product_name}' not found in database after import"


def _verify_collection_assigned(params: dict, result: dict) -> tuple:
    """Verify collection was actually assigned."""
    from sqlmodel import Session
    from app.models.product import Product

    product_id = params.get("product_id")
    collection_id = params.get("collection_id")

    if not product_id or not collection_id:
        return False, "Missing product_id or collection_id"

    with Session(engine) as session:
        product = session.get(Product, product_id)

    if product and product.collection_id == collection_id:
        return True, f"Product {product_id} verified in collection {collection_id}"

    return False, f"Collection assignment not verified for product {product_id}"


def _verify_price_updated(params: dict, result: dict) -> tuple:
    """Verify price was actually updated."""
    from sqlmodel import Session
    from app.models.product import Product

    product_id = params.get("product_id")
    new_price = params.get("final_price")

    if not product_id or not new_price:
        return False, "Missing product_id or price"

    with Session(engine) as session:
        product = session.get(Product, product_id)

    if product and abs(product.final_price - float(new_price)) < 0.01:
        return True, f"Price verified as ${product.final_price} for product {product_id}"

    return False, f"Price update not verified for product {product_id}"


# ============================================================
# SAFE ADAPTERS
# Real functions behind each adapter key
# ============================================================

def _adapter_search_products(params: dict) -> dict:
    from app.agents.cj_dropshipping import search_products
    keyword = params.get("keyword", "")
    markup_config = None
    try:
        from app.agents.store_config import get_config
        markup_config = get_config("default_markup", default=7.0)
    except:
        markup_config = 7.0

    products = search_products(keyword, limit=5)
    if not products:
        return {"success": False, "reason": "No products found", "products": []}

    result = []
    for p in products[:5]:
        raw_price = p.get("sellPrice", "0")
        if isinstance(raw_price, str) and "-" in raw_price:
            cost = float(raw_price.split("-")[0].strip())
        else:
            cost = float(raw_price) if raw_price else 0
        store_price = round(int(cost * markup_config) + 0.99, 2)
        result.append({
            "pid": p.get("pid", ""),
            "name": p.get("productNameEn", ""),
            "cost": cost,
            "store_price": store_price,
            "markup": markup_config
        })

    return {
        "success": True,
        "products": result,
        "summary": f"Found {len(result)} products for '{keyword}'",
        "response": _format_search_response(result, keyword)
    }


def _format_search_response(products: list, keyword: str) -> str:
    if not products:
        return f"No products found for '{keyword}'"
    lines = [f"I found {len(products)} products on CJ for '{keyword}':\n"]
    for i, p in enumerate(products, 1):
        lines.append(
            f"{i}. **{p['name']}**\n"
            f"   CJ cost: ${p['cost']:.2f} → Store price: ${p['store_price']:.2f} ({p['markup']}x markup)\n"
            f"   PID: {p['pid']}\n"
            f"   To import: say 'import {p['pid']}'\n"
        )
    lines.append("\nWhich ones fit Mikisi? Say 'import [pid]' for any you want added.")
    return "\n".join(lines)


def _adapter_import_product(params: dict) -> dict:
    from app.agents.cj_dropshipping import import_product_by_id
    pid = params.get("pid", "")
    markup = params.get("markup")
    if not markup:
        from app.agents.store_config import get_config
        markup = get_config("default_markup", default=7.0)

    result = import_product_by_id(pid, markup=markup)
    if result.get("success"):
        result["response"] = f"✅ **{result.get('product')}** has been added to Mikisi at ${result.get('store_price', 0):.2f}."
    return result


def _adapter_assign_collection(params: dict) -> dict:
    from sqlmodel import Session
    from app.models.product import Product

    product_id = params.get("product_id")
    collection_id = params.get("collection_id")

    if not product_id or not collection_id:
        return {"success": False, "reason": "Missing product_id or collection_id"}

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "reason": f"Product {product_id} not found"}
        old_collection = product.collection_id
        product.collection_id = collection_id
        session.add(product)
        session.commit()

    return {
        "success": True,
        "product_id": product_id,
        "collection_id": collection_id,
        "old_collection": old_collection,
        "response": f"✅ Product {product_id} moved to collection {collection_id}."
    }


def _adapter_update_price(params: dict) -> dict:
    from sqlmodel import Session
    from app.models.product import Product

    product_id = params.get("product_id")
    final_price = params.get("final_price")

    if not product_id or not final_price:
        return {"success": False, "reason": "Missing product_id or final_price"}

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "reason": f"Product {product_id} not found"}
        old_price = product.final_price
        product.final_price = float(final_price)
        session.add(product)
        session.commit()

    return {
        "success": True,
        "product_id": product_id,
        "old_price": old_price,
        "new_price": final_price,
        "response": f"✅ Price updated from ${old_price:.2f} to ${float(final_price):.2f}."
    }


def _adapter_delete_product(params: dict) -> dict:
    from sqlmodel import Session
    from app.models.product import Product

    product_id = params.get("product_id")
    if not product_id:
        return {"success": False, "reason": "Missing product_id"}

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "reason": f"Product {product_id} not found"}
        product.is_active = False
        session.add(product)
        session.commit()

    return {
        "success": True,
        "product_id": product_id,
        "response": f"✅ Product {product_id} removed from store."
    }


def _adapter_send_email(params: dict) -> dict:
    from app.agents.email_partner import send_email
    import os

    to = params.get("to", os.getenv("DENNIS_EMAIL"))
    subject = params.get("subject", "Message from ARIA")
    body = params.get("body", "")

    sent = send_email(to, subject, body, is_html=True)
    return {
        "success": sent,
        "sent": sent,
        "response": "✅ Email sent to your inbox." if sent else "Email failed to send."
    }


def _adapter_score_product(params: dict) -> dict:
    from app.agents.product_scoring import score_product
    result = score_product(params)
    return {
        "success": True,
        "score": result.total_score,
        "recommendation": result.recommendation,
        "response": f"Product scored {result.total_score:.2f} — recommendation: {result.recommendation}"
    }