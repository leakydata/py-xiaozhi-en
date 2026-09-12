"""Registering the screenshot MCP tool, and the factory behind it."""

import asyncio
import json
from typing import Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .screenshot_camera import ScreenshotCamera

logger = get_logger()


def create_screenshot_camera() -> ScreenshotCamera:
    """Build the desktop screenshot implementation."""
    return ScreenshotCamera()


def register_screenshot_tools(
    add_tool: Callable[[McpTool], None],
    photo_camera=None,
) -> None:
    """Register take_screenshot.

    photo_camera: optional; reuses the explain URL and token when analysing (the same camera take_photo uses).
    """
    camera = create_screenshot_camera()
    if photo_camera is not None and hasattr(photo_camera, "get_explain_url"):
        # share the vision configuration with the photo tool, when one is set
        try:
            url = getattr(photo_camera, "explain_url", None) or getattr(
                photo_camera, "_explain_url", None
            )
            token = getattr(photo_camera, "explain_token", None) or getattr(
                photo_camera, "_explain_token", None
            )
            if url and hasattr(camera, "set_explain_url"):
                camera.set_explain_url(url)
            if token and hasattr(camera, "set_explain_token"):
                camera.set_explain_token(token)
        except Exception as e:
            logger.debug(
                f"failed to copy the vision configuration to the screenshot camera: {e}",
                exc_info=True,
            )

    # keep a reference so analyse can fall back to the photo camera's explain settings
    camera._photo_camera_ref = photo_camera  # type: ignore[attr-defined]

    async def take_screenshot(arguments: dict) -> str:
        logger.info(
            f"Using screenshot camera implementation: {camera.__class__.__name__}"
        )

        question = arguments.get("question", "")
        display_id = arguments.get("display", None)

        if display_id:
            if isinstance(display_id, str):
                # The aliases the model might reasonably pass for each screen.
                if display_id.lower() in [
                    "main",
                    "primary",
                    "built-in",
                    "builtin",
                    "internal",
                    "laptop",
                ]:
                    display_id = "main"
                elif display_id.lower() in [
                    "secondary",
                    "second",
                    "external",
                    "extended",
                    "monitor",
                ]:
                    display_id = "secondary"
                else:
                    try:
                        display_id = int(display_id)
                    except ValueError:
                        logger.warning(
                            f"Invalid display parameter: {display_id}, using default"
                        )
                        display_id = None

        logger.info(
            f"Taking screenshot with question: {question}, display: {display_id}"
        )

        success = await asyncio.to_thread(camera.capture, display_id)
        if not success:
            logger.error("Failed to capture screenshot")
            return json.dumps(
                {"success": False, "message": "Failed to capture screenshot"}
            )

        logger.info("Screenshot captured, starting analysis...")
        return await asyncio.to_thread(camera.analyze, question)

    add_tool(
        McpTool(
            "take_screenshot",
            (
                "[Screenshots and screen analysis] Use this when the user asks to take a screenshot, "
                "look at the desktop, analyse the screen, read what is on screen, or run OCR over it. "
                "It captures the whole desktop, describes and analyses what is on it, extracts text with "
                "OCR, examines interface elements, identifies applications, reads error dialogs, checks "
                "the state of the desktop, and handles multiple screens. "
                "Arguments: { question: 'what you want to know about the screen', display: 'which screen (optional)' }. "
                "display accepts 'main' (or primary/built-in/laptop), 'secondary' (or second/external/monitor), "
                "a screen number, or nothing at all for every screen. "
                "Good for diagnosing an interface problem, checking what an app is doing, or reading an error. "
                "Note: this captures the desktop, so make sure the user is happy for you to do that."
            ),
            PropertyList(
                [
                    Property("question", PropertyType.STRING),
                    Property("display", PropertyType.STRING, default_value=""),
                ]
            ),
            take_screenshot,
        )
    )
    logger.info("registered take_screenshot (no global singleton)")
