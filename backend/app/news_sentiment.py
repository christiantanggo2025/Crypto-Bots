"""
News and sentiment aggregation for Gen 4. Fetches from multiple sources in parallel,
returns a short context string for the AI supervisor. Kept fast for cycle time.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.lab_settings import get_api_keys

# Timeout per source so we don't block the cycle
FETCH_TIMEOUT = 8.0


async def _cryptopanic(api_key: str) -> list[str]:
    if not api_key or api_key == "***":
        return []
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            r = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params={"auth_token": api_key, "filter": "hot", "public": "true", "kind": "news"},
            )
            if r.status_code != 200:
                return []
            data = r.json()
            results = data.get("results", [])[:5]
            return [str(r.get("title") or r.get("url", ""))[:80] for r in results if r.get("title")]
    except Exception:
        return []


async def _newsapi(api_key: str) -> list[str]:
    if not api_key or api_key == "***":
        return []
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            r = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "apiKey": api_key,
                    "q": "crypto OR bitcoin OR ethereum",
                    "language": "en",
                    "pageSize": 5,
                    "sortBy": "publishedAt",
                },
            )
            if r.status_code != 200:
                return []
            data = r.json()
            articles = data.get("articles", [])[:5]
            return [str(a.get("title", ""))[:80] for a in articles if a.get("title")]
    except Exception:
        return []


async def fetch_news_context() -> str:
    """Fetch from all configured sources in parallel and return one context string."""
    keys = get_api_keys()
    tasks = []
    if keys.get("cryptopanic_api_key"):
        tasks.append(_cryptopanic(keys["cryptopanic_api_key"]))
    else:
        tasks.append(asyncio.sleep(0, result=[]))
    if keys.get("news_api_key"):
        tasks.append(_newsapi(keys["news_api_key"]))
    else:
        tasks.append(asyncio.sleep(0, result=[]))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    lines = []
    for r in results:
        if isinstance(r, Exception):
            continue
        lines.extend(r)
    if not lines:
        return "No recent news headlines available."
    return "Recent headlines: " + " | ".join(lines[:8])
