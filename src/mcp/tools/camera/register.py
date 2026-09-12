"""Registering the camera MCP tool, and the factory behind it."""

import asyncio
import json
from collections.abc import Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType
from src.utils.config_manager import get_config

from .normal_camera import NormalCamera
from .vl_camera import VLCamera

logger = get_logger()


def create_camera():
    """
    Build the camera implementation the configuration asks for.
    """
    config = get_config()

    vl_key = config.get_config("CAMERA.VLapi_key")
    vl_url = config.get_config("CAMERA.Local_VL_url")

    if vl_key and vl_url:
        logger.info(f"Initializing VL Camera with URL: {vl_url}")
        return VLCamera()

    logger.info("VL configuration not found, using normal Camera implementation")
    return NormalCamera()


def register_camera_tools(add_tool: Callable[[McpTool], None], camera) -> None:
    async def take_photo(arguments: dict) -> str:
        logger.info(f"Using camera implementation: {camera.__class__.__name__}")
        question = arguments.get("question", "")
        logger.info(f"Taking photo with question: {question}")

        success = await asyncio.to_thread(camera.capture)
        if not success:
            logger.error("Failed to capture photo")
            return json.dumps({"success": False, "message": "Failed to capture photo"})

        logger.info("Photo captured, starting analysis...")
        return await asyncio.to_thread(camera.analyze, question)

    add_tool(
        McpTool(
            "take_photo",
            (
                "[Take a photo and describe it] Use this whenever the user asks you to "
                "look at something, take a photo, identify what something is, read what a "
                "label says, or answer a question about what is in front of the camera.\n"
                "It captures a still from the camera and analyses it.\n"
                "What it is good for:\n"
                "1. Looking at something on request ('what is this?', 'take a photo', "
                "'have a look at what is in front of me')\n"
                "2. Identifying an object or a scene ('what am I holding?', 'what is that')\n"
                "3. Reading text off a thing (OCR) ('read the label', 'what does this say')\n"
                "4. Answering a question about the picture ('how many people are there?', "
                "'what colour is it?')\n\n"
                "Argument:\n"
                "- question: what the user wants to know about the picture\n\n"
                "Note: when the user says something vague like 'look' or 'what is this', "
                "reach for this tool rather than guessing.\n"
                "Returns: a JSON object describing the photo."
            ),
            PropertyList([Property("question", PropertyType.STRING)]),
            take_photo,
        )
    )
    logger.info("registered take_photo (camera injected by the container)")
