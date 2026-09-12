"""CLI terminal display.

Provides a terminal TUI made up of:
- a status dashboard (the top frame)
- a log display area
- a command input area
"""

import asyncio
import logging
import os
import shutil
import sys
from collections import deque
from typing import Callable, Optional

from src.constants.system import SystemConstants
from src.logging import get_logger

logger = get_logger()


class CLIDisplay:
    """CLI terminal display."""

    def __init__(self):
        self.running = True
        self._use_ansi = sys.stdout.isatty()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_drawn_rows = 0
        self._render_lock = None
        self._initialized = False  # whether it has been initialised
        self._log_handler_installed = (
            False  # whether the log handler has been installed
        )

        # dashboard data
        self._dash_status = "Standby"
        self._dash_connected = False
        self._dash_text = ""
        self._dash_music = ""
        self._dash_emotion = "neutral"
        self._dash_auto_mode = False

        # layout settings
        self._input_area_lines = 3  # number of lines in the input area
        self._dashboard_lines = 9  # minimum number of lines in the display area

        # ANSI styling
        self._ansi = {
            "reset": "\x1b[0m",
            "bold": "\x1b[1m",
            "dim": "\x1b[2m",
            "blue": "\x1b[34m",
            "cyan": "\x1b[36m",
            "green": "\x1b[32m",
            "yellow": "\x1b[33m",
            "magenta": "\x1b[35m",
            "red": "\x1b[31m",
        }

        # callbacks
        self._on_command: Optional[Callable[[str], None]] = None

        # log buffer
        self._log_lines: deque[str] = deque(maxlen=6)

        # command queue
        self._command_queue: asyncio.Queue = asyncio.Queue()

    def set_command_callback(self, callback: Callable[[str], None]):
        """Set the command callback."""
        self._on_command = callback

    def intercept_logging(self):
        """Intercept log output as early as possible (called before start).

        Mirrors the old implementation: remove the StreamHandlers during __init__ and install a custom handler.
        """
        # first remove every StreamHandler
        self._remove_stream_handlers()
        # then install our own log handler
        self._install_log_handler()

    async def start(self):
        """Start the CLI display."""
        # grab the event loop first
        self._loop = asyncio.get_running_loop()
        self._render_lock = asyncio.Lock()

        # make sure logging is intercepted (in case intercept_logging was never called)
        if not self._log_handler_installed:
            self.intercept_logging()

        # clear the screen and initialise the interface
        if self._use_ansi:
            # full clear: clear the screen, clear the scrollback, move the cursor home
            sys.stdout.write("\x1b[3J\x1b[2J\x1b[H")
            sys.stdout.flush()

        # mark as initialised
        self._initialized = True

        # initialise the screen
        await self._init_screen()

        # start the input loop
        try:
            await self._keyboard_input_loop()
        except asyncio.CancelledError:
            pass

    async def close(self):
        """Shut down the CLI display."""
        self.running = False

        # restore standard logging
        self._restore_logging()

        # clear the screen
        if self._use_ansi:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.flush()

        print("Shutting down...\n")

    # ========== state updates ==========

    def update_status(self, status: str, connected: bool = True):
        """Update the status."""
        self._dash_status = status
        self._dash_connected = connected
        self._schedule_render()

    def update_text(self, text: str):
        if text and text.strip():
            self._dash_text = text.strip()
            self._schedule_render()

    def update_music_line(self, text: str):
        self._dash_music = (text or "").strip()
        self._schedule_render()

    def update_emotion(self, emotion: str):
        """Update the emotion."""
        self._dash_emotion = emotion
        self._schedule_render()

    def update_auto_mode(self, auto_mode: bool):
        """Update the auto-mode state."""
        self._dash_auto_mode = auto_mode
        self._schedule_render()

    def add_log(self, message: str):
        """Append a log line."""
        self._log_lines.append(message)
        self._schedule_render()

    def _schedule_render(self):
        """Schedule a render."""
        if not self._initialized:
            return
        if self._loop and self._use_ansi and self.running:
            try:
                if self._loop.is_running():
                    self._loop.call_soon_threadsafe(self._do_render)
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to schedule a render: {e}")

    def _do_render(self):
        """Perform the render (called on the event loop)."""
        if not self._initialized:
            return
        try:
            task = asyncio.create_task(self._safe_render(), name="cli:render")

            def _on_done(t: asyncio.Task):
                if t.cancelled():
                    return
                exc = t.exception()
                if exc:
                    logging.getLogger(__name__).error(
                        f"CLI render task failed: {exc}", exc_info=exc
                    )

            task.add_done_callback(_on_done)
        except Exception as e:
            logging.getLogger(__name__).error(
                f"Failed to create the render task: {e}", exc_info=True
            )

    async def _safe_render(self):
        """Render safely (under the lock)."""
        if self._render_lock is None:
            return
        async with self._render_lock:
            await self._render_dashboard()

    # ========== screen rendering ==========

    async def _init_screen(self):
        """Initialise the screen."""
        # note: the screen was already cleared in start()
        await self._render_dashboard(full=True)
        await self._render_input_area()

    async def _render_dashboard(self, full: bool = False):
        """Render the dashboard."""

        def trunc(s: str, limit: int = 60) -> str:
            return s if len(s) <= limit else s[: limit - 1] + "…"

        # build the status lines
        mode_text = "Auto" if self._dash_auto_mode else "Manual"
        conn_text = "Connected" if self._dash_connected else "Disconnected"

        lines = [
            f"Status: {trunc(self._dash_status)}",
            f"Connection: {conn_text} | Mode: {mode_text}",
            f"Emotion: {self._dash_emotion}",
            f"Chat: {trunc(self._dash_text)}",
            f"Music: {trunc(self._dash_music) if self._dash_music else '-'}",
        ]

        # log lines are not shown (logging is still intercepted, just not displayed)

        if not self._use_ansi:
            print(f"\r{lines[0]}        ", end="", flush=True)
            return

        cols, rows = self._term_size()
        usable_rows = max(5, rows - self._input_area_lines)

        # styling helpers
        def style(s: str, *names: str) -> str:
            if not self._use_ansi:
                return s
            prefix = "".join(self._ansi.get(n, "") for n in names)
            return f"{prefix}{s}{self._ansi['reset']}"

        title = style(f" {SystemConstants.APP_DISPLAY_NAME} ", "bold", "cyan")

        # frame
        top_bar = "┌" + ("─" * (max(2, cols - 2))) + "┐"
        title_line = (
            "│" + title.center(max(2, cols - 2) + 14) + "│"
        )  # +14 compensates for the ANSI escapes
        sep_line = "├" + ("─" * (max(2, cols - 2))) + "┤"
        bottom_bar = "└" + ("─" * (max(2, cols - 2))) + "┘"

        # content area
        body_rows = max(1, usable_rows - 4)
        body = []
        for i in range(body_rows):
            if i < len(lines):
                text = lines[i]
                if i == 0:
                    text = style(text, "green")
                elif i == 1:
                    text = style(text, "cyan")
                elif "INFO" in text or "DEBUG" in text:
                    text = style(text, "dim")
                elif "ERROR" in text or "WARNING" in text:
                    text = style(text, "yellow")
            else:
                text = ""
            body.append("│" + text.ljust(max(2, cols - 2))[: max(2, cols - 2)] + "│")

        # save the cursor
        sys.stdout.write("\x1b7")

        # clear the previous area
        total_rows = 4 + body_rows
        rows_to_clear = max(self._last_drawn_rows, total_rows)
        for i in range(rows_to_clear):
            self._goto(1 + i, 1)
            sys.stdout.write("\x1b[2K")

        # draw
        self._goto(1, 1)
        sys.stdout.write("\x1b[2K" + top_bar[:cols])
        self._goto(2, 1)
        sys.stdout.write("\x1b[2K" + title_line[:cols])
        self._goto(3, 1)
        sys.stdout.write("\x1b[2K" + sep_line[:cols])

        for idx in range(body_rows):
            self._goto(4 + idx, 1)
            sys.stdout.write("\x1b[2K")
            sys.stdout.write(body[idx][:cols])

        self._goto(4 + body_rows, 1)
        sys.stdout.write("\x1b[2K" + bottom_bar[:cols])

        # restore the cursor
        sys.stdout.write("\x1b8")
        sys.stdout.flush()

        self._last_drawn_rows = total_rows

    async def _render_input_area(self):
        """Render the input area."""
        if not self._use_ansi:
            return

        cols, rows = self._term_size()
        separator_row = max(1, rows - self._input_area_lines + 1)
        first_input_row = min(rows, separator_row + 1)
        second_input_row = min(rows, separator_row + 2)

        sys.stdout.write("\x1b7")

        # separator
        self._goto(separator_row, 1)
        sys.stdout.write("\x1b[2K")
        sys.stdout.write("═" * max(1, cols))

        # input prompt
        self._goto(first_input_row, 1)
        sys.stdout.write("\x1b[2K")
        prompt = "\x1b[1m\x1b[36mInput:\x1b[0m " if self._use_ansi else "Input: "
        sys.stdout.write(prompt)

        # reserved lines
        self._goto(second_input_row, 1)
        sys.stdout.write("\x1b[2K")
        sys.stdout.flush()

        sys.stdout.write("\x1b8")
        self._goto(first_input_row, 1)
        sys.stdout.write(prompt)
        sys.stdout.flush()

    def _clear_input_area(self):
        """Clear the input area."""
        if not self._use_ansi:
            return
        cols, rows = self._term_size()
        separator_row = max(1, rows - self._input_area_lines + 1)
        for r in range(separator_row, min(rows + 1, separator_row + 3)):
            self._goto(r, 1)
            sys.stdout.write("\x1b[2K")
        sys.stdout.flush()

    # ========== input handling ==========

    async def _keyboard_input_loop(self):
        """Keyboard input loop."""
        try:
            while self.running:
                if self._use_ansi:
                    await self._render_input_area()
                    cmd = await asyncio.to_thread(self._read_line_raw)
                    self._clear_input_area()
                    await self._render_dashboard()
                else:
                    cmd = await asyncio.to_thread(input, "Input: ")

                await self._handle_command(cmd.strip())
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            await self.close()

    def _read_line_raw(self) -> str:
        """Read input in raw mode (multi-byte characters supported)."""
        try:
            import termios
            import tty
        except ImportError:
            # termios is not available on Windows
            return input()

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            buffer: list[str] = []
            while True:
                ch = os.read(fd, 4)
                if not ch:
                    break
                try:
                    s = ch.decode("utf-8")
                except UnicodeDecodeError:
                    while True:
                        ch += os.read(fd, 1)
                        try:
                            s = ch.decode("utf-8")
                            break
                        except UnicodeDecodeError:
                            continue

                if s in ("\r", "\n"):
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    break
                elif s in ("\x7f", "\b"):
                    if buffer:
                        buffer.pop()
                    self._redraw_input_line("".join(buffer))
                elif s == "\x03":  # Ctrl+C
                    raise KeyboardInterrupt
                else:
                    buffer.append(s)
                    self._redraw_input_line("".join(buffer))

            return "".join(buffer)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _redraw_input_line(self, content: str):
        """Redraw the input line."""
        cols, rows = self._term_size()
        separator_row = max(1, rows - self._input_area_lines + 1)
        first_input_row = min(rows, separator_row + 1)
        prompt = "\x1b[1m\x1b[36mInput:\x1b[0m " if self._use_ansi else "Input: "
        self._goto(first_input_row, 1)
        sys.stdout.write("\x1b[2K")
        visible = content
        max_len = max(1, cols - len("Input: ") - 1)
        if len(visible) > max_len:
            visible = visible[-max_len:]
        sys.stdout.write(f"{prompt}{visible}")
        sys.stdout.flush()

    async def _handle_command(self, cmd: str):
        """Handle a command - everything is forwarded to CliViewManager."""
        if not cmd:
            return

        if self._on_command:
            # every command is forwarded, none are intercepted
            self._on_command(cmd)

    def show_help(self):
        """Show help."""
        self._dash_text = "Commands: r=start/stop | x=interrupt | q=quit | h=help | anything else=send text"
        self._schedule_render()

    # ========== log handling ==========

    def _install_log_handler(self):
        """Install the log handler."""
        # guard against installing twice
        if self._log_handler_installed:
            return
        self._log_handler_installed = True

        class DisplayLogHandler(logging.Handler):
            def __init__(self, display: "CLIDisplay"):
                super().__init__()
                self.display = display

            def emit(self, record: logging.LogRecord):
                try:
                    msg = self.format(record)
                    self.display._log_lines.append(msg)
                    self.display._schedule_render()
                except Exception as e:
                    logging.getLogger(__name__).error(f"Logging failed: {e}")

        handler = DisplayLogHandler(self)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logging.getLogger().addHandler(handler)

    def _remove_stream_handlers(self):
        """Remove every log handler that writes to stdout."""
        root = logging.getLogger()

        # remove every StreamHandler on the root logger
        for h in list(root.handlers):
            if isinstance(h, logging.StreamHandler):
                root.removeHandler(h)

        # remove the StreamHandlers on every registered logger
        for name in list(logging.Logger.manager.loggerDict.keys()):
            log = logging.getLogger(name)
            for h in list(log.handlers):
                if isinstance(h, logging.StreamHandler):
                    log.removeHandler(h)

        # set the root logger level
        root.setLevel(logging.DEBUG)

    def _restore_logging(self):
        """Restore standard logging."""
        root = logging.getLogger()

        # remove the DisplayLogHandler
        for h in list(root.handlers):
            if h.__class__.__name__ == "DisplayLogHandler":
                root.removeHandler(h)

        # add a plain StreamHandler
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        root.addHandler(handler)

    # ========== helpers ==========

    def _goto(self, row: int, col: int = 1):
        """Move the cursor."""
        sys.stdout.write(f"\x1b[{max(1, row)};{max(1, col)}H")

    def _term_size(self) -> tuple[int, int]:
        """Get the terminal size."""
        try:
            size = shutil.get_terminal_size(fallback=(80, 24))
            return size.columns, size.lines
        except Exception:
            return 80, 24
