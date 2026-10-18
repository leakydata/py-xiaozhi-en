"""Name the sounds the microphone hears that are not speech.

The assistant only ever receives words. Everything else the microphone picks up
- a keyboard, a dog, a kettle, music from the next room, a smoke alarm - is
thrown away, so it cannot notice what is going on around the person it is
talking to. This keeps a short, honest log of those sounds and hands the model a
digest on request.

An audio-tagging model (CED, 527 AudioSet classes, run by sherpa-onnx) labels a
sliding window of the microphone. Speech labels are dropped on purpose: what
was said already reaches the assistant as words, and the server keeps the
voice-recognition it does from the audio. Sounds made by the assistant itself
are kept out by skipping any window that overlaps playback.

Nothing here leaves the machine. The model only sees audio that was already
going to the server; what it adds is a few words of text the assistant can ask
for through the `ambient_sounds` tool.
"""

from __future__ import annotations

import csv
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.logging import get_logger

logger = get_logger()

SAMPLE_RATE = 16_000

#: Labels that are the voice, or a description of the room rather than a sound
#: in it. Matched against the full AudioSet display name.
IGNORED = frozenset(
    {
        "Speech",
        "Male speech, man speaking",
        "Female speech, woman speaking",
        "Child speech, kid speaking",
        "Conversation",
        "Narration, monologue",
        "Babbling",
        "Speech synthesizer",
        "Hubbub, speech noise, speech babble",
        "Whispering",
        "Shout",
        "Yell",
        "Human voice",
        "Silence",
        "Sound effect",
        "Noise",
        "Environmental noise",
        "White noise",
        "Pink noise",
        "Static",
        "Hum",
        "Mains hum",
        "Vibration",
        "Throbbing",
        "Reverberation",
        "Echo",
        "Inside, small room",
        "Inside, large room or hall",
        "Inside, public space",
        "Outside, urban or manmade",
        "Outside, rural or natural",
    }
)

#: A window is analysed at most this often; the model takes ~15 ms on a CPU.
_WINDOW_S = 3.0
_HOP_S = 1.5
#: Below this RMS the window is just the room being quiet.
_QUIET_RMS = 0.0008
#: Two detections of one label this far apart are the same event.
_MERGE_GAP_S = 12.0
_KEEP_S = 3 * 3600.0
_MAX_EVENTS = 600


@dataclass
class Event:
    label: str
    first: float
    last: float
    hits: int = 1
    peak: float = 0.0

    def confirmed(self) -> bool:
        """One strong detection, or the same one twice, not a single flicker."""
        return self.hits >= 2 or self.peak >= 0.6


def short_name(label: str) -> str:
    """AudioSet writes 'Smoke detector, smoke alarm'; the first name is enough."""
    return label.split(",")[0].strip()


def load_labels(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return [r[2] for r in rows[1:]]


class AmbientSounds:
    """A rolling log of the non-speech sounds heard, fed from the microphone.

    `on_audio_data` is called on the audio thread and only copies samples into
    a buffer. Everything else runs on a worker thread.
    """

    def __init__(
        self,
        *,
        min_confidence: float = 0.35,
        window_s: float = _WINDOW_S,
        hop_s: float = _HOP_S,
        playback_active: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_confidence = min_confidence
        self.window_s = window_s
        self.hop_s = hop_s
        self._playback_active = playback_active or (lambda: False)
        self._clock = clock

        self._lock = threading.Lock()
        self._buffer: deque[np.ndarray] = deque()
        self._buffered = 0
        self._last_playback = -1e9
        self._events: deque[Event] = deque(maxlen=_MAX_EVENTS)
        self._open: dict[str, Event] = {}

        # Time accounting, so the digest can say how much it could not hear.
        self._started = clock()
        self._analysed_s = 0.0
        self._masked_s = 0.0
        self._windows: deque[tuple[float, bool]] = deque()  # (time, analysed)

        self._tagger = None
        self._labels: list[str] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.enabled = False

    # ----------------------------------------------------------- audio thread

    def on_audio_data(self, block: np.ndarray) -> None:
        """Keep the last few seconds of microphone. Cheap: no analysis here."""
        if not self.enabled:
            return
        now = self._clock()
        if self._playback_active():
            self._last_playback = now
        a = np.asarray(block, dtype=np.float32).reshape(-1)
        keep = int(SAMPLE_RATE * (self.window_s + 1.0))
        with self._lock:
            self._buffer.append(a)
            self._buffered += a.size
            while self._buffered - self._buffer[0].size >= keep:
                self._buffered -= self._buffer.popleft().size

    def _take_window(self) -> np.ndarray | None:
        need = int(SAMPLE_RATE * self.window_s)
        with self._lock:
            if self._buffered < need:
                return None
            joined = np.concatenate(list(self._buffer))
        return joined[-need:]

    # ----------------------------------------------------------- the log

    def ingest(self, detections: list[tuple[str, float]], now: float) -> None:
        """Fold one window's labels into the event log."""
        for label, prob in detections:
            if prob < self.min_confidence or label in IGNORED:
                continue
            event = self._open.get(label)
            if event is not None and now - event.last <= _MERGE_GAP_S:
                event.last = now
                event.hits += 1
                event.peak = max(event.peak, prob)
            else:
                event = Event(label, now, now, 1, prob)
                self._open[label] = event
                self._events.append(event)
        cutoff = now - _KEEP_S
        while self._events and self._events[0].last < cutoff:
            old = self._events.popleft()
            if self._open.get(old.label) is old:
                del self._open[old.label]

    def note_window(self, now: float, analysed: bool) -> None:
        self._windows.append((now, analysed))
        cutoff = now - _KEEP_S
        while self._windows and self._windows[0][0] < cutoff:
            self._windows.popleft()

    # ----------------------------------------------------------- reading it

    def heard(self, minutes: float = 10.0, now: float | None = None) -> dict:
        """What was heard in the last `minutes`, newest first."""
        now = self._clock() if now is None else now
        span = max(1.0, minutes * 60.0)
        since = now - span
        by_label: dict[str, list[Event]] = {}
        for e in self._events:
            if e.confirmed() and e.last >= since:
                by_label.setdefault(e.label, []).append(e)

        sounds = []
        for label, events in by_label.items():
            last = max(e.last for e in events)
            first = min(e.first for e in events)
            sounds.append(
                {
                    "sound": short_name(label),
                    "times": len(events),
                    "last_seconds_ago": int(now - last),
                    "first_seconds_ago": int(now - first),
                    "going_on_now": now - last <= 2 * self.hop_s + 1.0,
                    "confidence": round(max(e.peak for e in events), 2),
                }
            )
        sounds.sort(key=lambda s: s["last_seconds_ago"])

        recent = [(t, ok) for t, ok in self._windows if t >= since]
        listened = sum(1 for _, ok in recent if ok)
        coverage = listened / len(recent) if recent else 0.0
        return {
            "window_minutes": round(minutes, 1),
            "sounds": sounds,
            "listened_fraction": round(coverage, 2),
            "listening": self.enabled,
        }

    def describe(self, minutes: float = 10.0, now: float | None = None) -> str:
        """The same thing as a sentence or two, for a briefing."""
        data = self.heard(minutes, now)
        if not data["listening"]:
            return "Ambient sound awareness is not running."
        if not data["sounds"]:
            return f"Nothing but quiet or speech in the last {minutes:g} minutes."
        parts = []
        for s in data["sounds"][:6]:
            if s["going_on_now"]:
                parts.append(f"{s['sound']} (happening now)")
            else:
                parts.append(f"{s['sound']} ({_ago(s['last_seconds_ago'])})")
        return "Background sounds lately: " + ", ".join(parts) + "."

    # ----------------------------------------------------------- the worker

    def load(self, model_dir: Path, num_threads: int = 2) -> bool:
        """Load the model. False when it is missing or sherpa cannot start it."""
        model = model_dir / "model.int8.onnx"
        labels = model_dir / "class_labels_indices.csv"
        if not model.exists() or not labels.exists():
            logger.info(f"ambient sounds: no model in {model_dir}, not listening")
            return False
        try:
            import sherpa_onnx

            config = sherpa_onnx.AudioTaggingConfig(
                model=sherpa_onnx.AudioTaggingModelConfig(
                    ced=str(model), num_threads=num_threads, provider="cpu"
                ),
                labels=str(labels),
                top_k=8,
            )
            self._tagger = sherpa_onnx.AudioTagging(config)
            self._labels = load_labels(labels)
            return True
        except Exception as e:
            logger.warning(f"ambient sounds: could not load the model: {e}")
            return False

    def start(self) -> None:
        if self._tagger is None or self._thread is not None:
            return
        self.enabled = True
        self._stop.clear()
        self._started = self._clock()
        self._thread = threading.Thread(
            target=self._run, name="ambient-sounds", daemon=True
        )
        self._thread.start()
        logger.info("ambient sounds: listening for non-speech sounds")

    def stop(self) -> None:
        self.enabled = False
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=3.0)
        self._tagger = None

    def _run(self) -> None:
        while not self._stop.wait(self.hop_s):
            try:
                self.step()
            except Exception as e:
                logger.warning(f"ambient sounds: analysis failed: {e}")

    def step(self) -> None:
        """Analyse the latest window, unless it cannot be trusted."""
        now = self._clock()
        window = self._take_window()
        if window is None:
            return
        # The assistant talking, or music the app is playing, is not the room.
        if now - self._last_playback < self.window_s:
            self.note_window(now, False)
            return
        if float(np.sqrt(np.mean(window * window))) < _QUIET_RMS:
            self.note_window(now, True)
            return
        stream = self._tagger.create_stream()
        stream.accept_waveform(SAMPLE_RATE, window)
        results = self._tagger.compute(stream)
        self.note_window(now, True)
        self.ingest([(e.name, float(e.prob)) for e in results], now)


def _ago(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds ago"
    return f"{round(seconds / 60)} minutes ago"


_instance: AmbientSounds | None = None


def get_ambient() -> AmbientSounds | None:
    """The running instance, or None when ambient awareness is off."""
    return _instance


def set_ambient(value: AmbientSounds | None) -> None:
    global _instance
    _instance = value
