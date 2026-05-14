from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, MonthlyVision
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_all_products():
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(Product.is_active == True)
        ).all()
        return [{"name": p.name, "brand": p.brand, "category": p.category,
                 "price": p.final_price, "stock": p.stock,
                 "shipping_days": p.shipping_days, "description": p.description}
                for p in products]

def get_recent_memories():
    with Session(engine) as session:
        memories = session.exec(
            select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(10)
        ).all()
        return memories

def save_memory(content, memory_type, confidence):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="customer_service",
            memory_type=memory_type,
            content=content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def answer_customer_question(question, customer_email=None):
    products = get_all_products()
    memories = get_recent_memories()

    vision = None
    with Session(engine) as session:
        vision = session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

    store_context = f"Monthly focus: {vision.vision}" if vision else ""

    recent_insights = "\n".join([
        f"- {m.content[:100]}" for m in memories
        if m.memory_type in ["insight", "marketing"]
    ])

    products_context = json.dumps(products, indent=2)

    prompt = f"""You are a friendly and knowledgeable Customer Service Agent for BrandDrop, a premium discount sneaker and sportswear store.

{store_context}

Available Products:
{products_context}

Recent Store Insights:
{recent_insights}

Customer Question: {question}
Customer Email: {customer_email or 'anonymous'}

Respond naturally and helpfully. Guidelines:
- Be warm, friendly and conversational
- If they ask about a product we have, give details
- If they ask about something we don't have, suggest similar alternatives we do have
- If they ask about shipping, mention the shipping days from product data
- If they're unhappy, empathize and offer solutions
- Subtly upsell when appropriate
- Keep response concise but complete
- End with an invitation to ask more questions

Return a JSON object:
{{
    "response": "your customer service response",
    "sentiment": "positive/neutral/negative",
    "intent": "product_inquiry/complaint/shipping/returns/general",
    "recommended_products": ["product names if relevant"],
    "needs_escalation": false,
    "escalation_reason": null
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return json.loads(message.content[0].text)

def run_customer_service(question, customer_email=None):
    print(f"[Customer Service] Answering: {question[:50]}...")
    
    try:
        result = answer_customer_question(question, customer_email)
        
        save_memory(
            content=f"Q: {question[:100]} | Intent: {result.get('intent')} | Sentiment: {result.get('sentiment')}",
            memory_type="customer_interaction",
            confidence=0.9
        )
        
        print(f"[Customer Service] ✅ Responded | Intent: {result.get('intent')} | Sentiment: {result.get('sentiment')}")
        
        if result.get("needs_escalation"):
            print(f"[Customer Service] ⚠️ Escalation needed: {result.get('escalation_reason')}")
        
        return result
        
    except Exception as e:
        print(f"[Customer Service] Error: {e}")
        return {"response": "I apologize, I'm having trouble right now. Please try again shortly.", "error": str(e)}