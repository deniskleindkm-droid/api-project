"""
Mikisi Instagram Content Agent.

Posting strategy: 3 product posts : 1 campaign post (3:1 ratio).
All images are Silverbene images — RAWSHOT will be plugged in later for campaign posts.

Product post  — uses product.image_url (primary Silverbene image), product-focused caption.
Campaign post — picks best product from catalog, uses a second gallery image if available
                (different angle), emotional brand storytelling caption.

Counter and all runtime state live in StoreConfig so nothing resets on deploy.
Only published products (is_published == True) are ever posted.

Engagement is pulled 24h after each post and fed into a learning loop that
updates the knowledge base in StoreConfig over time.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from sqlmodel import Session, select

from app.database import engine
from app.models.product import Product
from app.models.store_config import StoreConfig
from app.models.instagram_post import InstagramPost
from app.agents.store_config import get_config, set_config

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

CATEGORY_HASHTAGS = {
    "Rings":     ["#ring", "#silverring", "#sterlingsilverring", "#stackablering"],
    "Necklaces": ["#necklace", "#silvernecklace", "#pendantnecklace", "#925necklace"],
    "Bracelets": ["#bracelet", "#silverbracelet", "#sterlingsilverbracelet"],
    "Earrings":  ["#earrings", "#silverearrings", "#studs", "#dropearrings"],
    "Anklets":   ["#anklet", "#silveranklet", "#anklejewelry"],
    "Ear Cuffs": ["#earcuff", "#cartilageearring", "#nopiercing", "#earcuffs"],
}


# ── DEFAULTS ──────────────────────────────────────────────────────────────────

def _init_defaults():
    """
    Write Instagram agent defaults to StoreConfig only if they don't exist yet.
    Uses if-not-exists so counter and learned data survive deploys.
    """
    defaults = {
        "instagram_post_counter": (
            "0",
            "3:1 ratio counter — 0/1/2 = product post, 3 = campaign post"
        ),
        "instagram_recent_product_ids": (
            "[]",
            "JSON list of last 10 posted product IDs — prevents immediate repeats"
        ),
        "instagram_last_campaign_product_id": (
            "0",
            "Product ID used in last campaign post — avoided on next pick"
        ),
        "instagram_last_category": (
            "",
            "Category of last product post — used for category rotation"
        ),
        "instagram_knowledge_base": (
            json.dumps({
                "caption_rules": [
                    "Hook must land in 10-12 words — shows before 'read more' cut-off",
                    "Body: 2-3 sentences, product keywords woven in naturally (not forced)",
                    "Instagram captions act as search in 2026 — use real keywords, not hashtag stuffing",
                    "Saves and shares matter more than likes — write captions worth saving",
                    "Mikisi tone: elegant, confident, empowering — never pushy or salesy",
                ],
                "brand_voice": (
                    "Mikisi speaks to women who choose themselves. "
                    "Every piece is an act of self-worth."
                ),
                "posting_insights": {
                    "note": "No engagement data yet — insights build after 5+ posts."
                },
            }),
            "Instagram agent knowledge base — updated automatically by learning loop"
        ),
    }

    with Session(engine) as session:
        for key, (value, description) in defaults.items():
            existing = session.exec(
                select(StoreConfig).where(StoreConfig.key == key)
            ).first()
            if not existing:
                session.add(StoreConfig(key=key, value=value, description=description))
        session.commit()


# ── HASHTAG BUILDER ───────────────────────────────────────────────────────────

def _build_hashtags(category: str, material: str) -> str:
    tags = ["#mikisi", "#mikisico"]
    tags.extend(CATEGORY_HASHTAGS.get(category, ["#jewelry"]))

    if material:
        m = material.lower()
        if "925" in m or "sterling" in m:
            tags += ["#sterlingsilver", "#925silver"]
        if "rose" in m and "gold" in m:
            tags.append("#rosegold")
        elif "gold" in m:
            tags.append("#goldplated")
        if "rhodium" in m:
            tags.append("#rhodiumplated")

    tags += ["#jewelry", "#silverjewelry", "#minimalistjewelry"]

    seen, unique = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return " ".join(unique[:9])


# ── CAPTION GENERATION ────────────────────────────────────────────────────────

def _generate_caption(product: Product, post_type: str) -> str:
    kb_raw = get_config("instagram_knowledge_base", default="{}")
    brand_voice = get_config("brand_voice", default="Mikisi — luxury sterling silver jewelry.")

    try:
        kb = json.loads(kb_raw) if isinstance(kb_raw, str) else {}
    except Exception:
        kb = {}

    caption_rules = "\n".join(f"- {r}" for r in kb.get("caption_rules", []))
    bv = kb.get("brand_voice", brand_voice)

    product_url = f"https://mikisi.co/products/{product.id}"

    if post_type == "product":
        prompt = (
            f"Write an Instagram caption for this Mikisi product post.\n\n"
            f"Product: {product.name}\n"
            f"Category: {product.category}\n"
            f"Material: {product.material or '925 Sterling Silver'}\n"
            f"Price: ${product.final_price:.0f}\n"
            f"Description: {product.description[:400]}\n\n"
            f"Caption rules:\n{caption_rules}\n\n"
            f"Brand voice: {bv}\n\n"
            f"Structure: Hook (10-12 words) → Body (2-3 sentences) → "
            f"CTA: 'Shop now → {product_url}'\n"
            f"Do NOT include hashtags. Return caption text only."
        )
    else:
        prompt = (
            f"Write an emotional brand storytelling caption for a Mikisi campaign post.\n\n"
            f"Product: {product.name}\n"
            f"Category: {product.category}\n"
            f"Material: {product.material or '925 Sterling Silver'}\n"
            f"Description: {product.description[:400]}\n\n"
            f"Caption rules:\n{caption_rules}\n\n"
            f"Brand voice: {bv}\n\n"
            f"This is a campaign post — speak to her identity, not the product specs.\n"
            f"Do NOT mention price. No product listing language.\n"
            f"Structure: Emotional hook → Brand storytelling (2-3 sentences) → "
            f"CTA: 'Find yours → {product_url}'\n"
            f"Do NOT include hashtags. Return caption text only."
        )

    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[Instagram] Caption generation error: {e}")
        return (
            f"{product.name} — {product.material or '925 Sterling Silver'}. "
            f"Find yours at mikisi.co"
        )


# ── PRODUCT SELECTION ─────────────────────────────────────────────────────────

def _pick_product_post() -> Optional[Product]:
    """
    Pick the next product post candidate.
    Prioritises new arrivals, rotates categories, avoids the last 10 posted.
    Only published, in-stock products with an image qualify.
    """
    recent_ids_raw = get_config("instagram_recent_product_ids", default="[]")
    try:
        recent_ids = json.loads(recent_ids_raw)
    except Exception:
        recent_ids = []

    last_category = get_config("instagram_last_category", default="")
    from app.agents.store_config import get_hidden_categories
    hidden = get_hidden_categories()

    with Session(engine) as session:
        candidates = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.is_published == True,
                Product.stock > 0,
                Product.image_url != None,
            ).order_by(Product.created_at.desc()).limit(80)
        ).all()
    candidates = [p for p in candidates if p.category not in hidden]

    candidates = [p for p in candidates if p.id not in recent_ids]

    if not candidates:
        # All recent — reset window and pick newest published
        with Session(engine) as session:
            candidates = session.exec(
                select(Product).where(
                    Product.is_active == True,
                    Product.is_published == True,
                    Product.stock > 0,
                    Product.image_url != None,
                ).order_by(Product.created_at.desc()).limit(10)
            ).all()
        candidates = [p for p in candidates if p.category not in hidden]

    if not candidates:
        return None

    # Rotate: prefer a different category from last post
    non_last = [p for p in candidates if p.category != last_category]
    return non_last[0] if non_last else candidates[0]


def _pick_campaign_product() -> Optional[Product]:
    """
    Pick the best product for a campaign post.
    Scores on visual potential (category), price tier, image count.
    Avoids the product used in the last campaign post.
    Only published, in-stock products qualify.
    """
    last_id = int(get_config("instagram_last_campaign_product_id", default="0") or 0)
    from app.agents.store_config import get_hidden_categories
    hidden = get_hidden_categories()

    with Session(engine) as session:
        candidates = session.exec(
            select(Product).where(
                Product.is_active == True,
                Product.is_published == True,
                Product.stock > 0,
                Product.image_url != None,
            ).limit(300)
        ).all()
    candidates = [p for p in candidates if p.category not in hidden]

    if not candidates:
        return None

    def _score(p: Product) -> float:
        if p.id == last_id:
            return -100.0

        score = {
            "Necklaces": 3.0, "Earrings": 3.0,
            "Bracelets": 2.0, "Rings": 2.0,
            "Anklets": 1.5,   "Ear Cuffs": 1.5,
        }.get(p.category, 1.0)

        if p.is_premium:
            score += 2.0
        elif p.final_price > 100:
            score += 1.5
        elif p.final_price > 50:
            score += 1.0

        if p.images:
            try:
                score += min(len(json.loads(p.images)) * 0.2, 1.0)
            except Exception:
                pass

        return score

    return max(candidates, key=_score)


def _best_campaign_image(product: Product) -> str:
    """
    For campaign posts, prefer a second gallery image (different angle).
    Falls back to primary image_url if the gallery has only one image.
    """
    if product.images:
        try:
            gallery = json.loads(product.images)
            if len(gallery) > 1:
                return gallery[1]
            if gallery:
                return gallery[0]
        except Exception:
            pass
    return product.image_url or ""


# ── INSTAGRAM GRAPH API ───────────────────────────────────────────────────────

def _post_to_instagram(image_url: str, caption: str, hashtags: str,
                        instagram_catalog_id: str = "") -> dict:
    """
    Post to Instagram via Graph API.
    If instagram_catalog_id is set on the product, the post is tagged as a
    shoppable product so it pops up in Instagram Shop when tapped.
    To enable Instagram Shopping: connect your Facebook Commerce account,
    create a product catalog, then store each product's catalog ID in
    product.instagram_catalog_id.
    """
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")

    if not access_token or not account_id:
        print("[Instagram] Credentials not set — post skipped")
        return {"success": False, "reason": "credentials_missing"}

    try:
        full_caption = f"{caption}\n\n{hashtags}"

        container_params = {
            "image_url":    image_url,
            "caption":      full_caption,
            "access_token": access_token,
        }

        # Instagram Shopping — tag the product so it shows in Instagram Shop
        if instagram_catalog_id:
            container_params["product_tags"] = json.dumps([
                {"product_id": instagram_catalog_id}
            ])

        r = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media",
            params=container_params,
            timeout=30,
        )
        container = r.json()
        if "id" not in container:
            reason = container.get("error", {}).get("message", "Container creation failed")
            return {"success": False, "reason": reason}

        r2 = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media_publish",
            params={"creation_id": container["id"], "access_token": access_token},
            timeout=30,
        )
        pub = r2.json()
        if "id" in pub:
            return {"success": True, "post_id": pub["id"]}

        reason = pub.get("error", {}).get("message", "Publish failed")
        return {"success": False, "reason": reason}

    except Exception as e:
        return {"success": False, "reason": str(e)}


# ── STATE MANAGEMENT ──────────────────────────────────────────────────────────

def _save_post(product_id: int, post_type: str, image_url: str,
               caption: str, hashtags: str, instagram_post_id: str = ""):
    with Session(engine) as session:
        session.add(InstagramPost(
            product_id=product_id,
            post_type=post_type,
            image_url=image_url,
            caption=caption,
            hashtags=hashtags,
            instagram_post_id=instagram_post_id,
            posted_at=datetime.utcnow(),
        ))
        session.commit()


def _update_state(product: Product, post_type: str):
    counter = int(get_config("instagram_post_counter", default="0") or 0)

    if post_type == "campaign":
        set_config("instagram_post_counter", "0")
        set_config("instagram_last_campaign_product_id", str(product.id))
    else:
        set_config("instagram_post_counter", str(counter + 1))
        set_config("instagram_last_category", product.category)

    recent_raw = get_config("instagram_recent_product_ids", default="[]")
    try:
        recent = json.loads(recent_raw)
    except Exception:
        recent = []
    recent = [product.id] + [i for i in recent if i != product.id]
    set_config("instagram_recent_product_ids", json.dumps(recent[:10]))


# ── ENGAGEMENT PULL ───────────────────────────────────────────────────────────

def pull_engagement():
    """
    Pull Instagram engagement metrics for posts that are 24h+ old and not yet updated.
    Called daily by scheduler at 17:00 UTC (one hour after posting window).
    After updating, triggers the learning loop.
    """
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not access_token:
        print("[Instagram] No access token — engagement pull skipped")
        return

    cutoff = datetime.utcnow() - timedelta(hours=24)

    with Session(engine) as session:
        pending = session.exec(
            select(InstagramPost).where(
                InstagramPost.instagram_post_id != None,
                InstagramPost.instagram_post_id != "",
                InstagramPost.engagement_pulled_at == None,
                InstagramPost.posted_at <= cutoff,
            ).limit(20)
        ).all()

        for post in pending:
            try:
                # Insights: reach, saves, shares
                r = requests.get(
                    f"https://graph.facebook.com/v18.0/{post.instagram_post_id}/insights",
                    params={
                        "metric": "impressions,reach,saved,shares",
                        "access_token": access_token,
                    },
                    timeout=15,
                )
                insight_data = r.json().get("data", [])
                metrics = {
                    d["name"]: d.get("values", [{}])[0].get("value", 0)
                    for d in insight_data
                }

                # Likes and comments from media object
                r2 = requests.get(
                    f"https://graph.facebook.com/v18.0/{post.instagram_post_id}",
                    params={
                        "fields": "like_count,comments_count",
                        "access_token": access_token,
                    },
                    timeout=15,
                )
                media = r2.json()

                post.likes    = media.get("like_count", 0)
                post.comments = media.get("comments_count", 0)
                post.saves    = metrics.get("saved", 0)
                post.shares   = metrics.get("shares", 0)
                post.reach    = metrics.get("reach", 0)

                reach = max(post.reach, 1)
                post.engagement_score = (
                    post.likes + post.comments * 2 + post.saves * 3 + post.shares * 3
                ) / reach * 100

                post.engagement_pulled_at = datetime.utcnow()
                session.add(post)
                print(f"[Instagram] Engagement pulled: post {post.id} score={post.engagement_score:.2f}")

            except Exception as e:
                print(f"[Instagram] Engagement pull error for post {post.id}: {e}")

        session.commit()

    _update_learning()


# ── LEARNING LOOP ─────────────────────────────────────────────────────────────

def _update_learning():
    """
    Analyse all scored posts and update the knowledge base in StoreConfig.
    Only runs once there are 5+ scored posts — not enough data before that.
    """
    with Session(engine) as session:
        scored = session.exec(
            select(InstagramPost).where(
                InstagramPost.engagement_pulled_at != None,
                InstagramPost.engagement_score > 0,
            ).limit(100)
        ).all()

    if len(scored) < 5:
        return

    # Category performance
    cat_scores: dict = {}
    for post in scored:
        with Session(engine) as session:
            product = session.get(Product, post.product_id)
        if not product:
            continue
        cat_scores.setdefault(product.category, []).append(post.engagement_score)

    cat_avg = {
        cat: round(sum(s) / len(s), 2)
        for cat, s in cat_scores.items()
    }
    best_category = max(cat_avg, key=cat_avg.get) if cat_avg else "Necklaces"

    # Post type performance
    product_scores  = [p.engagement_score for p in scored if p.post_type == "product"]
    campaign_scores = [p.engagement_score for p in scored if p.post_type == "campaign"]
    avg_product  = round(sum(product_scores)  / len(product_scores),  2) if product_scores  else 0
    avg_campaign = round(sum(campaign_scores) / len(campaign_scores), 2) if campaign_scores else 0

    kb_raw = get_config("instagram_knowledge_base", default="{}")
    try:
        kb = json.loads(kb_raw) if isinstance(kb_raw, str) else {}
    except Exception:
        kb = {}

    kb["posting_insights"] = {
        "posts_analyzed":           len(scored),
        "best_category":            best_category,
        "category_avg_engagement":  cat_avg,
        "avg_product_post_score":   avg_product,
        "avg_campaign_post_score":  avg_campaign,
        "last_updated":             datetime.utcnow().isoformat(),
    }

    set_config("instagram_knowledge_base", json.dumps(kb))
    print(
        f"[Instagram] Learning updated — best: {best_category} | "
        f"product avg: {avg_product} | campaign avg: {avg_campaign}"
    )


# ── MAIN ENTRY ────────────────────────────────────────────────────────────────

def run_instagram_agent():
    """
    Daily Instagram posting agent — runs at 16:00 UTC (10:00 AM CST).
    Posts one piece of content per run based on the 3:1 counter.
    Auto-posting must be enabled via StoreConfig: auto_posting_enabled = true.
    """
    print("[Instagram] Agent running...")
    _init_defaults()

    if get_config("auto_posting_enabled", default="false") != "true":
        print("[Instagram] Auto-posting disabled — skipping")
        return

    counter   = int(get_config("instagram_post_counter", default="0") or 0)
    post_type = "campaign" if counter >= 3 else "product"

    product = _pick_campaign_product() if post_type == "campaign" else _pick_product_post()

    if not product:
        print(f"[Instagram] No published product available for {post_type} post")
        return

    print(f"[Instagram] {post_type.upper()} post: {product.name} (ID {product.id})")

    image_url = _best_campaign_image(product) if post_type == "campaign" else product.image_url
    if not image_url:
        print(f"[Instagram] No image available — skipping")
        return

    caption  = _generate_caption(product, post_type)
    hashtags = _build_hashtags(product.category, product.material or "")

    catalog_id = getattr(product, "instagram_catalog_id", "") or ""
    result = _post_to_instagram(image_url, caption, hashtags, catalog_id)

    if result.get("success"):
        post_id = result.get("post_id", "")
        _save_post(product.id, post_type, image_url, caption, hashtags, post_id)
        _update_state(product, post_type)

        try:
            from app.agents.nervous_system import emit
            emit(
                signal_type="INSTAGRAM_POST_PUBLISHED",
                sender="instagram_agent",
                payload={
                    "product_id":       product.id,
                    "product_name":     product.name,
                    "post_type":        post_type,
                    "instagram_post_id": post_id,
                    "counter_before":   counter,
                },
                priority=5,
            )
        except Exception as e:
            print(f"[Instagram] Signal error: {e}")

        print(f"[Instagram] ✅ Posted — {post_type} — {product.name}")

    else:
        reason = result.get("reason", "unknown")
        print(f"[Instagram] ❌ Post failed: {reason}")
        try:
            from app.agents.nervous_system import emit
            emit(
                signal_type="INSTAGRAM_POST_FAILED",
                sender="instagram_agent",
                payload={
                    "product_id":   product.id,
                    "product_name": product.name,
                    "post_type":    post_type,
                    "reason":       reason,
                },
                priority=7,
            )
        except Exception as e:
            print(f"[Instagram] Signal error: {e}")
