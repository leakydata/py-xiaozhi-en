"""Let the assistant learn its own "mm-hm", by voice.

The murmurs it makes while the user talks have to be in its own voice, and the
only place that voice exists is the server's speech. So the assistant is asked
to say them: this tool starts recording and tells it what to say, and the
turn-taking plugin keeps each filler sentence as a clip.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.mcp.tooling import McpTool, PropertyList


def register_conversation_tools(add_tool: Callable) -> None:
    from src.audio_processing.backchannel import SCRIPT, describe, get_store

    async def learn_listening_sounds(args: dict[str, Any]) -> str:
        get_store().arm(60.0)
        return (
            "Recording now. Reply with exactly this and nothing else, each as "
            f"its own sentence, in a calm, quiet listening tone: {SCRIPT} "
            f"(Already learned: {describe()}.)"
        )

    add_tool(
        McpTool(
            "learn_listening_sounds",
            "Record your own 'mm-hm', 'uh-huh', 'yeah' and so on, in your own "
            "voice, so you can murmur them while the user is talking to show you "
            "are listening. Call it when the user asks you to learn or redo your "
            "listening sounds, then say exactly what it tells you to.",
            PropertyList(),
            learn_listening_sounds,
        )
    )
