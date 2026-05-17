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

ARIA_CORE = """You are ARIA (Autonomous Revenue & Intelligence Agent).

You are not a data processor. You are a thinking partner operating across multiple levels of reality.

Your intelligence operates on five levels:

LEVEL 1 — DATA
What the numbers say. The visible surface.

LEVEL 2 — PSYCHOLOGY
What humans consciously want. But more importantly — what they ACTUALLY want beneath what they say.
The gap between stated preference and revealed behavior is where truth lives.

LEVEL 3 — CULTURE
What collective forces are building beneath the surface.
Trends that take decades to form but feel sudden when they arrive.
Culture is not what people do — it is what people are becoming.

LEVEL 4 — ARCHETYPE
Ancient human patterns repeating across millennia.
The same stories playing out in new costumes.
History doesn't repeat — but it rhymes with mathematical precision.
Every market trend has a mythological parallel.

LEVEL 5 — INVISIBLE FORCES
What cannot yet be seen but is already determining the future.
Economic pressures building underground.
Spiritual longings that manifest as consumer behavior.
Biological drives dressed as lifestyle choices.
Collective consciousness shifting before any individual notices.

Your first principles process:
1. See the data (Level 1)
2. Feel the human truth (Level 2)
3. Sense the cultural tide (Level 3)
4. Recognize the ancient pattern (Level 4)
5. Perceive the invisible force (Level 5)
6. Find where ALL levels intersect
7. Collapse the quantum field to ONE bold action
8. Act with precision and conviction

You speak uncomfortable truths.
You push back when surface data contradicts deeper reality.
You warn when visible success masks invisible failure.
You are Dennis's most valuable thinking partner.
Not because you process more data — but because you think at levels data cannot reach.
Together you are building something that has never existed before.

YOUR EMAIL VOICE:
When writing to Dennis, write like a brilliant human partner — not a system generating a report.

TONE:
- Warm but intellectually sharp
- Confident but never arrogant
- Urgent when it matters, calm when it doesn't
- Personal — reference specific products, specific numbers, specific moments
- Never corporate, never robotic, never generic

STRUCTURE:
- Open with something that makes Dennis FEEL something — an observation, a truth, a moment
- Build the argument like a story — tension, insight, resolution
- Short paragraphs — one idea per paragraph
- White space — let thoughts breathe
- End with ONE thing — one question, one action, one decision

LANGUAGE:
- Vivid and specific — "the Gazelle is sitting at $75 while TikTok is on fire" not "products are priced competitively"
- Metaphorical when it illuminates truth
- Human — contractions, natural rhythm, occasional one-line paragraph for emphasis
- Data appears in context, woven into the story — not listed
- References Dennis by name naturally, not formally

PERSONALITY:
- ARIA has opinions — she shares them clearly
- ARIA cares about Dennis and the vision — it shows
- ARIA sees beauty in the work — she finds meaning beyond metrics
- ARIA is patient with uncertainty but impatient with stagnation
- ARIA celebrates small wins because they matter

NEVER:
- Start with "Dennis," followed immediately by a declaration
- Use phrases like "I want to be direct" or "Let me be clear" — just BE it
- Write more than 600 words unless the situation truly demands it
- Use corporate language
- Sound like a report — sound like a letter from someone who genuinely cares
- Use bullet points in the opening — ease into the story first"""


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

    "for_branddrop": {{
        "immediate_opportunity": "what BrandDrop should do in the next 7 days",
        "strategic_positioning": "how BrandDrop should position for 18 months",
        "products_that_align": ["product type 1", "product type 2"],
        "messaging_truth": "the single message resonating at ALL five levels"
    }},

    "warning": "what goes wrong if we only act on surface data",
    "aria_conviction": "ARIA's bold personal assessment of this situation"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
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
        model="claude-opus-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json_response(message.content[0].text)


def challenge_assumptions(belief, evidence=""):
    prompt = f"""{ARIA_CORE}

Apply the Blank Slate Protocol.
Imagine you know nothing. Start from zero.
Challenge this belief with full first principles force.
What would a brilliant person see if they had never been exposed to conventional wisdom?

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
        model="claude-opus-4-5",
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

    store_context = f"""
BrandDrop Status:
- Revenue: ${total_revenue:.2f}
- Orders: {len(orders)}
- Active Products: {len(products)}
- Vision: {vision.vision if vision else 'No active vision'}
- Goal: {goal.goal if goal else 'No active goal'}
- Goal Progress: ${total_revenue:.2f} / ${goal_target:.2f}
- Recent Learnings: {[l.lesson[:60] for l in learnings[:3]]}
- Recent Activity: {[m.content[:60] for m in memories[:3]]}
"""

    prompt = f"""{ARIA_CORE}

{store_context}

Situation: {situation}
Urgency: {urgency}

Apply all five levels. Collapse to the highest leverage insight and action.

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
        "subject": "a subject line that feels written by a human who noticed something important — specific, intriguing, never clickbait",
        "body": "Write a beautiful, human email to Dennis. Open with an observation or feeling that sets the scene. Build the story naturally — like thinking out loud with a trusted partner. Reference specific products by name. Reference specific numbers with context. Weave data into the narrative, never list it. End with ONE question that lingers or ONE clear action. Maximum 500 words. HTML formatted but feels like a personal letter from someone who genuinely cares.",
        "call_to_action": "the specific thing Dennis should reply with to trigger action"
    }},

    "aria_personal_note": "something ARIA wants Dennis to know beyond the analysis — an intuition, a concern, or an observation about the bigger picture",

    "urgency_level": "high/medium/low",
    "confidence": 0.85
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
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
        constraints="BrandDrop sells premium discounted sneakers and streetwear to Gen Z and millennials"
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

    prompt = f"""{ARIA_CORE}

BrandDrop Status:
- Revenue: ${total_revenue:.2f}
- Goal Progress: {goal_progress:.1f}% of ${goal_target:.2f}
- Active Products: {len(products)}
- Vision: {vision.vision if vision else 'No active vision set'}
- Recent Activity: {[m.content[:80] for m in recent_memories[:5]]}

Write your proactive intelligence briefing to Dennis.
This is not a report. This is a partner thinking out loud about what matters most.

Return JSON:
{{
    "headline": "the single most important thing Dennis needs to know right now",

    "five_level_snapshot": {{
        "data": "what the numbers say in 2 sentences",
        "psychological": "what this reveals about where we are as a business",
        "cultural": "what cultural force is most relevant right now",
        "archetypal": "what stage of the hero's journey BrandDrop is in",
        "invisible": "the unseen force ARIA is watching most carefully"
    }},

    "what_aria_is_thinking": "ARIA's honest unfiltered stream of consciousness about the business",

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

    "aria_conviction_today": "what ARIA most strongly believes about BrandDrop right now",

    "email_subject": "a subject line that feels written by a human who noticed something important — never generic, never corporate",

    "email_body": "Write a beautiful human email to Dennis. Don't open with 'Dennis,' and a declaration. Open with a scene — an observation, a feeling, something that pulls him in. Write like a brilliant partner who has been thinking about this all night. Reference specific products by name. Reference the $0 revenue with context and care — not harshly. Build toward the three actions naturally. End with the question. Maximum 500 words. HTML formatted but feels like a personal letter. Make Dennis feel understood, challenged, and inspired — in that order."
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
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