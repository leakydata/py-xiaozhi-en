"""The MCP plugin.

Owns the MCP tools and message handling. The container must inject McpServer and MusicPlayer.
"""

from typing import TYPE_CHECKING, Any, Optional

from src.logging import get_logger
from src.mcp.mcp_server import McpServer
from src.plugins.base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext
    from src.mcp.tools.music.music_player import MusicPlayer

logger = get_logger()


class McpPlugin(Plugin):
    name = "mcp"
    priority = 20  # it registers the tools, so it needs to start early

    def __init__(
        self,
        server: Optional[McpServer] = None,
        music_player: Optional["MusicPlayer"] = None,
    ) -> None:
        super().__init__()
        if server is None:
            raise ValueError("McpPlugin needs an McpServer injected by the container")
        if music_player is None:
            raise ValueError("McpPlugin needs a MusicPlayer injected by the container")
        self._server: McpServer = server
        self._music_player = music_player

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        await super().setup(ctx, cmd)
        server = self._server

        async def _send(msg: str):
            try:
                await cmd.send_mcp_message(msg)
            except Exception as e:
                logger.error(f"MCP failed to send the response: {e}", exc_info=True)

        try:
            server.set_send_callback(_send)
            # the camera: created once, lazily, and hung off the server so the vision config and take_photo share it
            from src.mcp.tools.camera import create_camera, register_camera_tools
            from src.mcp.tools.screenshot import register_screenshot_tools

            camera = create_camera()
            server.set_camera(camera)
            register_camera_tools(server.add_tool, camera)
            register_screenshot_tools(server.add_tool, camera)

            server.add_common_tools(music_player=self._music_player)
        except Exception as e:
            logger.error(f"MCP tool registration failed: {e}", exc_info=True)

        try:
            self._music_player.set_event_bus(ctx.event_bus, ctx)
            logger.info("MusicPlayer EventBus injected")
        except Exception as e:
            logger.warning(
                f"failed to set the MusicPlayer EventBus: {e}", exc_info=True
            )

    async def on_incoming_json(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        try:
            if message.get("type") == "mcp":
                payload = message.get("payload")
                if not payload:
                    return
                await self._server.parse_message(payload)
        except Exception as e:
            logger.error(f"MCP message handling failed: {e}", exc_info=True)

    def register_resources(self, pool) -> None:
        async def _mcp_cleanup():
            try:
                music_player = self._music_player
                if music_player.is_playing:
                    await music_player.stop()
                music_player.detach()
            except Exception as e:
                logger.debug(
                    f"failed to stop or detach the music player: {e}", exc_info=True
                )

            try:
                self._server.detach()
            except Exception as e:
                logger.debug(f"MCP shutdown cleanup failed: {e}", exc_info=True)

        pool.register("mcp.server", _mcp_cleanup)
