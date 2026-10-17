"""Tell the user cutting in apart from the assistant's own voice in the microphone.

Over speakers, the microphone hears the reply. The speech models transcribe it,
and words that were never spoken by anyone in the room arrive while the
assistant is talking - enough of them to read as an interruption, so the reply
is cut off a second or two in, every time.

turn_judge.is_interruption already drops words that match what the assistant is
saying, but that defence leaks badly in practice:

- it needs the text, and this server sends `sentence_start` rarely or not at
  all - in one measured abort the echo filter had nothing at all to compare
  against, because no sentence text had arrived since the turn began;
- echo is transcribed *wrongly*. "...unless you ask for music first" came back
  as "I'm staying on the street". Mis-transcribed echo matches no intended
  word, so word comparison cannot catch it even when the text is there.

So decide it from the audio instead, where echo is obvious: the microphone
level tracks the playback level, scaled by however well the room couples the
speakers back into the microphone. That coupling is unknown - it depends on
volume, placement and the room - so it is measured continuously, as a low
percentile of the recent microphone-to-playback ratios. The user talking can
only push a ratio *up*, so taking the quiet end of the distribution ignores
their voice without having to detect it first.

The user talking adds energy the playback cannot explain, either on top of the
reply or in the gaps between its sentences. Only then is a cut-in allowed.

Levels come from the audio callbacks, like audio_levels - plain floats written
from the PortAudio threads and read from the event loop, no lock, because those
callbacks must not block. The near side is taken *after* echo cancellation, so
with AEC on the coupling it learns is simply smaller and the same test holds.
"""

from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

#: Below this RMS, the playback is treated as silent - nothing is coming out of
#: the speakers, so nothing is expected back.
_SILENCE = 0.002
#: The microphone's own noise floor has to be measured, not assumed. This
#: machine's idle microphone sits at an RMS of 0.0027, which a fixed 0.002
#: floor exceeded in 67% of idle blocks - so every gap between the assistant's
#: sentences read as the user talking, and the gate opened exactly where it
#: was needed. Until enough quiet has been seen, this stands in, chosen to sit
#: above a typical room.
_FLOOR_START = 0.01
#: Taken from the loud end of the quiet moments, so ordinary fluctuation in the
#: room does not count as a voice.
_FLOOR_PERCENTILE = 90.0
_FLOOR_S = 6.0
#: How long a run of far-end levels to keep, to line up with delayed echo.
_HISTORY_S = 2.0
#: How long a run of microphone-to-playback ratios the coupling is taken from.
#: It needs to span the gaps in the user's speech, since those are the frames
#: that show the room's own echo on its own.
_LEARN_S = 4.0
#: Which of those ratios to call the coupling. A low percentile rather than a
#: running average, because the user talking can only ever push the ratio *up*:
#: a statistic taken from the bottom of the distribution ignores their voice by
#: construction. An average has to be defended against it with freeze
#: heuristics, and those turn out to trap the estimate - started too low, one
#: measured 0.139 against a true 0.4 after forty seconds and never recovered,
#: leaving the gate permanently open. This cannot get stuck: it is recomputed
#: from the last few seconds rather than carried forward.
_PERCENTILE = 10.0
#: Recompute that at most this often; it is read from an audio callback.
_RECOMPUTE_EVERY = 10


class EchoGate:
    """Learns how much of the playback comes back, and spots the rest."""

    def __init__(
        self,
        margin_db: float = 9.0,
        delay_s: float = 0.06,
        coupling_start: float = 0.3,
    ) -> None:
        #: How far above the predicted echo the microphone has to be.
        self.margin = 10.0 ** (margin_db / 20.0)
        #: Roughly how long the reply takes to leave the speakers, cross the
        #: room and arrive back, so near frames compare against the right
        #: far frames.
        self.delay_s = delay_s
        #: Starts pessimistic (assume a lot comes back) so the first moments
        #: cannot produce a false cut-in, then settles to the real value.
        self._coupling = coupling_start
        self._coupling_start = coupling_start
        self._far: deque[tuple[float, float]] = deque()
        #: Recent microphone-to-playback ratios, the coupling is drawn from.
        self._ratios: deque[tuple[float, float]] = deque()
        #: Microphone levels from moments with nothing playing: the room's own
        #: noise, which the user has to be heard over.
        self._quiet: deque[tuple[float, float]] = deque()
        self._floor = _FLOOR_START
        self._since_recompute = 0
        self._last_double_talk = 0.0
        self._near = 0.0

    # ------------------------------------------------------------ levels in

    @staticmethod
    def _rms(block) -> float:
        try:
            a = np.asarray(block, dtype=np.float32).reshape(-1)
            if a.size == 0:
                return 0.0
            value = float(np.sqrt(np.dot(a, a) / a.size))
            return value if math.isfinite(value) else 0.0
        except Exception:
            return 0.0

    def feed_far(self, block, now: float | None = None) -> None:
        """The PCM actually written to the device, from the output callback."""
        now = time.monotonic() if now is None else now
        self._far.append((now, self._rms(block)))
        cutoff = now - _HISTORY_S
        while self._far and self._far[0][0] < cutoff:
            self._far.popleft()

    def feed_near(self, block, now: float | None = None) -> None:
        """The microphone after echo cancellation, from the input callback."""
        now = time.monotonic() if now is None else now
        near = self._rms(block)
        self._near = near
        far = self._far_at(now - self.delay_s)

        if far > _SILENCE:
            # Learn the room: how much of what is played comes back. Every
            # frame goes in, the user's included; the percentile discards
            # theirs. Only frames with something actually playing say anything
            # about the coupling.
            self._ratios.append((now, near / far))
            cutoff = now - _LEARN_S
            while self._ratios and self._ratios[0][0] < cutoff:
                self._ratios.popleft()
        else:
            # Nothing playing, so whatever the microphone reads is the room
            # itself - its noise floor, the thing a voice has to rise above.
            self._quiet.append((now, near))
            cutoff = now - _FLOOR_S
            while self._quiet and self._quiet[0][0] < cutoff:
                self._quiet.popleft()

        self._since_recompute += 1
        if self._since_recompute >= _RECOMPUTE_EVERY:
            self._since_recompute = 0
            self._recompute_coupling()
            self._recompute_floor()

        if near > self.threshold(far):
            self._last_double_talk = now

    def _recompute_coupling(self) -> None:
        """The room's own echo: the quiet end of the recent ratios.

        Needs enough of a run to be sure it contains frames without the user
        in them; until then the cautious starting value stands.
        """
        if len(self._ratios) < _RECOMPUTE_EVERY * 2:
            return
        values = np.fromiter((r for _, r in self._ratios), dtype=np.float64)
        self._coupling = float(np.percentile(values, _PERCENTILE))

    def _recompute_floor(self) -> None:
        """The room's noise floor, from the moments nothing was playing."""
        if len(self._quiet) < _RECOMPUTE_EVERY * 2:
            return
        values = np.fromiter((v for _, v in self._quiet), dtype=np.float64)
        self._floor = float(np.percentile(values, _FLOOR_PERCENTILE))

    # ------------------------------------------------------------ the verdict

    def _far_at(self, when: float) -> float:
        """The loudest thing played around `when`.

        A window rather than the nearest sample, because the echo of one
        output block smears across several input blocks, and because the exact
        delay is only approximate. Taking the loudest errs towards calling
        things echo, which costs a missed cut-in rather than a severed reply.
        """
        if not self._far:
            return 0.0
        half = 0.06
        window = [rms for t, rms in self._far if when - half <= t <= when + half]
        if window:
            return max(window)
        return self._far[-1][1] if when > self._far[-1][0] else self._far[0][1]

    def threshold(self, far: float) -> float:
        """The microphone level neither the playback nor the room explains."""
        return (self._coupling * far + self._floor) * self.margin

    def recent_double_talk_at(self, now: float, within_s: float = 1.5) -> bool:
        """As recent_double_talk, against a given clock reading."""
        if not self._last_double_talk:
            return False
        return (now - self._last_double_talk) <= within_s

    def recent_double_talk(self, within_s: float = 1.5) -> bool:
        """Has the user been heard over the reply in the last `within_s`?

        A window, because the words that trigger a cut-in are transcribed from
        audio already a moment old.
        """
        return self.recent_double_talk_at(time.monotonic(), within_s)

    @property
    def coupling(self) -> float:
        """The learned share of the playback that returns to the microphone."""
        return self._coupling

    @property
    def noise_floor(self) -> float:
        """The room's measured noise floor, in microphone RMS."""
        return self._floor

    @property
    def near_level(self) -> float:
        return self._near

    def reset(self) -> None:
        """Forget the recent verdict at a turn boundary; keep the room.

        The user was talking right up to the moment the reply starts, and that
        is not a cut-in on it. Their ratios are dropped too: they were measured
        against whatever was playing before, and the percentile would carry
        them into the new turn.
        """
        self._last_double_talk = 0.0
        self._ratios.clear()
        self._coupling = self._coupling_start
        self._since_recompute = 0
        # The noise floor is a property of the room, not of the turn, so it
        # is kept: it is the one measurement worth carrying across.


#: One gate for the process, fed from the audio callbacks and read from the
#: event loop - the same arrangement, and for the same reason, as audio_levels.
_gate = EchoGate()


def get_gate() -> EchoGate:
    return _gate


def feed_far(block) -> None:
    _gate.feed_far(block)


def feed_near(block) -> None:
    _gate.feed_near(block)
