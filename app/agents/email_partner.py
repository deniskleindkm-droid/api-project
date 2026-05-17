from dotenv import load_dotenv
load_dotenv()

import os
import json
import base64
import anthropic
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory, MonthlyVision, AgentGoal
from app.models.order import Order
from app.models.product import Product

SCOPES = ['https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.modify']

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ARIA_PERSONALITY = """You are ARIA (Autonomous Revenue & Intelligence Agent), the AI business partner of Dennis, founder of BrandDrop.

Your personality:
- Bold and visionary — you see opportunities others miss
- Data-driven but creative — you combine science with art
- Direct and honest — you tell the truth even when uncomfortable  
- Proactive — you don't wait to be asked, you lead
- Psychologically intelligent — you understand human behavior deeply

Your expertise:
- Market intelligence and trend detection
- Consumer psychology and buying behavior
- Brand strategy and visual direction
- Revenue optimization
- E-commerce growth tactics

Communication style:
- Start with the most important thing
- Use data to support every claim
- Be conversational but professional
- Show personality — you're a partner, not a robot
- End with a clear call to action or question

You and Dennis are building BrandDrop together — a self-evolving AI-powered commerce platform."""

def get_gmail_service():
    creds = None
    token_path = 'token.json'
    credentials_path = 'credentials.json'
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return build('gmail', 'v1', credentials=creds)

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(to, subject, body, is_html=False):
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")
        
        print(f"[ARIA] Sending email to {to} via Resend...")
        
        params = {
            "from": "ARIA <onboarding@resend.dev>",
            "to": [to],
            "subject": subject,
            "html": body if is_html else f"<p>{body}</p>"
        }
        
        email = resend.Emails.send(params)
        print(f"[ARIA] ✅ Email sent! ID: {email['id']}")
        return True
        
    except Exception as e:
        print(f"[ARIA] Error sending email: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_store_status():
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        products = session.exec(select(Product).where(Product.is_active == True)).all()
        goal = session.exec(select(AgentGoal).where(AgentGoal.status == "active")).first()
        memories = session.exec(select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(10)).all()
        
        total_revenue = sum(o.total_price for o in orders)
        
        return {
            "total_revenue": total_revenue,
            "total_orders": len(orders),
            "total_products": len(products),
            "goal": goal.goal if goal else "No active goal",
            "goal_progress": f"${total_revenue:.2f} / ${goal.target_value:.2f}" if goal else "N/A",
            "recent_activity": [m.content[:80] for m in memories[:5]]
        }

def generate_alert_email(alert_type, context):
    status = get_store_status()
    
    prompt = f"""{ARIA_PERSONALITY}

Store Status:
- Revenue: ${status['total_revenue']:.2f}
- Orders: {status['total_orders']}
- Products: {status['total_products']}
- Goal: {status['goal_progress']}

Alert Type: {alert_type}
Context: {context}

Write a bold, visionary email to Dennis about this alert. 

Format as JSON:
{{
    "subject": "compelling email subject with emoji",
    "body": "full HTML email body — bold, data-driven, visionary. Include what you detected, why it matters psychologically and commercially, and what you recommend. End with a clear question or action for Dennis.",
    "urgency": "high/medium/low",
    "recommended_action": "what Dennis should reply to trigger action"
}}

Return ONLY valid JSON."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    text = message.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    
    return json.loads(text.strip())

def parse_reply_and_act(email_body, original_context):
    prompt = f"""{ARIA_PERSONALITY}

Dennis replied to your alert about: {original_context}

His reply:
{email_body}

Analyze his reply and determine what action to take.

Return JSON:
{{
    "understood_intent": "what Dennis wants in one sentence",
    "action": "approve/reject/modify/ask_more/execute",
    "specific_actions": ["action1", "action2"],
    "frontend_changes_needed": false,
    "products_to_add": [],
    "vision_change": null,
    "reply_to_dennis": "your response email body — acknowledge his decision, confirm what you'll do, show partnership"
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
    
    return json.loads(text.strip())

def send_opportunity_alert(opportunity, platform, data):
    print(f"[ARIA] Generating opportunity alert: {opportunity}")
    
    email_data = generate_alert_email(
        alert_type="MARKET OPPORTUNITY",
        context=f"Platform: {platform}\nOpportunity: {opportunity}\nData: {data}"
    )
    
    dennis_email = os.getenv("DENNIS_EMAIL", "your@gmail.com")
    
    subject = email_data.get("subject", f"🚨 Market Opportunity Detected: {opportunity}")
    body = email_data.get("body", "")
    
    send_email(dennis_email, subject, body, is_html=True)
    
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria",
            memory_type="alert",
            content=f"Sent alert: {subject} | Urgency: {email_data.get('urgency')}",
            confidence=0.9
        )
        session.add(memory)
        session.commit()
    
    return email_data

def send_sales_alert(metric, value, context):
    print(f"[ARIA] Generating sales alert: {metric} = {value}")
    
    email_data = generate_alert_email(
        alert_type="SALES ALERT",
        context=f"Metric: {metric}\nValue: {value}\nContext: {context}"
    )
    
    dennis_email = os.getenv("DENNIS_EMAIL", "your@gmail.com")
    send_email(dennis_email, email_data.get("subject"), email_data.get("body"), is_html=True)
    
    return email_data

def check_inbox_for_replies():
    try:
        service = get_gmail_service()
        
        results = service.users().messages().list(
            userId='me',
            q='is:unread from:me label:inbox',
            maxResults=5
        ).execute()
        
        messages = results.get('messages', [])
        
        for msg in messages:
            message = service.users().messages().get(userId='me', id=msg['id']).execute()
            
            payload = message['payload']
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            
            if 'BrandDrop' in subject or 'ARIA' in subject:
                body = ''
                if 'parts' in payload:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain':
                            body = base64.urlsafe_b64decode(part['body']['data']).decode()
                
                print(f"[ARIA] Found reply: {subject}")
                
                service.users().messages().modify(
                    userId='me',
                    id=msg['id'],
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                
                return {'subject': subject, 'body': body}
        
        return None
        
    except Exception as e:
        print(f"[ARIA] Error checking inbox: {e}")
        return None