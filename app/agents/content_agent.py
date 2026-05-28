from dotenv import load_dotenv
load_dotenv()

import os
import json
import anthropic
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.content import ProductContent
from app.models.product import Product

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def get_brand_voice():
    """Get brand voice from database — never hardcoded."""
    try:
        from app.agents.store_config import get_config
        return get_config("brand_voice", default="Mikisi is a women's beauty accessories brand. Elegant, empowering, intimate.")
    except:
        return "Mikisi is a women's beauty accessories brand. Elegant, empowering, intimate."


def get_product_details(product_id):
    """Get full product details for content generation."""
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return None
        return {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "final_price": product.final_price,
            "original_price": product.original_price,
            "image_url": product.image_url,
            "brand": product.brand
        }


def generate_content_for_platform(product, platform, brand_voice):
    """
    Generate emotionally intelligent content for a specific platform.
    Three levels: product → emotion → identity.
    """

    platform_guides = {
        "instagram": {
            "format": "Caption under 150 words. Hook first line. Emotional storytelling. 10-15 hashtags at end.",
            "hook_format": "One powerful opening line that stops the scroll.",
            "max_hashtags": 15
        },
        "tiktok": {
            "format": "Hook for first 3 seconds. Conversational tone. Under 100 words. 5-8 hashtags.",
            "hook_format": "3-second video hook — what you say in the first 3 seconds to stop scrolling.",
            "max_hashtags": 8
        },
        "pinterest": {
            "format": "Descriptive, aspirational. SEO-friendly. Under 200 words. 5 keywords naturally woven in.",
            "hook_format": "Aspirational opening that paints a picture.",
            "max_hashtags": 5
        },
        "facebook": {
            "format": "Conversational story format. Can be longer — up to 200 words. Question at end to drive comments. 3-5 hashtags.",
            "hook_format": "Opening that feels like a friend sharing something special.",
            "max_hashtags": 5
        }
    }

    guide = platform_guides.get(platform, platform_guides["instagram"])

    prompt = f"""You are the content creator for Mikisi — a women's beauty accessories brand.

BRAND VOICE:
{brand_voice}

CONTENT PHILOSOPHY:
Content must operate on three levels:
1. PRODUCT LEVEL — what is this product specifically
2. EMOTIONAL LEVEL — what does this make a woman feel
3. IDENTITY LEVEL — who does she become when she owns this

Nike didn't sell shoes. They sold identity. Mikisi doesn't sell accessories. We sell the feeling of choosing yourself.

Every piece of content must make a woman feel something before she clicks.

PRODUCT:
- Name: {product['name']}
- Category: {product['category']}
- Price: ${product['final_price']:.2f} (was ${product['original_price']:.2f})
- Description: {product['description'][:300] if product['description'] else 'Beauty accessory'}

PLATFORM: {platform.upper()}
FORMAT GUIDE: {guide['format']}
HOOK FORMAT: {guide['hook_format']}

Generate content that:
- Opens with emotion not product features
- Makes her feel seen and elegant
- Never sounds like an ad — sounds like a truth she needed to hear
- Ends with subtle call to action
- Maximum {guide['max_hashtags']} hashtags

Return JSON only:
{{
    "hook": "the opening line or 3-second video hook",
    "caption": "full caption for the platform",
    "hashtags": "space separated hashtags",
    "emotional_angle": "one sentence — the core emotion this content triggers",
    "content_score": 0.0 to 1.0
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=800,
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


def save_content(product_id, platform, content_data):
    """Save generated content to database."""
    with Session(engine) as session:
        # Check if content already exists for this product/platform
        existing = session.exec(
            select(ProductContent).where(
                ProductContent.product_id == product_id,
                ProductContent.platform == platform,
                ProductContent.status == "ready"
            )
        ).first()

        if existing:
            print(f"[Content] Content already exists for product {product_id} on {platform}")
            return existing

        content = ProductContent(
            product_id=product_id,
            platform=platform,
            caption=content_data.get("caption", ""),
            hook=content_data.get("hook", ""),
            hashtags=content_data.get("hashtags", ""),
            emotional_angle=content_data.get("emotional_angle", ""),
            content_score=float(content_data.get("content_score", 0.5)),
            status="ready",
            created_at=datetime.utcnow()
        )
        session.add(content)
        session.commit()
        session.refresh(content)
        print(f"[Content] ✅ Content saved for product {product_id} on {platform}")
        return content


def score_content(content_data) -> float:
    """Score content quality — used by autonomy engine."""
    score = float(content_data.get("content_score", 0.5))
    return score


def generate_all_content(product_id) -> dict:
    """
    Generate content for all platforms for a product.
    Called when PRODUCT_IMPORTED signal received.
    """
    print(f"[Content] 🎨 Generating content for product {product_id}")

    product = get_product_details(product_id)
    if not product:
        print(f"[Content] Product {product_id} not found")
        return {"success": False, "reason": "Product not found"}

    brand_voice = get_brand_voice()
    platforms = ["instagram", "tiktok", "pinterest", "facebook"]
    results = {}

    for platform in platforms:
        try:
            print(f"[Content] Generating {platform} content for: {product['name'][:50]}")
            content_data = generate_content_for_platform(product, platform, brand_voice)
            content = save_content(product_id, platform, content_data)

            results[platform] = {
                "content_id": content.id,
                "score": content.content_score,
                "hook": content.hook[:100] if content.hook else "",
                "emotional_angle": content.emotional_angle
            }

            # Check autonomy — should we auto-post or signal ARIA?
            from app.agents.autonomy_engine import check_autonomy
            decision = check_autonomy(
                agent="content_agent",
                action="post_content",
                context={"content_score": content.content_score}
            )

            if decision["autonomous"]:
                # Signal posting agent
                from app.agents.nervous_system import emit
                emit(
                    signal_type="CONTENT_READY",
                    sender="content_agent",
                    payload={
                        "content_id": content.id,
                        "product_id": product_id,
                        "platform": platform,
                        "score": content.content_score,
                        "auto_post": True
                    },
                    priority=5
                )
                print(f"[Content] 📡 CONTENT_READY signal emitted for {platform}")
            else:
                print(f"[Content] Score {content.content_score:.2f} below threshold — flagged for ARIA review")
                from app.agents.nervous_system import emit
                emit(
                    signal_type="CONTENT_NEEDS_REVIEW",
                    sender="content_agent",
                    payload={
                        "content_id": content.id,
                        "product_id": product_id,
                        "platform": platform,
                        "score": content.content_score,
                        "reason": decision["rule"]
                    },
                    priority=4
                )

        except Exception as e:
            print(f"[Content] Error generating {platform} content: {e}")
            results[platform] = {"error": str(e)}

    print(f"[Content] ✅ Content generation complete for product {product_id}")
    return {
        "success": True,
        "product_id": product_id,
        "product_name": product["name"],
        "platforms": results
    }


def run_content_agent(product_id=None):
    """
    Run content agent.
    If product_id provided — generate for that product.
    Otherwise — find products without content and generate.
    """
    if product_id:
        return generate_all_content(product_id)

    # Find products without content
    with Session(engine) as session:
        products_with_content = session.exec(
            select(ProductContent.product_id).distinct()
        ).all()

        all_products = session.exec(
            select(Product).where(Product.is_active == True)
        ).all()

    products_needing_content = [
        p for p in all_products
        if p.id not in products_with_content
    ]

    print(f"[Content] Found {len(products_needing_content)} products needing content")

    for product in products_needing_content[:5]:  # Process 5 at a time
        generate_all_content(product.id)

    return {"processed": len(products_needing_content[:5])}