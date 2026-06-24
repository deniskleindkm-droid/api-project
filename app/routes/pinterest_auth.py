from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import base64
import httpx
import os

from app.agents.store_config import set_config

router = APIRouter(prefix="/auth/pinterest")

PINTEREST_CLIENT_ID = os.getenv("PINTEREST_CLIENT_ID")
PINTEREST_CLIENT_SECRET = os.getenv("PINTEREST_CLIENT_SECRET")
PINTEREST_REDIRECT_URI = os.getenv("PINTEREST_REDIRECT_URI")

PINTEREST_SCOPES = ",".join([
    "boards:read",
    "boards:write",
    "pins:read",
    "pins:write",
    "catalogs:read",
    "catalogs:write",
    "user_accounts:read",
])


@router.get("/login")
def pinterest_login():
    url = (
        "https://www.pinterest.com/oauth/"
        f"?client_id={PINTEREST_CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={PINTEREST_REDIRECT_URI}"
        f"&scope={PINTEREST_SCOPES}"
        "&state=mikisi_pinterest_auth"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def pinterest_callback(request: Request):
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

    basic_auth = base64.b64encode(
        f"{PINTEREST_CLIENT_ID}:{PINTEREST_CLIENT_SECRET}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.pinterest.com/v5/oauth/token",
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": PINTEREST_REDIRECT_URI,
            },
        )

    body = resp.json()

    if resp.status_code != 200 or "access_token" not in body:
        return JSONResponse(
            status_code=400,
            content={"error": "token_exchange_failed", "detail": body},
        )

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    refresh_token_expires_in = body.get("refresh_token_expires_in")
    scope = body.get("scope")

    set_config("pinterest_access_token", access_token, "Pinterest access token (from OAuth login)")
    if refresh_token:
        set_config("pinterest_refresh_token", refresh_token, "Pinterest refresh token (from OAuth login)")

    print(f"[Pinterest Auth] access_token={access_token}")
    print(f"[Pinterest Auth] refresh_token={refresh_token}")
    print(f"[Pinterest Auth] expires_in={expires_in}")
    print(f"[Pinterest Auth] scope={scope}")

    return {
        "message": "Pinterest authorization successful. Token stored in StoreConfig (pinterest_access_token).",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "refresh_token_expires_in": refresh_token_expires_in,
        "scope": scope,
    }
