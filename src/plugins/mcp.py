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

        await self._connect_mcp_clients(ctx)

        try:
            self._music_player.set_event_bus(ctx.event_bus, ctx)
            logger.info("MusicPlayer EventBus injected")
        except Exception as e:
            logger.warning(
                f"failed to set the MusicPlayer EventBus: {e}", exc_info=True
            )

    async def _connect_mcp_clients(self, ctx: "PluginContext") -> None:
        """Dial the other MCP servers, without letting them delay startup.

        Their tools have to be registered before the backend asks for the tool
        list, so this is awaited - but only up to a budget. A server that hangs
        would otherwise hold the whole assistant in setup. If the budget runs
        out the work carries on in the background, and whatever lands late asks
        the protocol to reconnect so the backend re-reads the list.
        """
        import asyncio

        try:
            from src.utils.config_manager import get_config

            config = get_config()
            if not config.get_config("MCP_CLIENT.ENABLED", True):
                return
            budget = float(config.get_config("MCP_CLIENT.STARTUP_TIMEOUT", 25))
        except Exception:
            budget = 25.0

        task = asyncio.ensure_future(self._server.connect_mcp_clients())
        try:
            count = await asyncio.wait_for(asyncio.shield(task), timeout=budget)
            if count:
                logger.info(f"MCP client: {count} tools from other servers")
        except asyncio.TimeoutError:
            logger.warning(
                f"MCP client: still connecting after {budget:.0f}s - carrying on, "
                "and their tools will appear once they land"
            )
            task.add_done_callback(lambda t: self._on_late_tools(t, ctx))
        except Exception as e:
            logger.warning(f"MCP client: could not connect: {e}", exc_info=True)

    def _on_late_tools(self, task, ctx: "PluginContext") -> None:
        """A server that finished after the budget: re-list the tools."""
        try:
            count = task.result()
        except Exception as e:
            logger.warning(f"MCP client: connecting failed in the end: {e}")
            return
        if not count:
            return
        logger.info(f"MCP client: {count} tools arrived late, asking for a re-list")
        try:
            import asyncio

            from src.core.event_bus import Events

            # This runs on the loop thread as a done callback, so the emit has
            # to be scheduled rather than awaited.
            asyncio.ensure_future(ctx.event_bus.emit(Events.PROTOCOL_RECONNECT_REQUEST))
        except Exception as e:
            logger.debug(f"could not request a protocol reconnect: {e}")

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
                # Ends the stdio child processes. Without this every restart
                # would leave another server running.
                await self._server.close_mcp_clients()
            except Exception as e:
                logger.debug(f"closing the MCP clients failed: {e}", exc_info=True)

            try:
                self._server.detach()
            except Exception as e:
                logger.debug(f"MCP shutdown cleanup failed: {e}", exc_info=True)

        pool.register("mcp.server", _mcp_cleanup)
