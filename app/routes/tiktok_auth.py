from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
import os

router = APIRouter(prefix="/auth/tiktok")

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI")


@router.get("/login")
def tiktok_login():
    url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        "&response_type=code"
        "&scope=user.info.basic,video.publish,video.upload"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
        "&state=mikisi_tiktok_auth"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def tiktok_callback(request: Request):
    error = request.query_params.get("error")
    code = request.query_params.get("code")

    if error or not code:
        return JSONResponse(
            status_code=400,
            content={
                "error": error or "missing_code",
                "error_description": request.query_params.get("error_description", "No authorization code returned"),
            },
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": TIKTOK_REDIRECT_URI,
            },
        )

    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"error": "token_exchange_failed", "detail": body},
        )

    open_id = body.get("open_id")
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    refresh_expires_in = body.get("refresh_expires_in")

    print(f"[TikTok Auth] open_id={open_id}")
    print(f"[TikTok Auth] access_token={access_token}")
    print(f"[TikTok Auth] refresh_token={refresh_token}")
    print(f"[TikTok Auth] expires_in={expires_in}")
    print(f"[TikTok Auth] refresh_expires_in={refresh_expires_in}")

    return {
        "message": "TikTok authorization successful. Copy the access_token to Railway as TIKTOK_ACCESS_TOKEN and save the refresh_token somewhere safe.",
        "open_id": open_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
    }


@router.get("/user")
async def tiktok_user_info():
    """
    Calls TikTok's /v2/user/info/ endpoint using the stored access token.
    Used to verify the token is valid and display connected account info.
    """
    access_token = os.getenv("TIKTOK_ACCESS_TOKEN")

    if not access_token:
        return JSONResponse(
            status_code=400,
            content={"error": "TIKTOK_ACCESS_TOKEN not set in environment variables"},
        )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://open.tiktokapis.com/v2/user/info/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={
                "fields": "open_id,union_id,avatar_url,display_name,bio_description,profile_deep_link,is_verified,follower_count,following_count,likes_count,video_count"
            },
        )

    if response.status_code != 200:
        return JSONResponse(
            status_code=500,
            content={
                "error": "TikTok API call failed",
                "status_code": response.status_code,
                "detail": response.json(),
            },
        )

    data = response.json()
    user = data.get("data", {}).get("user", {})
    print(f"[TikTok] User info fetched — display_name={user.get('display_name')} open_id={user.get('open_id')}")

    return JSONResponse(status_code=200, content=data)


@router.get("/refresh")
async def tiktok_refresh(refresh_token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"error": "token_refresh_failed", "detail": body},
        )

    open_id = body.get("open_id")
    access_token = body.get("access_token")
    new_refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    refresh_expires_in = body.get("refresh_expires_in")

    print(f"[TikTok Auth] Refreshed — open_id={open_id}")
    print(f"[TikTok Auth] access_token={access_token}")
    print(f"[TikTok Auth] refresh_token={new_refresh_token}")
    print(f"[TikTok Auth] expires_in={expires_in}")
    print(f"[TikTok Auth] refresh_expires_in={refresh_expires_in}")

    return {
        "open_id": open_id,
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
    }
