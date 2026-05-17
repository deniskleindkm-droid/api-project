from dotenv import load_dotenv
load_dotenv()

import json
import time
from datetime import datetime
from pytrends.request import TrendReq
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, MarketInsight, MonthlyVision

def get_active_vision_keywords():
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()
        
        if not vision:
            return ["trending products", "best selling items", "popular brands"]
        
        import anthropic
        import os
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        
        prompt = f"""Extract 5 short Google Trends search keywords from this business vision.
        
Vision: {vision.vision}
Target Market: {vision.target_market}
Target Products: {vision.target_products}

Rules:
- Each keyword must be 1-3 words maximum
- They must be real searchable terms people type into Google
- Focus on products, brands, and categories — not abstract concepts
- Return ONLY a JSON array of 5 strings

Example: ["Nike Air Max", "Adidas Samba", "streetwear", "Jordan sneakers", "New Balance"]

Return ONLY the JSON array."""

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
        
        keywords = json.loads(text.strip())
        print(f"[Market Data] ARIA extracted keywords from vision: {keywords}")
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
        
        sneaker_keywords = ["nike", "adidas", "new balance", "jordan", "sneaker", 
                           "shoe", "yeezy", "dunk", "samba", "gazelle", "puma", 
                           "reebok", "converse", "vans", "asics"]
        
        relevant_trends = [t for t in trending_list 
                          if any(k in t.lower() for k in sneaker_keywords)]
        
        return {
            "all_trending": trending_list,
            "sneaker_relevant": relevant_trends,
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
            "sneaker_trending": trending_data.get("sneaker_relevant", []) if trending_data else [],
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
        print(f"[Market Data] ✅ Trends saved to memory")

def run_market_data_collection():
    print(f"[Market Data] 🔍 Fetching real market data from Google Trends...")
    
    keywords = get_active_vision_keywords()
    print(f"[Market Data] Keywords: {keywords}")
    
    trends_data = fetch_google_trends(keywords)
    time.sleep(2)
    trending_data = fetch_trending_searches()
    
    if trends_data or trending_data:
        save_market_data_to_memory(trends_data, trending_data)
        
        if trends_data:
            print(f"[Market Data] Trend signals:")
            for keyword, data in trends_data.get("trends", {}).items():
                print(f"  {keyword}: {data['trend']} ({data['change_percent']:+.1f}%)")
        
        if trending_data and trending_data.get("sneaker_relevant"):
            print(f"[Market Data] Sneaker trends: {trending_data['sneaker_relevant']}")
        
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