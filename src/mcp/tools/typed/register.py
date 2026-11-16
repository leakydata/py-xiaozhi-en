"""typed_message: hand over what the user typed in the app's chat box."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.core import typed_messages
from src.mcp.tooling import McpTool, PropertyList

DESCRIPTION = (
    "What the user typed in the app's chat box, which is too long to send to you "
    "directly. Call it when you hear the cue 'read typed message', then answer "
    "what they wrote exactly as if they had said it aloud. Returns the waiting "
    "messages, oldest first."
)


async def typed_message_payload(args: dict[str, Any]) -> str:
    texts = typed_messages.take_all()
    if not texts:
        return json.dumps(
            {
                "messages": [],
                "note": "Nothing is waiting; they may have sent it already.",
            }
        )
    return json.dumps(
        {
            "messages": texts,
            "note": "The user typed this. Answer it as you would speech.",
        },
        ensure_ascii=False,
    )


def register_typed_tools(add_tool: Callable[[McpTool], None]) -> None:
    add_tool(
        McpTool("typed_message", DESCRIPTION, PropertyList([]), typed_message_payload)
    )
