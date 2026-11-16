"""Short cues the app sends as if the user had spoken them.

The only way to make the assistant say something unprompted is to send text as
a `listen`/`detect` message - the path a wake word takes. xiaozhi.me rejects
anything longer than a wake word ("Detect is only for wake words, do not send
long texts"): every message sent this way in the log, 22 to 192 characters, was
refused, so a check-in, a sound worth mentioning or a due reminder was silently
dropped. So the app sends a short fixed cue instead, and the personality text
and the briefing tell the assistant what each cue means.

The exact limit is not documented. The cues are kept to wake-word length, and
every rejection is recorded so callers can tell sent from heard.
"""

from __future__ import annotations

import asyncio
import time

#: No cue is longer than this. Typical wake words are 2-4 words.
MAX_CHARS = 12

#: Call list_reminders(scope="due"), announce each, then complete_reminder.
REMINDER = "reminder due"
#: The server ended the session but someone is still around: ask briefly
#: whether they want to keep talking.
STILL_THERE = "still there?"
#: A notable sound in a quiet room: call ambient_sounds and mention it if it
#: matters, in one sentence, without a question.
ROOM_SOUND = "room sound"

ALL = (REMINDER, STILL_THERE, ROOM_SOUND)

_REJECTION = "Detect is only for wake words"

_last_sent_at = -1e9
_last_sent_text = ""
_last_rejected_at = -1e9


def note_sent(text: str) -> float:
    """Record a detect text going out; returns when, for accepted()."""
    global _last_sent_at, _last_sent_text
    _last_sent_at = time.monotonic()
    _last_sent_text = text
    return _last_sent_at


def is_rejection(message: dict) -> bool:
    return (
        isinstance(message, dict)
        and message.get("type") == "alert"
        and _REJECTION in str(message.get("message", ""))
    )


def note_rejected() -> str:
    """Record that the server refused the last detect text; returns that text."""
    global _last_rejected_at
    _last_rejected_at = time.monotonic()
    return _last_sent_text


def rejected_since(when: float) -> bool:
    return _last_rejected_at >= when


async def accepted(sent_at: float, wait_s: float = 3.0) -> bool:
    """Give the server a moment to refuse, then say whether it did."""
    await asyncio.sleep(wait_s)
    return not rejected_since(sent_at)
