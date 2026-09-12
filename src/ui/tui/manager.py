"""The TUI ViewManager: a ViewPort implementation driving the Textual app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.core.event_bus import EventBus, Events
from src.logging import get_logger

if TYPE_CHECKING:
    from src.core.task_manager import TaskManager
    from src.ui.tui.app import XiaozhiTuiApp

logger = get_logger()


class TuiViewManager:
    """The TUI interface (a ViewPort, with the same set_* methods as the GUI, CLI and GPIO)."""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager | None = None,
    ):
        self._event_bus = event_bus
        self._task_manager = task_manager
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: XiaozhiTuiApp | None = None
        self._app_task: asyncio.Task | None = None

        self._auto_mode = False
        self._status = "Standby"
        self._connected = False
        self._chat_text = ""
        self._music_line = ""
        self._emotion = "neutral"

    async def start(self, mode: str = "tui"):
        """Start the TUI (this awaits until the user quits or the task is cancelled)."""
        try:
            from src.ui.tui.app import XiaozhiTuiApp
        except ImportError as e:
            logger.error(
                "TUI mode needs textual. Install it with:\n"
                "  uv sync --extra tui\n"
                "  pip install '.[tui]'\n"
                f"(the original error: {e})"
            )
            raise

        logger.info("TuiViewManager: starting the TUI...")
        self._running = True
        self._loop = asyncio.get_running_loop()

        self._app = XiaozhiTuiApp(
            on_command=self._handle_command,
            on_settings_saved=self._on_settings_saved,
        )
        self._app.status_text = self._status
        self._app.connected = self._connected
        self._app.auto_mode = self._auto_mode
        self._app.chat_text = self._chat_text
        self._app.music_line = self._music_line
        self._app.emotion = self._emotion

        # UIPlugin spawns this coroutine through the TaskManager; run_async is awaited here
        # until the user presses q or Ctrl+C, or close() calls app.exit()
        try:
            await self._app.run_async()
        except asyncio.CancelledError:
            logger.info("TuiViewManager: the TUI task was cancelled")
            app = self._app
            if app is not None:
                try:
                    app.exit()
                except Exception:
                    pass
            raise
        finally:
            self._running = False
            if self._app is not None:
                try:
                    self._app.uninstall_log_handler()
                except Exception:
                    pass
            logger.info("TuiViewManager: the TUI has finished")

    async def close(self):
        """Shut the TUI down."""
        logger.info("TuiViewManager: shutting down...")
        self._running = False
        app = self._app
        if app is not None:
            try:
                app.exit()
            except Exception:
                pass
            try:
                app.uninstall_log_handler()
            except Exception:
                pass
        logger.info("TuiViewManager: closed")

    def _handle_command(self, cmd: str):
        """Handle a user command."""
        cmd_lower = cmd.lower().strip()
        if cmd_lower == "r":
            self._safe_emit(Events.UI_MANUAL_TOGGLE)
        elif cmd_lower == "x":
            self._safe_emit(Events.UI_ABORT_REQUEST)
        elif cmd_lower == "q":
            self._safe_emit(Events.UI_QUIT_REQUEST)
        else:
            self._safe_emit(Events.UI_SEND_TEXT, {"text": cmd})

    def _on_settings_saved(self) -> None:
        """Tell the running app to reload after the settings are saved."""
        self._safe_emit(Events.CONFIG_CHANGED)

    def _safe_emit(self, event: str, data=None):
        """Emit an EventBus event safely."""

        def _start_emit():
            if data is None:
                return self._event_bus.emit(event)
            return self._event_bus.emit(event, data)

        if self._task_manager is not None:
            try:
                self._task_manager.schedule_nowait(_start_emit)
                return
            except Exception as e:
                logger.error(
                    f"TuiViewManager failed to schedule {event} through the TaskManager: {e}",
                    exc_info=True,
                )

        if not self._loop or not self._loop.is_running():
            return
        coro = _start_emit()
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

            def _done(f):
                try:
                    exc = f.exception()
                except Exception:
                    return
                if exc:
                    logger.error(
                        f"TuiViewManager failed to emit {event}: {exc}",
                        exc_info=exc,
                    )

            fut.add_done_callback(_done)
        except Exception as e:
            logger.error(
                f"TuiViewManager failed to schedule {event}: {e}", exc_info=True
            )
            if asyncio.iscoroutine(coro):
                coro.close()

    def _set_app_attr(self, name: str, value) -> None:
        app = self._app
        if app is None:
            return

        def _apply() -> None:
            setattr(app, name, value)

        try:
            app.call_from_thread(_apply)
        except Exception:
            try:
                _apply()
            except Exception as e:
                logger.debug(f"TUI set {name} failed: {e}")

    # ----- ViewPort -----

    @property
    def is_running(self) -> bool:
        return self._running

    def set_status(self, status: str, connected: bool = True):
        self._status = status
        self._connected = connected
        self._set_app_attr("status_text", status)
        self._set_app_attr("connected", connected)

    def set_chat_text(self, text: str):
        self._chat_text = text
        self._set_app_attr("chat_text", text)

    def set_music_line(self, text: str):
        self._music_line = text
        self._set_app_attr("music_line", text)

    def set_emotion(self, emotion: str):
        self._emotion = emotion
        self._set_app_attr("emotion", emotion)

    def set_auto_mode(self, auto_mode: bool):
        self._auto_mode = auto_mode
        self._set_app_attr("auto_mode", auto_mode)

    def set_button_text(self, text: str):
        logger.debug(f"TUI set_button_text: {text}")

    def is_auto_mode(self) -> bool:
        return bool(self._auto_mode)
