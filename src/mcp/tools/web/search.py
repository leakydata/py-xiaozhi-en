"""Web search with a keyless default and optional paid backends.

Provider selection:
  1. SYSTEM_OPTIONS.WEB_SEARCH.PROVIDER in config, or
  2. BRAVE_API_KEY / TAVILY_API_KEY in the environment, or
  3. Mojeek (no key, independent index)

DuckDuckGo is deliberately not used: both its html and lite endpoints answer
scripted requests with an anti-bot challenge page (HTTP 202, "anomaly"), so it
cannot serve as a keyless backend.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import aiohttp

from src.logging import get_logger
from src.utils.config_manager import get_config

from .htmltext import strip_tags

logger = get_logger()

_TIMEOUT = aiohttp.ClientTimeout(total=15)
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_MOJEEK = "https://www.mojeek.com/search"
_BRAVE = "https://api.search.brave.com/res/v1/web/search"
_TAVILY = "https://api.tavily.com/search"

# Mojeek result markup: <!--rs--> ... <!--re--> per hit.
_RESULT = re.compile(r"<!--rs-->(.*?)<!--re-->", re.S)
_URL = re.compile(r'href="([^"]+)"\s+class="ob"')
_TITLE = re.compile(r'<a class="title"[^>]*>(.*?)</a>', re.S)
_SNIPPET = re.compile(r'<p class="s">(.*?)</p>', re.S)


def _cfg(path: str, default=None):
    try:
        return get_config(path, default)
    except Exception:
        return default


def _provider() -> tuple[str, Optional[str]]:
    """Return (provider, api_key)."""
    configured = (_cfg("SYSTEM_OPTIONS.WEB_SEARCH.PROVIDER", "") or "").strip().lower()
    key = (_cfg("SYSTEM_OPTIONS.WEB_SEARCH.API_KEY", "") or "").strip()
    if configured in ("brave", "tavily") and key:
        return configured, key
    if os.environ.get("BRAVE_API_KEY"):
        return "brave", os.environ["BRAVE_API_KEY"]
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily", os.environ["TAVILY_API_KEY"]
    return "mojeek", None


async def _mojeek(session: aiohttp.ClientSession, query: str, n: int) -> list[dict]:
    async with session.get(
        _MOJEEK, params={"q": query}, headers={"User-Agent": _UA}
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Mojeek returned HTTP {r.status}")
        html = await r.text()

    out: list[dict] = []
    for block in _RESULT.findall(html):
        url = _URL.search(block)
        title = _TITLE.search(block)
        snip = _SNIPPET.search(block)
        if not url:
            continue
        out.append(
            {
                "title": strip_tags(title.group(1)) if title else "",
                "url": url.group(1),
                "snippet": strip_tags(snip.group(1)) if snip else "",
            }
        )
        if len(out) >= n:
            break
    return out


async def _brave(
    session: aiohttp.ClientSession, query: str, n: int, key: str
) -> list[dict]:
    headers = {"X-Subscription-Token": key, "Accept": "application/json"}
    params = {"q": query, "count": min(n, 20)}
    async with session.get(_BRAVE, params=params, headers=headers) as r:
        if r.status != 200:
            raise RuntimeError(f"Brave returned HTTP {r.status}")
        data = await r.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": strip_tags(item.get("description", "")),
        }
        for item in (data.get("web", {}).get("results") or [])[:n]
    ]


async def _tavily(
    session: aiohttp.ClientSession, query: str, n: int, key: str
) -> list[dict]:
    body = {"api_key": key, "query": query, "max_results": min(n, 20)}
    async with session.post(_TAVILY, json=body) as r:
        if r.status != 200:
            raise RuntimeError(f"Tavily returned HTTP {r.status}")
        data = await r.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in (data.get("results") or [])[:n]
    ]


async def web_search_payload(args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "No query given."}, ensure_ascii=False)
    try:
        n = max(1, min(10, int(args.get("max_results", 5))))
    except (TypeError, ValueError):
        n = 5

    provider, key = _provider()
    logger.info(f"[WebSearch] {provider}: {query!r} (max {n})")
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            if provider == "brave":
                results = await _brave(session, query, n, key)
            elif provider == "tavily":
                results = await _tavily(session, query, n, key)
            else:
                results = await _mojeek(session, query, n)
    except Exception as e:
        logger.warning(f"[WebSearch] {provider} failed: {e}")
        return json.dumps(
            {"error": f"Search failed ({provider}): {e}"}, ensure_ascii=False
        )

    if not results:
        return json.dumps(
            {
                "query": query,
                "provider": provider,
                "results": [],
                "note": "No results found.",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"query": query, "provider": provider, "results": results},
        ensure_ascii=False,
    )
