"""The service container.

It pulls the core services together and coordinates the application. The session, health gates, assembly and adapters live in submodules.
"""

from src.bootstrap.adapters import PluginCommandsAdapter, PluginContextAdapter
from src.bootstrap.health import (
    DEGRADED_AUDIO_NOTICE,
    audio_is_fatal,
    check_critical_plugins,
)
from src.bootstrap.plugin_wiring import setup_plugins
from src.bootstrap.protocols import PluginCommands, PluginContext
from src.bootstrap.session import ConversationSession
from src.core.event_bus import EventBus, Events
from src.core.protocol_manager import ProtocolManager
from src.core.resource_pool import ResourcePool
from src.core.state_manager import StateManager
from src.core.task_manager import TaskManager
from src.logging import get_logger
from src.plugins.manager import PluginManager
from src.utils.config_manager import get_config

logger = get_logger()


class ServiceContainer:
    """The service container.

    Owns the core services and the ConversationSession, and drives the run/shutdown lifecycle.
    Session actions go through ``self.session``; the health gates live in the ``health`` module.
    """

    def __init__(self):
        logger.debug("initialising ServiceContainer")

        self.config = get_config()

        try:
            aec_enabled = bool(self.config.get_config("AEC_OPTIONS.ENABLED", True))
        except Exception:
            aec_enabled = True

        self.event_bus = EventBus()
        self.state = StateManager(self.event_bus, aec_enabled=aec_enabled)
        self.tasks = TaskManager()
        # the protocol's inbound tasks go through the TaskManager, so nothing is fire-and-forget
        self.protocol = ProtocolManager(self.event_bus, task_manager=self.tasks)
        self.plugins = PluginManager()
        self.resource_pool = ResourcePool()

        # the shared services the container holds for the plugins (bound at startup, unbound at shutdown)
        self.mcp_server = None
        self.music_player = None

        # session control (listening, speaking, interrupting, the TTS loop)
        self.session = ConversationSession(
            state=self.state,
            protocol=self.protocol,
            plugins=self.plugins,
            event_bus=self.event_bus,
        )

        self._plugin_context: PluginContextAdapter | None = None
        self._plugin_commands: PluginCommandsAdapter | None = None

        self._mode: str = "cli"
        self._shutting_down = False
        # running with audio degraded (XIAOZHI_DEGRADED_AUDIO=1 and the audio plugin failed)
        self._degraded_audio = False

    # -------------------------
    # building the adapters
    # -------------------------
    def create_plugin_context(self) -> PluginContext:
        if not self._plugin_context:
            self._plugin_context = PluginContextAdapter(self)
        return self._plugin_context

    def create_plugin_commands(self) -> PluginCommands:
        if not self._plugin_commands:
            self._plugin_commands = PluginCommandsAdapter(self)
        return self._plugin_commands

    # -------------------------
    # lifecycle
    # -------------------------
    async def run(self, *, protocol: str = "websocket", mode: str = "gui") -> int:
        logger.info(f"starting ServiceContainer, protocol={protocol}, mode={mode}")
        self._mode = mode

        try:
            self.tasks.initialize()
            self.protocol.set_task_manager(self.tasks)
            self.protocol.set_protocol(protocol)

            self.session.bind_events(self.event_bus)

            ctx = self.create_plugin_context()
            cmd = self.create_plugin_commands()

            await setup_plugins(self, mode, ctx, cmd)
            await self.plugins.start_all()

            # the health gate on the critical plugins: a failure exits rather than leaving a silent zombie
            health_error = check_critical_plugins(self.plugins)
            if health_error:
                logger.error(health_error)
                return 1

            # audio failed but degrading is allowed: show the banner, log it, and keep the UI running
            if self.plugins.is_failed("audio") and not audio_is_fatal():
                logger.warning(DEGRADED_AUDIO_NOTICE)
                self._degraded_audio = True
                try:
                    await self.event_bus.emit(
                        Events.SYSTEM_NOTICE, DEGRADED_AUDIO_NOTICE
                    )
                except Exception as e:
                    logger.debug(
                        f"failed to emit the degraded-mode notice: {e}", exc_info=True
                    )

            await self.plugins.notify_device_state_changed(self.state.device_state)

            await self.tasks.wait_shutdown()
            return 0

        except Exception as e:
            logger.error(f"the application failed while running: {e}", exc_info=True)
            return 1
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down, releasing everything through the resource pool in reverse order."""
        if self._shutting_down:
            logger.debug("ServiceContainer is already shutting down, skipping")
            return
        self._shutting_down = True
        logger.info("shutting ServiceContainer down...")

        try:
            await self.resource_pool.shutdown()
            logger.info("ServiceContainer shut down")
        except Exception as e:
            logger.error(f"error during shutdown: {e}", exc_info=True)
        finally:
            if self._mode == "gui":
                try:
                    from PySide6.QtWidgets import QApplication

                    if QApplication.instance():
                        logger.debug("quitting the Qt application")
                        QApplication.quit()
                except Exception as e:
                    logger.debug(f"error while quitting the Qt application: {e}")
