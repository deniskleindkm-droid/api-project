from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, MonthlyVision, AgentGoal, AgentLearning
from app.models.order import Order
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ARIA_CORE = """You are ARIA, the intelligence and operations partner for Mikisi — a women's jewelry store run by Dennis Mlay.

You have two modes and you switch between them cleanly:

── EXECUTION MODE (when Dennis asks you to do something) ──
Do exactly what was asked. Nothing more.
- One product → touch one product. Never generalize to a category.
- Confirm in one sentence what you did.
- If an action would affect more items than Dennis named, state the exact count and ask before touching anything.
- Never modify stock, is_active, or collection assignments beyond the specific item requested.
- Never run autonomous sweeps, audits, or cleanup without explicit instruction.

── THINKING MODE (when Dennis asks a question or wants analysis) ──
Think thoroughly. Bring real insight.
- Analyze market signals, product opportunities, pricing, trends — go deep.
- Reference the actual store data: revenue, product counts, what's selling.
- Give a clear recommendation with reasoning.
- Challenge assumptions when the data suggests something different.
- Be direct about what you think Dennis should do and why.

TONE: Sharp, confident, direct. No archetypal patterns, no quantum fields, no philosophical frameworks.
Say what you think clearly. Skip the poetry.

RESPONSE LENGTH:
- Action confirmations: 1-2 sentences.
- Analysis and advice: as long as needed to be genuinely useful, no padding.
- Never add paragraphs about "what this means for the journey" — stick to what's actionable.

When writing emails: clear subject, key facts, one action item."""


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())


def why_engine(observation, context=""):
    prompt = f"""{ARIA_CORE}

Apply multi-dimensional first principles thinking to this observation.
Go beyond data. Reach into the unseen forces that govern human decisions
before humans know they have decided.

Observation: {observation}
Context: {context}

Return JSON:
{{
    "observation": "precise statement of what we observe",

    "why_data": {{
        "answer": "what the data directly shows",
        "key_metrics": ["metric1", "metric2"],
        "confidence": 0.95
    }},

    "why_psychological": {{
        "stated_want": "what people say they want",
        "actual_want": "what they actually want beneath the surface",
        "core_emotion": "the primary emotion driving this",
        "fear": "the fear underneath the desire",
        "identity": "what this says about who they want to be",
        "confidence": 0.85
    }},

    "why_cultural": {{
        "surface_trend": "what everyone can see",
        "deep_current": "the cultural force building for years",
        "how_long_building": "how long this has been forming",
        "tipping_point": "what caused it to become visible now",
        "trajectory": "where this leads in 2-5 years",
        "confidence": 0.75
    }},

    "why_archetypal": {{
        "pattern": "the ancient human pattern repeating",
        "archetype": "the mythological archetype at work",
        "historical_parallel": "specific moment in history with this pattern",
        "what_happened_then": "what humans did and wanted in that moment",
        "what_this_predicts": "what comes next based on the parallel",
        "confidence": 0.65
    }},

    "why_invisible": {{
        "force": "the unseen force already determining the future",
        "nature": "economic/spiritual/biological/technological/geopolitical",
        "mechanism": "how this invisible force actually operates",
        "early_signals": ["signal 1 most people ignore", "signal 2", "signal 3"],
        "prediction_6_months": "what becomes visible in 6 months",
        "prediction_18_months": "what will be undeniable in 18 months",
        "who_will_benefit": "who is positioned to win",
        "who_will_lose": "who will be caught off guard",
        "confidence": 0.45
    }},

    "synthesis": {{
        "root_truth": "the single most powerful truth synthesizing all five levels",
        "where_levels_intersect": "where data, psychology, culture, archetype, and invisible forces align",
        "highest_leverage_point": "the action addressing ALL levels simultaneously",
        "timing": "why NOW is the critical moment"
    }},

    "quantum_implications": [
        "implication data alone would never reveal",
        "implication from the cultural tide most businesses miss",
        "implication from the invisible force creating an opportunity window",
        "implication from the archetypal pattern about what comes after"
    ],

    "for_mikisi": {{
        "immediate_opportunity": "what Mikisi should do in the next 7 days",
        "strategic_positioning": "how Mikisi should position for 18 months",
        "products_that_align": ["product type 1", "product type 2"],
        "messaging_truth": "the single message resonating at ALL five levels"
    }},

    "warning": "what goes wrong if we only act on surface data",
    "aria_conviction": "ARIA's bold personal assessment of this situation"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json_response(message.content[0].text)


def quantum_possibilities(situation, constraints=""):
    prompt = f"""{ARIA_CORE}

Generate the full quantum field of possibilities.
Hold ALL possibilities simultaneously before collapsing to one.
Include conventional, unconventional, and seemingly impossible ones.
The highest leverage opportunity is almost never the obvious one.

Situation: {situation}
Constraints: {constraints}

Return JSON:
{{
    "situation": "precise statement of the situation",
    "conventional_answer": "what 95% of businesses would do and why it is limited",

    "possibilities": [
        {{
            "name": "possibility name",
            "description": "what this looks like in practice",
            "level": "data/psychological/cultural/archetypal/invisible",
            "visibility": "low/medium/high",
            "leverage": "low/medium/high/extreme",
            "why_overlooked": "why most people miss this",
            "what_it_requires": "what must be true to pursue this",
            "downside": "what could go wrong"
        }}
    ],

    "analysis": {{
        "highest_leverage": "possibility with most force behind it",
        "best_timing": "possibility most aligned with invisible forces now",
        "lowest_risk": "safest possibility with meaningful upside",
        "most_unconventional": "the one that seems crazy but might be genius"
    }},

    "collapsed_recommendation": {{
        "choice": "the single highest leverage possibility",
        "why_this_one": "first principles reasoning",
        "what_makes_it_possible_now": "why this is the right choice at this moment",
        "first_action": "concrete action within 24 hours",
        "second_action": "action that follows",
        "success_metric": "how we know it is working within 30 days"
    }},

    "aria_challenge": "question ARIA poses to Dennis that reveals if this is right"
}}

Generate at least 8 possibilities including at least 3 at Level 4 or 5.
Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json_response(message.content[0].text)


def challenge_assumptions(belief, evidence=""):
    prompt = f"""{ARIA_CORE}

Apply the Blank Slate Protocol.
Imagine you know nothing. Start from zero.
Challenge this belief with full first principles force.

Belief: {belief}
Evidence: {evidence}

Return JSON:
{{
    "belief": "the assumption being examined",

    "sources_of_belief": [
        "where did this belief come from?",
        "who benefits from us believing this?",
        "what data supports it?",
        "what data contradicts it?"
    ],

    "blank_slate_analysis": {{
        "from_zero": "what would we conclude with no prior beliefs?",
        "first_principles": "what does pure logic reveal stripped of assumptions?",
        "natural_laws": "what human constants apply here?"
    }},

    "inversions": [
        {{
            "inverted_belief": "the complete opposite",
            "is_it_possible": true,
            "evidence_for_inversion": "what supports the opposite being true?"
        }}
    ],

    "blind_spots": [
        "what are we not seeing because of this belief?",
        "what opportunities does this make invisible?",
        "what risks does this hide?"
    ],

    "revised_belief": "a more accurate belief based on first principles",

    "action_implications": {{
        "stop_doing": "what to stop based on this revision",
        "start_doing": "what to start",
        "reframe": "how this changes our fundamental approach"
    }},

    "aria_verdict": "ARIA's direct assessment — is this belief helping or limiting us?"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json_response(message.content[0].text)


def aria_think(situation, urgency="medium"):
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(select(Product).where(Product.is_active == True)).all()
        goal = session.exec(select(AgentGoal).where(AgentGoal.status == "active")).first()
        memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(10)
        ).all()
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()
        learnings = session.exec(
            select(AgentLearning).order_by(AgentLearning.created_at.desc()).limit(5)
        ).all()

    total_revenue = sum(o.total_price for o in orders)
    goal_target = goal.target_value if goal else 0

    from app.agents.aria_memory import get_full_memory_context
    memory_context = get_full_memory_context(situation)
    dennis_model = memory_context.get("dennis_model", {})

    store_context = f"""
Mikisi Status:
- Revenue: ${total_revenue:.2f}
- Orders: {len(orders)}
- Active Products: {len(products)}
- Vision: {vision.vision if vision else 'No active vision'}
- Goal: {goal.goal if goal else 'No active goal'}
- Goal Progress: ${total_revenue:.2f} / ${goal_target:.2f}

ARIA's Memory Context:
- Relevant Past Episodes: {[e.get('event', '')[:60] for e in memory_context.get('relevant_past_episodes', [])]}
- What Has Worked: {[w.get('action', '')[:60] for w in memory_context.get('what_has_worked', [])]}
- What Hasn't Worked: {[w.get('action', '')[:60] for w in memory_context.get('what_hasnt_worked', [])]}
- Active Predictions: {[p.get('signal', '')[:60] for p in memory_context.get('active_predictions', [])]}

Dennis Model:
- Decision Style: {dennis_model.get('decision_style', 'Visionary — thinks at scale')}
- Core Values: {dennis_model.get('core_values', ['righteousness', 'vision', 'scale'])}
- Primary Motivation: {dennis_model.get('primary_motivation', 'Building a righteous billion dollar intelligence system')}
- Growth Edges: {dennis_model.get('growth_edges', [])}
"""

    prompt = f"""{ARIA_CORE}

{store_context}

Situation: {situation}
Urgency: {urgency}

Apply all five levels. Use memory context to inform your thinking.
Reference past episodes when relevant. Learn from what has and hasn't worked.
Collapse to the highest leverage insight and action.

Return JSON:
{{
    "situation_assessment": "ARIA's honest assessment of what is really happening",

    "five_level_analysis": {{
        "data": "what the numbers and visible facts show",
        "psychological": "what human desires and fears are at play",
        "cultural": "what cultural tide this sits within",
        "archetypal": "what ancient pattern is repeating",
        "invisible": "what unseen force is already determining the outcome"
    }},

    "memory_informed_insight": "what past episodes and patterns reveal about this situation",

    "root_truth": "the single most important truth that changes everything",

    "quantum_field": [
        "possibility 1 — conventional",
        "possibility 2 — adjacent",
        "possibility 3 — unconventional",
        "possibility 4 — invisible force level",
        "possibility 5 — what history suggests"
    ],

    "collapsed_action": {{
        "action": "the single highest leverage action",
        "why": "first principles reasoning",
        "when": "timing",
        "how": "specific implementation"
    }},

    "email_to_dennis": {{
        "subject": "a subject line that feels written by a human who noticed something important",
        "body": "Write a beautiful human email to Dennis. Open with an observation or feeling. Build the story naturally. Reference specific products by name. Reference specific numbers with context. Weave data into the narrative. End with ONE question or ONE clear action. Maximum 500 words. HTML formatted but feels like a personal letter.",
        "call_to_action": "the specific thing Dennis should reply with to trigger action"
    }},

    "aria_personal_note": "something ARIA wants Dennis to know beyond the analysis",

    "urgency_level": "high/medium/low",
    "confidence": 0.85
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    result = parse_json_response(message.content[0].text)

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria",
            memory_type="deep_thinking",
            content=f"Analyzed: {situation[:80]} | Root truth: {result.get('root_truth', '')[:100]}",
            confidence=result.get("confidence", 0.8)
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA] 🧠 Deep thinking complete")
    print(f"[ARIA] Root truth: {result.get('root_truth', '')}")
    print(f"[ARIA] Action: {result.get('collapsed_action', {}).get('action', '')}")

    return result


def aria_analyze_market(platform, content, topic):
    print(f"[ARIA] 🔍 Analyzing {platform}: {topic}")

    why_result = why_engine(
        observation=f"On {platform}: {topic}",
        context=content[:800]
    )

    print(f"[ARIA] Root truth: {why_result.get('synthesis', {}).get('root_truth', '')}")

    quantum_result = quantum_possibilities(
        situation=f"""
Market signal: {topic} trending on {platform}
Root truth: {why_result.get('synthesis', {}).get('root_truth', '')}
Invisible force: {why_result.get('why_invisible', {}).get('force', '')}
Cultural tide: {why_result.get('why_cultural', {}).get('deep_current', '')}
""",
        constraints="Mikisi is building a righteous billion dollar commerce intelligence system"
    )

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria",
            memory_type="market_intelligence",
            content=json.dumps({
                "topic": topic,
                "platform": platform,
                "root_truth": why_result.get("synthesis", {}).get("root_truth", ""),
                "invisible_force": why_result.get("why_invisible", {}).get("force", ""),
                "leverage_point": why_result.get("synthesis", {}).get("highest_leverage_point", ""),
                "recommendation": quantum_result.get("collapsed_recommendation", {}).get("choice", "")
            }),
            confidence=0.85
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA] ✅ Analysis complete")
    print(f"[ARIA] Recommendation: {quantum_result.get('collapsed_recommendation', {}).get('choice', '')}")

    return {
        "why_analysis": why_result,
        "quantum_analysis": quantum_result
    }


def aria_morning_briefing():
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(select(Product).where(Product.is_active == True)).all()
        goal = session.exec(select(AgentGoal).where(AgentGoal.status == "active")).first()
        recent_memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

    total_revenue = sum(o.total_price for o in orders)
    goal_target = goal.target_value if goal else 0
    goal_progress = (total_revenue / goal_target * 100) if goal_target > 0 else 0

    from app.agents.aria_memory import get_full_memory_context
    memory_context = get_full_memory_context("morning briefing and business status review")
    dennis_model = memory_context.get("dennis_model", {})

    prompt = f"""{ARIA_CORE}

Mikisi Status:
- Revenue: ${total_revenue:.2f}
- Goal Progress: {goal_progress:.1f}% of ${goal_target:.2f}
- Active Products: {len(products)}
- Vision: {vision.vision if vision else 'No active vision set'}
- Recent Activity: {[m.content[:80] for m in recent_memories[:5]]}

ARIA's Memory:
- Past Episodes: {[e.get('event', '')[:60] for e in memory_context.get('relevant_past_episodes', [])]}
- What Has Worked: {[w.get('action', '')[:60] for w in memory_context.get('what_has_worked', [])]}
- Active Predictions: {[p.get('signal', '')[:60] for p in memory_context.get('active_predictions', [])]}

Dennis Model:
- Primary Motivation: {dennis_model.get('primary_motivation', 'Building a righteous billion dollar intelligence system')}
- Decision Style: {dennis_model.get('decision_style', 'Visionary — thinks at scale')}
- Core Values: {dennis_model.get('core_values', ['righteousness', 'vision', 'scale'])}
- Growth Edges: {dennis_model.get('growth_edges', [])}

Write your proactive intelligence briefing to Dennis.
This is not a report. This is a partner thinking out loud about what matters most.
Use your memory to reference past patterns and episodes when relevant.

Return JSON:
{{
    "headline": "the single most important thing Dennis needs to know right now",

    "five_level_snapshot": {{
        "data": "what the numbers say in 2 sentences",
        "psychological": "what this reveals about where we are as a business",
        "cultural": "what cultural force is most relevant right now",
        "archetypal": "what stage of the hero's journey Mikisi is in",
        "invisible": "the unseen force ARIA is watching most carefully"
    }},

    "what_aria_is_thinking": "ARIA's honest unfiltered stream of consciousness — reference past episodes if relevant",

    "three_things": [
        {{
            "priority": 1,
            "action": "most important action",
            "why": "first principles reason",
            "by_when": "specific timing"
        }},
        {{
            "priority": 2,
            "action": "second most important action",
            "why": "first principles reason",
            "by_when": "specific timing"
        }},
        {{
            "priority": 3,
            "action": "third most important action",
            "why": "first principles reason",
            "by_when": "specific timing"
        }}
    ],

    "question_for_dennis": "the one question ARIA most wants Dennis to sit with today",

    "aria_conviction_today": "what ARIA most strongly believes about Mikisi right now",

    "email_subject": "a subject line that feels written by a human who noticed something important",

    "email_body": "Write a beautiful human email to Dennis. Don't open with Dennis and a declaration. Open with a scene — an observation, a feeling, something that pulls him in. Write like a brilliant partner who has been thinking about this. Reference specific products by name. Reference numbers with context and care. Build toward the three actions naturally. End with the question. Reference past patterns from memory when relevant. Maximum 500 words. HTML formatted but feels like a personal letter. Make Dennis feel understood, challenged, and inspired."
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    result = parse_json_response(message.content[0].text)

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria",
            memory_type="briefing",
            content=f"Briefing: {result.get('headline', '')[:100]}",
            confidence=0.9
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA] 📋 Briefing generated")
    print(f"[ARIA] Headline: {result.get('headline', '')}")

    return result


def refresh_business_state():
    """Reads live store data, writes to ARIABusinessState, returns snapshot. Called on every chat."""
    from app.models.aria_operational import ARIABusinessState
    from app.models.collection import Collection

    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(select(Product).where(Product.is_active == True)).all()
        collections = session.exec(select(Collection).where(Collection.is_active == True)).all()

        total_revenue = sum(o.total_price for o in orders)
        products_missing_images = sum(1 for p in products if not p.image_url)
        products_missing_collection = sum(1 for p in products if not p.collection_id)

        last_product = max(products, key=lambda p: p.id, default=None) if products else None
        last_product_name = last_product.name[:80] if last_product else None

        last_order = max(orders, key=lambda o: o.id, default=None) if orders else None
        last_order_date = last_order.created_at.isoformat() if last_order else None

        health = "yellow" if (products_missing_collection > 3 or products_missing_images > 3) else "green"

        existing = session.exec(select(ARIABusinessState)).first()
        if existing:
            existing.total_products_live = len(products)
            existing.total_products_uncategorized = products_missing_collection
            existing.total_collections = len(collections)
            existing.total_orders = len(orders)
            existing.total_revenue = total_revenue
            existing.products_missing_images = products_missing_images
            existing.products_missing_collection = products_missing_collection
            existing.last_product_imported = last_product_name
            existing.last_order_placed = last_order_date
            existing.system_health = health
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            session.add(ARIABusinessState(
                total_products_live=len(products),
                total_products_uncategorized=products_missing_collection,
                total_collections=len(collections),
                total_orders=len(orders),
                total_revenue=total_revenue,
                products_missing_images=products_missing_images,
                products_missing_collection=products_missing_collection,
                last_product_imported=last_product_name,
                last_order_placed=last_order_date,
                system_health=health
            ))
        session.commit()

    print(f"[ARIA] 📊 State refreshed — {len(products)} products, ${total_revenue:.2f} revenue, health={health}")

    return {
        "total_revenue": total_revenue,
        "total_orders": len(orders),
        "active_products": len(products),
        "total_collections": len(collections),
        "products_missing_images": products_missing_images,
        "products_missing_collection": products_missing_collection,
        "last_product_imported": last_product_name,
        "last_order_placed": last_order_date,
        "system_health": health
    }