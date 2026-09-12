"""The volume MCP tools. register_volume_tools injects the VolumeController; there is no module-level singleton."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .volume_controller import VolumeController

logger = get_logger()


def create_volume_controller() -> VolumeController | None:
    """Build the volume controller; None when a dependency is missing or it fails to start."""
    if not VolumeController.check_dependencies():
        return None
    try:
        return VolumeController()
    except Exception as e:
        logger.error(f"the volume controller failed to initialise: {e}", exc_info=True)
        return None


def register_volume_tools(
    add_tool: Callable[[McpTool], None],
    controller: VolumeController | None = None,
) -> None:
    """Register the volume tools with McpServer (the closures hold the controller; nothing global is written).

    When controller is None this tries create_volume_controller(). If that fails too, the tools
    are still registered but report that volume control is unavailable, so they never vanish from the list.
    """
    if controller is None:
        controller = create_volume_controller()

    async def set_volume(args: dict[str, Any]) -> bool:
        try:
            volume = args["volume"]
            logger.info(f"[VolumeTools] setting the volume to {volume}")
            if not (0 <= volume <= 100):
                logger.warning(f"[VolumeTools] volume out of range: {volume}")
                return False
            if controller is None:
                logger.warning(
                    "[VolumeTools] volume control is unavailable, cannot set the volume"
                )
                return False
            await asyncio.to_thread(controller.set_volume, volume)
            logger.info(f"[VolumeTools] volume set: {volume}")
            return True
        except KeyError:
            logger.error("[VolumeTools] the volume argument is missing")
            return False
        except Exception as e:
            logger.error(f"[VolumeTools] failed to set the volume: {e}", exc_info=True)
            return False

    async def get_volume(args: dict[str, Any]) -> int:
        try:
            logger.info("[VolumeTools] reading the current volume")
            if controller is None:
                logger.warning(
                    "[VolumeTools] volume control is unavailable, returning the default"
                )
                return VolumeController.DEFAULT_VOLUME
            current = await asyncio.to_thread(controller.get_volume)
            logger.info(f"[VolumeTools] current volume: {current}")
            return current
        except Exception as e:
            logger.error(f"[VolumeTools] failed to read the volume: {e}", exc_info=True)
            return VolumeController.DEFAULT_VOLUME

    async def get_volume_status(args: dict[str, Any]) -> str:
        try:
            if controller is not None:
                current = await asyncio.to_thread(controller.get_volume)
                status = {
                    "volume": current,
                    "muted": current == 0,
                    "available": True,
                }
            else:
                status = {
                    "volume": 50,
                    "muted": False,
                    "available": False,
                    "reason": "Dependencies not available",
                }
        except Exception as e:
            logger.warning(
                f"[VolumeTools] failed to read the volume status: {e}", exc_info=True
            )
            status = {
                "volume": 50,
                "muted": False,
                "available": False,
                "error": str(e),
            }
        return json.dumps(status, ensure_ascii=False)

    tools: list[McpTool] = [
        McpTool(
            "self.audio_speaker.set_volume",
            (
                "Set the system speaker volume to an absolute value (0-100).\n"
                "Use when user mentions: volume, sound, louder, quieter, mute, unmute, adjust volume.\n"
                "Examples: 'set volume to 50', 'turn volume up', 'make it louder', 'mute', "
                "'quieter', 'turn it down a bit', 'unmute'.\n"
                "Parameter:\n"
                "- volume: Integer (0-100) representing the target volume level. Set to 0 for mute."
            ),
            PropertyList(
                [Property("volume", PropertyType.INTEGER, min_value=0, max_value=100)]
            ),
            set_volume,
        ),
        McpTool(
            "self.audio_speaker.get_volume",
            (
                "Get the current system speaker volume level.\n"
                "Use when user asks about: current volume, volume level, how loud, what's the volume.\n"
                "Examples: 'what is the current volume?', 'how loud is it?', 'check volume level', "
                "'where is the volume set?'.\n"
                "Returns: Integer (0-100) representing the current volume level."
            ),
            PropertyList(),
            get_volume,
        ),
        McpTool(
            "self.audio_speaker.get_volume_status",
            (
                "Get detailed speaker volume status including whether audio output is muted and "
                "whether the volume controller dependencies are available. Returns a JSON payload "
                "with fields: volume (0-100), muted (bool), available (bool), reason/error(optional)."
            ),
            PropertyList(),
            get_volume_status,
        ),
    ]

    for tool in tools:
        add_tool(tool)
    logger.info(
        "registered %d volume MCP tools (VolumeController injected, available=%s)",
        len(tools),
        controller is not None,
    )
