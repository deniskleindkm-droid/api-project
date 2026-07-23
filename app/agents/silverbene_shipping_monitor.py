"""
Silverbene Shipping Monitor
Polls hello@mikisi.co inbox via IMAP every 2 hours.

Recognition of what a Silverbene email actually IS (shipping notification
vs. something else) and extraction of tracking details is LLM-based, not
hardcoded keyword/regex matching. Silverbene has no tracking API (confirmed
2026-07-23 by probing every plausible endpoint name against their live
API — all 404) and tracking numbers come from a third-party carrier
system on their own site, so the number's shape isn't something we can
safely guess a fixed pattern for. An LLM read is also what lets this
recognize OTHER Silverbene email types (payment requests, missing
customer info, etc.) by name instead of silently treating anything that
doesn't match a keyword list as irrelevant — per Dennis 2026-07-23, only
the shipping-notification path is actually acted on for now; everything
else is logged and left unread for a human to see, not auto-handled.

When it IS a shipping notification, this agent:
  1. Extracts the tracking number (and carrier, if mentioned) via the LLM
  2. Matches it to an OrderTracking record via Silverbene's own order ID
     (cj_order_id) — the only reliable correlation key, since Silverbene
     never has the real customer's identity (hello@mikisi.co is used
     deliberately as their contact, see silverbene_adapter.place_order)
  3. Automatically sends the Mikisi-branded shipping email to the real
     customer
  4. Marks the inbox email as read so it's never processed twice
"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import json
import email
import imaplib
import anthropic
from email.header import decode_header
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.order import Order, OrderTracking

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Silverbene sends from these domains
_SILVERBENE_SENDERS = ["silverbene.com", "silverbene"]


def _imap_connect():
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_password:
        print("[ShippingMonitor] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set")
        return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, gmail_password)
        return mail
    except Exception as e:
        print(f"[ShippingMonitor] IMAP connect error: {e}")
        return None


def _get_email_text(msg) -> str:
    """Extract plain text + html body from email message."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(part.get_payload(decode=True).decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            parts.append(msg.get_payload(decode=True).decode(charset, errors="replace"))
        except Exception:
            pass
    text = "\n".join(parts)
    # Strip HTML tags for a cleaner LLM read — body may be html-only.
    return re.sub(r'<[^<]+?>', ' ', text)


def _classify_email(subject: str, body: str) -> dict:
    """
    Reads a Silverbene email like a person would and returns structured
    JSON: what type of email this is, and (for shipping notifications)
    the tracking details. Falls back to {"type": "other"} on any parse
    failure — never raises, since one malformed LLM response shouldn't
    take down the whole scan.
    """
    prompt = f"""You're reading an email from Silverbene, our jewelry dropship supplier, sent to our own operations inbox (hello@mikisi.co — never the real customer's email; Silverbene never has that).

Subject: {subject}

Body:
{body[:3000]}

Classify this email and extract any relevant details. Return ONLY valid JSON, no other text, no markdown fences:
{{
  "type": "shipping_notification" | "payment_required" | "missing_customer_info" | "other",
  "silverbene_order_id": "<Silverbene's own order/reference number if mentioned anywhere, else null>",
  "tracking_number": "<tracking number if this is a shipping notification, else null>",
  "carrier": "<carrier/logistics company name if mentioned, e.g. USPS/DHL/EMS/4PX, else null>"
}}"""
    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r'^```(json)?|```$', '', text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"[ShippingMonitor] Classification error: {e}")
        return {"type": "other"}


def _find_matching_order(silverbene_order_id: str, text: str) -> "OrderTracking | None":
    """
    Find an unshipped OrderTracking record. Prefers an exact match on the
    LLM-extracted silverbene_order_id; falls back to a raw substring
    search of the full email text (handles cases where the LLM missed
    it but it's still literally present); falls back further to "only
    one unshipped order exists, it must be this one" as a last resort.
    """
    with Session(engine) as session:
        pending = session.exec(
            select(OrderTracking).where(
                OrderTracking.supplier_name == "Silverbene",
                OrderTracking.shipping_notified == False,
            )
        ).all()

    if not pending:
        return None

    if silverbene_order_id:
        for t in pending:
            if t.cj_order_id and str(t.cj_order_id).strip() == str(silverbene_order_id).strip():
                print(f"[ShippingMonitor] Matched order {t.order_id} via extracted silverbene_order_id={silverbene_order_id}")
                return t

    for t in pending:
        if t.cj_order_id and str(t.cj_order_id) in text:
            print(f"[ShippingMonitor] Matched order {t.order_id} via cj_order_id={t.cj_order_id} found in raw text")
            return t

    if len(pending) == 1:
        print(f"[ShippingMonitor] Single unshipped order — assuming order {pending[0].order_id}")
        return pending[0]

    print(f"[ShippingMonitor] {len(pending)} unshipped orders but none matched email")
    return None


def run_silverbene_shipping_monitor():
    """
    Main entry point — called by the scheduler every 2 hours.
    Scans hello@mikisi.co inbox for Silverbene emails, classifies each
    one, and acts on shipping notifications. Returns a summary dict so
    the scheduler heartbeat can report something more meaningful than
    "ran" (see run_silverbene_shipping_monitor's caller in scheduler.py).
    """
    print(f"\n[ShippingMonitor] Scanning inbox — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    result = {"connected": False, "processed": 0, "matched": [], "unmatched": [], "skipped": []}

    mail = _imap_connect()
    if not mail:
        return result
    result["connected"] = True

    try:
        mail.select("INBOX")

        _, msgs = mail.search(None, '(UNSEEN FROM "silverbene")')
        email_ids = msgs[0].split() if msgs[0] else []

        if not email_ids:
            print("[ShippingMonitor] No unread Silverbene emails")
            return result

        print(f"[ShippingMonitor] Found {len(email_ids)} unread Silverbene email(s)")

        for eid in email_ids:
            try:
                _, data = mail.fetch(eid, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                raw_subject = msg.get("Subject", "")
                decoded = decode_header(raw_subject)[0]
                subject = decoded[0].decode(decoded[1] or "utf-8") if isinstance(decoded[0], bytes) else decoded[0]

                sender = msg.get("From", "")
                body = _get_email_text(msg)
                result["processed"] += 1

                if not any(s in sender.lower() for s in _SILVERBENE_SENDERS):
                    # IMAP's FROM filter already restricts to "silverbene",
                    # so this shouldn't normally trigger — kept as a guard
                    # in case the search ever broadens.
                    continue

                print(f"[ShippingMonitor] Email: from={sender!r} subject={subject!r}")

                classification = _classify_email(subject, body)
                etype = classification.get("type", "other")

                if etype != "shipping_notification":
                    print(f"[ShippingMonitor] Recognized as '{etype}' — not automated yet, left unread for manual review")
                    result["skipped"].append({"subject": subject, "type": etype})
                    continue

                sb_order_id = (classification.get("silverbene_order_id") or "").strip()
                tracking_number = (classification.get("tracking_number") or "").strip()
                carrier = (classification.get("carrier") or "").strip() or None

                if not tracking_number:
                    print("[ShippingMonitor] Looked like a shipping notice but no tracking number extracted — left unread")
                    result["skipped"].append({"subject": subject, "type": "shipping_notification_no_tracking"})
                    continue

                print(f"[ShippingMonitor] Tracking: {tracking_number} via {carrier or 'unknown carrier'}")

                tracking = _find_matching_order(sb_order_id, body + " " + subject)
                if not tracking:
                    print("[ShippingMonitor] Could not match to an order — left unread")
                    result["unmatched"].append({"subject": subject, "silverbene_order_id": sb_order_id})
                    continue

                # Update the tracking record
                with Session(engine) as session:
                    t = session.get(OrderTracking, tracking.id)
                    t.tracking_number = tracking_number
                    t.carrier = carrier
                    t.status = "dispatched"
                    t.shipped_at = datetime.utcnow()
                    session.add(t)
                    session.commit()
                    session.refresh(t)
                    tracking = t

                # Send Mikisi-branded customer notification
                if not tracking.shipping_notified and tracking.customer_email:
                    from app.agents.tracking_agent import send_shipping_email
                    sent = send_shipping_email(tracking)
                    if sent:
                        with Session(engine) as session:
                            t = session.get(OrderTracking, tracking.id)
                            t.shipping_notified = True
                            session.add(t)
                            session.commit()

                        with Session(engine) as session:
                            order = session.get(Order, tracking.order_id)
                            if order:
                                order.status = "shipped"
                                order.tracking_number = tracking_number
                                session.add(order)
                                session.commit()

                        print(f"[ShippingMonitor] Customer notified: {tracking.customer_email}")
                    else:
                        print(f"[ShippingMonitor] Failed to send customer email")

                # Stage 2 variant confirmation — mark order as Silverbene-confirmed
                if tracking.cj_order_id:
                    try:
                        from app.agents.order_variant_tracker import confirm_silverbene_shipped
                        confirm_silverbene_shipped(tracking.cj_order_id)
                    except Exception as vce:
                        print(f"[ShippingMonitor] VariantTracker confirm error: {vce}")

                mail.store(eid, "+FLAGS", "\\Seen")
                result["matched"].append({"order_id": tracking.order_id, "tracking_number": tracking_number})

            except Exception as e:
                import traceback
                print(f"[ShippingMonitor] Error processing email {eid}: {e}")
                traceback.print_exc()

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    print(f"[ShippingMonitor] Done — {len(result['matched'])} matched, {len(result['unmatched'])} unmatched, {len(result['skipped'])} skipped")
    return result
