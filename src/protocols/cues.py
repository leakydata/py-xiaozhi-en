"""Short cues the app sends as if the user had spoken them.

The only way to make the assistant say something unprompted is to send text as
a `listen`/`detect` message - the path a wake word takes. xiaozhi.me rejects
anything longer than a wake word ("Detect is only for wake words, do not send
long texts"): every message sent this way in the log, 22 to 192 characters, was
refused, so a check-in, a sound worth mentioning or a due reminder was silently
dropped. So the app sends a short fixed cue instead, and the personality text
and the briefing tell the assistant what each cue means.

The limit is not documented. scripts/cue_probe.py measured it on 2026-11-15:
texts of 2-21 characters were accepted (the server transcribes them as the user
speaking and she answers), so the cues are worded to make sense on their own -
"ask if I'm here" made her ask "Are you there?" even without being told what it
means. Every refusal is still recorded so callers can tell sent from heard.
"""

from __future__ import annotations

import asyncio
import time

#: No cue is longer than this; 21 was the longest measured to be accepted.
MAX_CHARS = 18

#: Call list_reminders(scope="due"), announce each, then complete_reminder.
REMINDER = "read due reminders"
#: The server ended the session but someone is still around: ask briefly
#: whether they want to keep talking.
STILL_THERE = "ask if I'm here"
#: A notable sound in a quiet room: call ambient_sounds and mention it if it
#: matters, in one sentence, without a question.
ROOM_SOUND = "check room sounds"

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


def is_echo(text: str, within_s: float = 15.0) -> bool:
    """Is this transcript just our own cue coming back?

    The server reports an accepted cue as `stt`, exactly as if the user had
    said it ("still there?" at 21:49:11 was logged as the user speaking). It
    must not count as the user talking: that would reset the quiet-redial
    budget, look like a reply to a check-in, and land in the transcript.
    """
    # only the app's own cues: text typed in the chat box goes the same way
    # and is the user's
    if _last_sent_text not in ALL or time.monotonic() - _last_sent_at > within_s:
        return False
    norm = " ".join(str(text or "").lower().split()).strip(" .!?")
    return bool(norm) and norm == " ".join(_last_sent_text.lower().split()).strip(
        " .!?"
    )


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
