"""Claude Code MCP tools: a deeper reasoning brain on the user's subscription.

The sandbox in runner.py is not configurable on purpose. These tools are driven
by speech through a third-party LLM, so a switch that removed the tool
restrictions would put a shell-capable agent behind the microphone on a machine
with passwordless sudo. Reasoning, analysis and explanation - which is what this
is for - need no write or shell access.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from . import runner

logger = get_logger()

# The synchronous path blocks a voice turn, so it gets a short leash regardless
# of the configured budget.
_SYNC_CAP = 45.0


def _cfg(path: str, default=None):
    try:
        from src.utils.config_manager import get_config

        return get_config().get_config(path, default)
    except Exception:
        return default


def _settings() -> tuple[float, str | None]:
    try:
        timeout = float(_cfg("CLAUDE_CODE.TIMEOUT_SECONDS", 120))
    except (TypeError, ValueError):
        timeout = 120.0
    model = (_cfg("CLAUDE_CODE.MODEL", "") or "").strip() or None
    return timeout, model


def _unavailable() -> str | None:
    if not bool(_cfg("CLAUDE_CODE.ENABLED", True)):
        return "Claude Code is disabled in settings."
    if not runner.available():
        return "The claude CLI is not installed on this machine."
    return None


async def ask_claude_payload(args: dict[str, Any]) -> str:
    question = str(args.get("question", "")).strip()
    if not question:
        return json.dumps({"error": "No question given."})
    if why := _unavailable():
        return json.dumps({"error": why})

    timeout, model = _settings()
    res = await runner.ask(question, timeout=min(timeout, _SYNC_CAP), model=model)
    if not res.get("ok"):
        return json.dumps({"error": res.get("error")})
    return json.dumps({"answer": res["text"]}, ensure_ascii=False)


async def _background(question: str, timeout: float, model: str | None) -> None:
    res = await runner.ask(question, timeout=timeout, model=model)
    if res.get("ok"):
        text = f"Here is what I found about {question}: {res['text']}"
    else:
        text = f"I could not finish looking into {question}: {res.get('error')}"
    try:
        from src.memory.store import get_memory

        # Due now, so the reminder scheduler announces it. That reuses the
        # existing guards: it will not speak into a closed channel or talk over
        # the user, and holds the answer until it can actually be heard.
        get_memory().add(
            text[:1500],
            kind="event",
            due_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source="claude_code",
        )
        logger.info("[ClaudeCode] background answer queued for announcement")
    except Exception as e:
        logger.warning(f"[ClaudeCode] could not queue the answer: {e}")


async def ask_claude_background_payload(args: dict[str, Any]) -> str:
    question = str(args.get("question", "")).strip()
    if not question:
        return json.dumps({"error": "No question given."})
    if why := _unavailable():
        return json.dumps({"error": why})

    timeout, model = _settings()
    asyncio.create_task(_background(question, timeout, model))
    return json.dumps(
        {
            "started": True,
            "note": "Tell the user you are looking into it and will speak up when you "
            "have the answer. Do not wait or call this again.",
        }
    )


def register_claude_code_tools(add_tool: Callable[[McpTool], None]) -> None:
    if not runner.available():
        logger.info("claude CLI not found; Claude Code tools not registered")
        return

    tools = [
        McpTool(
            "ask_claude",
            (
                "Ask Claude Code - a much stronger reasoning model running locally "
                "on the user's own subscription - a hard question. Use it for "
                "anything needing careful reasoning, analysis, planning, maths, "
                "code, or a detailed explanation you cannot answer well yourself. "
                "Takes 10-45 seconds, so tell the user you are thinking about it. "
                "For anything likely to take longer, use ask_claude_background "
                "instead. Args: question - a complete, self-contained question."
            ),
            PropertyList([Property("question", PropertyType.STRING, default_value="")]),
            ask_claude_payload,
        ),
        McpTool(
            "ask_claude_background",
            (
                "Same as ask_claude, but returns immediately and announces the "
                "answer out loud when it is ready. Use for research or anything "
                "that may take more than about 45 seconds, so the user is not left "
                "waiting in silence. Tell them you will report back. "
                "Args: question - a complete, self-contained question."
            ),
            PropertyList([Property("question", PropertyType.STRING, default_value="")]),
            ask_claude_background_payload,
        ),
    ]
    for t in tools:
        add_tool(t)
    logger.info("Registered %d Claude Code MCP tools", len(tools))
