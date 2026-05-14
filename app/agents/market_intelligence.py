from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, AgentTask, MarketInsight, MonthlyVision

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_active_vision():
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()
        return vision

def save_insight(platform, topic, sentiment, demand_signal,
                 target_demographic, location_signal, product_keywords, raw_data):
    with Session(engine) as session:
        insight = MarketInsight(
            platform=platform,
            topic=topic,
            sentiment=sentiment,
            demand_signal=demand_signal,
            target_demographic=target_demographic,
            location_signal=location_signal,
            product_keywords=product_keywords,
            raw_data=raw_data
        )
        session.add(insight)
        session.commit()
        session.refresh(insight)
        return insight

def save_memory(content, memory_type, source, confidence):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="market_intelligence",
            memory_type=memory_type,
            content=content,
            source=source,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def create_task_for_scout(insight_data):
    with Session(engine) as session:
        task = AgentTask(
            from_agent="market_intelligence",
            to_agent="product_scout",
            task_type="scout",
            payload=json.dumps(insight_data)
        )
        session.add(task)
        session.commit()

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())

def analyze_market(topic, platform, raw_content):
    vision = get_active_vision()
    vision_context = f"Monthly vision: {vision.vision}\nTarget market: {vision.target_market}\nTarget products: {vision.target_products}" if vision else "No active vision set"

    prompt = f"""You are a Market Intelligence Agent for an e-commerce store called BrandDrop.
    
{vision_context}

Analyze this content from {platform} about "{topic}":

{raw_content}

Extract and return a JSON object with:
{{
    "topic": "main topic being discussed",
    "sentiment": "positive/negative/neutral",
    "demand_signal": "high/medium/low",
    "target_demographic": "who is buying/interested (age, lifestyle, etc)",
    "location_signal": "any location mentions or global",
    "product_keywords": "comma separated product keywords",
    "key_insight": "one sentence insight for the store",
    "recommended_products": ["product1", "product2"],
    "confidence": 0.8
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return parse_json_response(message.content[0].text)

def run_market_intelligence(topic, platform, raw_content):
    print(f"[Market Intelligence] Analyzing {platform} content about: {topic}")

    try:
        analysis = analyze_market(topic, platform, raw_content)

        insight = save_insight(
            platform=platform,
            topic=topic,
            sentiment=analysis.get("sentiment", "neutral"),
            demand_signal=analysis.get("demand_signal", "low"),
            target_demographic=analysis.get("target_demographic"),
            location_signal=analysis.get("location_signal"),
            product_keywords=analysis.get("product_keywords", ""),
            raw_data=raw_content[:500]
        )

        save_memory(
            content=analysis.get("key_insight", ""),
            memory_type="insight",
            source=platform,
            confidence=analysis.get("confidence", 0.5)
        )

        if analysis.get("demand_signal") in ["high", "medium"]:
            create_task_for_scout({
                "insight_id": insight.id,
                "recommended_products": analysis.get("recommended_products", []),
                "product_keywords": analysis.get("product_keywords", ""),
                "target_demographic": analysis.get("target_demographic"),
                "demand_signal": analysis.get("demand_signal"),
                "platform": platform,
                "topic": topic
            })
            print(f"[Market Intelligence] High/medium demand detected — task sent to Product Scout")

        print(f"[Market Intelligence] Analysis complete. Demand: {analysis.get('demand_signal')} | Sentiment: {analysis.get('sentiment')}")
        return analysis

    except Exception as e:
        print(f"[Market Intelligence] Error: {e}")
        return None