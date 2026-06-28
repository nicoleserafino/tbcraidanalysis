"""WCL v2 GraphQL client."""

from __future__ import annotations

import httpx
from backend.wcl.auth import get_access_token

GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"

# Shared client for connection reuse (HTTP/2 multiplexing, keep-alive)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def graphql_query(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against WCL v2 API."""
    token = await get_access_token()
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    client = _get_client()
    resp = await client.post(
        GRAPHQL_URL,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        errors = data["errors"]
        raise RuntimeError(f"WCL GraphQL error: {errors[0].get('message', errors)}")

    return data.get("data", {})
