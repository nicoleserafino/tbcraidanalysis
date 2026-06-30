"""WCL v2 GraphQL client."""

from __future__ import annotations

import asyncio
import logging

import httpx
from backend.wcl.auth import get_access_token

GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFFS = (1, 2, 4)

# Global concurrency limiter to avoid overwhelming WCL API
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(6)
    return _semaphore

# Shared client for connection reuse (HTTP/2 multiplexing, keep-alive)
_client: httpx.AsyncClient | None = None
logger = logging.getLogger(__name__)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def graphql_query(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against WCL v2 API."""
    async with _get_semaphore():
        token = await get_access_token()
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        client = _get_client()
        for attempt in range(len(RETRY_BACKOFFS) + 1):
            try:
                resp = await client.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code in RETRY_STATUS_CODES and attempt < len(RETRY_BACKOFFS):
                    backoff = RETRY_BACKOFFS[attempt]
                    logger.warning(
                        "Retrying WCL GraphQL request after status %s (attempt %s/%s) in %ss",
                        resp.status_code,
                        attempt + 1,
                        len(RETRY_BACKOFFS),
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "errors" in data:
                    errors = data["errors"]
                    raise RuntimeError(f"WCL GraphQL error: {errors[0].get('message', errors)}")

                return data.get("data", {})
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= len(RETRY_BACKOFFS):
                    raise
                backoff = RETRY_BACKOFFS[attempt]
                logger.warning(
                    "Retrying WCL GraphQL request after connection error %s (attempt %s/%s) in %ss",
                    exc.__class__.__name__,
                    attempt + 1,
                    len(RETRY_BACKOFFS),
                    backoff,
                )
                await asyncio.sleep(backoff)

        raise RuntimeError("WCL GraphQL request failed after retries")
