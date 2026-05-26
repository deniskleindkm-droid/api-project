import os
import anthropic
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.autonomy import ProductScore

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def score_product(product: dict) -> ProductScore:
    """
    Score a product before importing.
    Uses real data where available, AI judgment for visual and fit scoring.
    
    product dict must have:
    - supplier_product_id
    - supplier_name
    - name
    - category
    - cost_price
    - image_url (optional)
    - variants (list)
    """

    name = product.get("name", "")
    category = product.get("category", "")
    cost_price = float(product.get("cost_price", 0))
    image_url = product.get("image_url", "")
    variants = product.get("variants", [])

    # SCORE 1 — Supplier rating (from variant data or default)
    supplier_rating = 0.5
    if variants:
        supplier_rating = 0.8  # Has variants = more established product

    # SCORE 2 — Order volume score
    order_volume_score = 0.5  # Default until we have real sales data

    # SCORE 3 — Price score (sustainable margin potential)
    price_score = 0.5
    if cost_price > 0:
        if cost_price <= 2.0:
            price_score = 0.9  # Very low cost = high margin potential
        elif cost_price <= 5.0:
            price_score = 0.8
        elif cost_price <= 15.0:
            price_score = 0.6
        elif cost_price <= 30.0:
            price_score = 0.4
        else:
            price_score = 0.2

    # SCORE 4 — Visual score (AI judges if product fits Mikisi aesthetics)
    visual_score = 0.5
    try:
        prompt = f"""You are the visual quality assessor for Mikisi — a premium women's beauty accessories store.

Product to assess:
- Name: {name}
- Category: {category}
- Cost price: ${cost_price}
- Has image: {"yes" if image_url else "no"}

Score this product's fit for Mikisi on these criteria:
1. Does it fit women's beauty accessories?
2. Does the category suggest photogenic, elegant products?
3. Is the price point appropriate for a beauty store?

Return JSON only:
{{
    "visual_score": 0.0 to 1.0,
    "category_fit": 0.0 to 1.0,
    "reasoning": "one sentence"
}}"""

        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1][4:] if parts[1].startswith("json") else parts[1]

        result = json.loads(text.strip())
        visual_score = result.get("visual_score", 0.5)
        category_fit = result.get("category_fit", 0.5)
        print(f"[Scoring] AI assessment: {result.get('reasoning', '')}")

    except Exception as e:
        print(f"[Scoring] AI scoring failed: {e} — using defaults")
        category_fit = 0.5

    # SCORE 5 — Trend score (placeholder — will connect to market agent)
    trend_score = 0.5

    # TOTAL SCORE — weighted average
    total_score = round(
        supplier_rating * 0.20 +
        order_volume_score * 0.15 +
        trend_score * 0.20 +
        visual_score * 0.20 +
        category_fit * 0.15 +
        price_score * 0.10,
        3
    )

    # RECOMMENDATION based on score
    if total_score >= 0.65:
        recommendation = "auto_import"
    elif total_score >= 0.45:
        recommendation = "review"
    else:
        recommendation = "reject"

    print(f"[Scoring] {name[:50]} → score: {total_score} → {recommendation}")

    # Save to database
    scored = ProductScore(
        supplier_product_id=product.get("supplier_product_id", ""),
        supplier_name=product.get("supplier_name", ""),
        product_name=name[:200],
        category=category,
        cost_price=cost_price,
        image_url=image_url[:500] if image_url else "",
        supplier_rating=supplier_rating,
        order_volume_score=order_volume_score,
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
    """
    Score a product and use autonomy engine to decide what to do.
    Returns action to take.
    """
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
        return {
            "action": "auto_import",
            "score": scored.total_score,
            "product_id": scored.supplier_product_id
        }
    else:
        print(f"[Scoring] 📋 Flagging for review: {product.get('name', '')[:50]}")
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
        return {
            "action": "needs_review",
            "score": scored.total_score,
            "signal_to": decision["signal_to"]
        }