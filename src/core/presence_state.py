"""A few timestamps the session and the room plugins share.

The session decides whether to redial after the server hangs up; the ambient
plugin decides whether to check in or wake on a voice; the reminders plugin
decides when it may interrupt. They need to agree on the same facts - when the
user last spoke, whether they said goodbye, whether the session just redialled
on its own - so those live here rather than in any one of them.
"""

from __future__ import annotations

import time

_last_user_speech = -1e9
_last_activity = -1e9
_last_redial = -1e9
_stand_down_until = -1e9


def now() -> float:
    return time.monotonic()


def user_spoke() -> None:
    """The server transcribed something the user said."""
    global _last_user_speech, _last_activity
    _last_user_speech = _last_activity = time.monotonic()


def activity() -> None:
    """Any conversation traffic: the assistant replying, a transcript."""
    global _last_activity
    _last_activity = time.monotonic()


def redialled() -> None:
    """The session reconnected on its own after a quiet hang-up."""
    global _last_redial
    _last_redial = time.monotonic()


def stand_down(seconds: float) -> None:
    """The user said goodbye: nothing should start talking for a while."""
    global _stand_down_until
    _stand_down_until = time.monotonic() + seconds


def standing_down() -> bool:
    return time.monotonic() < _stand_down_until


def last_user_speech() -> float:
    return _last_user_speech


def last_activity() -> float:
    return _last_activity


def last_redial() -> float:
    return _last_redial


def reset() -> None:
    """For tests."""
    global _last_user_speech, _last_activity, _last_redial, _stand_down_until
    _last_user_speech = _last_activity = _last_redial = _stand_down_until = -1e9
