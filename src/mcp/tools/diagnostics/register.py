"""Diagnostics tool registration: app_health and read_logs."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from . import logs

logger = get_logger()

_HEALTH = (
    "A summary of how this app has been behaving, from its own log: errors, "
    "warnings, what the xiaozhi server said (alerts and errors), how often the "
    "connection dropped and who ended it, how many times you were interrupted "
    "and why, audio underflows, wake word detections, and when the app last "
    "started. START HERE whenever the user says something is not working, you "
    "cut out, went idle, did not hear them, or you suspect a problem of your "
    "own - before guessing and before asking them to describe it. Then use "
    "read_logs to look at the lines behind anything it flags. Read it and "
    "explain in plain speech what is wrong and what would help; never read "
    "counts or JSON aloud. Args: minutes - how far back (default 60, up to "
    "1440)."
)

_READ = (
    "Read lines from this app's own log, newest last, filtered and shortened "
    "(secrets are hidden). Use it after app_health points at something, or to "
    "answer 'what just happened'. Args: minutes - how far back (default 15); "
    "level - debug, info, warning or error (default warning; use info for "
    "state changes, interruptions and connection events, debug only for a "
    "narrow window); contains - only lines containing this text, e.g. "
    "'interrupted', 'server alert', 'wake word'; logger - only from modules "
    "whose name contains this, e.g. 'turn_taking', 'websocket', 'ambient'; "
    "max_lines - how many (default 40). If the result says older matches were "
    "left out, narrow the window or add a filter instead of repeating the "
    "call."
)


def _lines():
    return logs.read_tail(logs.log_path())


async def app_health_payload(args: dict[str, Any]) -> str:
    try:
        minutes = max(1.0, min(1440.0, float(args.get("minutes", 60) or 60)))
    except (TypeError, ValueError):
        minutes = 60.0
    try:
        return json.dumps(logs.summarise(_lines(), minutes), ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[Diagnostics] app_health failed: {e}")
        return json.dumps({"error": f"Could not read the log: {e}"})


async def read_logs_payload(args: dict[str, Any]) -> str:
    try:
        minutes = max(1.0, min(1440.0, float(args.get("minutes", 15) or 15)))
    except (TypeError, ValueError):
        minutes = 15.0
    try:
        max_lines = int(args.get("max_lines", 40) or 40)
    except (TypeError, ValueError):
        max_lines = 40
    try:
        found = logs.select(
            logs.window(_lines(), minutes),
            level=str(args.get("level", "warning") or "warning"),
            contains=str(args.get("contains", "") or ""),
            logger=str(args.get("logger", "") or ""),
            max_lines=max_lines,
        )
        found["window_minutes"] = minutes
        if not found["lines"]:
            found["note"] = found.get(
                "note",
                "Nothing matched. Try a longer window, a lower level, or no filter.",
            )
        return json.dumps(found, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[Diagnostics] read_logs failed: {e}")
        return json.dumps({"error": f"Could not read the log: {e}"})


def register_diagnostics_tools(add_tool: Callable[[McpTool], None]) -> None:
    add_tool(
        McpTool(
            "app_health",
            _HEALTH,
            PropertyList(
                [
                    Property(
                        "minutes",
                        PropertyType.INTEGER,
                        default_value=60,
                        min_value=1,
                        max_value=1440,
                    )
                ]
            ),
            app_health_payload,
        )
    )
    add_tool(
        McpTool(
            "read_logs",
            _READ,
            PropertyList(
                [
                    Property(
                        "minutes",
                        PropertyType.INTEGER,
                        default_value=15,
                        min_value=1,
                        max_value=1440,
                    ),
                    Property("level", PropertyType.STRING, default_value="warning"),
                    Property("contains", PropertyType.STRING, default_value=""),
                    Property("logger", PropertyType.STRING, default_value=""),
                    Property(
                        "max_lines",
                        PropertyType.INTEGER,
                        default_value=40,
                        min_value=5,
                        max_value=160,
                    ),
                ]
            ),
            read_logs_payload,
        )
    )
