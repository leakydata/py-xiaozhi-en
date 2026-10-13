"""Leave a record of why the process ended, however it ended.

The app once vanished mid-reply with nothing in the log: no traceback, no core
dump, no segfault in the kernel log, no shutdown sequence. Only a few ways out
leave that little behind - a terminating signal Python does not handle
(SIGHUP when the terminal closes, SIGTERM), or a library calling _exit() after
printing one line to a terminal that may be gone. Qt on Wayland does exactly
that when its connection to the compositor breaks.

So this writes, synchronously and straight to logs/exit.log - not through the
logging queue, whose last lines die with the process:

- native crashes: every thread's Python stack (faulthandler)
- SIGTERM / SIGHUP: which one arrived, then a graceful shutdown like Ctrl+C
- Qt's own warnings and errors, which otherwise only reach stderr
- a normal exit, so that a missing "exited" line itself means "cut off"
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import signal
import sys
import time
from collections.abc import Callable

from src.logging import get_logger

logger = get_logger()

_file = None
#: Qt messages that are worth a synchronous write: these are the ones printed
#: just before Qt gives up on the display and exits.
_FATAL_HINTS = ("wayland", "xcb", "xio", "display", "compositor", "fatal")


def _path() -> str:
    from src.utils.resource_finder import get_log_dir

    return os.path.join(str(get_log_dir()), "exit.log")


def record(line: str) -> None:
    """Append one line to exit.log right now, bypassing the logging queue."""
    if _file is None:
        return
    try:
        _file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {line}\n")
        _file.flush()
        os.fsync(_file.fileno())
    except Exception:
        pass


def install(on_signal: Callable[[str], None] | None = None) -> str:
    """Start recording. `on_signal(name)` runs on SIGTERM/SIGHUP to shut down cleanly."""
    global _file
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _file = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 - lives as long as the process
    record(f"started: {' '.join(sys.argv)}")

    # Native crashes print every thread's stack here, then the process dies
    # as it would have.
    faulthandler.enable(file=_file, all_threads=True)

    def _on_terminate(signum, _frame):
        name = signal.Signals(signum).name
        record(f"received {name}")
        logger.warning(f"{name} received, shutting down")
        if on_signal is not None:
            try:
                on_signal(name)
                return
            except Exception as e:
                record(f"graceful shutdown on {name} failed: {e}")
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            try:
                signal.signal(sig, _on_terminate)
            except (ValueError, OSError):
                pass  # not the main thread, or not supported here

    atexit.register(lambda: record("exited"))
    return path


def install_qt_messages() -> None:
    """Route Qt's own messages into the log, and the dangerous ones into exit.log."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    def handler(mode, context, message):
        text = str(message)
        if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
            record(f"Qt {mode.name}: {text}")
            logger.error(f"Qt: {text}")
        elif mode == QtMsgType.QtWarningMsg:
            if any(h in text.lower() for h in _FATAL_HINTS):
                record(f"Qt warning: {text}")
            logger.warning(f"Qt: {text}")
        else:
            logger.debug(f"Qt: {text}")

    qInstallMessageHandler(handler)
