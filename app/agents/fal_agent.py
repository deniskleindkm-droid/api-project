"""
fal.ai FLUX 1.1 Pro Ultra — lifestyle product images for Mikisi.
No Claude calls per product. Prompts are templates with product slots filled in.
Three images per product: clean shot + dark skin lifestyle + light skin lifestyle.
Skin tone rotates systematically across all content so Mikisi reflects every woman.
"""
import os
import fal_client

os.environ["FAL_KEY"] = os.getenv("FAL_KEY", "")

MODEL = "fal-ai/flux-pro/v1.1-ultra"

# Cost: $0.04 per image
COST_PER_IMAGE = 0.04

# Four skin tones, rotated by product_id % 4 — never default to one
SKIN_TONES = ["deep_brown", "medium_brown", "olive", "fair"]

SKIN_TONE_DESC = {
    "deep_brown":    "deep rich brown skin, melanin-rich, African or African-American woman, 25-45",
    "medium_brown":  "warm medium brown skin, Latina or South Asian woman, 25-45",
    "olive":         "light olive skin, Mediterranean or Middle Eastern woman, 25-45",
    "fair":          "fair porcelain skin, soft warm ivory complexion, European or East Asian woman, 25-45",
}

# Per-category shot composition
CATEGORY_COMPOSITION = {
    "rings":     ("close crop of a woman's hand, fingers slightly curved", "1:1"),
    "necklaces": ("close crop of collarbone and neck, necklace draped on skin", "4:5"),
    "bracelets": ("close crop of wrist and forearm, wrist raised slightly", "4:5"),
    "earrings":  ("side profile from jaw down, earring visible against neck, hair falls softly", "4:5"),
    "anklets":   ("bare ankle and foot on soft linen surface, soft afternoon light", "4:5"),
    "ear cuffs": ("behind-the-ear close crop, hair swept gently aside", "4:5"),
}

BRAND_TAIL = (
    "Mikisi luxury jewelry brand, ivory and warm rose gold color palette, "
    "soft warm natural light golden hour diffused, no harsh shadows, no studio flash, "
    "cream ivory background, photorealistic, ultra detailed, editorial luxury intimate"
)


def _skin_tone_for(product_id: int) -> str:
    return SKIN_TONES[product_id % 4]


def _composition(category: str) -> tuple:
    return CATEGORY_COMPOSITION.get(category.lower(), ("close crop of hand wearing jewelry", "1:1"))


def _call_fal(prompt: str, aspect_ratio: str) -> str:
    result = fal_client.subscribe(
        MODEL,
        arguments={
            "prompt": prompt,
            "num_images": 1,
            "enable_safety_checker": False,
            "output_format": "jpeg",
            "aspect_ratio": aspect_ratio,
        },
    )
    images = result.get("images", [])
    return images[0]["url"] if images else ""


def generate_clean_shot(product_name: str, material: str) -> str:
    """
    Product alone on ivory marble — no person, pure product focus.
    Used as the primary product panel image.
    """
    prompt = (
        f"Professional product photography of {product_name}, "
        f"{material} jewelry piece isolated, "
        "placed on white Italian marble, soft directional warm light, "
        "cream ivory background, macro detail, no hands, pure product, "
        f"{BRAND_TAIL}"
    )
    try:
        return _call_fal(prompt, "1:1")
    except Exception as e:
        print(f"[fal.ai] Clean shot failed '{product_name}': {e}")
        return ""


def generate_lifestyle_shot(product_name: str, material: str,
                             category: str, product_id: int,
                             skin_tone: str = None) -> str:
    """
    Product worn on skin — partial body, no full face.
    skin_tone: override, else auto-rotated from product_id.
    """
    tone = skin_tone or _skin_tone_for(product_id)
    skin_desc = SKIN_TONE_DESC[tone]
    composition, aspect = _composition(category)

    prompt = (
        f"{composition}, {skin_desc}, "
        f"wearing {product_name}, {material} catching warm golden light, "
        "expression calm and self-possessed, she chose herself, "
        "natural hair movement, clean neutral nails, jewelry is the focus, "
        "shallow depth of field 85mm f/1.4, "
        "NEVER full face forward looking at camera, "
        f"{BRAND_TAIL}"
    )
    try:
        return _call_fal(prompt, aspect)
    except Exception as e:
        print(f"[fal.ai] Lifestyle {tone} failed '{product_name}': {e}")
        return ""


def generate_hero_image() -> str:
    """Cinematic hero banner image — no specific product."""
    prompt = (
        "Cinematic close crop, 925 sterling silver jewelry draped on warm brown skin, "
        "collarbone and neck, cream and gold tones, light drifts across frame catching "
        "silver details, editorial luxury, Tiffany aesthetic, "
        "empowering intimate, photorealistic, ultra detailed, "
        f"{BRAND_TAIL}"
    )
    try:
        return _call_fal(prompt, "16:9")
    except Exception as e:
        print(f"[fal.ai] Hero image failed: {e}")
        return ""


def generate_collection_tile_image(collection_name: str) -> str:
    """Editorial flat lay for a collection tile."""
    prompt = (
        f"Flat lay editorial of {collection_name} on cream marble surface, "
        "925 sterling silver pieces arranged elegantly, "
        "warm light from top left, subtle shadows, "
        f"{BRAND_TAIL}"
    )
    try:
        return _call_fal(prompt, "1:1")
    except Exception as e:
        print(f"[fal.ai] Collection tile image failed '{collection_name}': {e}")
        return ""
