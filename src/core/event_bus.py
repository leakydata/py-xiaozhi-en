"""Event bus.

Decoupled communication between components.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from src.logging import get_logger

logger = get_logger()


# predefined event names
class Events:
    """
    Predefined event constants.
    """

    # device state
    DEVICE_STATE_CHANGED = "device_state_changed"

    # protocol
    PROTOCOL_CONNECTED = "protocol_connected"
    PROTOCOL_DISCONNECTED = "protocol_disconnected"
    INCOMING_JSON = "incoming_json"
    INCOMING_AUDIO = "incoming_audio"

    # network errors
    NETWORK_ERROR = "network_error"

    # audio channel
    AUDIO_CHANNEL_OPENED = "audio_channel_opened"
    AUDIO_CHANNEL_CLOSED = "audio_channel_closed"
    # AudioCodec lifecycle (AudioPlugin -> MusicPlayer and other subscribers, so nothing wires a set() directly)
    AUDIO_CODEC_CHANGED = "audio_codec_changed"
    # request a re-enumeration of the audio devices (settings-page refresh; the streams must be stopped before the PortAudio reinit)
    # payload: an optional asyncio.Future, set_result(list|dict|None) on completion
    AUDIO_DEVICES_REFRESH_REQUEST = "audio_devices_refresh_request"

    # application lifecycle
    APP_SHUTDOWN = "app_shutdown"
    # system-level notices (the degraded-mode banner and so on, payload: str)
    SYSTEM_NOTICE = "system_notice"

    # music player events
    MUSIC_STATE_CHANGED = "music_state_changed"  # playback state changed
    MUSIC_LYRICS_UPDATE = "music_lyrics_update"  # lyrics updated
    MUSIC_PROGRESS_UPDATE = "music_progress_update"  # progress updated

    # music control commands (driving MusicPlayer from outside)
    MUSIC_PAUSE_REQUEST = "music_pause_request"  # request a pause (for TTS, say)
    MUSIC_RESUME_REQUEST = "music_resume_request"  # request a resume

    # UI actions (interface -> plugin)
    UI_BUTTON_PRESS = "ui_button_press"  # manual: press
    UI_BUTTON_RELEASE = "ui_button_release"  # manual: release
    UI_MANUAL_TOGGLE = "ui_manual_toggle"  # manual: click once to start/stop recording
    UI_AUTO_TOGGLE = "ui_auto_toggle"  # switch between auto and manual
    UI_AUTO_START = "ui_auto_start"  # auto: start/stop the conversation
    UI_ABORT_REQUEST = "ui_abort_request"  # interrupt
    UI_SEND_TEXT = "ui_send_text"  # send text
    UI_QUIT_REQUEST = "ui_quit_request"  # quit
    UI_OPEN_SETTINGS = "ui_open_settings"  # open settings
    UI_TOGGLE_WINDOW = "ui_toggle_window"  # show/hide the main window (GUI)

    # configuration change events
    CONFIG_CHANGED = (
        "config_changed"  # the configuration changed (a hot reload is needed)
    )
    # after the exposed MCP tools change: drop and reconnect the protocol so the server re-runs tools/list
    PROTOCOL_RECONNECT_REQUEST = "protocol_reconnect_request"


# the set of known event names: a typo produces a warning in on/emit, which helps when debugging
_KNOWN_EVENTS: frozenset[str] = frozenset(
    v for k, v in vars(Events).items() if not k.startswith("_") and isinstance(v, str)
)


class EventBus:
    """Event bus.

    Async event handling, for loosely coupled communication between components.

    Usage:     bus = EventBus()

    # register a handler  async def on_state_changed(state):     print(f"State: {state}")

    bus.on(Events.DEVICE_STATE_CHANGED, on_state_changed)

    # emit an event   await bus.emit(Events.DEVICE_STATE_CHANGED, DeviceState.LISTENING)

    # remove a handler  bus.off(Events.DEVICE_STATE_CHANGED, on_state_changed)
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable[..., Awaitable[None]]]] = defaultdict(
            list
        )

    @staticmethod
    def _warn_if_unknown(event: str, action: str) -> None:
        if event not in _KNOWN_EVENTS:
            logger.warning(
                f"EventBus: {action} an unknown event name {event!r} (probably a typo; "
                "use the Events.* constants)"
            )

    def on(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Register an event handler.

        Args:
            event: the event name
            handler: the async handler
        """
        self._warn_if_unknown(event, "registering")
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)
            logger.debug(f"EventBus: registered handler {handler.__name__} -> {event}")

    def off(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Remove an event handler.

        Args:
            event: the event name
            handler: the handler to remove
        """
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)
            logger.debug(f"EventBus: removed handler {handler.__name__} <- {event}")

    def clear(self, event: str = None) -> None:
        """Clear event handlers.

        Args:
            event: the event name; None clears every handler
        """
        if event is None:
            self._handlers.clear()
            logger.debug("EventBus: cleared every handler")
        elif event in self._handlers:
            self._handlers[event].clear()
            logger.debug(f"EventBus: cleared every handler for {event}")

    async def emit(self, event: str, data: Any = None) -> None:
        """Emit an event.

        Every registered handler is called in parallel.

        Args:
            event: the event name
            data: the event payload
        """
        handlers = list(self._handlers.get(event, []))
        if not handlers:
            # still warn about an unknown name with no subscribers, so a typo is not lost silently
            self._warn_if_unknown(event, "emitting")
            return

        logger.debug(f"EventBus: emitting {event} to {len(handlers)} handler(s)")

        # run every handler in parallel
        tasks = []
        for handler in handlers:
            try:
                tasks.append(self._safe_call(handler, data))
            except Exception as e:
                logger.error(
                    f"EventBus: failed to create a task for {handler.__name__}: {e}",
                    exc_info=True,
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def emit_sequential(self, event: str, data: Any = None) -> None:
        """Emit an event sequentially.

        Handlers are called one at a time, in registration order.

        Args:
            event: the event name
            data: the event payload
        """
        handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            await self._safe_call(handler, data)

    async def _safe_call(
        self, handler: Callable[..., Awaitable[None]], data: Any
    ) -> None:
        """
        Call a handler, catching any exception.
        """
        try:
            if data is None:
                await handler()
            else:
                await handler(data)
        except Exception as e:
            logger.error(
                f"EventBus: handler {handler.__name__} raised: {e}",
                exc_info=True,
            )

    def has_handlers(self, event: str) -> bool:
        """
        Whether the event has any handlers.
        """
        return bool(self._handlers.get(event))

    def handler_count(self, event: str) -> int:
        """
        The number of handlers registered for the event.
        """
        return len(self._handlers.get(event, []))
