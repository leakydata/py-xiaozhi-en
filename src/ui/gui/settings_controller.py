"""The settings window: lazily creating SettingsModel, and opening the window."""

from src.core.event_bus import EventBus, Events
from src.core.task_manager import TaskManager
from src.logging import get_logger
from src.ui.shared.bridge import EventBridge

logger = get_logger()


class SettingsController:
    """Creates SettingsModel on demand; opening the settings reloads it and tells QML."""

    def __init__(
        self,
        event_bus: EventBus,
        tasks: TaskManager,
        bridge: EventBridge,
    ) -> None:
        self._event_bus = event_bus
        self._tasks = tasks
        self._bridge = bridge
        self._settings_model = None

    @property
    def settings_model(self):
        return self.ensure_model()

    def ensure_model(self):
        """Create SettingsModel on demand - on the first QML injection, or when the settings open."""
        if self._settings_model is None:
            from src.ui.gui.models import SettingsModel

            self._settings_model = SettingsModel(
                event_bus=self._event_bus,
                task_manager=self._tasks,
            )
            self._settings_model.configSaved.connect(self._on_config_saved)
            self._settings_model.mcpToolsNeedReconnect.connect(
                self._on_mcp_tools_need_reconnect
            )
            logger.debug("SettingsController: SettingsModel created")
        return self._settings_model

    def _on_config_saved(self) -> None:
        logger.info("SettingsController: settings saved, triggering a reload")
        self._tasks.spawn(
            self._event_bus.emit(Events.CONFIG_CHANGED), name="ui:config_changed"
        )

    def _on_mcp_tools_need_reconnect(self) -> None:
        """The MCP disabled-tools list changed: ask the session to reconnect so the server lists the tools again."""
        logger.info(
            "SettingsController: the MCP tool list changed, asking the protocol to reconnect"
        )
        self._tasks.spawn(
            self._event_bus.emit(Events.PROTOCOL_RECONNECT_REQUEST),
            name="ui:protocol_reconnect",
        )

    def open_settings(self) -> None:
        """Reload the settings and the device list, then have QML show the window."""
        self.ensure_model().reload()
        self._bridge.showSettingsWindow.emit()
        logger.debug("SettingsController: sent the open-settings signal")
