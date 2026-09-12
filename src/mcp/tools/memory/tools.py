"""Memory MCP tools: remember, recall, reminders.

These are what turn the local store into something the assistant can actually
use. Without them every conversation starts from zero.

Times are handled generously: the model may pass an ISO timestamp or a plain
phrase ("in 30 minutes", "tomorrow 9am"), and the resolved time is echoed back
so it can confirm out loud rather than silently guessing wrong.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.logging import get_logger
from src.memory.speaker import get_current as get_current_speaker
from src.memory.store import get_memory

logger = get_logger()

_REL = re.compile(
    r"^\s*(?:in\s+)?(\d+)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\b",
    re.I,
)
_UNITS = {
    "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
    "d": "days", "day": "days", "days": "days",
    "w": "weeks", "week": "weeks", "weeks": "weeks",
}
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _parse_when(when: str) -> Optional[datetime]:
    """ISO first, then a few spoken forms. Returns tz-aware local time."""
    when = (when or "").strip()
    if not when:
        return None
    try:
        dt = datetime.fromisoformat(when)
        return dt if dt.tzinfo else dt.astimezone()
    except ValueError:
        pass

    now = _local_now()
    low = when.lower()

    m = _REL.match(low)
    if m:
        return now + timedelta(**{_UNITS[m.group(2).lower()]: int(m.group(1))})

    base = None
    if low.startswith("tomorrow"):
        base = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif low.startswith("today") or low.startswith("tonight"):
        base = now.replace(second=0, microsecond=0)
        if low.startswith("tonight"):
            base = base.replace(hour=19, minute=0)
    if base is not None:
        c = _CLOCK.search(low.split(" ", 1)[1] if " " in low else "")
        if c:
            hour = int(c.group(1)) % 12
            if (c.group(3) or "").lower() == "pm":
                hour += 12
            elif not c.group(3) and hour < 8:
                hour += 12  # a bare "at 3" almost always means the afternoon
            base = base.replace(hour=hour, minute=int(c.group(2) or 0))
        return base
    return None


def _fmt(dt: datetime) -> str:
    return dt.astimezone().strftime("%A %d %b %Y at %-I:%M %p")


def _row(r: dict) -> dict:
    out = {"id": r["id"], "kind": r["kind"], "text": r["text"]}
    if r.get("due_at"):
        try:
            out["due"] = _fmt(datetime.fromisoformat(r["due_at"]))
        except Exception:
            out["due"] = r["due_at"]
    if r.get("speaker"):
        out["speaker"] = r["speaker"]
    if r.get("score") is not None:
        out["relevance"] = r["score"]
    return out


async def remember_payload(args: dict[str, Any]) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return json.dumps({"error": "Nothing to remember - text was empty."})
    kind = str(args.get("kind", "note")).lower()
    if kind not in ("note", "fact", "event"):
        kind = "note"
    speaker = str(args.get("speaker", "") or "") or get_current_speaker()
    tags = str(args.get("tags", "") or "") or None
    try:
        nid = get_memory().add(text, kind=kind, speaker=speaker, tags=tags)
    except Exception as e:
        logger.warning(f"[Memory] remember failed: {e}")
        return json.dumps({"error": f"Could not save: {e}"})
    logger.info(f"[Memory] remembered #{nid} ({kind}): {text[:60]}")
    return json.dumps({"saved": True, "id": nid, "kind": kind, "text": text})


async def recall_payload(args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "No query given."})
    try:
        k = max(1, min(10, int(args.get("max_results", 5))))
    except (TypeError, ValueError):
        k = 5
    try:
        rows = get_memory().search(query, k=k)
    except Exception as e:
        logger.warning(f"[Memory] recall failed: {e}")
        return json.dumps({"error": f"Could not search: {e}"})
    if not rows:
        return json.dumps(
            {"query": query, "results": [],
             "note": "Nothing relevant stored. Say so rather than guessing."}
        )
    return json.dumps({"query": query, "results": [_row(r) for r in rows]},
                      ensure_ascii=False)


async def set_reminder_payload(args: dict[str, Any]) -> str:
    text = str(args.get("text", "")).strip()
    when = str(args.get("when", "")).strip()
    if not text:
        return json.dumps({"error": "No reminder text given."})
    if not when:
        return json.dumps({"error": "No time given. Ask when they want reminding."})
    dt = _parse_when(when)
    if dt is None:
        return json.dumps({
            "error": f"Could not understand the time {when!r}. Ask for a clearer "
                     "time, or pass an ISO timestamp."
        })
    speaker = str(args.get("speaker", "") or "") or get_current_speaker()
    try:
        nid = get_memory().add(
            text, kind="reminder",
            due_at=dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
            speaker=speaker,
        )
    except Exception as e:
        return json.dumps({"error": f"Could not save the reminder: {e}"})
    logger.info(f"[Memory] reminder #{nid} at {dt.isoformat()}: {text[:50]}")
    # echo the resolved time so the assistant can confirm it out loud
    return json.dumps({"saved": True, "id": nid, "text": text, "due": _fmt(dt)})


async def list_reminders_payload(args: dict[str, Any]) -> str:
    scope = str(args.get("scope", "upcoming")).lower()
    mem = get_memory()
    try:
        if scope == "due":
            rows = mem.due()
        elif scope == "all":
            rows = mem.recent(limit=20, kind="reminder")
        else:
            rows = mem.upcoming()
    except Exception as e:
        return json.dumps({"error": f"Could not list reminders: {e}"})
    return json.dumps(
        {"scope": scope, "now": _fmt(_local_now()),
         "reminders": [_row(r) for r in rows]},
        ensure_ascii=False,
    )


async def complete_reminder_payload(args: dict[str, Any]) -> str:
    try:
        nid = int(args.get("id", 0))
    except (TypeError, ValueError):
        return json.dumps({"error": "id must be a number."})
    ok = get_memory().complete(nid)
    return json.dumps({"completed": ok, "id": nid} if ok
                      else {"error": f"No reminder with id {nid}."})


async def memory_topics_payload(args: dict[str, Any]) -> str:
    try:
        groups = get_memory().topics()
    except Exception as e:
        logger.warning(f"[Memory] topics failed: {e}")
        return json.dumps({"error": f"Could not group memories: {e}"})
    if not groups:
        return json.dumps({"topics": [],
                           "note": "Not enough related memories to form themes yet."})
    return json.dumps({"topics": groups}, ensure_ascii=False)


async def current_time_payload(args: dict[str, Any]) -> str:
    now = _local_now()
    return json.dumps({
        "local_time": _fmt(now),
        "iso": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
    })
