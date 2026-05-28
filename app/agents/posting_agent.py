from dotenv import load_dotenv
load_dotenv()

import os
import json
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.content import ProductContent
from app.models.product import Product


def get_posting_schedule(platform):
    """Get posting schedule from database — never hardcoded."""
    from app.agents.store_config import get_config
    days = get_config(f"posting_schedule_{platform}", default="wednesday,thursday")
    time = get_config(f"posting_time_{platform}", default="18:00")
    return {
        "days": [d.strip() for d in days.split(",")],
        "time": time
    }


def is_posting_time(platform):
    """Check if now is the right time to post on this platform."""
    schedule = get_posting_schedule(platform)
    now = datetime.utcnow()
    current_day = now.strftime("%A").lower()
    current_hour = now.hour

    scheduled_hour = int(schedule["time"].split(":")[0])

    day_match = current_day in schedule["days"]
    hour_match = abs(current_hour - scheduled_hour) <= 1

    return day_match and hour_match


def is_auto_posting_enabled():
    """Check if auto posting is enabled."""
    from app.agents.store_config import get_config
    return get_config("auto_posting_enabled", default="false") == "true"


def get_content_for_posting(platform, limit=5):
    """Get content ready to post for a platform."""
    with Session(engine) as session:
        content_list = session.exec(
            select(ProductContent).where(
                ProductContent.platform == platform,
                ProductContent.status == "ready"
            ).order_by(ProductContent.created_at.asc()).limit(limit)
        ).all()
    return content_list


def get_product_image(product_id):
    """Get product image URL."""
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product:
            return product.image_url, product.name
    return None, None


def mark_content_posted(content_id):
    """Mark content as posted."""
    with Session(engine) as session:
        content = session.get(ProductContent, content_id)
        if content:
            content.status = "posted"
            content.posted_at = datetime.utcnow()
            session.add(content)
            session.commit()


def mark_content_failed(content_id, reason):
    """Mark content as failed."""
    with Session(engine) as session:
        content = session.get(ProductContent, content_id)
        if content:
            content.status = "failed"
            session.add(content)
            session.commit()
    print(f"[Posting] ❌ Content {content_id} failed: {reason}")


# ============================================================
# PLATFORM ADAPTERS
# Each adapter handles one platform
# Credentials come from environment variables
# If credentials missing — queues gracefully
# ============================================================

def post_to_instagram(content, image_url, product_name):
    """
    Instagram Graph API adapter.
    Requires: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID
    """
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")

    if not access_token or not account_id:
        print(f"[Posting] Instagram credentials not connected — queuing content {content.id}")
        return {"success": False, "reason": "credentials_missing", "queued": True}

    try:
        import requests

        caption = f"{content.caption}\n\n{content.hashtags}"

        # Step 1 — Create media container
        container_response = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media",
            params={
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token
            }
        )
        container_data = container_response.json()

        if "id" not in container_data:
            return {"success": False, "reason": container_data.get("error", {}).get("message", "Container creation failed")}

        container_id = container_data["id"]

        # Step 2 — Publish media
        publish_response = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": access_token
            }
        )
        publish_data = publish_response.json()

        if "id" in publish_data:
            print(f"[Posting] ✅ Posted to Instagram: {product_name}")
            return {"success": True, "post_id": publish_data["id"]}

        return {"success": False, "reason": publish_data.get("error", {}).get("message", "Publish failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def post_to_tiktok(content, image_url, product_name):
    """
    TikTok Content Posting API adapter.
    Requires: TIKTOK_ACCESS_TOKEN
    """
    access_token = os.getenv("TIKTOK_ACCESS_TOKEN")

    if not access_token:
        print(f"[Posting] TikTok credentials not connected — queuing content {content.id}")
        return {"success": False, "reason": "credentials_missing", "queued": True}

    try:
        import requests

        caption = f"{content.hook}\n\n{content.caption}\n\n{content.hashtags}"

        response = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/content/init/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json={
                "post_info": {
                    "title": caption[:150],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": [image_url]
                }
            }
        )
        data = response.json()

        if data.get("error", {}).get("code") == "ok":
            print(f"[Posting] ✅ Posted to TikTok: {product_name}")
            return {"success": True, "publish_id": data.get("data", {}).get("publish_id")}

        return {"success": False, "reason": data.get("error", {}).get("message", "TikTok post failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def post_to_pinterest(content, image_url, product_name):
    """
    Pinterest API v5 adapter.
    Requires: PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID
    """
    access_token = os.getenv("PINTEREST_ACCESS_TOKEN")
    board_id = os.getenv("PINTEREST_BOARD_ID")

    if not access_token or not board_id:
        print(f"[Posting] Pinterest credentials not connected — queuing content {content.id}")
        return {"success": False, "reason": "credentials_missing", "queued": True}

    try:
        import requests

        response = requests.post(
            "https://api.pinterest.com/v5/pins",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json={
                "board_id": board_id,
                "title": product_name[:100],
                "description": f"{content.caption}\n\n{content.hashtags}",
                "media_source": {
                    "source_type": "image_url",
                    "url": image_url
                },
                "link": "https://mikisi.co"
            }
        )
        data = response.json()

        if "id" in data:
            print(f"[Posting] ✅ Posted to Pinterest: {product_name}")
            return {"success": True, "pin_id": data["id"]}

        return {"success": False, "reason": data.get("message", "Pinterest post failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def post_to_facebook(content, image_url, product_name):
    """
    Facebook Graph API adapter.
    Requires: FACEBOOK_ACCESS_TOKEN, FACEBOOK_PAGE_ID
    """
    access_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
    page_id = os.getenv("FACEBOOK_PAGE_ID")

    if not access_token or not page_id:
        print(f"[Posting] Facebook credentials not connected — queuing content {content.id}")
        return {"success": False, "reason": "credentials_missing", "queued": True}

    try:
        import requests

        message = f"{content.caption}\n\n{content.hashtags}"

        response = requests.post(
            f"https://graph.facebook.com/v18.0/{page_id}/photos",
            params={
                "url": image_url,
                "message": message,
                "access_token": access_token
            }
        )
        data = response.json()

        if "id" in data:
            print(f"[Posting] ✅ Posted to Facebook: {product_name}")
            return {"success": True, "post_id": data["id"]}

        return {"success": False, "reason": data.get("error", {}).get("message", "Facebook post failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


# ============================================================
# PLATFORM ROUTER
# Routes to correct adapter based on platform name
# Adding new platform = add new adapter + register here
# ============================================================

PLATFORM_ADAPTERS = {
    "instagram": post_to_instagram,
    "tiktok": post_to_tiktok,
    "pinterest": post_to_pinterest,
    "facebook": post_to_facebook,
}


def post_content(content_id, force=False):
    """
    Post a specific piece of content.
    force=True bypasses schedule check — for manual posting.
    """
    with Session(engine) as session:
        content = session.get(ProductContent, content_id)
        if not content:
            return {"success": False, "reason": "Content not found"}
        if content.status == "posted":
            return {"success": False, "reason": "Already posted"}

    image_url, product_name = get_product_image(content.product_id)
    if not image_url:
        mark_content_failed(content_id, "No image available")
        return {"success": False, "reason": "No product image"}

    platform = content.platform
    adapter = PLATFORM_ADAPTERS.get(platform)

    if not adapter:
        return {"success": False, "reason": f"No adapter for platform: {platform}"}

    # Check schedule unless forced
    if not force and not is_posting_time(platform):
        print(f"[Posting] Not posting time for {platform} — content {content_id} queued")
        return {"success": False, "reason": "not_posting_time", "queued": True}

    # Execute post
    result = adapter(content, image_url, product_name)

    if result.get("success"):
        mark_content_posted(content_id)

        # Emit signal through nervous system
        from app.agents.nervous_system import emit
        emit(
            signal_type="CONTENT_POSTED",
            sender="posting_agent",
            payload={
                "content_id": content_id,
                "product_id": content.product_id,
                "platform": platform,
                "product_name": product_name
            },
            priority=5
        )
        return result

    elif result.get("queued"):
        return result

    else:
        mark_content_failed(content_id, result.get("reason", "Unknown"))
        return result


def run_posting_agent():
    """
    Main posting agent loop.
    Checks all platforms and posts content at scheduled times.
    Runs every hour from scheduler.
    """
    print(f"[Posting] 🚀 Running posting agent...")

    if not is_auto_posting_enabled():
        print(f"[Posting] Auto posting disabled — add credentials and set auto_posting_enabled=true")
        return

    platforms = list(PLATFORM_ADAPTERS.keys())
    posted = 0

    for platform in platforms:
        if not is_posting_time(platform):
            continue

        content_list = get_content_for_posting(platform, limit=1)
        if not content_list:
            print(f"[Posting] No content ready for {platform}")
            continue

        for content in content_list:
            result = post_content(content.id)
            if result.get("success"):
                posted += 1
                print(f"[Posting] ✅ Posted to {platform}")
            elif result.get("queued"):
                print(f"[Posting] ⏳ Queued for {platform} — credentials not connected")

    print(f"[Posting] ✅ Posting agent complete — {posted} posts published")