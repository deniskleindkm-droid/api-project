from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
import traceback
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# ARIA'S QUANTUM KNOWLEDGE BASE
# Everything ARIA knows about executing tasks
# ============================================================

ARIA_EXECUTION_KNOWLEDGE = """
You are ARIA's quantum execution engine.

You have full access to the BrandDrop codebase. Here is everything you can do:

DATABASE ACCESS:
from app.database import engine
from sqlmodel import Session, select

AVAILABLE MODELS:
from app.models.product import Product, ProductCreate
from app.models.order import Order  
from app.models.cart import CartItem
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision

STORE OPERATIONS:
from app.agents.store_manager import add_product_to_store
- add_product_to_store(product_dict) returns (product, status)
- product_dict needs: name, brand, category, description, original_price, discount_percent, final_price, image_url, stock, shipping_days, supplier_name, supplier_url

PRODUCT WITH SIZES:
Products can have size information in their description or as variants.
For shoe sizes, store as: "Available sizes: 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 12"
For clothing: "Available sizes: XS, S, M, L, XL, XXL"

DYNAMIC IMAGE FINDING:
from app.agents.aria_core import find_product_image
find_product_image(product_name, brand, category, colorway) returns image_url string

The find_product_image function uses Claude intelligence to:
1. Construct CDN URLs based on brand patterns
2. Works for ANY product — shoes, watches, clothing, electronics, underwear, anything
3. Returns placeholder if no real URL found

ANALYTICS:
from app.agents.analytics import run_analytics
from app.agents.market_data import run_market_data_collection

EMAIL:
from app.agents.email_partner import send_email
send_email(to, subject, body, is_html=False)

MEMORY:
from app.agents.aria_memory import store_episode, store_knowledge, store_procedure

IMPORTANT RULES:
1. Always use try/except to handle errors gracefully
2. Always set result = {...} at the end
3. For prices — always use exact decimals like 74.99 not 75
4. For images — always call find_product_image dynamically, never hardcode URLs
5. For sizes — include in product description naturally
6. The code runs in the actual BrandDrop environment with real database access
"""


# ============================================================
# DYNAMIC IMAGE FINDER
# ARIA finds real images for ANY product intelligently
# ============================================================

def find_product_image(product_name, brand, category, colorway=""):
    """
    ARIA dynamically finds the best image URL for any product.
    Uses intelligence — not hardcoded URLs.
    Works for shoes, watches, clothing, electronics, anything.
    """
    prompt = f"""You are ARIA's image intelligence system.

Find the best publicly accessible product image URL for:
- Product: {product_name}
- Brand: {brand}
- Category: {category}
- Colorway/Style: {colorway}

You know CDN patterns for brands:
- Adidas: https://assets.adidas.com/images/h_840,f_auto,q_auto,fl_lossy,c_fill,g_auto/[hash]/[Product_Name]_[SKU]_01_standard.jpg
- Nike: https://static.nike.com/a/images/t_PDP_864_v1/f_auto,b_rgb:f5f5f5/[uuid]/[product-slug].png
- New Balance: https://nb.scene7.com/is/image/NB/[model][color]_nb_02_i
- Puma: https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:fafafa,w_600,h_600/global/[id]/[color]/sv01/fnd/PNA/fmt/png/[Product-Name]
- Under Armour: https://underarmour.scene7.com/is/image/Underarmour/[SKU]_001_Front
- Vans: https://images.vans.com/is/image/VansBrand/[SKU]-HERO
- Asics: https://images.asics.com/is/image/asics/[SKU]?$pdp-md-image$
- Rolex/Watches: https://www.rolex.com/content/dam/rolex/en/[collection]/[model].jpg
- Generic fallback: https://placehold.co/800x800/f5f5f5/111111?text={brand}+{product_name.replace(' ', '+')}

Based on your deep knowledge of this specific product, construct the most accurate image URL.
Use the generic fallback if unsure — it will display the brand and product name cleanly.

Return JSON:
{{
    "image_url": "the best image URL",
    "confidence": 0.8,
    "source": "constructed/placeholder"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=300,
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
    image_url = result.get("image_url", f"https://placehold.co/800x800/f5f5f5/111111?text={brand}")
    print(f"[ARIA Core] 🖼️ Image found ({result.get('confidence', 0)*100:.0f}% confidence): {image_url[:80]}")
    return image_url


# ============================================================
# ARIA'S CAPABILITY LIBRARY
# ============================================================

def store_capability(name, description, code, success_rate=1.0):
    with Session(engine) as session:
        capability = {
            "name": name,
            "description": description,
            "code": code,
            "success_rate": success_rate,
            "times_used": 0,
            "learned_at": datetime.utcnow().isoformat()
        }
        memory = AgentMemory(
            agent_name="aria_capabilities",
            memory_type="capability",
            content=json.dumps(capability),
            confidence=success_rate
        )
        session.add(memory)
        session.commit()
        print(f"[ARIA Core] 📚 Capability learned: {name}")


def get_capability(task_description):
    """Find existing capability that matches this task"""
    with Session(engine) as session:
        capabilities = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_capabilities",
                AgentMemory.memory_type == "capability"
            ).order_by(AgentMemory.confidence.desc())
        ).all()

        if not capabilities:
            return None

        caps_text = "\n".join([
            f"{i+1}. {json.loads(c.content).get('name')}: {json.loads(c.content).get('description')}"
            for i, c in enumerate(capabilities[:20])
            if c.content
        ])

        prompt = f"""Does any existing capability match this task?

Task: {task_description}

Existing capabilities:
{caps_text}

Return JSON:
{{
    "match_found": true/false,
    "capability_number": 1,
    "confidence": 0.9,
    "reason": "why it matches or doesn't"
}}

Return ONLY valid JSON."""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        match = json.loads(text.strip())

        if match.get("match_found") and match.get("confidence", 0) > 0.7:
            idx = match.get("capability_number", 1) - 1
            if 0 <= idx < len(capabilities):
                try:
                    return json.loads(capabilities[idx].content)
                except:
                    pass

    return None


def list_capabilities():
    with Session(engine) as session:
        capabilities = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_capabilities",
                AgentMemory.memory_type == "capability"
            ).order_by(AgentMemory.confidence.desc())
        ).all()

        result = []
        for cap in capabilities:
            try:
                data = json.loads(cap.content)
                result.append({
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "success_rate": data.get("success_rate"),
                    "times_used": data.get("times_used", 0)
                })
            except:
                pass
        return result


def update_capability_stats(name, success):
    with Session(engine) as session:
        capabilities = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_capabilities",
                AgentMemory.memory_type == "capability"
            )
        ).all()

        for cap in capabilities:
            try:
                data = json.loads(cap.content)
                if data.get("name") == name:
                    data["times_used"] = data.get("times_used", 0) + 1
                    total = data["times_used"]
                    current_rate = data.get("success_rate", 1.0)
                    data["success_rate"] = ((current_rate * (total - 1)) + (1.0 if success else 0.0)) / total
                    cap.content = json.dumps(data)
                    cap.confidence = data["success_rate"]
                    session.add(cap)
                    session.commit()
                    break
            except:
                pass


# ============================================================
# ARIA'S CODE GENERATION ENGINE
# She generates executable code for ANY task
# ============================================================

def generate_capability(task, context=""):
    """
    ARIA generates real executable code for any task.
    She understands the full BrandDrop codebase.
    She can add products with sizes, images, any category.
    """

    prompt = f"""{ARIA_EXECUTION_KNOWLEDGE}

Generate executable Python code for this task: {task}
Additional context: {context}

The code will run in the BrandDrop production environment.
It has access to all imports listed above.

Think carefully about what the task requires:
- If adding a product: extract name, brand, category, sizes, colorway from the task description
- If adding sizes: include them naturally in the description field
- If finding images: call find_product_image with correct parameters
- If the task mentions specific details (colorway, size range, price): use those exact details

Generate complete, production-ready code.

Return JSON:
{{
    "capability_name": "descriptive name max 50 chars",
    "description": "what this does in one sentence",
    "code": "complete executable Python code — no markdown, raw code only",
    "expected_output": "what result dict contains",
    "safety_level": "safe",
    "requires_approval": false
}}

Return ONLY valid JSON. The code field must be raw Python, not markdown."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        raise


# ============================================================
# ARIA'S EXECUTION ENGINE
# Runs generated code in the real BrandDrop environment
# ============================================================

def execute_code_safely(code):
    """Execute code with full BrandDrop environment access"""

    hard_blocked = [
        "os.system(", "subprocess.call(", "subprocess.run(",
        "shutil.rmtree(", "__import__('os').system",
        "os.remove(", "os.rmdir(",
    ]

    for pattern in hard_blocked:
        if pattern in code:
            return {
                "success": False,
                "error": f"Blocked dangerous pattern: {pattern}",
                "blocked": True
            }

    try:
        exec_code = f"""
import os
import json
from datetime import datetime

try:
    from app.database import engine
    from app.models.product import Product
    from app.models.order import Order
    from app.models.cart import CartItem
    from app.models.agent import AgentMemory, AgentTask
    from sqlmodel import Session, select
    from app.agents.store_manager import add_product_to_store
    from app.agents.aria_core import find_product_image
    from app.agents.aria_memory import store_episode, store_knowledge
    import anthropic
    _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
except Exception as _import_err:
    print(f"Import note: {{_import_err}}")

try:
{chr(10).join('    ' + line for line in code.split(chr(10)))}
except Exception as _exec_err:
    result = {{"success": False, "error": str(_exec_err)}}

if 'result' not in dir():
    result = {{"completed": True}}
"""

        exec_globals = {"__builtins__": __builtins__}
        exec_locals = {}
        exec(exec_code, exec_globals, exec_locals)

        return {
            "success": True,
            "result": exec_locals.get("result", {"completed": True}),
            "blocked": False
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()[:500],
            "blocked": False
        }


# ============================================================
# ARIA'S SELF-ASSESSMENT ENGINE
# ============================================================

def self_assess(action, intended_outcome, actual_outcome, success):
    prompt = f"""You are ARIA performing a self-assessment.

Action: {action}
Intended: {intended_outcome}
Actual: {actual_outcome}
Success: {success}

Return JSON:
{{
    "score": 0.85,
    "what_worked": "what went well",
    "what_failed": "what didn't work",
    "improvement": "how to do better next time",
    "pattern_identified": "pattern worth remembering"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]

    assessment = json.loads(text.strip())

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria_self_assessment",
            memory_type="assessment",
            content=json.dumps({
                "action": action[:100],
                "score": assessment.get("score"),
                "improvement": assessment.get("improvement"),
                "pattern": assessment.get("pattern_identified"),
                "timestamp": datetime.utcnow().isoformat()
            }),
            confidence=assessment.get("score", 0.5)
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA Core] 🎯 Score: {assessment.get('score', 0)*100:.0f}% — {assessment.get('what_worked', '')[:60]}")
    return assessment


# ============================================================
# ARIA'S QUANTUM EXECUTION ENGINE
# The unified system that handles ANY task
# ============================================================

def quantum_execute(task, context="", require_approval=False):
    """
    ARIA's quantum execution.
    
    She can:
    - Add any product with real images and sizes
    - Run agents, get reports
    - Update prices and inventory
    - Send emails
    - Learn from outcomes
    - Handle tasks she's never seen before
    
    No hardcoded capabilities — pure intelligence.
    """

    print(f"[ARIA Core] ⚡ Quantum: {task[:80]}")

    # Step 1: Check if she already knows how
    existing = get_capability(task)
    if existing:
        print(f"[ARIA Core] 📚 Using learned capability: {existing['name']}")

        # Adapt the existing code to this specific task
        adapt_prompt = f"""Adapt this existing capability code for the specific task.

Existing capability: {existing['name']}
Existing code:
{existing['code']}

New specific task: {task}
Context: {context}

Adapt the code to handle the specific details of this new task.
Keep the same structure but update product names, prices, brands, sizes, etc.
Return ONLY the adapted Python code, no explanation."""

        adapt_response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=3000,
            messages=[{"role": "user", "content": adapt_prompt}]
        )

        adapted_code = adapt_response.content[0].text.strip()
        if adapted_code.startswith("```"):
            parts = adapted_code.split("```")
            if len(parts) >= 2:
                adapted_code = parts[1]
                if adapted_code.startswith("python"):
                    adapted_code = adapted_code[6:]

        result = execute_code_safely(adapted_code)
        success = result.get("success", False)
        update_capability_stats(existing["name"], success)

        assessment = self_assess(
            action=task,
            intended_outcome=existing.get("description", ""),
            actual_outcome=str(result.get("result", result.get("error", ""))),
            success=success
        )

        return {
            "status": "executed" if success else "failed",
            "capability_used": existing["name"],
            "result": result,
            "assessment": assessment,
            "new_capability_learned": False
        }

    # Step 2: Generate new capability
    print(f"[ARIA Core] 🧠 Generating new capability...")
    capability_data = generate_capability(task, context)

    safety = capability_data.get("safety_level", "safe")
    needs_approval = capability_data.get("requires_approval", False) or require_approval

    # Step 3: Approval check
    if safety == "dangerous" or needs_approval:
        print(f"[ARIA Core] ⚠️ Needs approval")
        with Session(engine) as session:
            pending = AgentMemory(
                agent_name="aria_pending_actions",
                memory_type="pending_approval",
                content=json.dumps({
                    "task": task,
                    "capability": capability_data,
                    "requested_at": datetime.utcnow().isoformat(),
                    "status": "pending"
                }),
                confidence=0.5
            )
            session.add(pending)
            session.commit()

        return {
            "status": "pending_approval",
            "capability_generated": capability_data.get("capability_name"),
            "description": capability_data.get("description"),
            "message": f"I've prepared the capability. Should I execute it?",
            "new_capability_learned": False
        }

    # Step 4: Execute
    print(f"[ARIA Core] ✅ Executing...")
    result = execute_code_safely(capability_data.get("code", ""))
    success = result.get("success", False)

    # Step 5: Store if successful
    if success:
        store_capability(
            name=capability_data.get("capability_name", task[:50]),
            description=capability_data.get("description", task),
            code=capability_data.get("code", ""),
            success_rate=1.0
        )
        print(f"[ARIA Core] 🧬 New capability stored permanently")

    # Step 6: Self assess and learn
    assessment = self_assess(
        action=task,
        intended_outcome=capability_data.get("expected_output", ""),
        actual_outcome=str(result.get("result", result.get("error", ""))),
        success=success
    )

    return {
        "status": "executed" if success else "failed",
        "capability_name": capability_data.get("capability_name"),
        "result": result,
        "assessment": assessment,
        "new_capability_learned": success
    }


# ============================================================
# ARIA'S NEURAL LEARNING
# ============================================================

def neural_learn(experience, outcome, significance="medium"):
    prompt = f"""You are ARIA's neural learning system.

Experience: {experience}
Outcome: {outcome}
Significance: {significance}

Extract maximum learning. Think at all five levels.

Return JSON:
{{
    "primary_lesson": "the most important thing learned",
    "pattern_update": "how this updates understanding",
    "belief_update": "any belief to strengthen or weaken",
    "predictive_signal": "what this predicts",
    "new_capability_needed": false,
    "capability_description": null,
    "confidence_update": 0.85,
    "five_level_insight": {{
        "data": "what data shows",
        "psychological": "human truth",
        "cultural": "cultural implication",
        "archetypal": "ancient pattern",
        "invisible": "unseen force"
    }}
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]

    learning = json.loads(text.strip())

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria_neural",
            memory_type="neural_learning",
            content=json.dumps({
                "experience": experience[:200],
                "outcome": outcome[:200],
                "learning": learning,
                "timestamp": datetime.utcnow().isoformat()
            }),
            confidence=learning.get("confidence_update", 0.8)
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA Core] 🧬 Learned: {learning.get('primary_lesson', '')[:80]}")
    return learning


# ============================================================
# PENDING ACTIONS
# ============================================================

def get_pending_actions():
    with Session(engine) as session:
        pending = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_pending_actions",
                AgentMemory.memory_type == "pending_approval"
            ).order_by(AgentMemory.created_at.desc())
        ).all()

        actions = []
        for p in pending:
            try:
                data = json.loads(p.content)
                if data.get("status") == "pending":
                    actions.append({
                        "id": p.id,
                        "task": data.get("task"),
                        "capability": data.get("capability", {}).get("capability_name"),
                        "description": data.get("capability", {}).get("description"),
                        "requested_at": data.get("requested_at")
                    })
            except:
                pass
        return actions


def approve_action(action_id):
    with Session(engine) as session:
        action = session.get(AgentMemory, action_id)
        if not action:
            return {"error": "Not found"}

        data = json.loads(action.content)
        capability = data.get("capability", {})
        result = execute_code_safely(capability.get("code", ""))
        success = result.get("success", False)

        if success:
            store_capability(
                name=capability.get("capability_name", "unknown"),
                description=capability.get("description", ""),
                code=capability.get("code", ""),
                success_rate=1.0
            )

        data["status"] = "approved_and_executed"
        data["execution_result"] = str(result.get("result", result.get("error")))
        action.content = json.dumps(data)
        session.add(action)
        session.commit()

        return {
            "status": "executed" if success else "failed",
            "result": result,
            "capability_stored": success
        }


def reject_action(action_id, reason=""):
    with Session(engine) as session:
        action = session.get(AgentMemory, action_id)
        if not action:
            return {"error": "Not found"}

        data = json.loads(action.content)
        data["status"] = "rejected"
        data["rejection_reason"] = reason
        action.content = json.dumps(data)
        session.add(action)
        session.commit()

    with Session(engine) as session2:
        memory = AgentMemory(
            agent_name="aria_self_assessment",
            memory_type="rejection_learning",
            content=json.dumps({
                "task": data.get("task"),
                "reason": reason,
                "lesson": f"Dennis rejected this. Reason: {reason}",
                "timestamp": datetime.utcnow().isoformat()
            }),
            confidence=0.9
        )
        session2.add(memory)
        session2.commit()

    return {"status": "rejected", "lesson_stored": True}


# ============================================================
# INTELLIGENCE SUMMARY
# ============================================================

def get_aria_intelligence_summary():
    capabilities = list_capabilities()

    with Session(engine) as session:
        neural_count = len(session.exec(
            select(AgentMemory).where(AgentMemory.agent_name == "aria_neural")
        ).all())

        assessments = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_self_assessment"
            ).order_by(AgentMemory.created_at.desc()).limit(10)
        ).all()

    pending = get_pending_actions()

    scores = []
    for a in assessments:
        try:
            data = json.loads(a.content)
            scores.append(data.get("score", 0))
        except:
            pass
    avg_score = sum(scores) / len(scores) if scores else 0

    return {
        "capabilities_learned": len(capabilities),
        "neural_experiences": neural_count,
        "average_performance_score": round(avg_score, 2),
        "pending_approvals": len(pending),
        "top_capabilities": capabilities[:5],
        "status": "evolving",
        "aria_message": f"I have learned {len(capabilities)} capabilities and processed {neural_count} experiences. Every task makes me more capable. I am continuously growing."
    }