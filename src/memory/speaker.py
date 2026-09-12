"""Current speaker, if the server tells us who is talking.

Speaker recognition on xiaozhi is a server-side feature: it identifies the
voice from the audio it already receives and injects the name into the model's
context, so the name comes back inside the spoken reply rather than as
metadata. Nothing needs sending from this end for that to work.

A live capture of a text-driven session showed stt carrying only
{type, text, session_id} - no identity field. That capture cannot rule out a
field appearing for real audio, or once voiceprints are enrolled for a device,
so this module watches for one and records it instead of discarding it.

The value is programmatic use: tagging memories with who said them, per-person
reminders, and gating barge-in so only a known speaker can interrupt.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.logging import get_logger

logger = get_logger()

# Field names worth watching. The protocol is not documented for this, so we
# accept the plausible spellings rather than guessing exactly one.
_FIELDS = ("speaker", "speaker_id", "speaker_name", "user", "user_name", "username")

_lock = threading.Lock()
_current: Optional[str] = None
_reported: set[str] = set()


def note_message(message: Any) -> None:
    """Inspect an inbound protocol message for a speaker identity."""
    if not isinstance(message, dict):
        return
    if message.get("type") not in ("stt", "llm"):
        return
    for field in _FIELDS:
        value = message.get(field)
        if value is None:
            continue
        name = str(value).strip()
        if not name:
            continue
        # Log the first sighting of each field so it is obvious the server
        # started sending identity, rather than it silently changing behaviour.
        if field not in _reported:
            _reported.add(field)
            logger.info(f"the server sent a speaker identity: {field}={name!r}")
        set_current(name)
        return


def set_current(name: Optional[str]) -> None:
    global _current
    with _lock:
        if name != _current:
            _current = name
            logger.debug(f"current speaker: {name!r}")


def get_current() -> Optional[str]:
    with _lock:
        return _current


def clear() -> None:
    set_current(None)
