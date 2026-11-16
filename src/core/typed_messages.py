"""Text typed in the chat box, waiting for the assistant to read it.

xiaozhi.me only accepts about 21 characters of text sent the way the chat box
sends it (a `listen`/`detect` message): anything longer gets "Detect is only for
wake words, do not send long texts" and the assistant never sees it. So a long
message is parked here and a short cue is sent instead; the cue makes her call
the typed_message tool, which hands the text over.
"""

from __future__ import annotations

import threading
import time

#: Longest text the server accepts as a detect message (measured 2026-11-15).
DIRECT_MAX_CHARS = 21
#: Anything typed this long ago and never fetched is dropped as stale.
_STALE_S = 600

_lock = threading.Lock()
_pending: list[tuple[float, str]] = []


def park(text: str) -> None:
    with _lock:
        _pending.append((time.monotonic(), text))


def take_all() -> list[str]:
    """Everything waiting, oldest first; empties the queue."""
    with _lock:
        now = time.monotonic()
        out = [t for at, t in _pending if now - at < _STALE_S]
        _pending.clear()
        return out


def clear() -> None:
    with _lock:
        _pending.clear()
