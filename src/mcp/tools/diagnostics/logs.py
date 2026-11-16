"""Read and summarise the app's own log, for the assistant to troubleshoot with.

The log is a few megabytes of DEBUG lines, far too much to hand a language
model, and it contains things that should not leave the machine (tokens). So
this reads only the tail, filters by time and level, collapses repeats, redacts
secrets and caps the size, and offers a summary of the things that usually
explain a complaint: errors, what the server said, drops, interruptions.

Read-only. Nothing here writes to the log or changes any setting.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
#: How much of the end of the file is looked at. A busy hour of DEBUG is about
#: a megabyte; this covers several.
_TAIL_BYTES = 6 * 1024 * 1024
_MAX_LINE = 260
_MAX_LINES = 80

_SECRET = re.compile(
    r"""(?ix)
    ( (?:access[_-]?token|token|api[_-]?key|secret|password|authorization|bearer)
      ["']?\s*[:=]?\s*["']? )
    ( [A-Za-z0-9._\-+/=]{8,} )
    """
)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b")


@dataclass
class Line:
    when: datetime
    level: str
    logger: str
    message: str

    @property
    def rank(self) -> int:
        return LEVELS.get(self.level.lower(), 20)

    def short(self) -> str:
        return (
            f"{self.when:%H:%M:%S} {self.level[:4]} "
            f"{self.logger.rsplit('.', 1)[-1]}: {redact(self.message)}"
        )[:_MAX_LINE]


def redact(text: str) -> str:
    """Strip anything that looks like a credential."""
    text = _SECRET.sub(lambda m: m.group(1) + "[hidden]", text)
    return _LONG_TOKEN.sub("[hidden]", text)


def log_path() -> Path:
    from src.utils.resource_finder import get_user_log_dir

    return get_user_log_dir() / "app.log"


def parse_line(raw: str) -> Line | None:
    """`2026-11-15 19:48:24 | INFO     | [-] | src.x | message | MainThread`."""
    parts = raw.rstrip("\n").split(" | ", 4)
    if len(parts) < 5:
        return None
    try:
        when = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    message = parts[4]
    head, sep, tail = message.rpartition(" | ")
    if sep and " " not in tail.strip():
        message = head  # the trailing thread name
    return Line(when, parts[1].strip(), parts[3].strip(), message)


def read_tail(path: Path, max_bytes: int = _TAIL_BYTES) -> list[Line]:
    """The parsed lines from the end of the file. Continuation lines (the
    multi-line JSON dumps) are dropped."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # a partial line
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        line = parse_line(raw)
        if line is not None:
            out.append(line)
    return out


def window(
    lines: list[Line], minutes: float, now: datetime | None = None
) -> list[Line]:
    now = now or datetime.now()
    since = now - timedelta(minutes=minutes)
    return [ln for ln in lines if ln.when >= since]


def select(
    lines: list[Line],
    *,
    level: str = "warning",
    contains: str = "",
    logger: str = "",
    max_lines: int = _MAX_LINES,
) -> dict:
    """Filter, collapse repeats, keep the most recent `max_lines`."""
    floor = LEVELS.get((level or "warning").lower(), 30)
    needle = (contains or "").strip().lower()
    where = (logger or "").strip().lower()
    picked = [
        ln
        for ln in lines
        if ln.rank >= floor
        and (not needle or needle in ln.message.lower())
        and (not where or where in ln.logger.lower())
    ]
    # collapse runs of the same message
    rows: list[list] = []
    for ln in picked:
        text = ln.short()[9:]  # without the time, so repeats compare equal
        if rows and rows[-1][1] == text:
            rows[-1][2] += 1
            rows[-1][3] = ln
        else:
            rows.append([ln, text, 1, ln])
    cap = max(1, min(_MAX_LINES * 2, int(max_lines)))
    cut = len(rows) > cap
    rows = rows[-cap:]
    shown = [
        (first.short() + (f"  (x{n}, last {last.when:%H:%M:%S})" if n > 1 else ""))
        for first, _t, n, last in rows
    ]
    result: dict = {"lines": shown, "matched": len(picked)}
    if cut:
        result["note"] = (
            "Older matches were left out to keep this short. Narrow the "
            "window, raise the level or add a filter rather than asking again."
        )
    return result


# ---------------------------------------------------------------- the summary

_ALERT = re.compile(r"server (alert|error): (.*)")
_INTERRUPT = re.compile(r"interrupted by (.*)")


def _distinct(lines: list[Line], limit: int = 8) -> list[dict]:
    counts: Counter = Counter()
    last: dict[str, datetime] = {}
    for ln in lines:
        text = re.sub(r"'session_id': '[^']*'", "", redact(ln.message))
        key = re.sub(r"\d+", "#", text)[:200]
        counts[key] += 1
        last[key] = ln.when
    return [
        {"what": k, "times": n, "last": f"{last[k]:%H:%M:%S}"}
        for k, n in counts.most_common(limit)
    ]


def summarise(lines: list[Line], minutes: float, now: datetime | None = None) -> dict:
    """What usually explains a complaint, for the last `minutes`."""
    now = now or datetime.now()
    recent = window(lines, minutes, now)
    if not recent:
        return {
            "window_minutes": minutes,
            "note": "No log lines in that window: the app may not have been "
            "running, or logging is off.",
        }

    def has(text: str, ln: Line) -> bool:
        return text in ln.message

    problems = [ln for ln in recent if ln.rank >= 40]
    warnings = [ln for ln in recent if ln.rank == 30]
    alerts = [ln for ln in recent if _ALERT.search(ln.message)]
    drops = [
        ln
        for ln in recent
        if has("protocol channel closed", ln) or has("Connection lost", ln)
    ]
    by_server = [ln for ln in recent if has("closed cleanly by the server", ln)]
    reconnects = [ln for ln in recent if "reconnect" in ln.message.lower()]
    interrupts = [ln for ln in recent if _INTERRUPT.search(ln.message)]
    echo_ignored = [ln for ln in recent if has("ignoring own echo", ln)]
    underflows = [ln for ln in recent if "underflow" in ln.message.lower()]
    wake = [ln for ln in recent if has("wake word detected", ln)]
    states = [ln for ln in recent if has("device state:", ln)]
    starts = [ln for ln in lines if has("plugins sorted topologically", ln)]
    ambient = [ln for ln in recent if ln.message.startswith("ambient:")]

    out: dict = {
        "window_minutes": minutes,
        "now": f"{now:%Y-%m-%d %H:%M:%S}",
        "app_last_started": f"{starts[-1].when:%Y-%m-%d %H:%M:%S}" if starts else None,
        "errors": len(problems),
        "warnings": len(warnings),
        "connection_drops": len(drops),
        "drops_started_by_the_server": len(by_server),
        "reconnect_messages": len(reconnects),
        "interruptions_of_the_assistant": len(interrupts),
        "own_echo_ignored": len(echo_ignored),
        "audio_underflows": len(underflows),
        "wake_word_detections": len(wake),
        "ambient_sound_events": len(ambient),
    }
    if states:
        out["last_state_change"] = (
            f"{states[-1].when:%H:%M:%S} {states[-1].message[-40:]}"
        )
    if alerts:
        out["server_messages"] = _distinct(alerts)
    if problems:
        out["error_kinds"] = _distinct(problems)
    if warnings:
        out["warning_kinds"] = _distinct(
            [w for w in warnings if not _ALERT.search(w.message)]
        )
    if interrupts:
        out["last_interruptions"] = [
            f"{ln.when:%H:%M:%S} {redact(ln.message)}"[:300] for ln in interrupts[-3:]
        ]
    return out
