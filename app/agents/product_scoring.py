import os
import json
import anthropic
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.autonomy import ProductScore

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# JEWELRY SCORING — 6 dimensions
# 1. Metal quality   — paramount for a jewelry brand
# 2. Image count     — minimum 3 required by quality standard
# 3. Price / margin  — sustainable business
# 4. Brand fit       — AI judges jewelry aesthetic
# 5. Category fit    — is it actually jewelry
# 6. Trend           — market signal (placeholder for market agent)
#
# Field repurposing (ProductScore schema unchanged):
#   supplier_rating      → metal_quality_score
#   order_volume_score   → image_count_score
# ============================================================

def _detect_metal_quality(name: str, category: str) -> tuple:
    """Returns (score 0-1, metal_type string)."""
    text = f"{name} {category}".lower()

    if "moissanite" in text:
        return 1.0, "moissanite"
    if "925" in text or "sterling silver" in text:
        return 0.95, "925_silver"
    if "surgical steel" in text or "implant grade" in text:
        return 0.90, "surgical_steel"
    if "titanium" in text:
        return 0.85, "titanium"
    if "pvd" in text:
        return 0.80, "pvd_plated"
    if "18k" in text or "gold plated" in text or "gold-plated" in text:
        return 0.75, "gold_plated"
    if "stainless steel" in text:
        return 0.70, "stainless_steel"
    if "alloy" in text or "zinc alloy" in text or "copper alloy" in text:
        return 0.25, "base_metal"
    if "plastic" in text or "acrylic" in text or "resin" in text:
        return 0.0, "plastic"

    return 0.35, "unknown"


def _image_count_score(image_url: str, images) -> tuple:
    """Returns (score 0-1, count int)."""
    count = 0
    if isinstance(images, list):
        count = len(images)
    elif isinstance(images, str) and images:
        try:
            count = len(json.loads(images))
        except Exception:
            count = 1 if image_url else 0
    elif image_url:
        count = 1

    if count >= 3:
        return 1.0, count
    if count == 2:
        return 0.5, count
    if count == 1:
        return 0.2, count
    return 0.0, 0


def score_product(product: dict) -> ProductScore:
    """
    Score a jewelry product across 6 dimensions before importing.
    Hard rejects: plastic/unknown metal or zero images.
    """
    name = product.get("name", "")
    category = product.get("category", "")
    cost_price = float(product.get("cost_price", 0))
    image_url = product.get("image_url", "")
    images = product.get("images", [])

    # D1 — Metal quality
    metal_score, metal_type = _detect_metal_quality(name, category)

    # D2 — Image count
    image_score, image_count = _image_count_score(image_url, images)

    # D3 — Price / margin potential
    price_score = 0.5
    if cost_price > 0:
        if cost_price <= 2.0:
            price_score = 0.95
        elif cost_price <= 5.0:
            price_score = 0.85
        elif cost_price <= 10.0:
            price_score = 0.70
        elif cost_price <= 20.0:
            price_score = 0.50
        elif cost_price <= 40.0:
            price_score = 0.30
        else:
            price_score = 0.15

    # D4 & D5 — AI brand fit + category fit (one cheap Haiku call)
    visual_score = 0.5
    category_fit = 0.5
    try:
        prompt = (
            f"You assess products for Mikisi, a luxury jewelry brand.\n"
            f"Product: {name} | Category: {category} | Metal: {metal_type} | Cost: ${cost_price:.2f} | Images: {image_count}\n"
            f"Return JSON only: {{\"visual_score\": 0.0, \"category_fit\": 0.0, \"reasoning\": \"one sentence\"}}\n"
            f"visual_score = quality jewelry aesthetic (0-1). category_fit = is it a ring/necklace/bracelet/earring/anklet/piercing (0-1)."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1][4:] if parts[1].startswith("json") else parts[1]
        result = json.loads(text.strip())
        visual_score = float(result.get("visual_score", 0.5))
        category_fit = float(result.get("category_fit", 0.5))
        print(f"[Scoring] {result.get('reasoning', '')}")
    except Exception as e:
        print(f"[Scoring] AI assessment failed: {e}")

    # D6 — Trend score (placeholder — market agent populates this later)
    trend_score = 0.5

    total_score = round(
        metal_score  * 0.30 +
        image_score  * 0.20 +
        price_score  * 0.15 +
        visual_score * 0.15 +
        category_fit * 0.10 +
        trend_score  * 0.10,
        3
    )

    # Hard rejects override score
    if metal_type == "plastic":
        recommendation = "reject"
    elif image_count == 0:
        recommendation = "reject"
    elif total_score >= 0.65:
        recommendation = "auto_import"
    elif total_score >= 0.45:
        recommendation = "review"
    else:
        recommendation = "reject"

    print(f"[Scoring] {name[:50]} | metal={metal_type} images={image_count} score={total_score} → {recommendation}")

    scored = ProductScore(
        supplier_product_id=product.get("supplier_product_id", ""),
        supplier_name=product.get("supplier_name", ""),
        product_name=name[:200],
        category=category,
        cost_price=cost_price,
        image_url=image_url[:500] if image_url else "",
        supplier_rating=metal_score,
        order_volume_score=image_score,
        trend_score=trend_score,
        visual_score=visual_score,
        price_score=price_score,
        total_score=total_score,
        recommendation=recommendation,
        scored_at=datetime.utcnow()
    )

    with Session(engine) as session:
        session.add(scored)
        session.commit()
        session.refresh(scored)

    return scored


def score_and_decide(product: dict) -> dict:
    """Score a product and use autonomy engine to decide action."""
    from app.agents.autonomy_engine import check_autonomy
    from app.agents.nervous_system import emit

    scored = score_product(product)
    decision = check_autonomy(
        agent="product_agent",
        action="import_product",
        context={"total_score": scored.total_score}
    )

    if decision["autonomous"]:
        print(f"[Scoring] ✅ Auto-importing: {product.get('name', '')[:50]}")
        emit(
            signal_type="PRODUCT_APPROVED",
            sender="product_scoring",
            payload={
                "supplier_product_id": scored.supplier_product_id,
                "supplier_name": scored.supplier_name,
                "name": scored.product_name,
                "total_score": scored.total_score,
                "recommendation": scored.recommendation
            },
            priority=5
        )
        return {"action": "auto_import", "score": scored.total_score, "product_id": scored.supplier_product_id}

    print(f"[Scoring] Flagging for review: {product.get('name', '')[:50]}")
    emit(
        signal_type="PRODUCT_NEEDS_REVIEW",
        sender="product_scoring",
        receiver=decision["signal_to"],
        payload={
            "supplier_product_id": scored.supplier_product_id,
            "name": scored.product_name,
            "total_score": scored.total_score,
            "reason": decision["rule"]
        },
        priority=decision["priority"]
    )
    return {"action": "needs_review", "score": scored.total_score, "signal_to": decision["signal_to"]}
