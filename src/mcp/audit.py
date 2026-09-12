"""Append-only audit log of every tool the assistant runs.

The assistant can now write files, run Python, read hardware and query the web,
driven by whoever is speaking. When something unexpected happens - a file
changed, a reminder nobody set, an odd command - the first question is "what did
it actually do", and the normal app log buries that between audio frames.

One JSON object per line in the user data dir, so it survives restarts and can
be read with tail, grep or jq. Failures here are swallowed: audit logging must
never be the reason a tool call breaks.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.logging import get_logger
from src.utils.resource_finder import get_user_data_dir

logger = get_logger()

MAX_ARG_CHARS = 400
MAX_RESULT_CHARS = 400
_lock = threading.Lock()


def path() -> Path:
    p = get_user_data_dir() / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _clip(value: Any, limit: int) -> Any:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = text.replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def record(tool: str, args: Any, *, ok: bool, result: Any = None,
           error: str | None = None, ms: int | None = None) -> None:
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "args": _clip(args, MAX_ARG_CHARS),
        "ok": ok,
    }
    if ms is not None:
        entry["ms"] = ms
    if error:
        entry["error"] = _clip(error, MAX_RESULT_CHARS)
    elif result is not None:
        entry["result"] = _clip(result, MAX_RESULT_CHARS)
    try:
        line = json.dumps(entry, ensure_ascii=False)
        with _lock, open(path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:  # never break a tool call over logging
        logger.debug(f"audit write failed: {e}")


def tail(limit: int = 20, tool: str | None = None) -> list[dict]:
    """Most recent entries, newest last."""
    p = path()
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-2000:]
    except Exception:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if tool and entry.get("tool") != tool:
            continue
        out.append(entry)
    return out[-max(1, min(int(limit), 200)):]
