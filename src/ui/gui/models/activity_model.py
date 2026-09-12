"""Live view of what the assistant is doing.

Answers "is it working or is it stuck?" - when a tool is running you can see
which one, with its arguments and a timer that keeps counting. The audit file
only gains an entry once a call completes, which is precisely too late.

Polls the in-memory feed rather than pushing signals from the call site: tool
calls run on the asyncio loop, the GUI lives on the Qt loop, and a 4Hz poll of
a deque is cheaper and simpler than marshalling across them.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QTimer, Signal

from src.ui.gui.models.base_model import BaseModel

_POLL_MS = 250


def _summarise(entry: dict) -> dict:
    """Flatten one feed entry into something QML can bind to directly."""
    state = entry.get("state", "running")
    ms = entry.get("ms")
    if state == "running":
        ms = entry.get("elapsed_ms", 0)
    if ms is None:
        took = ""
    elif ms < 1000:
        took = f"{ms} ms"
    else:
        took = f"{ms / 1000:.1f} s"

    detail = entry.get("detail") or ""
    if state == "running":
        detail = entry.get("args") or ""
    return {
        "tool": entry.get("tool", "?"),
        "args": entry.get("args", ""),
        "state": state,
        "took": took,
        "detail": detail,
        "running": state == "running",
        "failed": state == "failed",
    }


class ActivityModel(BaseModel):
    """Recent and in-flight tool calls, for the activity panel."""

    activityChanged = Signal()
    busyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._busy = 0
        self._signature = ""

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _poll(self) -> None:
        try:
            from src.mcp import audit

            entries = audit.feed(40)
            busy = audit.running_count()
        except Exception:
            return

        rows = [_summarise(e) for e in reversed(entries)]  # newest first
        # Cheap change detection: rebuilding the QML list on every tick would
        # reset scroll position and churn delegates for no reason.
        signature = "|".join(f"{r['tool']}:{r['state']}:{r['took']}" for r in rows)
        if signature != self._signature:
            self._signature = signature
            self._rows = rows
            self.activityChanged.emit()
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit()

    @Property(list, notify=activityChanged)
    def activity(self) -> list:
        return self._rows

    @Property(int, notify=busyChanged)
    def busyCount(self) -> int:
        return self._busy

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy > 0
