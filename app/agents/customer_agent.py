from dotenv import load_dotenv
load_dotenv()

import os
import re
import json
import imaplib
import email
import anthropic
from email.header import decode_header
from datetime import datetime, timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order, OrderTracking

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Supplier/ops senders that share this inbox but aren't customers -- these
# have their own dedicated agents (e.g. silverbene_shipping_monitor) that
# know how to read them properly and route action items to Dennis directly.
# Without this exclusion, this agent's hourly *unfiltered* UNSEEN scan reaches
# them first (it's more frequent than silverbene_shipping_monitor's 2-hour
# scan) and marks them \Seen after misclassifying them as generic customer
# mail -- which is exactly what buried two real "please send the correct
# shipping address" requests from Silverbene behind a low-urgency internal
# signal instead of an alert to Dennis (see order #21, 2026-07-22/23).
# "dhl" (substring, not just "dhl.com") deliberately casts wide -- DHL sends
# On Demand Delivery / shipment notices from several subdomains, and a false
# exclusion here just means the dedicated dhl_monitor sees it instead, while
# a missed exclusion means the exact order #21-style misclassification bug.
_SUPPLIER_SENDER_DOMAINS = ["silverbene.com", "cjdropship.com", "cjdropshipping.com", "dhl"]


def _is_supplier_email(sender: str) -> bool:
    sender_lower = sender.lower()
    return any(domain in sender_lower for domain in _SUPPLIER_SENDER_DOMAINS)


# ============================================================
# EMAIL INBOX — IMAP
# ============================================================

def connect_inbox():
    """Connect to Gmail inbox via IMAP."""
    try:
        gmail_address = os.getenv("GMAIL_ADDRESS")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")

        if not gmail_address or not gmail_password:
            print("[Customer] Gmail credentials not configured")
            return None

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, gmail_password)
        return mail
    except Exception as e:
        print(f"[Customer] Inbox connection error: {e}")
        return None


def fetch_unread_emails(limit=10):
    """Fetch unread customer emails from inbox."""
    mail = connect_inbox()
    if not mail:
        return []

    try:
        mail.select("inbox")
        status, messages = mail.search(None, "UNSEEN")

        if status != "OK":
            return []

        email_ids = messages[0].split()
        if not email_ids:
            print("[Customer] No unread emails")
            return []

        emails = []
        for email_id in email_ids[-limit:]:
            try:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                # Decode subject
                subject = decode_header(msg["Subject"])[0]
                if isinstance(subject[0], bytes):
                    subject = subject[0].decode(subject[1] or "utf-8")
                else:
                    subject = subject[0]

                # Get sender
                sender = msg.get("From", "")

                if _is_supplier_email(sender):
                    # Leave unread (no \Seen) and don't classify -- this
                    # belongs to a supplier-specific agent, not the generic
                    # customer pipeline.
                    print(f"[Customer] Skipping supplier email from {sender!r} -- not a customer, leaving for its own agent")
                    continue

                # Get body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                emails.append({
                    "email_id": email_id.decode(),
                    "subject": subject,
                    "sender": sender,
                    "body": body[:1000],
                    "date": msg.get("Date", "")
                })

                # Mark as read
                mail.store(email_id, "+FLAGS", "\\Seen")

            except Exception as e:
                print(f"[Customer] Error reading email {email_id}: {e}")

        mail.logout()
        return emails

    except Exception as e:
        print(f"[Customer] Fetch error: {e}")
        return []


# ============================================================
# EMAIL CLASSIFICATION
# ============================================================

def classify_email(subject, body, sender):
    """
    Use ARIA to classify incoming customer email.
    Returns category and suggested response.
    """
    try:
        prompt = f"""You are ARIA — customer intelligence for Mikisi, a women's beauty accessories store.

A customer sent this email:
From: {sender}
Subject: {subject}
Body: {body[:500]}

Classify this email and draft a response.

Categories:
- tracking_inquiry: customer asking about order status or delivery
- complaint: unhappy customer, damaged product, wrong item, not received
- question: general product or store question
- compliment: positive feedback
- refund_request: customer wants refund or return
- other: anything else

Return JSON only:
{{
    "category": "tracking_inquiry/complaint/question/compliment/refund_request/other",
    "urgency": "low/medium/high/critical",
    "summary": "one sentence summary of what customer wants",
    "auto_respond": true or false,
    "response_subject": "email subject for reply",
    "response_body": "full HTML email response — warm, elegant, Mikisi brand voice. Sign as Mikisi Customer Care.",
    "escalate_to_aria": true or false,
    "escalation_reason": "why this needs ARIA attention if escalating"
}}

Auto-respond only for: tracking_inquiry, question, compliment.
Always escalate: complaint, refund_request.
Keep responses warm, elegant, never robotic.
Never make promises about specific delivery dates.
Never offer refunds without ARIA approval."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
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

    except Exception as e:
        print(f"[Customer] Classification error: {e}")
        return {
            "category": "other",
            "urgency": "medium",
            "auto_respond": False,
            "escalate_to_aria": True,
            "escalation_reason": f"Classification failed: {e}"
        }


# ============================================================
# DELIVERY PREFERENCE REPLIES
# ============================================================
# Shipping-confirmation emails (tracking_agent.send_shipping_email) invite
# the customer to reply with where to leave their package. Their reply lands
# here as "Re: Your Mikisi order #<id> has shipped! 📦" -- the order number
# survives standard mail-client "Re:" quoting, which is what lets this match
# back to the OrderTracking record without any other correlation id. This
# must run BEFORE classify_email(), since the generic classifier has no
# concept of "delivery preference" and would misfile a one-line "leave it in
# the garage" reply as a vague "question" or "other".

_ORDER_ID_IN_SUBJECT = re.compile(r"order\s*#(\d+)", re.IGNORECASE)


def _find_pending_delivery_preference_order(subject: str) -> "OrderTracking | None":
    """
    Looks up the OrderTracking record a reply is about, via the order id
    embedded in the shipping email's subject line. Only matches orders that
    actually asked for a preference (delivery_preference_requested) -- a
    reply to some unrelated "order #22" mention shouldn't be swallowed here.
    """
    match = _ORDER_ID_IN_SUBJECT.search(subject or "")
    if not match:
        return None
    order_id = int(match.group(1))
    with Session(engine) as session:
        return session.exec(
            select(OrderTracking).where(
                OrderTracking.order_id == order_id,
                OrderTracking.delivery_preference_requested == True,
            )
        ).first()


def _extract_delivery_preference(body: str) -> str | None:
    """
    Reads a reply like a person would and pulls out the actual delivery
    instruction, if there is one. Returns None (not "none" or "") when the
    reply isn't really a delivery preference -- e.g. someone replying to
    ask an unrelated question on the same thread -- so callers can tell
    "nothing to store" apart from a real, empty-string instruction.
    """
    prompt = f"""A customer replied to a Mikisi shipping-confirmation email that asked:
"Want your package left somewhere specific, or don't need a signature? Just reply and let us know."

Their reply:
{body[:1000]}

Extract ONLY the delivery instruction itself (e.g. "Leave in the garage, between the two doors" or "No signature needed, leave at front door"), written as a clean instruction for a courier. If the reply doesn't actually contain a delivery instruction (e.g. it's a question, thanks, or unrelated), return null.

Return ONLY valid JSON, no markdown fences:
{{"instruction": "<the instruction, or null>"}}"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r'^```(json)?|```$', '', text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        return data.get("instruction") or None
    except Exception as e:
        print(f"[Customer] Delivery preference extraction error: {e}")
        return None


def _handle_delivery_preference_reply(tracking: "OrderTracking", subject: str, body: str) -> bool:
    """
    Stores the customer's delivery preference and acknowledges receipt.
    Returns True if this email was actually a delivery-preference reply
    (caller should skip generic classification either way once matched --
    even a non-instruction reply on this thread isn't a fresh support case).
    """
    instruction = _extract_delivery_preference(body)
    if instruction:
        with Session(engine) as session:
            t = session.get(OrderTracking, tracking.id)
            if t:
                t.delivery_preference = instruction
                session.add(t)
                session.commit()
        print(f"[Customer] 📦 Delivery preference captured for order {tracking.order_id}: {instruction!r}")

        from app.agents.tracking_agent import maybe_send_delivery_relay_alert
        maybe_send_delivery_relay_alert(tracking.id)

        send_customer_reply(
            tracking.customer_email,
            f"Re: {subject}",
            f"""<html><body style="font-family:'Georgia',serif;background:#fdf9f6;padding:40px;">
<div style="max-width:600px;margin:0 auto;background:white;padding:32px;">
<p style="font-size:14px;color:#0e0e0e;line-height:1.8;">Got it — we've passed your delivery instructions along to the courier:</p>
<p style="font-size:14px;color:#6b6b6b;font-style:italic;">"{instruction}"</p>
<p style="font-size:13px;color:#6b6b6b;line-height:1.8;">Thank you for choosing Mikisi.</p>
</div></body></html>""",
        )
    return True


# ============================================================
# EMAIL SENDING
# ============================================================

def send_customer_reply(to, subject, body):
    """Send reply to customer."""
    try:
        from app.agents.email_partner import send_email
        sent = send_email(to, subject, body, is_html=True)
        return sent
    except Exception as e:
        print(f"[Customer] Reply send error: {e}")
        return False


def send_followup_email(customer_email, customer_name, order_details):
    """Send follow up email after delivery."""
    try:
        from app.agents.email_partner import send_email

        first_name = customer_name.split()[0] if customer_name else "there"

        subject = "How was your Mikisi experience? ✨"
        body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Georgia',serif;background:#fdf9f6;margin:0;padding:40px;">
<div style="max-width:600px;margin:0 auto;background:white;padding:48px;">

    <div style="text-align:center;margin-bottom:40px;">
        <h1 style="font-family:'Georgia',serif;font-size:28px;font-weight:300;
                   letter-spacing:6px;color:#0e0e0e;text-transform:uppercase;">
            Mik<em style="color:#d4849c;font-style:italic;">i</em>si
        </h1>
    </div>

    <h2 style="font-family:'Georgia',serif;font-size:24px;font-weight:300;
               color:#0e0e0e;margin-bottom:16px;">
        We'd love to hear from you, {first_name}
    </h2>

    <p style="font-size:14px;color:#6b6b6b;line-height:1.8;margin-bottom:24px;">
        Your order has arrived — and we hope it brought a little elegance to your day.
        Every piece we curate is chosen with intention, and your experience matters deeply to us.
    </p>

    <p style="font-size:14px;color:#6b6b6b;line-height:1.8;margin-bottom:24px;">
        How did we do? Simply reply to this email and let us know.
        We read every message personally.
    </p>

    <div style="background:#f9eef2;padding:24px;margin-bottom:32px;text-align:center;">
        <p style="font-size:14px;color:#d4849c;font-style:italic;margin:0;">
            "Every piece tells a story. We hope yours was beautiful."
        </p>
    </div>

    <p style="font-size:13px;color:#6b6b6b;line-height:1.8;">
        If anything wasn't perfect, please tell us. We're here to make it right.
    </p>

    <div style="border-top:1px solid #ece5dd;margin-top:40px;padding-top:24px;text-align:center;">
        <p style="font-size:11px;color:#d8d0c8;letter-spacing:2px;text-transform:uppercase;">
            With love, Mikisi
        </p>
    </div>

</div>
</body>
</html>"""

        sent = send_email(customer_email, subject, body, is_html=True)
        if sent:
            print(f"[Customer] ✅ Follow up sent to {customer_email}")
        return sent

    except Exception as e:
        print(f"[Customer] Follow up error: {e}")
        return False


# ============================================================
# COMPLAINT ESCALATION
# ============================================================

def escalate_complaint(sender, subject, body, classification):
    """Signal ARIA when complaint received."""
    from app.agents.nervous_system import emit
    emit(
        signal_type="COMPLAINT_RECEIVED",
        sender="customer_agent",
        payload={
            "customer_email": sender,
            "subject": subject,
            "body": body[:500],
            "category": classification.get("category"),
            "urgency": classification.get("urgency"),
            "summary": classification.get("summary"),
            "escalation_reason": classification.get("escalation_reason")
        },
        priority=1
    )
    print(f"[Customer] 🚨 Complaint escalated to ARIA: {subject}")


# ============================================================
# MAIN CUSTOMER AGENT
# ============================================================

def run_customer_agent():
    """
    Main customer agent loop.
    Reads inbox, classifies emails, responds or escalates.
    Runs every hour from scheduler.
    """
    print(f"[Customer] 📬 Checking customer inbox...")

    emails = fetch_unread_emails(limit=10)

    if not emails:
        print(f"[Customer] No new customer emails")
        return

    print(f"[Customer] Found {len(emails)} new emails")

    for email_data in emails:
        try:
            sender = email_data["sender"]
            subject = email_data["subject"]
            body = email_data["body"]

            print(f"[Customer] Processing: {subject} from {sender}")

            # Delivery-preference replies are handled separately, before
            # generic classification -- see _find_pending_delivery_preference_order.
            pending_tracking = _find_pending_delivery_preference_order(subject)
            if pending_tracking:
                _handle_delivery_preference_reply(pending_tracking, subject, body)
                continue

            # Classify email
            classification = classify_email(subject, body, sender)
            category = classification.get("category")
            urgency = classification.get("urgency")

            print(f"[Customer] Category: {category} | Urgency: {urgency}")

            # Auto respond if appropriate
            if classification.get("auto_respond"):
                reply_subject = classification.get("response_subject", f"Re: {subject}")
                reply_body = classification.get("response_body", "")

                if reply_body:
                    sent = send_customer_reply(sender, reply_subject, reply_body)
                    if sent:
                        from app.agents.nervous_system import emit
                        emit(
                            signal_type="CUSTOMER_CONTACTED",
                            sender="customer_agent",
                            payload={
                                "customer_email": sender,
                                "category": category,
                                "auto_responded": True
                            },
                            priority=7
                        )

            # Escalate if needed
            if classification.get("escalate_to_aria"):
                escalate_complaint(sender, subject, body, classification)

                # Also notify Dennis for critical issues
                if urgency == "critical":
                    from app.agents.email_partner import send_email
                    dennis_email = os.getenv("DENNIS_EMAIL")
                    send_email(
                        dennis_email,
                        f"🚨 Critical Customer Issue — {subject}",
                        f"""
<html><body style="font-family:sans-serif;padding:20px;">
<h2 style="color:#d4849c;">Critical Customer Issue</h2>
<p><strong>From:</strong> {sender}</p>
<p><strong>Subject:</strong> {subject}</p>
<p><strong>Category:</strong> {category}</p>
<p><strong>Summary:</strong> {classification.get('summary', '')}</p>
<p><strong>Message:</strong></p>
<p>{body[:500]}</p>
</body></html>""",
                        is_html=True
                    )

        except Exception as e:
            print(f"[Customer] Error processing email: {e}")

    print(f"[Customer] ✅ Inbox check complete")


def handle_post_delivery_followup(order_id, customer_email, customer_name):
    """
    Called by tracking agent when order is delivered.
    Sends follow up email after 2 days.
    """
    # For now send immediately — future: schedule for 2 days after delivery
    send_followup_email(customer_email, customer_name, {})