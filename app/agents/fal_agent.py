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
            "prompt":           prompt,
            "num_images":       1,
            "output_format":    "jpeg",
            "aspect_ratio":     aspect_ratio,
            "safety_tolerance": "6",   # 1=strictest 6=most permissive — correct param for FLUX Pro Ultra
        },
    )
    images = result.get("images", [])
    if not images:
        # Log the full response so Railway shows exactly what fal.ai returned
        print(f"[fal.ai] Empty images in response. Full result: {result}")
        return ""
    return images[0]["url"]


def _safe_call(prompt: str, aspect_ratio: str, label: str) -> tuple:
    """
    Calls fal.ai and returns (url, error_message).
    error_message is '' on success, actual exception text on failure.
    """
    try:
        url = _call_fal(prompt, aspect_ratio)
        if not url:
            return "", "fal.ai returned empty images array (possible safety filter or API issue)"
        return url, ""
    except Exception as e:
        import traceback
        msg = str(e)
        print(f"[fal.ai] EXCEPTION in {label}: {msg}")
        traceback.print_exc()
        return "", msg


def generate_clean_shot(product_name: str, material: str) -> tuple:
    """Returns (url, error). url is '' on failure."""
    prompt = (
        f"Professional product photography of {product_name}, "
        f"{material} jewelry piece isolated, "
        "placed on white Italian marble, soft directional warm light, "
        "cream ivory background, macro detail, no hands, pure product, "
        f"{BRAND_TAIL}"
    )
    return _safe_call(prompt, "1:1", f"clean_shot:{product_name}")


def generate_lifestyle_shot(product_name: str, material: str,
                             category: str, product_id: int,
                             skin_tone: str = None) -> tuple:
    """Returns (url, error). url is '' on failure."""
    tone = skin_tone or _skin_tone_for(product_id)
    skin_desc = SKIN_TONE_DESC[tone]
    composition, aspect = _composition(category)

    prompt = (
        f"{composition}, {skin_desc}, "
        f"wearing {product_name}, {material} catching warm golden light, "
        "expression calm and self-possessed, she chose herself, "
        "natural hair movement, clean neutral nails, jewelry is the focus, "
        "shallow depth of field 85mm f/1.4, "
        "partial body only, no full face toward camera, "
        f"{BRAND_TAIL}"
    )
    return _safe_call(prompt, aspect, f"lifestyle:{product_name}:{tone}")


def generate_hero_image() -> tuple:
    """Returns (url, error)."""
    prompt = (
        "Cinematic close crop, 925 sterling silver jewelry draped on warm brown skin, "
        "collarbone and neck, cream and gold tones, light drifts across frame catching "
        "silver details, editorial luxury, Tiffany aesthetic, "
        "empowering intimate, photorealistic, ultra detailed, "
        f"{BRAND_TAIL}"
    )
    return _safe_call(prompt, "16:9", "hero_image")


def generate_collection_tile_image(collection_name: str) -> tuple:
    """Returns (url, error)."""
    prompt = (
        f"Flat lay editorial of {collection_name} jewelry on cream marble surface, "
        "925 sterling silver pieces arranged elegantly, "
        "warm light from top left, subtle shadows, "
        f"{BRAND_TAIL}"
    )
    return _safe_call(prompt, "1:1", f"collection_tile:{collection_name}")
