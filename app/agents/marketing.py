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

def get_pending_tasks():
    with Session(engine) as session:
        tasks = session.exec(
            select(AgentTask).where(
                AgentTask.to_agent == "marketing",
                AgentTask.status == "pending"
            )
        ).all()
        return tasks

def mark_task_done(task_id, result):
    with Session(engine) as session:
        task = session.get(AgentTask, task_id)
        if task:
            task.status = "done"
            task.result = result
            task.completed_at = datetime.utcnow()
            session.add(task)
            session.commit()

def mark_task_failed(task_id, error):
    with Session(engine) as session:
        task = session.get(AgentTask, task_id)
        if task:
            task.status = "failed"
            task.result = error
            session.add(task)
            session.commit()

def save_memory(content, memory_type, confidence):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="marketing",
            memory_type=memory_type,
            content=content,
            confidence=confidence
        )
        session.add(memory)
        session.commit()

def get_recent_insights():
    with Session(engine) as session:
        insights = session.exec(
            select(MarketInsight).order_by(MarketInsight.created_at.desc()).limit(5)
        ).all()
        return insights

def get_active_vision():
    with Session(engine) as session:
        return session.exec(
            select(MonthlyVision).where(MonthlyVision.is_active == True)
        ).first()

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())

def generate_marketing_content(product_data):
    vision = get_active_vision()
    insights = get_recent_insights()

    vision_context = f"Monthly vision: {vision.vision}\nTarget market: {vision.target_market}" if vision else ""

    insights_context = ""
    if insights:
        insights_context = "Recent market insights:\n" + "\n".join([
            f"- {i.platform}: {i.topic} ({i.demand_signal} demand, {i.target_demographic})"
            for i in insights
        ])

    prompt = f"""You are a Marketing Agent for BrandDrop, a premium discount sneaker and sportswear store.

{vision_context}

{insights_context}

Generate marketing content for this new product:
- Name: {product_data.get('name')}
- Brand: {product_data.get('brand')}
- Category: {product_data.get('category')}
- Description: {product_data.get('description')}
- Original Price: ${product_data.get('original_price')}
- Sale Price: ${product_data.get('final_price')}
- Discount: {product_data.get('discount_percent')}%

Generate a JSON object with:
{{
    "instagram_caption": "engaging Instagram caption with emojis and hashtags",
    "twitter_post": "punchy Twitter/X post under 280 chars",
    "facebook_post": "longer Facebook post with story angle",
    "tiktok_hook": "first 3 seconds hook for TikTok video",
    "reddit_post": "authentic Reddit post for sneaker subreddit",
    "email_subject": "email subject line",
    "email_body": "short promotional email body",
    "key_selling_points": ["point1", "point2", "point3"],
    "target_audience": "description of who to target",
    "best_platforms": ["platform1", "platform2"],
    "psychological_angle": "the psychology behind why people will buy this"
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return parse_json_response(message.content[0].text)

def run_marketing():
    print("[Marketing Agent] Checking for pending tasks...")
    tasks = get_pending_tasks()

    if not tasks:
        print("[Marketing Agent] No pending tasks")
        return

    for task in tasks:
        print(f"[Marketing Agent] Processing task {task.id}")
        try:
            product_data = json.loads(task.payload)
            content = generate_marketing_content(product_data)

            product_name = product_data.get('name', 'Unknown')

            save_memory(
                content=json.dumps({
                    "product": product_name,
                    "instagram": content.get("instagram_caption", ""),
                    "twitter": content.get("twitter_post", ""),
                    "psychological_angle": content.get("psychological_angle", ""),
                    "target_audience": content.get("target_audience", "")
                }),
                memory_type="marketing",
                confidence=0.85
            )

            print(f"[Marketing Agent] ✅ Generated content for: {product_name}")
            print(f"[Marketing Agent] Twitter: {content.get('twitter_post', '')}")
            print(f"[Marketing Agent] Target: {content.get('target_audience', '')}")

            mark_task_done(task.id, json.dumps(content))

        except Exception as e:
            print(f"[Marketing Agent] Error on task {task.id}: {e}")
            mark_task_failed(task.id, str(e))