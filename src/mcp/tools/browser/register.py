"""browser_tabs: the titles of the tabs open in the user's browsers.

KDE's Plasma Browser Integration extension (installed in Chrome here) lets
KRunner search open tabs over D-Bus. That search matches a title or address
containing the query and needs at least one character, so listing every tab
means searching each letter and digit and merging the results by tab id.
Listing is read-only and returns titles, not addresses. Acting is limited to
two things: opening an http(s) address in the default browser (xdg-open) and
bringing an existing tab to the front (the same D-Bus runner's Run call).
Nothing here can read a page, type into one, or close a tab.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import string
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

logger = get_logger()

_SERVICE = "org.kde.plasma.browser_integration"

DESCRIPTION = (
    "The titles of the tabs open in the user's web browsers (mostly Chrome), "
    "with which browser each is in. Use it when they ask what tabs or pages "
    "they have open, what they were reading, or to find the tab about "
    "something. Titles only: no addresses, no page contents, and it cannot "
    "tell which tab is in front (take_screenshot shows that). To read a page, "
    "ask the user for it or search the web. "
    "Args: contains - optional text; only tabs whose title contains it."
)


def _match(char: str) -> list[list]:
    r = subprocess.run(
        [
            "busctl",
            "--user",
            "--json=short",
            "call",
            _SERVICE,
            "/TabsRunner",
            "org.kde.krunner1",
            "Match",
            "s",
            char,
        ],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if r.returncode != 0:
        return []
    return json.loads(r.stdout)["data"][0]


def list_tabs() -> dict[str, Any]:
    """Every open tab as {"title", "browser"}, or an explanation if it cannot."""
    if not shutil.which("busctl"):
        return {
            "tabs": [],
            "note": "busctl is not installed, so tabs cannot be listed.",
        }
    tabs: dict[str, dict[str, str]] = {}
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for rows in pool.map(_match, string.ascii_lowercase + string.digits):
                for row in rows:
                    tabs[str(row[0])] = {"title": row[1], "browser": row[2]}
    except Exception as e:
        logger.debug(f"browser_tabs: {e}", exc_info=True)
        return {
            "tabs": [],
            "note": "Could not reach the browser extension. It needs the Plasma "
            "Browser Integration extension in the browser, and the browser open.",
        }
    if not tabs:
        return {
            "tabs": [],
            "note": "No tabs found: the browser may be closed, or lacks the "
            "Plasma Browser Integration extension.",
        }
    return {"tabs": list(tabs.values())}


def filter_tabs(result: dict[str, Any], contains: str) -> dict[str, Any]:
    contains = (contains or "").strip().lower()
    tabs = result.get("tabs", [])
    if contains:
        tabs = [t for t in tabs if contains in t["title"].lower()]
    out = dict(result)
    out["tabs"] = tabs
    out["count"] = len(tabs)
    return out


async def browser_tabs_payload(args: dict[str, Any]) -> str:
    result = await asyncio.to_thread(list_tabs)
    return json.dumps(filter_tabs(result, args.get("contains", "")), ensure_ascii=False)


def _find(contains: str) -> list[tuple[str, dict[str, str]]]:
    """(tab id, tab) pairs whose title contains the text."""
    contains = contains.strip().lower()
    found: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rows in pool.map(_match, string.ascii_lowercase + string.digits):
            for row in rows:
                found[str(row[0])] = {"title": row[1], "browser": row[2]}
    return [(i, t) for i, t in found.items() if contains in t["title"].lower()]


def switch_to_tab(contains: str) -> dict[str, Any]:
    if not contains.strip():
        return {"switched": False, "note": "Say which tab, by a word from its title."}
    try:
        hits = _find(contains)
    except Exception:
        return {"switched": False, "note": "Could not reach the browser extension."}
    if not hits:
        return {
            "switched": False,
            "note": f"No open tab has {contains!r} in its title.",
        }
    if len(hits) > 1:
        return {
            "switched": False,
            "note": "More than one tab matches; ask which, or use a longer part of the title.",
            "matches": [t["title"] for _, t in hits[:8]],
        }
    tab_id, tab = hits[0]
    r = subprocess.run(
        [
            "busctl",
            "--user",
            "call",
            _SERVICE,
            "/TabsRunner",
            "org.kde.krunner1",
            "Run",
            "ss",
            tab_id,
            "",
        ],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if r.returncode != 0:
        return {"switched": False, "note": "The browser did not accept the request."}
    return {"switched": True, "title": tab["title"]}


def open_address(url: str) -> dict[str, Any]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "opened": False,
            "note": "Only full http or https addresses can be opened.",
        }
    try:
        subprocess.Popen(
            ["xdg-open", url.strip()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return {"opened": False, "note": f"Could not open it: {e}"}
    return {"opened": True, "url": url.strip()}


async def switch_payload(args: dict[str, Any]) -> str:
    return json.dumps(
        await asyncio.to_thread(switch_to_tab, str(args.get("contains", ""))),
        ensure_ascii=False,
    )


async def open_payload(args: dict[str, Any]) -> str:
    return json.dumps(await asyncio.to_thread(open_address, str(args.get("url", ""))))


def register_browser_tools(add_tool: Callable[[McpTool], None]) -> None:
    add_tool(
        McpTool(
            "browser_tabs",
            DESCRIPTION,
            PropertyList([Property("contains", PropertyType.STRING, default_value="")]),
            browser_tabs_payload,
        )
    )
    add_tool(
        McpTool(
            "browser_switch_tab",
            "Bring an already-open browser tab to the front, found by a word from its "
            "title (see browser_tabs). If several match it lists them instead; ask "
            "which. Args: contains - part of the tab's title.",
            PropertyList([Property("contains", PropertyType.STRING)]),
            switch_payload,
        )
    )
    add_tool(
        McpTool(
            "browser_open",
            "Open a web address in a new tab of the user's default browser. Only "
            "full http/https addresses. Use it when they ask to open or pull up a "
            "site; for facts you need yourself, use web search instead. "
            "Args: url - the full address.",
            PropertyList([Property("url", PropertyType.STRING)]),
            open_payload,
        )
    )
