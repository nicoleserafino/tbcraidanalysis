"""WCL v2 OAuth2 client credentials flow."""

import time
import httpx
from backend.config import get_settings

_token_cache: dict = {"access_token": None, "expires_at": 0}

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"


async def get_access_token() -> str:
    """Get a valid access token, refreshing if expired."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
            },
            auth=(settings.wcl_client_id, settings.wcl_client_secret),
        )
        resp.raise_for_status()
        data = resp.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["access_token"]
