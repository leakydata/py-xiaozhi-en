"""The EventBus bridge - converting between Python signals and QML signals."""

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.core.event_bus import EventBus, Events
from src.logging import get_logger

logger = get_logger()


class EventBridge(QObject):
    """Bridges the EventBus and QML in both directions.

    QML -> Python: QML calls a slot, which emits an EventBus event
    Python -> QML: an EventBus event fires a Python Signal that QML is connected to

    Device activation is handled by the separate GuiActivation window, so the main bridge no longer carries the activation signals.
    """

    # ========== Python -> QML signals ==========

    # window control
    showWindow = Signal()
    hideWindow = Signal()
    showSettingsWindow = Signal()  # show the settings window

    # ========== construction ==========

    def __init__(
        self, event_bus: EventBus, task_manager=None, parent: QObject | None = None
    ):
        super().__init__(parent)
        self._event_bus = event_bus
        self._task_manager = task_manager

    def _emit_event(self, event: str, data=None):
        """Emit an EventBus event safely, scheduling onto the asyncio loop from the Qt main thread."""
        if self._task_manager is None:
            logger.error("EventBridge: no TaskManager was injected, cannot emit events")
            return

        def do_emit():
            try:
                task_name = (
                    f"bridge:{event.split('.')[-1]}"
                    if "." in event
                    else f"bridge:{event}"
                )
                self._task_manager.spawn(
                    self._event_bus.emit(event, data), name=task_name
                )
            except Exception as e:
                logger.warning(
                    f"EventBridge: failed to emit {event}: {e}",
                    exc_info=True,
                )

        # QTimer.singleShot makes sure this runs on the Qt event loop
        QTimer.singleShot(0, do_emit)

    # ========== QML → Python (Slots) ==========

    @Slot()
    def onButtonPress(self):
        """Manual mode: button pressed."""
        logger.debug("EventBridge: button pressed")
        self._emit_event(Events.UI_BUTTON_PRESS)

    @Slot()
    def onButtonRelease(self):
        """Manual mode: button released."""
        logger.debug("EventBridge: button released")
        self._emit_event(Events.UI_BUTTON_RELEASE)

    @Slot()
    def onManualToggle(self):
        """Manual mode: toggle recording (click to start or stop)."""
        logger.debug("EventBridge: manual recording toggled")
        self._emit_event(Events.UI_MANUAL_TOGGLE)

    @Slot()
    def onAutoToggle(self):
        """Toggle auto mode."""
        logger.debug("EventBridge: auto mode toggled")
        self._emit_event(Events.UI_AUTO_TOGGLE)

    @Slot()
    def onAutoStart(self):
        """Auto mode: start or stop the conversation."""
        logger.debug("EventBridge: auto mode start/stop conversation")
        self._emit_event(Events.UI_AUTO_START)

    @Slot()
    def onAbort(self):
        """Interrupt request."""
        logger.debug("EventBridge: interrupt requested")
        self._emit_event(Events.UI_ABORT_REQUEST)

    @Slot(str)
    def onSendText(self, text: str):
        """Send text."""
        if text.strip():
            logger.debug(f"EventBridge: sending text: {text[:20]}...")
            from src.ui.shared.events import UISendTextRequest

            self._emit_event(Events.UI_SEND_TEXT, UISendTextRequest(text=text))

    @Slot()
    def onQuitRequest(self):
        """Quit request."""
        logger.info("EventBridge: quit requested")
        self._emit_event(Events.UI_QUIT_REQUEST)

    @Slot()
    def onOpenSettings(self):
        """Open the settings window - emits straight to QML."""
        logger.debug("EventBridge: opening the settings window")
        self.showSettingsWindow.emit()
