"""The assistant's "mm-hm", "yeah" and "right", in its own voice.

A murmur in any other voice sounds like a second person in the room, so the
clips are recorded from the assistant itself: asked once to say each one as
its own sentence, the app keeps the audio of those sentences. They are stored
under the user data dir and played back, quietly, in the user's pauses.

This module is the store and the recording; when to play one is
turn_judge.backchannel_due, and playing it is the turn-taking plugin's job.
"""

from __future__ import annotations

import random
import re
import time
import wave
from pathlib import Path

import numpy as np

from src.logging import get_logger

logger = get_logger()

#: What gets recorded, and how each might be written back by the server.
FILLERS = {
    "mm-hm": ("mm-hm", "mm hm", "mmhm", "mhm", "mm-hmm", "mm hmm", "mmhmm", "hmm-hmm"),
    "uh-huh": ("uh-huh", "uh huh", "uhhuh", "uh-hu"),
    "yeah": ("yeah", "yea", "yep"),
    "right": ("right",),
    "okay": ("okay", "ok"),
    "i-see": ("i see",),
}

#: What the assistant is asked to say when learning them.
SCRIPT = "Mm-hm. Uh-huh. Yeah. Right. Okay. I see."

_LOOKUP = {v: k for k, vs in FILLERS.items() for v in vs}
_SHORTEST_S, _LONGEST_S = 0.12, 1.6
#: Clips are levelled to this peak, quieter than the assistant's normal speech,
#: the way a murmur is quieter than talking.
_PEAK = 0.35


def filler_name(text: str) -> str | None:
    """'Mm-hm.' -> 'mm-hm'; anything that is not exactly a filler -> None."""
    t = re.sub(r"[^a-z\- ]", "", (text or "").lower()).strip(" -")
    t = re.sub(r"\s+", " ", t)
    return _LOOKUP.get(t)


def trim(pcm: np.ndarray, rate: int) -> np.ndarray | None:
    """Cut the silence either side and level it; None if nothing usable is left."""
    pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if not len(pcm):
        return None
    peak = float(np.max(np.abs(pcm)))
    if peak < 1e-3:
        return None
    loud = np.flatnonzero(np.abs(pcm) > peak * 0.06)
    pad = int(0.03 * rate)
    pcm = pcm[max(loud[0] - pad, 0) : loud[-1] + pad]
    seconds = len(pcm) / rate
    if not (_SHORTEST_S <= seconds <= _LONGEST_S):
        return None
    # A short fade at each end so a cut never clicks.
    fade = min(int(0.01 * rate), len(pcm) // 4)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        pcm[:fade] *= ramp
        pcm[-fade:] *= ramp[::-1]
    return (pcm * (_PEAK / peak)).astype(np.float32)


class BackchannelStore:
    """The clips on disk, and whether a recording is under way."""

    def __init__(self, folder: Path | None = None) -> None:
        if folder is None:
            from src.utils.resource_finder import get_user_data_dir

            folder = Path(get_user_data_dir()) / "backchannels"
        self.folder = Path(folder)
        self._clips: dict[str, tuple[np.ndarray, int]] | None = None
        self._armed_until = 0.0
        self._last_played: str | None = None

    # ---------------------------------------------------------- clips

    def clips(self) -> dict[str, tuple[np.ndarray, int]]:
        if self._clips is None:
            self._clips = {}
            for f in sorted(self.folder.glob("*.wav")):
                try:
                    with wave.open(str(f)) as w:
                        rate = w.getframerate()
                        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                    self._clips[f.stem] = (x.astype(np.float32) / 32768.0, rate)
                except Exception as e:
                    logger.warning(f"backchannel: could not read {f.name}: {e}")
        return self._clips

    def names(self) -> list[str]:
        return sorted(self.clips())

    def save(self, name: str, pcm: np.ndarray, rate: int) -> bool:
        clip = trim(pcm, rate)
        if clip is None:
            logger.info(f"backchannel: '{name}' came out empty or the wrong length")
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{name}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())
        self._clips = None
        logger.info(f"backchannel: learned '{name}' ({len(clip) / rate:.2f}s)")
        return True

    def pick(self, rate: int) -> np.ndarray | None:
        """A clip at the playback rate, avoiding the one played last time."""
        clips = self.clips()
        if not clips:
            return None
        choices = [n for n in clips if n != self._last_played] or list(clips)
        name = random.choice(choices)
        self._last_played = name
        pcm, src = clips[name]
        if src != rate:
            import soxr

            pcm = soxr.resample(pcm, src, rate).astype(np.float32)
        return pcm

    # ---------------------------------------------------------- recording

    def arm(self, seconds: float = 60.0) -> None:
        """Record the assistant's next sentences that are fillers."""
        self._armed_until = time.monotonic() + seconds

    def disarm(self) -> None:
        self._armed_until = 0.0

    @property
    def armed(self) -> bool:
        return time.monotonic() < self._armed_until


class Harvester:
    """Cuts one continuous recording of the assistant into its sentences.

    The text of a sentence arrives as a JSON message and its audio through a
    separate, direct path, so the two do not line up to the frame. Rather than
    start and stop a recording per sentence and risk clipping the first
    syllable, everything is recorded and cut at the boundaries afterwards,
    with the silence either side trimmed.
    """

    def __init__(self) -> None:
        self.marks: list[tuple[int, str]] = []

    def mark(self, sample_index: int, text: str) -> None:
        self.marks.append((sample_index, text))

    def split(self, pcm: np.ndarray, rate: int) -> dict[str, np.ndarray]:
        back = int(0.12 * rate)  # the text can trail its audio slightly
        out: dict[str, np.ndarray] = {}
        for i, (start, text) in enumerate(self.marks):
            name = filler_name(text)
            if name is None or name in out:
                continue
            end = self.marks[i + 1][0] if i + 1 < len(self.marks) else len(pcm)
            seg = pcm[max(start - back, 0) : max(end - back, start)]
            if len(seg):
                out[name] = seg
        return out


_store: BackchannelStore | None = None


def get_store() -> BackchannelStore:
    global _store
    if _store is None:
        _store = BackchannelStore()
    return _store


def describe() -> str:
    names = get_store().names()
    return ", ".join(names) if names else "none yet"
