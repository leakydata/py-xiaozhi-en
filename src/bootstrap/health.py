"""The startup health gate, and what happens when audio is unavailable.

Nothing to do with the session itself: it only decides, from which plugins failed and the environment, whether to exit or carry on degraded.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

# exit straight away on a startup failure, rather than sitting in a zombie wait_shutdown
CRITICAL_PLUGINS = ("ui",)
# audio is critical by default; with XIAOZHI_DEGRADED_AUDIO=1 a failure degrades instead of exiting
AUDIO_CRITICAL = True

DEGRADED_AUDIO_NOTICE = "Running without audio - no microphone or speaker was available. The settings still work; restart once the device is fixed."


class _PluginHealth(Protocol):
    def is_failed(self, name: str) -> bool: ...


def audio_is_fatal() -> bool:
    """Whether an audio failure should end the process.

    - XIAOZHI_DISABLE_AUDIO=1: deliberately off, so not a failure at all
    - XIAOZHI_DEGRADED_AUDIO=1: a failure carries on degraded, with the UI and settings usable
    - otherwise: an audio failure exits with status 1
    """
    if os.getenv("XIAOZHI_DISABLE_AUDIO") == "1":
        return False
    if os.getenv("XIAOZHI_DEGRADED_AUDIO") == "1":
        return False
    return AUDIO_CRITICAL


def check_critical_plugins(plugins: _PluginHealth) -> Optional[str]:
    """Check that the critical plugins came up.

    Returns:
        a description of what went wrong, or None when everything is healthy
    """
    failed: list[str] = []
    for name in CRITICAL_PLUGINS:
        if plugins.is_failed(name):
            failed.append(name)

    if audio_is_fatal() and plugins.is_failed("audio"):
        failed.append("audio")

    if not failed:
        return None

    hints = []
    if "audio" in failed:
        hints.append(
            "To run without audio at all, set XIAOZHI_DISABLE_AUDIO=1. "
            "To carry on without a microphone, with the UI and settings still usable, set XIAOZHI_DEGRADED_AUDIO=1."
        )
    return (
        f"These critical plugins failed to start: {', '.join(failed)}. "
        "The application will exit rather than sit there doing nothing."
        + (" " + " ".join(hints) if hints else "")
    )
