"""
TikTok access token storage + refresh.

Access tokens expire every 24h. Refresh tokens are single-use — TikTok
rotates them on every refresh call, so both values get persisted to
StoreConfig (DB) on each refresh. DB value takes priority; env var is
only the initial seed from the first manual OAuth login.
"""
import os
import httpx
from app.agents.store_config import get_config, set_config

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")


def get_access_token():
    return get_config("tiktok_access_token", default=os.getenv("TIKTOK_ACCESS_TOKEN"))


def get_refresh_token():
    return get_config("tiktok_refresh_token", default=os.getenv("TIKTOK_REFRESH_TOKEN"))


def refresh():
    """
    Exchange the current refresh token for a new access + refresh token
    and persist both to StoreConfig. Returns the new token dict, or
    raises on failure so the scheduler can alert.
    """
    current_refresh_token = get_refresh_token()
    if not current_refresh_token:
        raise RuntimeError("No TikTok refresh token available — run /auth/tiktok/login first")

    resp = httpx.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": current_refresh_token,
        },
        timeout=15,
    )
    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        raise RuntimeError(f"TikTok token refresh failed: {body}")

    set_config("tiktok_access_token", body["access_token"], "TikTok access token (auto-refreshed daily)")
    set_config("tiktok_refresh_token", body["refresh_token"], "TikTok refresh token (rotates on every refresh)")
    if body.get("open_id"):
        set_config("tiktok_open_id", body["open_id"], "TikTok open_id")

    print(f"[TikTok Token] ✅ Refreshed — expires_in={body.get('expires_in')}s")
    return body
