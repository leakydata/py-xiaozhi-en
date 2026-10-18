"""The ambient_sounds tool: what the microphone has heard that is not speech."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.audio_processing.ambient_sounds import get_ambient
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

DESCRIPTION = (
    "What the microphone has picked up lately that is NOT speech: a keyboard, "
    "a dog, a kettle, running water, music from another room, a door, an "
    "alarm, someone coughing. It is how you know what is going on around the "
    "user besides what they say. Use it when they ask what you can hear or "
    "what that noise was, when something they say refers to a sound ('did "
    "you hear that?'), and before assuming it is quiet. Each sound has "
    "'going_on_now', how many times it occurred, how long ago it was last "
    "heard, and a confidence from 0 to 1. Treat it as a hint from a "
    "classifier, not a fact: under 0.5 say 'sounded like', and never invent "
    "a sound that is not listed. 'listened_fraction' is how much of the "
    "period the microphone was free to listen; it is low while you were "
    "speaking or music was playing, so a short list then means you could not "
    "hear, not that nothing happened. Speech is deliberately left out. "
    "'presence' says when someone was last audibly around (a voice, typing, "
    "footsteps, a cough...), so you can tell they are still there while they "
    "are not talking. It cannot say who, and silence is not absence: they may "
    "be reading. "
    "Args: minutes - how far back to look (default 10, up to 180)."
)


async def ambient_sounds_payload(args: dict[str, Any]) -> str:
    ambient = get_ambient()
    if ambient is None:
        return json.dumps(
            {
                "listening": False,
                "note": "Ambient sound awareness is switched off or its model "
                "is missing. Say you cannot hear the room rather than guess.",
            }
        )
    try:
        minutes = float(args.get("minutes", 10))
    except (TypeError, ValueError):
        minutes = 10.0
    minutes = max(0.5, min(180.0, minutes))
    return json.dumps(ambient.heard(minutes), ensure_ascii=False)


def register_ambient_tools(add_tool: Callable[[McpTool], None]) -> None:
    add_tool(
        McpTool(
            "ambient_sounds",
            DESCRIPTION,
            PropertyList(
                [
                    Property(
                        "minutes",
                        PropertyType.INTEGER,
                        default_value=10,
                        min_value=1,
                        max_value=180,
                    )
                ]
            ),
            ambient_sounds_payload,
        )
    )
