# -*- coding: utf-8 -*-
"""Shared audio level meters for UI animation (lip-sync, VU rings).

Written from the PortAudio callback threads, read from the UI thread. Values are
plain floats, so reads/writes are atomic under the GIL — no lock is taken, because
the audio callbacks must stay non-blocking. A dropped or torn update here is
visually irrelevant: the next callback overwrites it milliseconds later.

Deliberately NOT an EventBus event. Levels update at the audio callback rate
(50-100 Hz); pushing that through the async bus would create thousands of tasks
per minute and require call_soon_threadsafe from the audio thread. Polling a float
at the UI's own refresh rate is cheaper and has no threading hazard.
"""

from __future__ import annotations

import numpy as np

# Rise fast so consonants register, fall slowly so the mouth doesn't strobe.
_ATTACK = 0.6
_RELEASE = 0.82
# Speech RMS sits around 0.01-0.2; sqrt curve + gain maps that to a usable 0-1.
_GAIN = 2.4

_input_level = 0.0
_output_level = 0.0


def _shape(block) -> float:
    """RMS of a float32 block, perceptually curved and clamped to 0..1."""
    try:
        a = np.asarray(block, dtype=np.float32).reshape(-1)
        if a.size == 0:
            return 0.0
        rms = float(np.sqrt(np.dot(a, a) / a.size))
        if not np.isfinite(rms):
            return 0.0
        return min(1.0, (rms**0.5) * _GAIN)
    except Exception:
        return 0.0


def _smooth(prev: float, target: float) -> float:
    if target > prev:
        return prev + (target - prev) * _ATTACK
    return prev * _RELEASE


def feed_input(block) -> None:
    """Called from the audio input callback (microphone)."""
    global _input_level
    _input_level = _smooth(_input_level, _shape(block))


def feed_output(block) -> None:
    """Called from the audio output callback (TTS + music actually played)."""
    global _output_level
    _output_level = _smooth(_output_level, _shape(block))


def get_input_level() -> float:
    return _input_level


def get_output_level() -> float:
    return _output_level


def reset() -> None:
    global _input_level, _output_level
    _input_level = 0.0
    _output_level = 0.0
