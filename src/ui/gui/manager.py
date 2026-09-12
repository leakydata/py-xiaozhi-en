"""The GUI ViewManager: composes QmlAppHost, the main window and the settings controller into a ViewPort."""

from PySide6.QtCore import QObject, Slot

from src.core.event_bus import EventBus, Events
from src.core.task_manager import TaskManager
from src.logging import get_logger
from src.ui.gui.main_controller import MainWindowController
from src.ui.gui.models.activity_model import ActivityModel
from src.ui.gui.qml_host import QmlAppHost
from src.ui.gui.services import TrayService
from src.ui.gui.settings_controller import SettingsController
from src.ui.shared.bridge import EventBridge

logger = get_logger()


class GuiViewManager(QObject):
    """The GUI entry point (a ViewPort, plus the settings helpers).

    Device activation happens in the separate GuiActivation window before the container starts, so the main window no longer carries an activation model or API.
    """

    def __init__(self, event_bus: EventBus, task_manager: TaskManager | None = None):
        super().__init__()
        self._event_bus = event_bus
        self._running = False

        self._owns_tasks = task_manager is None
        if task_manager is not None:
            self._tasks = task_manager
        else:
            self._tasks = TaskManager()
            self._tasks.initialize()

        self._bridge = EventBridge(event_bus, task_manager=self._tasks)
        self._host = QmlAppHost()
        self._main = MainWindowController()
        self._activity = ActivityModel()
        self._settings = SettingsController(event_bus, self._tasks, self._bridge)
        self._tray_service: TrayService | None = None

        self._event_bus.on(Events.UI_TOGGLE_WINDOW, self._on_toggle_window)
        self._event_bus.on(Events.DEVICE_STATE_CHANGED, self._on_device_state_changed)
        logger.debug("GuiViewManager: subscribed to the window toggle event")

    async def _on_device_state_changed(self, payload=None) -> None:
        """Feed idle/listening/speaking to the avatar.

        Must be a coroutine: EventBus._safe_call awaits every handler.
        """
        try:
            state = payload.get("new_state") if isinstance(payload, dict) else payload
            value = getattr(state, "value", state)
            self._main.set_device_state(str(value))
        except Exception as e:
            logger.warning(f"GuiViewManager: failed to update the device state: {e}")

    async def start(self, mode: str = "gui"):
        if mode == "cli":
            logger.info("GuiViewManager: CLI mode, skipping the GUI setup")
            return

        logger.info("GuiViewManager: starting the GUI...")
        self._running = True

        self._host.create_engine()
        self._host.inject_context(
            {
                "eventBridge": self._bridge,
                "mainModel": self._main.main_model,
                "settingsModel": self._settings.ensure_model(),
                "emotionService": self._main.emotion_service,
                "activityModel": self._activity,
            }
        )
        self._host.load_main()
        # on a cold start just show it without taking focus, so macOS does not shove another fullscreen app off its Space
        self._host.show_root(activate=False)
        self._setup_tray()
        self._main.set_neutral_emotion()
        logger.info("GuiViewManager: GUI started")

    async def close(self):
        logger.info("GuiViewManager: shutting down...")
        self._running = False
        if self._tray_service:
            self._tray_service.hide()
        self._host.shutdown()
        logger.info("GuiViewManager: closed")

    def _setup_tray(self) -> None:
        root = self._host.root_window()
        if root is None:
            return
        self._tray_service = TrayService(root)
        self._tray_service.setup(
            on_show=self._host.show_root,
            on_quit=self._request_quit,
        )

    def _request_quit(self) -> None:
        self._tasks.spawn(
            self._event_bus.emit(Events.UI_QUIT_REQUEST), name="ui:quit_request"
        )

    async def _on_toggle_window(self, data=None):
        logger.debug("GuiViewManager: window toggle event received")
        self.toggle_window()

    # ----- ViewPort -----

    @property
    def is_running(self) -> bool:
        return self._running

    def set_chat_text(self, text: str) -> None:
        self._main.set_chat_text(text)

    def set_music_line(self, text: str) -> None:
        self._main.set_music_line(text)

    def set_emotion(self, emotion: str) -> None:
        self._main.set_emotion(emotion)

    def set_status(self, status: str, connected: bool = True) -> None:
        self._main.set_status(status, connected)

    def set_button_text(self, text: str) -> None:
        self._main.set_button_text(text)

    def set_auto_mode(self, auto_mode: bool) -> None:
        self._main.set_auto_mode(auto_mode)

    def is_auto_mode(self) -> bool:
        return self._main.is_auto_mode()

    # ----- settings and window -----

    @property
    def main_model(self):
        return self._main.main_model

    @property
    def settings_model(self):
        return self._settings.settings_model

    @Slot()
    def toggle_mode(self):
        self._tasks.spawn(
            self._event_bus.emit(Events.UI_AUTO_TOGGLE), name="ui:auto_toggle"
        )

    @Slot()
    def toggle_window(self):
        self._host.toggle_root_visible()

    def open_settings(self):
        if not self._host.engine:
            logger.warning(
                "GuiViewManager: the engine is not initialised, cannot open the settings"
            )
            return
        self._settings.open_settings()
