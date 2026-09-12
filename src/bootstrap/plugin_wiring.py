"""Wiring up the plugins and the shared services.

One place for creating McpServer and MusicPlayer, registering the plugin list, hooking up the resource-pool cleanup, and wiring the direct audio path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.logging import get_logger

if TYPE_CHECKING:
    from src.bootstrap.container import ServiceContainer
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()


def bind_shared_services(container: "ServiceContainer") -> None:
    """Create the services the plugins share (McpServer, MusicPlayer); only the container holds them.

    Nothing is written to a module-level singleton; the plugins and MCP tools get the same instance by construction or closure.
    """
    from src.mcp.mcp_server import McpServer
    from src.mcp.tools.music.music_player import MusicPlayer

    if container.mcp_server is None:
        container.mcp_server = McpServer()

    if container.music_player is None:
        container.music_player = MusicPlayer()

    logger.debug("shared services created: McpServer, MusicPlayer")


def unbind_shared_services(container: "ServiceContainer") -> None:
    """Release the shared services (called in the last stage of the resource pool)."""
    if container.music_player is not None:
        try:
            container.music_player.detach()
        except Exception as e:
            logger.debug(f"failed to detach MusicPlayer: {e}", exc_info=True)
    if container.mcp_server is not None:
        try:
            container.mcp_server.detach()
        except Exception as e:
            logger.debug(f"failed to detach McpServer: {e}", exc_info=True)
    container.music_player = None
    container.mcp_server = None


async def setup_plugins(
    container: "ServiceContainer",
    mode: str,
    ctx: "PluginContext",
    cmd: "PluginCommands",
) -> None:
    """Bind the shared services, register and initialise the plugins, and hook up the cleanup and direct audio path."""
    from src.plugins.audio import AudioPlugin
    from src.plugins.mcp import McpPlugin
    from src.plugins.reminders import RemindersPlugin
    from src.plugins.shortcuts import ShortcutsPlugin
    from src.plugins.ui import UIPlugin
    from src.plugins.wake_word import WakeWordPlugin

    bind_shared_services(container)

    # create the plugins (Audio publishes the codec as an event rather than being handed MusicPlayer)
    audio_plugin = AudioPlugin()
    wake_word_plugin = WakeWordPlugin()
    ui_plugin = UIPlugin(mode=mode, task_manager=container.tasks)
    shortcuts_plugin = ShortcutsPlugin()
    reminders_plugin = RemindersPlugin()
    mcp_plugin = McpPlugin(
        server=container.mcp_server,
        music_player=container.music_player,
    )

    container.plugins.register(
        mcp_plugin,
        audio_plugin,
        wake_word_plugin,
        ui_plugin,
        shortcuts_plugin,
        reminders_plugin,
    )

    await container.plugins.setup_all(ctx, cmd)

    register_cleanup_resources(container)

    # wire the direct audio path (TTS audio skips the EventBus, which cuts latency)
    if not audio_plugin.failed:
        container.protocol.set_audio_handler(audio_plugin.on_incoming_audio)


def register_cleanup_resources(container: "ServiceContainer") -> None:
    """Register every module's cleanup with the resource pool (first registered is released last)."""
    pool = container.resource_pool

    # registered first means released last: the shared services unbind after the plugins clean up
    pool.register("shared_services", lambda: unbind_shared_services(container))

    # the event bus is released last but one
    pool.register("event_bus", container.event_bus.clear)

    # each plugin registers its own resources
    for plugin in container.plugins._plugins:
        plugin.register_resources(pool)

    # network connections
    pool.register("protocol", container.protocol.disconnect)

    # async tasks
    pool.register("tasks", container.tasks.cancel_all)
