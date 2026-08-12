"""Fetch a web page and return readable text.

The URL comes from an LLM, so it is treated as untrusted input: only http(s),
no private/loopback/link-local addresses (blocks router admin pages and cloud
metadata endpoints), a capped body size and a bounded redirect chain.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import aiohttp

from src.logging import get_logger

from .htmltext import html_to_text

logger = get_logger()

_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_BYTES = 2_000_000
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TEXTUAL = ("text/html", "text/plain", "application/xhtml", "application/xml", "text/")


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _is_public(host: str) -> tuple[bool, str]:
    """Resolve host and require every address to be public."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return False, f"could not resolve host: {e}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, f"unparseable address {addr!r}"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"refusing non-public address {addr}"
    return True, ""


def _check(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"only http/https are allowed, got {parsed.scheme!r}"
    if not parsed.hostname:
        return False, "URL has no host"
    return _is_public(parsed.hostname)


async def fetch_page_payload(args: dict[str, Any]) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return _err("No URL given.")
    if "://" not in url:
        url = "https://" + url
    try:
        max_length = max(200, min(20000, int(args.get("max_length", 8000))))
    except (TypeError, ValueError):
        max_length = 8000

    ok, why = _check(url)
    if not ok:
        logger.warning(f"[WebReader] blocked {url!r}: {why}")
        return _err(f"Refusing to fetch this URL ({why}).")

    logger.info(f"[WebReader] fetching {url}")
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                url, headers={"User-Agent": _UA}, max_redirects=5, allow_redirects=True
            ) as r:
                # a redirect can land somewhere private, so re-check the final URL
                final = str(r.url)
                ok, why = _check(final)
                if not ok:
                    logger.warning(f"[WebReader] blocked redirect to {final!r}: {why}")
                    return _err(f"Refusing to follow this redirect ({why}).")
                if r.status != 200:
                    return _err(f"HTTP {r.status} from {final}")
                ctype = (r.headers.get("Content-Type") or "").lower()
                if ctype and not any(t in ctype for t in _TEXTUAL):
                    return _err(f"Not a readable text page (Content-Type: {ctype}).")
                # content.read(n) returns only what is buffered (often the
                # first chunk), so accumulate until EOF or the cap.
                chunks, total = [], 0
                async for chunk in r.content.iter_chunked(65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= _MAX_BYTES:
                        break
                raw = b"".join(chunks)
    except Exception as e:
        logger.warning(f"[WebReader] fetch failed: {e}")
        return _err(f"Could not fetch the page: {e}")

    try:
        html = raw.decode("utf-8", errors="replace")
    except Exception:
        html = str(raw)

    title, text = html_to_text(html)
    truncated = len(text) > max_length
    return json.dumps(
        {
            "url": final,
            "title": title,
            "text": text[:max_length],
            "truncated": truncated,
        },
        ensure_ascii=False,
    )
