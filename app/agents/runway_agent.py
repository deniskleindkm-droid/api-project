"""
Runway ML Gen-4 Turbo — product and collection videos for Mikisi.
Takes a fal.ai-generated image as the input frame, adds motion on top.
Videos: top 20 products + 6 collection tiles + 1 hero banner.
Daily: 2 new videos per category (12/day).
Cost: ~$0.25 per 5s clip, ~$0.50 per 10s hero.

Switched from gen3a_turbo to gen4_turbo 2026-09-11 — gen3a_turbo was
deprecated and sunset by Runway on 2026-07-30, so every call silently
failed (task creation errored, generate_product_video returned "") from
that date until this fix; every video generated in that window is
missing, not just lower quality. gen4_turbo only accepts duration 5 or
10 (not 6) and a fixed set of "W:H" ratio strings, not the old free-form
768:1280 — 720:1280 is gen4_turbo's actual portrait option (confirmed
against Runway's own docs.dev.runwayml.com/assets/inputs/ reference).
"""
import os
import time
import requests

RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
RUNWAY_BASE    = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"
POLL_INTERVAL  = 10   # seconds between status checks
POLL_TIMEOUT   = 300  # 5 minutes max wait

HEADERS = {
    "Authorization": f"Bearer {RUNWAY_API_KEY}",
    "X-Runway-Version": RUNWAY_VERSION,
    "Content-Type": "application/json",
}

# Motion prompts per category — applied on top of the fal.ai input image
CATEGORY_MOTION = {
    "rings":     ("Premium jewelry product campaign. The camera makes a smooth small arc "
                  "around the stationary ring, moving from the initial view to a "
                  "three-quarter angle while gently moving closer. Show the stone facets "
                  "and side of the setting clearly. Bright soft studio lighting produces "
                  "distinct natural glints across several facets. Keep the entire ring "
                  "sharp and in frame. Preserve the exact ring geometry, stones, colors "
                  "and metal from the first frame. No text, no engravings, no logos, "
                  "no writing on the metal.",
                  5),
    "necklaces": ("Light moves slowly left to right across the necklace catching silver and stone, "
                  "breathing motion on skin, 5 seconds, seamless, no sudden movement",
                  5),
    "bracelets": ("Light moves across the stones slowly, wrist shifts weight once, "
                  "5 seconds, elegant loop",
                  5),
    "earrings":  ("Hair shifts gently once then settles, earring catches light, "
                  "5 seconds, slow intimate",
                  5),
    "anklets":   ("Foot shifts weight softly once, anklet catches light, "
                  "5 seconds, golden afternoon feel",
                  5),
    "ear cuffs": ("Hair settles back slowly over ear, ear cuff visible in full light, "
                  "5 seconds total, intimate close-up",
                  5),
}

COLLECTION_MOTION = (
    "Cinematic slow drift across jewelry pieces on cream marble surface, "
    "light moves gently catching silver details, "
    "5 seconds seamless loop, luxury editorial",
    5,
)

HERO_MOTION = (
    "Cinematic light drift across silver jewelry on warm skin, "
    "cream and gold tones, slow pan left to right, "
    "10 seconds seamless loop, luxury editorial, Tiffany atmosphere, "
    "empowering intimate",
    10,
)


def _create_task(image_url: str, prompt: str, duration: int) -> str:
    """Submit a generation task. Returns task_id or ''."""
    try:
        r = requests.post(
            f"{RUNWAY_BASE}/image_to_video",
            headers=HEADERS,
            json={
                "model":        "gen4_turbo",
                "promptImage":  image_url,
                "promptText":   prompt,
                "duration":     duration,
                "ratio":        "720:1280",  # gen4_turbo's actual portrait option
            },
            timeout=30,
        )
        data = r.json()
        task_id = data.get("id", "")
        if not task_id:
            print(f"[Runway] Task creation failed: {data}")
        return task_id
    except Exception as e:
        print(f"[Runway] Task creation error: {e}")
        return ""


def _poll_task(task_id: str) -> str:
    """Poll until SUCCEEDED. Returns video URL or ''."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{RUNWAY_BASE}/tasks/{task_id}",
                headers=HEADERS,
                timeout=30,
            )
            data = r.json()
            status = data.get("status", "")

            if status == "SUCCEEDED":
                outputs = data.get("output", [])
                return outputs[0] if outputs else ""

            if status in ("FAILED", "CANCELLED"):
                print(f"[Runway] Task {task_id} ended with status: {status}")
                return ""

            print(f"[Runway] Task {task_id} status: {status} — waiting {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"[Runway] Poll error for {task_id}: {e}")
            time.sleep(POLL_INTERVAL)

    print(f"[Runway] Task {task_id} timed out after {POLL_TIMEOUT}s")
    return ""


def generate_product_video(image_url: str, category: str) -> tuple:
    """
    Generate a product video from a lifestyle image.
    Returns (video_url, duration_seconds, cost_usd).
    image_url must be a permanent URL (Cloudinary) — not fal.ai (expires).
    """
    prompt, duration = CATEGORY_MOTION.get(
        category.lower(), CATEGORY_MOTION["necklaces"]
    )
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05  # Runway Gen-3 ~$0.05/second
    return video_url, duration, cost


def generate_collection_video(image_url: str, collection_name: str) -> tuple:
    """Collection tile video — 6 seconds."""
    prompt_base, duration = COLLECTION_MOTION
    prompt = f"{prompt_base}, {collection_name} collection"
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05
    return video_url, duration, cost


def generate_hero_video(image_url: str) -> tuple:
    """Hero banner video — 10 seconds."""
    prompt, duration = HERO_MOTION
    task_id = _create_task(image_url, prompt, duration)
    if not task_id:
        return "", 0, 0.0

    video_url = _poll_task(task_id)
    cost = duration * 0.05
    return video_url, duration, cost
