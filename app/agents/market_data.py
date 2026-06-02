from dotenv import load_dotenv
load_dotenv()

import json
import time
from datetime import datetime
from pytrends.request import TrendReq
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, MarketInsight, MonthlyVision
from app.models.product import Product


def get_active_vision_keywords():
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

        products = session.exec(
            select(Product).where(Product.is_active == True)
        ).all()

        recent_chats = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria",
                AgentMemory.memory_type == "conversation"
            ).order_by(AgentMemory.created_at.desc()).limit(20)
        ).all()

    import anthropic
    import os
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    product_names = [p.name for p in products]
    product_categories = list(set([p.category for p in products]))
    chat_context = " | ".join([m.content[:100] for m in recent_chats]) if recent_chats else ""

    prompt = f"""You are the market intelligence system for Mikisi — a women's beauty accessories store founded by Dennis Mlay.

Current products in store: {product_names}
Product categories: {product_categories}
Business vision: {vision.vision if vision else 'Women beauty accessories store expanding globally'}
Recent conversations about expansion: {chat_context[:500] if chat_context else 'No recent chats'}

Your job is to extract 5 Google Trends keywords that will:
1. Track demand for current products
2. Discover what beauty products women are actively searching for right now
3. Identify emerging beauty trends worth adding to Mikisi
4. Track what competitors in beauty accessories are doing
5. Understand what the global beauty market wants

Think like a beauty market analyst. What are women searching for right now?
Consider: skincare rituals, hair tools, jewelry trends, makeup accessories, beauty gadgets, self-care products.

Rules:
- Each keyword must be 1-3 words maximum
- Real searchable terms people type into Google
- Focus on beauty, hair, skincare, jewelry, self-care
- Never include sneakers, shoes, or streetwear
- Mix current product keywords with emerging beauty trend keywords
- Return ONLY a JSON array of 5 strings

Return ONLY the JSON array."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
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

    keywords = json.loads(text.strip())
    print(f"[Market Data] ARIA extracted keywords from products + chats + market: {keywords}")
    return keywords[:5]


def fetch_google_trends(keywords, timeframe="today 3-m"):
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        keywords = keywords[:5]
        pytrends.build_payload(keywords, timeframe=timeframe, geo='US')

        interest_df = pytrends.interest_over_time()
        related_queries = pytrends.related_queries()

        trends_data = {}

        if not interest_df.empty:
            for keyword in keywords:
                if keyword in interest_df.columns:
                    recent_values = interest_df[keyword].tail(4).tolist()
                    avg_recent = sum(recent_values) / len(recent_values) if recent_values else 0
                    older_values = interest_df[keyword].head(4).tolist()
                    avg_older = sum(older_values) / len(older_values) if older_values else 0

                    trend_direction = "rising" if avg_recent > avg_older * 1.1 else "falling" if avg_recent < avg_older * 0.9 else "stable"

                    trends_data[keyword] = {
                        "current_interest": round(avg_recent, 1),
                        "trend": trend_direction,
                        "change_percent": round(((avg_recent - avg_older) / avg_older * 100) if avg_older > 0 else 0, 1)
                    }

        rising_queries = {}
        for keyword in keywords:
            if keyword in related_queries and related_queries[keyword].get("rising") is not None:
                rising_df = related_queries[keyword]["rising"]
                if not rising_df.empty:
                    rising_queries[keyword] = rising_df.head(5)["query"].tolist()

        return {
            "trends": trends_data,
            "rising_queries": rising_queries,
            "fetched_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"[Market Data] Google Trends error: {e}")
        return None


def fetch_trending_searches():
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        trending = pytrends.trending_searches(pn='united_states')
        trending_list = trending[0].tolist()[:20]

        beauty_keywords = ["beauty", "hair", "skin", "makeup", "jewelry",
                          "accessory", "face", "nail", "lash", "brow",
                          "serum", "mask", "glow", "moisturizer", "foundation",
                          "lipstick", "blush", "concealer", "skincare", "self care",
                          "hair clip", "barrette", "hair tool", "facial", "roller"]

        relevant_trends = [t for t in trending_list
                          if any(k in t.lower() for k in beauty_keywords)]

        return {
            "all_trending": trending_list,
            "beauty_relevant": relevant_trends,
            "fetched_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        print(f"[Market Data] Trending searches error: {e}")
        return None


def save_market_data_to_memory(trends_data, trending_data):
    with Session(engine) as session:
        content = json.dumps({
            "trends": trends_data.get("trends", {}) if trends_data else {},
            "rising_queries": trends_data.get("rising_queries", {}) if trends_data else {},
            "beauty_trending": trending_data.get("beauty_relevant", []) if trending_data else [],
            "fetched_at": datetime.utcnow().isoformat()
        })

        memory = AgentMemory(
            agent_name="market_data",
            memory_type="google_trends",
            content=content,
            confidence=0.9
        )
        session.add(memory)
        session.commit()
        print(f"[Market Data] ✅ Beauty trends saved to memory")


def run_market_data_collection():
    print(f"[Market Data] 🔍 Fetching real beauty market data from Google Trends...")

    keywords = get_active_vision_keywords()
    print(f"[Market Data] Keywords: {keywords}")

    trends_data = fetch_google_trends(keywords)
    time.sleep(2)
    trending_data = fetch_trending_searches()

    if trends_data or trending_data:
        save_market_data_to_memory(trends_data, trending_data)

        if trends_data:
            print(f"[Market Data] Beauty trend signals:")
            for keyword, data in trends_data.get("trends", {}).items():
                print(f"  {keyword}: {data['trend']} ({data['change_percent']:+.1f}%)")

        if trending_data and trending_data.get("beauty_relevant"):
            print(f"[Market Data] Beauty trending: {trending_data['beauty_relevant']}")

        # Emit trend signals through nervous system
        if trends_data:
            from app.agents.nervous_system import emit
            for keyword, data in trends_data.get("trends", {}).items():
                if data.get("trend") == "rising":
                    emit(
                        signal_type="TREND_DETECTED",
                        sender="market_agent",
                        payload={
                            "keyword": keyword,
                            "trend": data.get("trend"),
                            "change_percent": data.get("change_percent", 0),
                            "current_interest": data.get("current_interest", 0)
                        },
                        priority=4
                    )
                    print(f"[Market Data] 📡 Trend signal emitted: {keyword} is rising")

        return {
            "trends": trends_data,
            "trending": trending_data
        }

    return None



def get_latest_market_data():
    with Session(engine) as session:
        memory = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "market_data",
                AgentMemory.memory_type == "google_trends"
            ).order_by(AgentMemory.created_at.desc())
        ).first()

        if memory:
            return json.loads(memory.content)
        return None