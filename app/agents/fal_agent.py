"""
fal.ai image generation for Mikisi products.

Uses FLUX Pro Redux (image-to-image reference model) so the generated images
show the EXACT same product from Silverbene, just in a new setting.

Clean shot:    same product + ivory marble background
Lifestyle:     same product worn on skin, Mikisi brand aesthetic

The Silverbene source image is always passed as the reference — we never invent
a different product from text alone.
"""
import os
import fal_client

os.environ["FAL_KEY"] = os.getenv("FAL_KEY", "")

# FLUX Pro Redux — reference-guided generation, preserves product identity
REDUX_MODEL = "fal-ai/flux-pro/v1/redux"

SKIN_TONES = ["deep_brown", "medium_brown", "olive", "fair"]

SKIN_TONE_DESC = {
    "deep_brown":   "deep rich brown skin, melanin-rich, African or African-American woman, 25-45",
    "medium_brown": "warm medium brown skin, Latina or South Asian woman, 25-45",
    "olive":        "light olive skin, Mediterranean or Middle Eastern woman, 25-45",
    "fair":         "fair porcelain skin, soft warm ivory complexion, European or East Asian woman, 25-45",
}

CATEGORY_COMPOSITION = {
    "rings":     ("close crop of a woman's hand, fingers slightly curved, ring clearly visible", "square_hd"),
    "necklaces": ("close crop of collarbone and neck, necklace draped on skin", "portrait_4_3"),
    "bracelets": ("close crop of wrist and forearm, bracelet clearly visible", "portrait_4_3"),
    "earrings":  ("side profile from jaw down, earring visible against neck, hair falls softly", "portrait_4_3"),
    "anklets":   ("bare ankle and foot on soft linen surface", "portrait_4_3"),
    "ear cuffs": ("behind-the-ear close crop, hair swept gently aside, cuff visible", "portrait_4_3"),
}

BRAND_TAIL = (
    "Mikisi luxury jewelry brand, ivory and warm rose gold color palette, "
    "soft warm natural light golden hour diffused, no harsh shadows, "
    "cream ivory background tones, photorealistic, ultra detailed, editorial luxury"
)


def _skin_tone_for(product_id: int) -> str:
    return SKIN_TONES[product_id % 4]


def _call_redux(source_url: str, prompt: str, image_size: str) -> str:
    """
    FLUX Redux: takes source_url as reference image, generates the same product
    in the context described by prompt. Returns image URL.
    """
    result = fal_client.subscribe(
        REDUX_MODEL,
        arguments={
            "image_url":   source_url,
            "prompt":      prompt,
            "image_size":  image_size,
            "num_images":  1,
            "output_format": "jpeg",
            "safety_tolerance": "6",
        },
    )
    images = result.get("images", []) if result else []
    if not images:
        print(f"[fal.ai] Redux returned empty. Full response: {result}")
        return ""
    return images[0]["url"]


def _safe_redux(source_url: str, prompt: str, image_size: str, label: str) -> tuple:
    """Returns (url, error_message)."""
    if not source_url:
        return "", "No source image URL — cannot use Redux without a reference"
    try:
        url = _call_redux(source_url, prompt, image_size)
        if not url:
            return "", "fal.ai Redux returned empty images array"
        return url, ""
    except Exception as e:
        import traceback
        print(f"[fal.ai] EXCEPTION in {label}: {e}")
        traceback.print_exc()
        return "", str(e)


def generate_clean_shot(product_name: str, material: str,
                        source_url: str = "") -> tuple:
    """
    Same product placed on ivory marble with studio lighting.
    source_url = Silverbene product image URL (required for Redux).
    Returns (url, error).
    """
    prompt = (
        f"The exact same {product_name} jewelry piece, "
        f"{material}, "
        "isolated on white Italian marble surface, "
        "soft directional studio lighting, cream ivory background, "
        "macro detail, product photography, no hands, "
        f"{BRAND_TAIL}"
    )
    return _safe_redux(source_url, prompt, "square_hd", f"clean_shot:{product_name}")


def generate_lifestyle_shot(product_name: str, material: str,
                             category: str, product_id: int,
                             source_url: str = "",
                             skin_tone: str = None) -> tuple:
    """
    Same product worn on skin — partial body, no full face.
    source_url = Silverbene product image URL (required for Redux).
    Returns (url, error).
    """
    tone = skin_tone or _skin_tone_for(product_id)
    skin_desc = SKIN_TONE_DESC[tone]
    composition, image_size = CATEGORY_COMPOSITION.get(
        category.lower(), ("close crop of hand wearing the jewelry", "square_hd")
    )

    prompt = (
        f"{composition}, {skin_desc}, "
        f"wearing the exact same {product_name}, {material} catching warm golden light, "
        "expression calm and self-possessed, she chose herself, "
        "natural hair movement, clean neutral nails, jewelry is the focus, "
        "shallow depth of field 85mm f/1.4, "
        "partial body only, no full face toward camera, "
        f"{BRAND_TAIL}"
    )
    return _safe_redux(source_url, prompt, image_size,
                       f"lifestyle:{product_name}:{tone}")


def generate_hero_image(source_url: str = "") -> tuple:
    """
    Cinematic hero banner — jewelry on warm skin.
    If source_url provided, uses Redux for consistency. Otherwise pure text prompt.
    Returns (url, error).
    """
    if source_url:
        prompt = (
            "Cinematic close crop, the same jewelry draped on warm brown skin, "
            "collarbone and neck, cream and gold tones, "
            "light drifts across frame catching silver and stone details, "
            "editorial luxury, Tiffany aesthetic, empowering intimate, "
            f"{BRAND_TAIL}"
        )
        return _safe_redux(source_url, prompt, "landscape_16_9", "hero_image")

    # No source — fall back to text-to-image for hero
    from fal_client import subscribe as fal_subscribe
    prompt = (
        "Cinematic close crop, 925 sterling silver jewelry draped on warm brown skin, "
        "collarbone and neck, cream and gold tones, "
        "light drifts across frame catching silver details, "
        "editorial luxury, empowering intimate, photorealistic, ultra detailed, "
        f"{BRAND_TAIL}"
    )
    try:
        result = fal_subscribe(
            "fal-ai/flux-pro/v1.1-ultra",
            arguments={
                "prompt": prompt,
                "num_images": 1,
                "output_format": "jpeg",
                "aspect_ratio": "16:9",
                "safety_tolerance": "6",
            },
        )
        images = result.get("images", []) if result else []
        if not images:
            return "", "fal.ai returned empty for hero"
        return images[0]["url"], ""
    except Exception as e:
        import traceback
        traceback.print_exc()
        return "", str(e)


def generate_collection_tile_image(collection_name: str) -> tuple:
    """
    Editorial flat lay for a collection tile — text-to-image (no specific product).
    Returns (url, error).
    """
    from fal_client import subscribe as fal_subscribe
    prompt = (
        f"Flat lay editorial of {collection_name} jewelry on cream marble surface, "
        "925 sterling silver pieces arranged elegantly, "
        "warm light from top left, subtle shadows, "
        f"{BRAND_TAIL}"
    )
    try:
        result = fal_subscribe(
            "fal-ai/flux-pro/v1.1-ultra",
            arguments={
                "prompt": prompt,
                "num_images": 1,
                "output_format": "jpeg",
                "aspect_ratio": "1:1",
                "safety_tolerance": "6",
            },
        )
        images = result.get("images", []) if result else []
        if not images:
            return "", "fal.ai returned empty for collection tile"
        return images[0]["url"], ""
    except Exception as e:
        import traceback
        traceback.print_exc()
        return "", str(e)
