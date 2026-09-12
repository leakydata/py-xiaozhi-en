"""Screenshot tools for MCP.

The caller creates and injects the screenshot instance.
"""

from .register import create_screenshot_camera, register_screenshot_tools

__all__ = [
    "create_screenshot_camera",
    "register_screenshot_tools",
]
