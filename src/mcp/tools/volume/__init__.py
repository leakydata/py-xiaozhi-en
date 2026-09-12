"""The volume tools.

- VolumeController and the per-platform backends: see volume_controller and windows|macos|linux
- register_volume_tools: registers them with McpServer, the closures holding the controller - no module singleton
"""

from .register import create_volume_controller, register_volume_tools
from .volume_controller import VolumeController

__all__ = [
    "VolumeController",
    "create_volume_controller",
    "register_volume_tools",
]
