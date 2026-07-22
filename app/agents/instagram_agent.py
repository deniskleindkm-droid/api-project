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
import time
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

# Instagram enforcement, Dec 2025: a hard 5-hashtag cap per post/Reel —
# excess tags get truncated/rejected, not just deprioritized (Mosseri /
# @Creators: "a few specific tags actually perform better than a long
# list of generic ones"). Researched 2026-07-18. Picks exactly ONE best
# tag per category instead of the old 3-4 variants — the old approach
# alone would already blow the whole budget before material/discovery
# tags get a slot. Still keyed off the full CATEGORY_HASHTAGS list below
# (index 3, the most specific variant) so there's one source of truth.
_CATEGORY_HASHTAG_PRIMARY = {cat: tags[-1] for cat, tags in CATEGORY_HASHTAGS.items()}

# Mid-volume (5K-500K posts) community/discovery tags — sweet spot per
# research: big enough for active search traffic, small enough a post
# isn't buried in seconds. Replaces the old #jewelry/#silverjewelry/
# #jewelrylovers (10M+ posts each — too broad to be useful, not banned,
# just no real reach at that volume).
_NICHE_DISCOVERY_TAGS = ["#handmadejewelry", "#jewelrymaker", "#artisanjewelry"]


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
        "instagram_manual_campaign_product_id": (
            "0",
            "Manually queued product ID for the NEXT campaign post — set via "
            "POST /admin/instagram/queue-campaign, consumed once posted"
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
    """
    Exactly 5 hashtags, in priority order — Instagram's hard cap (see
    module-level comment above _CATEGORY_HASHTAG_PRIMARY). Mix per
    research: 1 branded + 1 category/style + 1 material + up to 2 niche
    discovery tags, never generic broad ones.
    """
    tags = ["#mikisi"]
    tags.append(_CATEGORY_HASHTAG_PRIMARY.get(category, "#jewelrygram"))

    if material:
        m = material.lower()
        if "rose" in m and "gold" in m:
            tags.append("#rosegold")
        elif "gold" in m:
            tags.append("#goldplated")
        elif "rhodium" in m:
            tags.append("#rhodiumplated")
        elif "925" in m or "sterling" in m:
            tags.append("#sterlingsilverjewelry")

    seen, unique = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    for t in _NICHE_DISCOVERY_TAGS:
        if len(unique) >= 5:
            break
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return " ".join(unique[:5])


# ── CAPTION GENERATION ────────────────────────────────────────────────────────

# Where each category is actually worn — injected into the caption prompt
# so the LLM is never left to guess, and checked against the LLM's own
# output afterward (see _wrong_body_part_words). Found live 2026-07-18:
# a campaign caption for a RING said "Your wrists deserve more than
# whispers" — the model defaulted to the most common jewelry-caption body
# part (wrist) rather than the one that actually applies to this product.
CATEGORY_BODY_PART = {
    "Rings":     "finger",
    "Bracelets": "wrist",
    "Anklets":   "ankle",
    "Necklaces": "neck",
    "Earrings":  "ear",
    "Ear Cuffs": "ear",
}

# Every body-part word grouped by which part it actually belongs to —
# used to build the "wrong words for this category" list below. Plurals
# and close synonyms included (e.g. "collarbone" for neck, "earlobe" for
# ear) since a caption is just as wrong saying "collarbone" on a ring as
# it is saying "wrist" outright.
_BODY_PART_WORDS = {
    "finger": ["finger", "fingers"],
    "wrist":  ["wrist", "wrists"],
    "ankle":  ["ankle", "ankles"],
    "neck":   ["neck", "collarbone", "collarbones", "throat"],
    "ear":    ["ear", "ears", "earlobe", "earlobes"],
}

_WORD_RE_CACHE = {}


def _wrong_body_part_words(category: str) -> list:
    """Every body-part word that does NOT belong to this category."""
    correct = CATEGORY_BODY_PART.get(category)
    if not correct:
        return []
    words = []
    for part, terms in _BODY_PART_WORDS.items():
        if part != correct:
            words.extend(terms)
    return words


def _has_wrong_body_part(text: str, category: str) -> bool:
    """
    True if the caption mentions a body part that isn't the one this
    product is actually worn on (e.g. "wrist" on a ring). Word-boundary
    matched so "ear" doesn't false-positive inside "wear"/"early"/"heard".
    """
    wrong_words = _wrong_body_part_words(category)
    if not wrong_words:
        return False
    if category not in _WORD_RE_CACHE:
        import re
        _WORD_RE_CACHE[category] = re.compile(
            r'\b(' + '|'.join(wrong_words) + r')\b', re.I
        )
    return bool(_WORD_RE_CACHE[category].search(text))


def _fallback_caption(product: Product) -> str:
    return (
        f"{product.name} — {product.material or '925 Sterling Silver'}. "
        f"Find yours at mikisi.co"
    )


def _strip_stray_header(text: str) -> str:
    """
    Haiku occasionally prepends a markdown title line despite being told
    "caption text only" (seen live: "# Blue Sapphire Tennis Bracelet
    Campaign Caption") — strip a leading "# ..." line before it ever
    reaches a real post. Safe to strip unconditionally: the prompt already
    forbids hashtags in the caption body (those come from _build_hashtags
    separately), so a real caption never legitimately starts with a "#"
    line.
    """
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("#"):
        return "\n".join(lines[1:]).strip()
    return text


def _generate_caption(product: Product, post_type: str) -> str:
    kb_raw = get_config("instagram_knowledge_base", default="{}")
    brand_voice = get_config("brand_voice", default="Mikisi — luxury sterling silver jewelry.")

    try:
        kb = json.loads(kb_raw) if isinstance(kb_raw, str) else {}
    except Exception:
        kb = {}

    caption_rules = "\n".join(f"- {r}" for r in kb.get("caption_rules", []))
    bv = kb.get("brand_voice", brand_voice)

    body_part = CATEGORY_BODY_PART.get(product.category, "")
    body_part_rule = (
        f"This is a {product.category[:-1] if product.category.endswith('s') else product.category} "
        f"— worn on the {body_part}. Every physical/wearing reference MUST say "
        f"{body_part} or {body_part}s. NEVER mention any other body part "
        f"(wrist, ankle, neck/collarbone, ear/finger) unless {body_part} is that same part.\n"
        if body_part else ""
    )

    def _build_prompt(correction: str = "") -> str:
        # Instagram feed captions can't contain a clickable link at all
        # (only the bio link, Stories stickers, and Shopping tags are ever
        # tappable) — a raw URL here is just dead text a customer would
        # have to manually retype, and it exposes a bare internal product
        # ID. The Shopping tag (see meta_catalog.resolve_meta_product_id,
        # applied uniformly to every post type in run_instagram_agent) is
        # the actual tap-to-shop mechanism now, so the CTA just points at
        # that instead of printing a URL.
        if post_type == "product":
            return (
                f"Write an Instagram caption for this Mikisi product post.\n\n"
                f"Product: {product.name}\n"
                f"Category: {product.category}\n"
                f"Material: {product.material or '925 Sterling Silver'}\n"
                f"Price: ${product.final_price:.0f}\n"
                f"Description: {product.description[:400]}\n\n"
                f"{body_part_rule}"
                f"Caption rules:\n{caption_rules}\n\n"
                f"Brand voice: {bv}\n\n"
                f"Structure: Hook (10-12 words) → Body (2-3 sentences) → "
                f"CTA: 'Tap to shop 🛍️'\n"
                f"Do NOT include a URL or 'link in bio' — the shopping bag tap handles that.\n"
                f"Do NOT include hashtags. Return caption text only."
                f"{correction}"
            )
        return (
            f"Write an emotional brand storytelling caption for a Mikisi campaign post.\n\n"
            f"Product: {product.name}\n"
            f"Category: {product.category}\n"
            f"Material: {product.material or '925 Sterling Silver'}\n"
            f"Description: {product.description[:400]}\n\n"
            f"{body_part_rule}"
            f"Caption rules:\n{caption_rules}\n\n"
            f"Brand voice: {bv}\n\n"
            f"This is a campaign post — speak to her identity, not the product specs.\n"
            f"Do NOT mention price. No product listing language.\n"
            f"Structure: Emotional hook → Brand storytelling (2-3 sentences) → "
            f"CTA: 'Tap to shop the look 🛍️'\n"
            f"Do NOT include a URL or 'link in bio' — the shopping bag tap handles that.\n"
            f"Do NOT include hashtags. Return caption text only."
            f"{correction}"
        )

    def _call_llm(prompt: str) -> str:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return _strip_stray_header(response.content[0].text.strip())

    try:
        text = _call_llm(_build_prompt())
        if _has_wrong_body_part(text, product.category):
            print(f"[Instagram] Caption mentioned the wrong body part for "
                  f"{product.name} ({product.category}) — regenerating")
            correction = (
                f"\n\nIMPORTANT: your previous draft incorrectly referenced the "
                f"wrong body part. This is a {product.category} — it goes on the "
                f"{body_part}. Do not repeat that mistake."
            )
            text = _call_llm(_build_prompt(correction))
            if _has_wrong_body_part(text, product.category):
                print(f"[Instagram] Still wrong after retry for {product.name} "
                      f"— using safe fallback caption")
                return _fallback_caption(product)
        return text
    except Exception as e:
        print(f"[Instagram] Caption generation error: {e}")
        return _fallback_caption(product)


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

    Manual override first: Dennis is choosing which RAWSHOT photoshoot
    goes out next while he's still new to this (see
    instagram_manual_campaign_product_id, set via POST
    /admin/instagram/queue-campaign) — consumed exactly once, cleared in
    _update_state() only after that product's post actually succeeds, so a
    failed post doesn't silently lose the manual choice.

    Falls back to automatic scoring (visual potential, price tier, image
    count) when nothing is queued. Avoids the product used in the last
    campaign post either way. Only published, in-stock products qualify.
    """
    manual_id = int(get_config("instagram_manual_campaign_product_id", default="0") or 0)
    if manual_id:
        with Session(engine) as session:
            manual_product = session.get(Product, manual_id)
        if (manual_product and manual_product.is_active and manual_product.is_published
                and manual_product.stock > 0 and manual_product.image_url):
            return manual_product
        print(f"[Instagram] Queued campaign product {manual_id} no longer eligible — falling back to auto-pick")

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
    For campaign posts, prefer a real on-model RAWSHOT lifestyle photo
    (product.content_lifestyle_url — see rawshot_import_agent.py) over a
    plain second Silverbene gallery angle, since that's the whole point of
    a campaign post: emotional, on-model storytelling, not a product shot.
    Falls back to a second gallery image, then the primary image_url, for
    products that don't have a RAWSHOT photoshoot yet.
    """
    if product.content_lifestyle_url:
        return product.content_lifestyle_url
    # Cloudinary-cached gallery preferred over raw Silverbene URLs — hotlinking
    # their origin hit real intermittent 503s on carousel posts (2026-07-19),
    # while RAWSHOT/Cloudinary-backed images had zero failures. See
    # store_manager.py's image-caching docstring and
    # [[project_cloudinary_gallery_caching]] — falls back to the raw gallery
    # only for products not yet backfilled onto Cloudinary.
    gallery_source = product.content_images or product.images
    if gallery_source:
        try:
            gallery = json.loads(gallery_source)
            if len(gallery) > 1:
                return gallery[1]
            if gallery:
                return gallery[0]
        except Exception:
            pass
    return product.content_image_url or product.image_url or ""


# ── INSTAGRAM GRAPH API ───────────────────────────────────────────────────────

def _extract_error(response: dict, default: str) -> str:
    """
    A generic Graph API error (e.g. "(#100) Invalid parameter") often has
    more specific detail in error_user_msg/error_user_title/error_data
    that .message alone drops — found live 2026-07-18 debugging a product-
    tagging failure where .message never changed but the underlying cause
    did (Shop eligibility, then something else). Surface everything so a
    real failure is diagnosable from the response alone, not by guessing.
    """
    err = response.get("error", {})
    if not err:
        return default
    parts = [err.get("message", default)]
    if err.get("error_user_title"):
        parts.append(f"[{err['error_user_title']}]")
    if err.get("error_user_msg"):
        parts.append(f"— {err['error_user_msg']}")
    if err.get("error_subcode"):
        parts.append(f"(subcode {err['error_subcode']})")
    return " ".join(parts)


def _wait_for_container_ready(container_id: str, access_token: str,
                               max_attempts: int = 10, delay: float = 3.0) -> Optional[str]:
    """
    Polls a media container's status_code until FINISHED. Publishing right
    after container creation races Meta's own async image download/
    validation — found live 2026-07-18 as subcode 2207027 ("Media ID is
    not available... please wait for a moment") once the actual product-
    tagging permission block (catalog_management) was resolved. Returns
    None once ready, or an error reason string on failure/timeout.
    """
    for _ in range(max_attempts):
        r = requests.get(
            f"https://graph.facebook.com/v18.0/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=15,
        )
        status = r.json().get("status_code")
        if status == "FINISHED":
            return None
        if status == "ERROR":
            return "Container processing failed (status_code=ERROR)"
        time.sleep(delay)
    return "Container did not finish processing in time"


def _post_to_instagram(image_url: str, caption: str, hashtags: str,
                        meta_catalog_product_id: str = "") -> dict:
    """
    Post to Instagram via Graph API.
    If meta_catalog_product_id is set (resolved via
    app.agents.meta_catalog.resolve_meta_product_id — requires
    FACEBOOK_CATALOG_ID + FACEBOOK_ACCESS_TOKEN, see that module's
    docstring), the post is tagged as a shoppable product so the
    shopping-bag icon appears and links straight to it. A missing/failed
    tag never blocks the post — the caption's direct product link
    (mikisi.co/products/{id}) already works regardless.
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

        # Instagram Shopping — tag the product so the shopping-bag icon
        # shows and links to it. x/y (0-1 range) position the tag bubble
        # on the image — center, lower-third, where jewelry on a model
        # typically sits. A single fixed position is a reasonable default
        # for a single-product post; revisit if photos vary a lot in
        # composition.
        if meta_catalog_product_id:
            container_params["product_tags"] = json.dumps([
                {"product_id": meta_catalog_product_id, "x": 0.5, "y": 0.7}
            ])

        r = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media",
            params=container_params,
            timeout=30,
        )
        container = r.json()
        if "id" not in container:
            return {"success": False, "reason": _extract_error(container, "Container creation failed")}

        wait_err = _wait_for_container_ready(container["id"], access_token)
        if wait_err:
            return {"success": False, "reason": wait_err}

        r2 = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media_publish",
            params={"creation_id": container["id"], "access_token": access_token},
            timeout=30,
        )
        pub = r2.json()
        if "id" in pub:
            return {"success": True, "post_id": pub["id"]}

        return {"success": False, "reason": _extract_error(pub, "Publish failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def _post_to_instagram_carousel(image_urls: list, caption: str, hashtags: str,
                                 meta_catalog_product_id: str = "") -> dict:
    """
    Post a multi-image carousel to Instagram via Graph API.

    Three-step flow, different from a single-image post: each image
    becomes its own "child" container (is_carousel_item=true, no caption
    on these), then one parent container references all children plus the
    single caption (media_type=CAROUSEL, children=<comma-joined ids>),
    then the parent gets published. The caption/hashtags only ever go on
    the parent — never per-child.

    Product tagging on a carousel attaches to individual child images, not
    the parent container — there's no "tag the whole carousel" concept.
    Tags only the first child here (index 0) since every image in one of
    these posts shows the same single product; revisit if a carousel ever
    mixes multiple products.

    Falls back to _post_to_instagram for a single-image list — not a
    carousel at that point, and Instagram's carousel endpoint requires 2+
    children anyway.
    """
    if not image_urls:
        return {"success": False, "reason": "no_images"}
    if len(image_urls) == 1:
        return _post_to_instagram(image_urls[0], caption, hashtags, meta_catalog_product_id)

    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
    if not access_token or not account_id:
        print("[Instagram] Credentials not set — post skipped")
        return {"success": False, "reason": "credentials_missing"}

    # Instagram carousels support at most 10 images.
    image_urls = image_urls[:10]

    try:
        child_ids = []
        for i, image_url in enumerate(image_urls):
            child_params = {
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": access_token,
            }
            if i == 0 and meta_catalog_product_id:
                child_params["product_tags"] = json.dumps([
                    {"product_id": meta_catalog_product_id, "x": 0.5, "y": 0.7}
                ])
            r = requests.post(
                f"https://graph.facebook.com/v18.0/{account_id}/media",
                params=child_params,
                timeout=30,
            )
            child = r.json()
            if "id" not in child:
                return {"success": False, "reason": _extract_error(child, f"Child container {i} failed")}
            child_ids.append(child["id"])

        full_caption = f"{caption}\n\n{hashtags}"
        parent_params = {
            "media_type":   "CAROUSEL",
            "children":     ",".join(child_ids),
            "caption":      full_caption,
            "access_token": access_token,
        }
        r2 = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media",
            params=parent_params,
            timeout=30,
        )
        parent = r2.json()
        if "id" not in parent:
            return {"success": False, "reason": _extract_error(parent, "Carousel container creation failed")}

        wait_err = _wait_for_container_ready(parent["id"], access_token)
        if wait_err:
            return {"success": False, "reason": wait_err}

        r3 = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media_publish",
            params={"creation_id": parent["id"], "access_token": access_token},
            timeout=30,
        )
        pub = r3.json()
        if "id" in pub:
            return {"success": True, "post_id": pub["id"]}

        return {"success": False, "reason": _extract_error(pub, "Publish failed")}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def _post_reel_to_instagram(video_url: str, caption: str, hashtags: str,
                             meta_catalog_product_id: str = "") -> dict:
    """
    Post a Reel to Instagram via Graph API. Same container -> poll ->
    publish shape as _post_to_instagram, but media_type=REELS + video_url
    instead of image_url, and a much longer poll window —  video
    processing takes 30s to several minutes per Meta's own docs, vs.
    images which finish in a few seconds (_wait_for_container_ready's
    default 3s x 10 attempts is sized for images only).

    share_to_feed=true so it also shows in the feed grid, not just the
    Reels tab — matches how every other post_type here behaves (always
    lands in the feed).
    """
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")

    if not access_token or not account_id:
        print("[Instagram] Credentials not set — post skipped")
        return {"success": False, "reason": "credentials_missing"}

    try:
        full_caption = f"{caption}\n\n{hashtags}"

        container_params = {
            "media_type":    "REELS",
            "video_url":     video_url,
            "caption":       full_caption,
            "share_to_feed": "true",
            "access_token":  access_token,
        }

        if meta_catalog_product_id:
            container_params["product_tags"] = json.dumps([
                {"product_id": meta_catalog_product_id, "x": 0.5, "y": 0.7}
            ])

        r = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media",
            params=container_params,
            timeout=30,
        )
        container = r.json()
        if "id" not in container:
            return {"success": False, "reason": _extract_error(container, "Container creation failed")}

        wait_err = _wait_for_container_ready(container["id"], access_token, max_attempts=40, delay=5.0)
        if wait_err:
            return {"success": False, "reason": wait_err}

        r2 = requests.post(
            f"https://graph.facebook.com/v18.0/{account_id}/media_publish",
            params={"creation_id": container["id"], "access_token": access_token},
            timeout=30,
        )
        pub = r2.json()
        if "id" in pub:
            return {"success": True, "post_id": pub["id"]}

        return {"success": False, "reason": _extract_error(pub, "Publish failed")}

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
        set_config("instagram_manual_campaign_product_id", "0")  # consumed — see _pick_campaign_product
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

    # content_image_url (Cloudinary-cached) preferred over the raw Silverbene
    # image_url for the same reason _best_campaign_image() prefers Cloudinary
    # for campaign posts — hotlinking Silverbene's origin caused real
    # intermittent posting failures (2026-07-19). This was the one posting
    # path that never got that fix — only the campaign path did.
    image_url = _best_campaign_image(product) if post_type == "campaign" else (product.content_image_url or product.image_url)
    if not image_url:
        print(f"[Instagram] No image available — skipping")
        return

    caption  = _generate_caption(product, post_type)
    hashtags = _build_hashtags(product.category, product.material or "")

    from app.agents.meta_catalog import resolve_meta_product_id
    catalog_id = resolve_meta_product_id(product.id)
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


# ── MANUAL POSTING ────────────────────────────────────────────────────────────
# Dennis is posting by hand for now, deliberately not via the automatic 3:1
# counter/scheduler — he picks exactly which product, which images, and which
# post type each time (see conversation 2026-07-18). This never touches
# instagram_post_counter or the automatic pickers (_pick_product_post/
# _pick_campaign_product) at all, and auto_posting_enabled stays whatever it
# already was — calling this does not turn on automatic posting.

def post_manually(product_id: int, post_type: str, image_count: Optional[int] = None,
                   image_urls: Optional[list] = None, dry_run: bool = True,
                   skip_catalog_tag: bool = False) -> dict:
    """
    Post one specific product on command — the manual counterpart to
    run_instagram_agent()'s automatic picker.

    image_urls: explicit list, used verbatim in order — overrides
      image_count/post_type defaults entirely. Use this for a hand-picked
      set of images. Ignored for post_type="reel" (use image_urls[0] as
      an explicit video_url override instead — see below).
    image_count: for post_type="product", takes the first N images from
      the product's own gallery (product.images) instead of just the
      primary image_url. Ignored if image_urls is given.
    post_type="campaign" with no image_urls defaults to
      product.content_lifestyle_url (the RAWSHOT photoshoot image, see
      rawshot_import_agent.py) — falls back to _best_campaign_image() if
      that's not set.
    post_type="reel" posts product.video_url (the RAWSHOT photoshoot
      video, see rawshot_import_agent.py) as an Instagram Reel. Pass a
      single explicit video_url via image_urls[0] to override.
    skip_catalog_tag: post without attempting the Shopping tag at all —
      useful to isolate whether a failure is the tagging call itself
      (e.g. the account not yet approved for Instagram Shopping/
      instagram_shopping_tag_products) vs. something in the base post.

    dry_run=True (the default — deliberately, given how much review this
    launch has had) generates the real caption/hashtags/catalog-tag
    resolution and reports exactly what WOULD be posted, without calling
    the Graph API at all. Only pass dry_run=False once you've reviewed
    the preview and are ready for the real, live, public post.
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
    if not product:
        return {"success": False, "reason": "product_not_found"}
    if post_type not in ("product", "campaign", "reel"):
        return {"success": False, "reason": "post_type must be 'product', 'campaign', or 'reel'"}

    if post_type == "reel":
        video_url = (image_urls[0] if image_urls else None) or product.video_url
        if not video_url:
            return {"success": False, "reason": "no_video_resolved"}

        caption  = _generate_caption(product, post_type)
        hashtags = _build_hashtags(product.category, product.material or "")

        catalog_id = ""
        if not skip_catalog_tag:
            from app.agents.meta_catalog import resolve_meta_product_id
            catalog_id = resolve_meta_product_id(product.id)

        preview = {
            "product_id":       product.id,
            "product_name":     product.name,
            "post_type":        post_type,
            "video_url":        video_url,
            "caption":          caption,
            "hashtags":         hashtags,
            "meta_catalog_tag": catalog_id or None,
        }

        if dry_run:
            preview["dry_run"] = True
            return preview

        result = _post_reel_to_instagram(video_url, caption, hashtags, catalog_id)

        if result.get("success"):
            post_id = result.get("post_id", "")
            _save_post(product.id, post_type, video_url, caption, hashtags, post_id)
            _update_state(product, post_type)
            print(f"[Instagram] ✅ Manually posted — reel — {product.name}")
        else:
            print(f"[Instagram] ❌ Manual post failed: {result.get('reason')}")

        return {**preview, "dry_run": False, **result}

    if image_urls:
        images = [u for u in image_urls if u]
    elif post_type == "campaign":
        images = [product.content_lifestyle_url] if product.content_lifestyle_url else \
                 ([_best_campaign_image(product)] if _best_campaign_image(product) else [])
    else:
        # Prefer the Cloudinary-cached gallery (content_images) over raw
        # Silverbene URLs (images) — hotlinking Silverbene's gallery directly
        # hit real intermittent 503s from their CDN on real posts (2026-07-19).
        # Falls back to raw images only for products not yet backfilled (see
        # image_cdn_agent.py's backfill_product_galleries).
        gallery = []
        gallery_source = product.content_images or product.images
        if gallery_source:
            try:
                gallery = json.loads(gallery_source)
            except Exception:
                gallery = []
        if image_count and gallery:
            images = gallery[:image_count]
        else:
            images = [product.content_image_url or product.image_url] if (product.content_image_url or product.image_url) else []

    images = [u for u in images if u]
    if not images:
        return {"success": False, "reason": "no_images_resolved"}

    caption  = _generate_caption(product, post_type)
    hashtags = _build_hashtags(product.category, product.material or "")

    catalog_id = ""
    if not skip_catalog_tag:
        from app.agents.meta_catalog import resolve_meta_product_id
        catalog_id = resolve_meta_product_id(product.id)

    preview = {
        "product_id":   product.id,
        "product_name": product.name,
        "post_type":    post_type,
        "images":       images,
        "carousel":     len(images) > 1,
        "caption":      caption,
        "hashtags":     hashtags,
        "meta_catalog_tag": catalog_id or None,
    }

    if dry_run:
        preview["dry_run"] = True
        return preview

    if len(images) > 1:
        result = _post_to_instagram_carousel(images, caption, hashtags, catalog_id)
    else:
        result = _post_to_instagram(images[0], caption, hashtags, catalog_id)

    if result.get("success"):
        post_id = result.get("post_id", "")
        _save_post(product.id, post_type, images[0], caption, hashtags, post_id)
        _update_state(product, post_type)
        print(f"[Instagram] ✅ Manually posted — {post_type} — {product.name}")
    else:
        print(f"[Instagram] ❌ Manual post failed: {result.get('reason')}")

    return {**preview, "dry_run": False, **result}


# ── MANUAL CATCH-UP QUEUE (2026-07-21) ──
# Dennis's exact 12-item posting order, re-approved 2026-07-21 after fixing
# the real-variant-to-checkout bugs that made him delete the original posts
# (see project memory: project_instagram_catchup_order, project_
# guest_checkout_422_bug, project_size_chip_invalid_selection). He wants
# these spaced ~1 hour apart and posted unattended — do not reorder or
# substitute any item without his explicit say-so.
INSTAGRAM_CATCHUP_QUEUE = [
    {"product_id": 572,  "post_type": "product",  "image_count": 4},
    {"product_id": 597,  "post_type": "product",  "image_count": 3},
    {"product_id": 657,  "post_type": "product",  "image_count": 3},
    {"product_id": 1121, "post_type": "campaign", "image_count": None},
    {"product_id": 766,  "post_type": "product",  "image_count": 3},
    {"product_id": 1085, "post_type": "product",  "image_count": 3},
    {"product_id": 757,  "post_type": "product",  "image_count": 3},
    {"product_id": 1012, "post_type": "campaign", "image_count": None},
    {"product_id": 489,  "post_type": "product",  "image_count": 3},
    {"product_id": 769,  "post_type": "product",  "image_count": 3},
    {"product_id": 945,  "post_type": "product",  "image_count": 3},
    {"product_id": 947,  "post_type": "campaign", "image_count": None},
]


def run_instagram_catchup_queue():
    """
    Posts the next not-yet-posted item in INSTAGRAM_CATCHUP_QUEUE, one per
    call — scheduled hourly (see app/scheduler.py) so the 12 items go out
    roughly 1 hour apart, unattended. Progress is tracked via StoreConfig
    (instagram_catchup_index), the same pattern as instagram_post_counter —
    deliberately NOT the generic InstagramPost history table, since that
    could still contain stale rows from the original (since-deleted)
    2026-07-19 batch and would make "already posted" checks ambiguous.
    Runs entirely in-process (no HTTP call, no master_key needed) — this is
    what lets it run unattended on a schedule without embedding any
    credential in external cloud-agent config.
    """
    from app.agents.store_config import get_config, set_config
    from datetime import datetime, timedelta
    index = int(get_config("instagram_catchup_index", default="0") or 0)
    if index >= len(INSTAGRAM_CATCHUP_QUEUE):
        return  # queue complete — nothing to do, job just no-ops from here on

    # Self-regulating time guard — every job registered with next_run_time=
    # utcnow() (see scheduler.py's "catch up the backlog on this deploy"
    # pattern, used across several jobs) re-fires immediately on EVERY app
    # restart, not just once. Found live 2026-07-21: this job would otherwise
    # post the next queue item on every single deploy that happens while the
    # queue is still running, rapid-firing through Dennis's explicitly-
    # requested 1-hour spacing the moment two deploys land within an hour of
    # each other. Tracked independently of APScheduler's own state (which is
    # in-memory and doesn't survive a restart anyway) via a StoreConfig
    # timestamp, so this self-regulates no matter how often the scheduler
    # actually invokes it.
    last_post_at = get_config("instagram_catchup_last_post_at", default="")
    if last_post_at:
        try:
            elapsed = datetime.utcnow() - datetime.fromisoformat(last_post_at)
            if elapsed < timedelta(minutes=55):
                print(f"[Instagram Catchup] Skipping — only {elapsed} since last post, waiting for ~1h spacing")
                return
        except Exception:
            pass

    fail_key = f"instagram_catchup_fail_count_{index}"
    fail_count = int(get_config(fail_key, default="0") or 0)

    item = INSTAGRAM_CATCHUP_QUEUE[index]
    print(f"[Instagram Catchup] Posting item {index+1}/{len(INSTAGRAM_CATCHUP_QUEUE)}: product {item['product_id']} ({item['post_type']})")

    result = post_manually(
        product_id=item["product_id"],
        post_type=item["post_type"],
        image_count=item["image_count"],
        dry_run=False,
    )

    if result.get("success"):
        set_config("instagram_catchup_index", str(index + 1))
        set_config(fail_key, "0")
        set_config("instagram_catchup_last_post_at", datetime.utcnow().isoformat())
        print(f"[Instagram Catchup] ✅ Item {index+1}/{len(INSTAGRAM_CATCHUP_QUEUE)} posted — product {item['product_id']}")
    else:
        fail_count += 1
        set_config(fail_key, str(fail_count))
        reason = result.get("reason", "unknown")
        print(f"[Instagram Catchup] ❌ Item {index+1} failed (attempt {fail_count}): {reason}")
        if fail_count >= 3:
            # Give up on this item after 3 tries so the whole queue doesn't
            # stall forever behind one bad product — alert Dennis since he
            # explicitly won't be watching this run.
            try:
                from app.agents.email_partner import send_email
                import os
                dennis = os.getenv("DENNIS_EMAIL")
                if dennis:
                    send_email(
                        to=dennis,
                        subject=f"Instagram catch-up queue — item {index+1} skipped after 3 failures",
                        body=f"<p>Product {item['product_id']} ({item['post_type']}) failed 3 times in a row: {reason}</p><p>Skipping it so the rest of the queue still goes out on schedule. Worth checking this one manually.</p>",
                        is_html=True,
                    )
            except Exception as e:
                print(f"[Instagram Catchup] Failed to send skip-alert email: {e}")
            set_config("instagram_catchup_index", str(index + 1))
            set_config(fail_key, "0")
            set_config("instagram_catchup_last_post_at", datetime.utcnow().isoformat())
