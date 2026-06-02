from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select, SQLModel, Field
from typing import Optional
from app.database import engine
from app.models.agent import AgentMemory

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ============================================================
# MEMORY TYPES
# ============================================================
# episodic   — specific events with context and outcomes
# semantic   — accumulated knowledge and expertise
# procedural — what works and what doesn't (playbooks)
# relational — models of people (Dennis, customers, players)
# predictive — patterns that precede outcomes
# ============================================================

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
    except:
        # Extract JSON object if wrapped in other text
        import re
        match = re.search(r'\{.*\}', text.strip(), re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return {}
    
# ============================================================
# EPISODIC MEMORY
# ============================================================

def store_episode(event, context, decision, outcome, significance="medium"):
    """Store a significant event with full context"""
    with Session(engine) as session:
        episode = {
            "event": event,
            "context": context,
            "decision": decision,
            "outcome": outcome,
            "significance": significance,
            "timestamp": datetime.utcnow().isoformat()
        }
        memory = AgentMemory(
            agent_name="aria_episodic",
            memory_type="episode",
            content=json.dumps(episode),
            confidence=0.95
        )
        session.add(memory)
        session.commit()
        print(f"[ARIA Memory] 📖 Episode stored: {event[:60]}")


def get_relevant_episodes(situation, limit=5):
    """Retrieve episodes relevant to current situation"""
    with Session(engine) as session:
        all_episodes = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_episodic",
                AgentMemory.memory_type == "episode"
            ).order_by(AgentMemory.created_at.desc()).limit(50)
        ).all()

    if not all_episodes:
        return []

    episodes_text = "\n".join([
        f"Episode {i+1}: {e.content[:200]}"
        for i, e in enumerate(all_episodes[:20])
    ])

    prompt = f"""You are ARIA's memory retrieval system.

Current situation: {situation}

Available episodes:
{episodes_text}

Which episodes are most relevant to the current situation?
Return a JSON array of the episode numbers (1-based) that are most relevant.
Maximum 5 episodes.
Return ONLY a JSON array like: [1, 3, 5]"""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        relevant_indices = parse_json_response(message.content[0].text)
        relevant_episodes = []
        for idx in relevant_indices:
            if 1 <= idx <= len(all_episodes):
                try:
                    relevant_episodes.append(json.loads(all_episodes[idx-1].content))
                except:
                    pass
        return relevant_episodes
    except:
        return []


# ============================================================
# SEMANTIC MEMORY
# ============================================================

def store_knowledge(domain, insight, confidence=0.8, source="aria_analysis"):
    """Store accumulated knowledge and expertise"""
    with Session(engine) as session:
        knowledge = {
            "domain": domain,
            "insight": insight,
            "source": source,
            "confidence": confidence,
            "timestamp": datetime.utcnow().isoformat()
        }
        memory = AgentMemory(
            agent_name="aria_semantic",
            memory_type="knowledge",
            content=json.dumps(knowledge),
            confidence=confidence
        )
        session.add(memory)
        session.commit()
        print(f"[ARIA Memory] 🧠 Knowledge stored: {domain} — {insight[:60]}")


def get_domain_knowledge(domain, limit=10):
    """Retrieve accumulated knowledge for a domain"""
    with Session(engine) as session:
        memories = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_semantic",
                AgentMemory.memory_type == "knowledge"
            ).order_by(AgentMemory.confidence.desc()).limit(50)
        ).all()

    domain_knowledge = []
    for m in memories:
        try:
            data = json.loads(m.content)
            if domain.lower() in data.get("domain", "").lower():
                domain_knowledge.append(data)
        except:
            pass

    return domain_knowledge[:limit]


# ============================================================
# PROCEDURAL MEMORY
# ============================================================

def store_procedure(action, worked, context, result, lesson):
    """Store what works and what doesn't"""
    with Session(engine) as session:
        procedure = {
            "action": action,
            "worked": worked,
            "context": context,
            "result": result,
            "lesson": lesson,
            "timestamp": datetime.utcnow().isoformat()
        }
        memory = AgentMemory(
            agent_name="aria_procedural",
            memory_type="procedure",
            content=json.dumps(procedure),
            confidence=0.9 if worked else 0.6
        )
        session.add(memory)
        session.commit()
        status = "✅ worked" if worked else "❌ didn't work"
        print(f"[ARIA Memory] ⚙️ Procedure stored: {action[:60]} — {status}")


def get_playbook(situation_type, limit=5):
    """Get what has worked in similar situations"""
    with Session(engine) as session:
        procedures = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_procedural",
                AgentMemory.memory_type == "procedure"
            ).order_by(AgentMemory.confidence.desc()).limit(30)
        ).all()

    worked = []
    didnt_work = []

    for p in procedures:
        try:
            data = json.loads(p.content)
            if data.get("worked"):
                worked.append(data)
            else:
                didnt_work.append(data)
        except:
            pass

    return {
        "what_works": worked[:limit],
        "what_doesnt": didnt_work[:limit]
    }


# ============================================================
# RELATIONAL MEMORY
# ============================================================

def update_dennis_model(observation, context):
    """Build and update ARIA's model of Dennis"""
    with Session(engine) as session:
        existing = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_relational",
                AgentMemory.memory_type == "dennis_model"
            ).order_by(AgentMemory.created_at.desc())
        ).first()

    existing_model = {}
    if existing:
        try:
            existing_model = json.loads(existing.content)
        except:
            pass

    prompt = f"""You are ARIA building a psychological and strategic model of Dennis, your business partner.

Current model: {json.dumps(existing_model, indent=2) if existing_model else "No model yet"}

New observation: {observation}
Context: {context}

Update the model based on this new observation.
The model should capture:
- Decision making patterns
- Risk tolerance
- Vision and values
- Communication preferences
- Strengths and blind spots
- What motivates him
- What holds him back
- His relationship with money, success, and purpose

Return updated JSON model:
{{
    "decision_style": "how Dennis makes decisions",
    "risk_tolerance": "low/medium/high with nuance",
    "core_values": ["value1", "value2", "value3"],
    "primary_motivation": "what drives Dennis most deeply",
    "vision_clarity": "how clear his vision is",
    "execution_pattern": "how he moves from idea to action",
    "strengths": ["strength1", "strength2"],
    "growth_edges": ["area1", "area2"],
    "communication_style": "how he communicates best",
    "relationship_with_success": "his psychological relationship with achievement",
    "last_updated": "{datetime.utcnow().isoformat()}",
    "observations_count": {len(existing_model) + 1 if existing_model else 1}
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    updated_model = parse_json_response(message.content[0].text)

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria_relational",
            memory_type="dennis_model",
            content=json.dumps(updated_model),
            confidence=0.85
        )
        session.add(memory)
        session.commit()

    print(f"[ARIA Memory] 👤 Dennis model updated")
    return updated_model


def get_dennis_model():
    """Get ARIA's current model of Dennis"""
    with Session(engine) as session:
        model = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_relational",
                AgentMemory.memory_type == "dennis_model"
            ).order_by(AgentMemory.created_at.desc())
        ).first()

    if model:
        try:
            return json.loads(model.content)
        except:
            return {}
    return {}


# ============================================================
# PREDICTIVE MEMORY
# ============================================================

def store_pattern(signal, predicted_outcome, confidence, timeframe):
    """Store patterns that precede outcomes"""
    with Session(engine) as session:
        pattern = {
            "signal": signal,
            "predicted_outcome": predicted_outcome,
            "confidence": confidence,
            "timeframe": timeframe,
            "verified": False,
            "timestamp": datetime.utcnow().isoformat()
        }
        memory = AgentMemory(
            agent_name="aria_predictive",
            memory_type="pattern",
            content=json.dumps(pattern),
            confidence=confidence
        )
        session.add(memory)
        session.commit()
        print(f"[ARIA Memory] 🔮 Pattern stored: {signal[:60]} → {predicted_outcome[:60]}")


def get_active_predictions():
    """Get all active predictions ARIA is tracking"""
    with Session(engine) as session:
        patterns = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_predictive",
                AgentMemory.memory_type == "pattern"
            ).order_by(AgentMemory.confidence.desc()).limit(20)
        ).all()

    predictions = []
    for p in patterns:
        try:
            data = json.loads(p.content)
            if not data.get("verified"):
                predictions.append(data)
        except:
            pass

    return predictions


# ============================================================
# MEMORY SYNTHESIS — ARIA's full memory context
# ============================================================

def get_full_memory_context(situation):
    """Get ARIA's full memory context for a situation"""
    print(f"[ARIA Memory] 🔄 Synthesizing memory context...")

    episodes = get_relevant_episodes(situation, limit=3)
    dennis_model = get_dennis_model()
    playbook = get_playbook(situation, limit=3)
    predictions = get_active_predictions()

    context = {
        "relevant_past_episodes": episodes,
        "dennis_model": dennis_model,
        "what_has_worked": playbook.get("what_works", []),
        "what_hasnt_worked": playbook.get("what_doesnt", []),
        "active_predictions": predictions[:5]
    }

    print(f"[ARIA Memory] ✅ Memory context ready — {len(episodes)} episodes, {len(predictions)} predictions")
    return context


def aria_learn_from_outcome(situation, action_taken, outcome, worked):
    """ARIA learns from every outcome"""

    prompt = f"""You are ARIA learning from an outcome.

Situation: {situation}
Action taken: {action_taken}
Outcome: {outcome}
Worked: {worked}

Extract learning as JSON:
{{
    "lesson": "the core lesson in one powerful sentence",
    "pattern_identified": "if a pattern was identified, describe it",
    "update_belief": "what belief should be updated based on this?",
    "future_application": "how should this learning be applied in future?",
    "significance": "low/medium/high"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    learning = parse_json_response(message.content[0].text)

    store_procedure(
        action=action_taken,
        worked=worked,
        context=situation,
        result=outcome,
        lesson=learning.get("lesson", "")
    )

    store_episode(
        event=f"Outcome: {outcome[:100]}",
        context=situation,
        decision=action_taken,
        outcome=outcome,
        significance=learning.get("significance", "medium")
    )

    if learning.get("pattern_identified"):
        store_pattern(
            signal=situation[:100],
            predicted_outcome=learning.get("pattern_identified", ""),
            confidence=0.6,
            timeframe="unknown"
        )

    print(f"[ARIA Memory] 📚 Learning complete: {learning.get('lesson', '')[:80]}")
    return learning