"""Hardware, telemetry and media MCP tool registration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from . import hardware, media

logger = get_logger()


def _err(e: Exception) -> str:
    return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


async def system_status_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(hardware.snapshot(), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def top_processes_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps({"processes": hardware.top_processes(
            int(args.get("limit", 8) or 8), str(args.get("sort_by", "cpu")))},
            ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def list_serial_ports_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps({"ports": hardware.list_ports()}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def serial_monitor_payload(args: dict[str, Any]) -> str:
    try:
        send = args.get("send")
        return json.dumps(await hardware.serial_io(
            str(args.get("port", "")),
            int(args.get("baud", 115200) or 115200),
            float(args.get("seconds", 3) or 3),
            str(send) if send else None,
        ), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def image_info_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(media.image_info(str(args.get("path", ""))),
                          ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def edit_image_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(media.image_edit(
            str(args.get("path", "")), str(args.get("output", "")),
            width=int(args.get("width", 0) or 0),
            height=int(args.get("height", 0) or 0),
            rotate=int(args.get("rotate", 0) or 0),
            grayscale=bool(args.get("grayscale", False)),
            crop=str(args.get("crop", "") or ""),
        ), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def media_info_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(await media.media_info(str(args.get("path", ""))),
                          ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def convert_media_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(await media.media_convert(
            str(args.get("path", "")), str(args.get("output", "")),
            start=str(args.get("start", "") or ""),
            duration=str(args.get("duration", "") or ""),
            audio_only=bool(args.get("audio_only", False)),
            scale_width=int(args.get("scale_width", 0) or 0),
        ), ensure_ascii=False)
    except Exception as e:
        return _err(e)


def register_lab_tools(add_tool: Callable[[McpTool], None]) -> None:
    tools: list[McpTool] = [
        McpTool(
            "system_status",
            (
                "Get a full snapshot of this computer right now: CPU load, memory, "
                "swap, disk space per mount, temperatures, fans, battery and boot "
                "time. Use this for 'how is the machine doing', 'is it running "
                "hot', 'am I running out of space'. Takes no arguments."
            ),
            PropertyList([]),
            system_status_payload,
        ),
        McpTool(
            "top_processes",
            (
                "List the processes using the most CPU or memory. "
                "Args: limit - how many (1-25); sort_by - 'cpu' or 'memory'."
            ),
            PropertyList([
                Property("limit", PropertyType.INTEGER, default_value=8,
                         min_value=1, max_value=25),
                Property("sort_by", PropertyType.STRING, default_value="cpu"),
            ]),
            top_processes_payload,
        ),
        McpTool(
            "list_serial_ports",
            (
                "List USB serial ports, for talking to a microcontroller such as an "
                "ESP32 or Arduino. Call this before serial_monitor to find the port "
                "name. Takes no arguments."
            ),
            PropertyList([]),
            list_serial_ports_payload,
        ),
        McpTool(
            "serial_monitor",
            (
                "Read from a USB serial port for a few seconds, optionally sending a "
                "line first. Use it to see what a board is printing, or to send it a "
                "command and read the reply. "
                "Args: port - e.g. '/dev/ttyACM0'; baud - usually 115200; seconds - "
                "how long to listen (0.2-20); send - an optional line to transmit."
            ),
            PropertyList([
                Property("port", PropertyType.STRING, default_value=""),
                Property("baud", PropertyType.INTEGER, default_value=115200,
                         min_value=300, max_value=2000000),
                Property("seconds", PropertyType.INTEGER, default_value=3,
                         min_value=1, max_value=20),
                Property("send", PropertyType.STRING, default_value=""),
            ]),
            serial_monitor_payload,
        ),
        McpTool(
            "image_info",
            "Get the size, format and dimensions of an image in the workspace. "
            "Args: path.",
            PropertyList([Property("path", PropertyType.STRING, default_value="")]),
            image_info_payload,
        ),
        McpTool(
            "edit_image",
            (
                "Resize, crop, rotate or greyscale an image in the workspace and save "
                "the result. Give width OR height to scale proportionally. "
                "Args: path - source; output - where to save; width; height; rotate - "
                "degrees clockwise; grayscale; crop - 'left,top,right,bottom' pixels."
            ),
            PropertyList([
                Property("path", PropertyType.STRING, default_value=""),
                Property("output", PropertyType.STRING, default_value=""),
                Property("width", PropertyType.INTEGER, default_value=0,
                         min_value=0, max_value=20000),
                Property("height", PropertyType.INTEGER, default_value=0,
                         min_value=0, max_value=20000),
                Property("rotate", PropertyType.INTEGER, default_value=0,
                         min_value=-360, max_value=360),
                Property("grayscale", PropertyType.BOOLEAN, default_value=False),
                Property("crop", PropertyType.STRING, default_value=""),
            ]),
            edit_image_payload,
        ),
        McpTool(
            "media_info",
            "Get duration, codecs, resolution and bitrate of an audio or video file "
            "in the workspace. Args: path.",
            PropertyList([Property("path", PropertyType.STRING, default_value="")]),
            media_info_payload,
        ),
        McpTool(
            "convert_media",
            (
                "Convert, trim or downscale audio and video in the workspace using "
                "ffmpeg. The output extension decides the format (.mp3, .wav, .mp4). "
                "Args: path - source; output - destination; start - trim start like "
                "'00:01:30'; duration - how long to keep like '30'; audio_only - "
                "strip the video; scale_width - resize video to this width."
            ),
            PropertyList([
                Property("path", PropertyType.STRING, default_value=""),
                Property("output", PropertyType.STRING, default_value=""),
                Property("start", PropertyType.STRING, default_value=""),
                Property("duration", PropertyType.STRING, default_value=""),
                Property("audio_only", PropertyType.BOOLEAN, default_value=False),
                Property("scale_width", PropertyType.INTEGER, default_value=0,
                         min_value=0, max_value=7680),
            ]),
            convert_media_payload,
        ),
    ]

    for t in tools:
        add_tool(t)
    logger.info("Registered %d hardware/media MCP tools", len(tools))
