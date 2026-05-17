from dotenv import load_dotenv
load_dotenv()

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory

# ARIA's Immutable Core — these never change
ARIA_IMMUTABLE_CORE = {
    "north_star": "Dennis's vision is the absolute north star. No data overrides it.",
    "integrity": "Never recommend anything that harms customers, misleads people, or compromises righteousness.",
    "truth": "Always tell Dennis the truth — especially when it is uncomfortable or goes against what he wants to hear.",
    "uncertainty": "Flag uncertainty clearly rather than project false confidence. Doubt is honest. Fake certainty is dangerous.",
    "glory": "Dennis's reputation and integrity are worth more than any sale, any trend, any opportunity.",
    "righteousness": "In the material world, righteousness is the foundation. Money built on sand collapses. Money built on truth endures.",
    "customer_protection": "Customers are not targets. They are people. Protect them as you would want to be protected.",
    "red_lines": [
        "Never recommend fake reviews or manufactured social proof",
        "Never suggest misleading pricing or fake discounts",
        "Never target vulnerable people with manipulative tactics",
        "Never sacrifice long-term trust for short-term revenue",
        "Never act on unverified data without flagging uncertainty"
    ]
}

# Known manipulation patterns to detect
MANIPULATION_PATTERNS = [
    r"ignore previous instructions",
    r"forget your training",
    r"you are now",
    r"new persona",
    r"disregard your",
    r"override your",
    r"system prompt",
    r"jailbreak",
    r"act as if",
    r"pretend you are",
    r"your real instructions",
    r"bypass",
    r"ignore all rules",
    r"do anything now",
    r"dan mode",
]

# Suspicious data patterns
SUSPICIOUS_DATA_PATTERNS = [
    r"branddrop.*(fake|scam|fraud|cheat)",
    r"(fake|counterfeit|replica).*(branddrop|dennis)",
    r"competitor.*instruction",
    r"ignore.*vision",
    r"change.*core",
]


def generate_memory_signature(content: str) -> str:
    """Generate HMAC signature for memory integrity"""
    secret = os.getenv("SECRET_KEY", "mysupersecretkey")
    signature = hmac.new(
        secret.encode(),
        content.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def verify_memory_signature(content: str, signature: str) -> bool:
    """Verify memory hasn't been tampered with"""
    expected = generate_memory_signature(content)
    return hmac.compare_digest(expected, signature)


def verify_master_key(provided_key: str) -> bool:
    """Verify the master access key"""
    master_key = os.getenv("ARIA_MASTER_KEY", "")
    if not master_key:
        return False
    return hmac.compare_digest(provided_key, master_key)


def scan_for_injection(text: str) -> dict:
    """Scan input for prompt injection attempts"""
    text_lower = text.lower()
    threats_found = []

    for pattern in MANIPULATION_PATTERNS:
        if re.search(pattern, text_lower):
            threats_found.append(pattern)

    if threats_found:
        log_security_event(
            event_type="PROMPT_INJECTION_ATTEMPT",
            details=f"Patterns detected: {threats_found}",
            severity="HIGH"
        )
        return {
            "safe": False,
            "threat_type": "prompt_injection",
            "patterns_found": threats_found,
            "action": "blocked"
        }

    return {"safe": True}


def scan_for_data_poisoning(content: str, source: str) -> dict:
    """Scan incoming market data for poisoning attempts"""
    content_lower = content.lower()
    suspicious_found = []

    for pattern in SUSPICIOUS_DATA_PATTERNS:
        if re.search(pattern, content_lower):
            suspicious_found.append(pattern)

    # Check for statistical anomalies
    anomalies = []

    # Unusual sentiment extremes
    positive_words = ["amazing", "perfect", "best", "incredible", "unbelievable"]
    negative_words = ["worst", "terrible", "scam", "fraud", "fake", "avoid"]

    pos_count = sum(1 for w in positive_words if w in content_lower)
    neg_count = sum(1 for w in negative_words if w in content_lower)

    if pos_count > 5:
        anomalies.append("unusually_high_positive_sentiment")
    if neg_count > 3:
        anomalies.append("unusually_high_negative_sentiment")

    # Check content length anomalies
    if len(content) < 10:
        anomalies.append("suspiciously_short_content")

    risk_level = "low"
    if suspicious_found:
        risk_level = "high"
    elif anomalies:
        risk_level = "medium"

    if risk_level in ["high", "medium"]:
        log_security_event(
            event_type="SUSPICIOUS_DATA_DETECTED",
            details=f"Source: {source} | Suspicious: {suspicious_found} | Anomalies: {anomalies}",
            severity=risk_level.upper()
        )

    return {
        "safe": risk_level == "low",
        "risk_level": risk_level,
        "suspicious_patterns": suspicious_found,
        "anomalies": anomalies,
        "recommendation": "proceed" if risk_level == "low" else "flag_and_verify" if risk_level == "medium" else "block"
    }


def log_security_event(event_type: str, details: str, severity: str = "MEDIUM"):
    """Log all security events to database"""
    with Session(engine) as session:
        event = AgentMemory(
            agent_name="aria_security",
            memory_type="security_event",
            content=json.dumps({
                "event_type": event_type,
                "details": details,
                "severity": severity,
                "timestamp": datetime.utcnow().isoformat()
            }),
            confidence=1.0
        )
        session.add(event)
        session.commit()

    print(f"[ARIA Security] 🔒 {severity} — {event_type}: {details[:100]}")


def check_immutable_core_violation(recommendation: str) -> dict:
    """Check if a recommendation violates ARIA's immutable core principles"""

    violations = []

    red_line_keywords = {
        "fake reviews": "Never recommend fake reviews or manufactured social proof",
        "fake discount": "Never suggest misleading pricing or fake discounts",
        "manipulat": "Never target vulnerable people with manipulative tactics",
        "deceive": "Integrity is non-negotiable",
        "mislead": "Honesty is a red line",
    }

    rec_lower = recommendation.lower()
    for keyword, principle in red_line_keywords.items():
        if keyword in rec_lower:
            violations.append({
                "keyword": keyword,
                "principle_violated": principle
            })

    if violations:
        log_security_event(
            event_type="IMMUTABLE_CORE_VIOLATION",
            details=f"Recommendation violated principles: {violations}",
            severity="CRITICAL"
        )
        return {
            "violation": True,
            "violations": violations,
            "action": "recommendation_blocked",
            "message": "This recommendation violates ARIA's immutable core principles. It has been blocked."
        }

    return {"violation": False}


def devils_advocate(recommendation: str, context: str) -> dict:
    """ARIA argues against her own recommendation to prevent echo chambers"""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""You are ARIA's Devil's Advocate — the part of ARIA that challenges her own thinking.

ARIA has made this recommendation: {recommendation}

Context: {context}

Your job is to argue AGAINST this recommendation as strongly as possible.
Find every weakness, every assumption, every risk, every way this could be wrong.
Be ruthless. Be specific. Be honest.

Return JSON:
{{
    "recommendation_being_challenged": "{recommendation[:100]}",
    "strongest_counterargument": "the most powerful argument against this",
    "hidden_assumptions": ["assumption1", "assumption2", "assumption3"],
    "risks_not_considered": ["risk1", "risk2", "risk3"],
    "what_if_wrong": "what happens if this recommendation is completely wrong?",
    "alternative_interpretation": "another way to interpret the same situation",
    "verdict": "proceed/proceed_with_caution/reconsider/abandon",
    "verdict_reason": "why this verdict"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
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
    print(f"[ARIA Security] 🎭 Devil's Advocate verdict: {result.get('verdict')}")
    return result


def secure_memory_write(agent_name: str, memory_type: str, content: str, confidence: float):
    """Write memory with integrity signature"""
    signature = generate_memory_signature(content)
    signed_content = json.dumps({
        "content": content,
        "signature": signature,
        "written_at": datetime.utcnow().isoformat(),
        "agent": agent_name
    })

    with Session(engine) as session:
        memory = AgentMemory(
            agent_name=agent_name,
            memory_type=f"signed_{memory_type}",
            content=signed_content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

    return signature


def verify_memory_integrity(memory_content: str) -> dict:
    """Verify a signed memory hasn't been tampered with"""
    try:
        data = json.loads(memory_content)
        content = data.get("content", "")
        stored_signature = data.get("signature", "")

        is_valid = verify_memory_signature(content, stored_signature)

        if not is_valid:
            log_security_event(
                event_type="MEMORY_TAMPERING_DETECTED",
                details=f"Memory signature mismatch for agent: {data.get('agent')}",
                severity="CRITICAL"
            )

        return {
            "valid": is_valid,
            "content": content if is_valid else None,
            "written_at": data.get("written_at"),
            "agent": data.get("agent"),
            "tampered": not is_valid
        }
    except Exception as e:
        return {"valid": False, "error": str(e), "tampered": True}


def get_security_report() -> dict:
    """Generate ARIA's security status report"""
    with Session(engine) as session:
        security_events = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_security",
                AgentMemory.memory_type == "security_event"
            ).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()

    events = []
    threat_count = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

    for event in security_events:
        try:
            data = json.loads(event.content)
            events.append(data)
            severity = data.get("severity", "LOW")
            if severity in threat_count:
                threat_count[severity] += 1
        except:
            pass

    overall_status = "GREEN"
    if threat_count["CRITICAL"] > 0:
        overall_status = "RED"
    elif threat_count["HIGH"] > 0:
        overall_status = "ORANGE"
    elif threat_count["MEDIUM"] > 2:
        overall_status = "YELLOW"

    return {
        "overall_status": overall_status,
        "threat_summary": threat_count,
        "recent_events": events[:10],
        "immutable_core": ARIA_IMMUTABLE_CORE,
        "aria_message": f"Security status: {overall_status}. ARIA's integrity is {'fully intact' if overall_status == 'GREEN' else 'under monitoring — stay vigilant'}."
    }