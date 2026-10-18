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

#: Speech labels. Not logged as sounds, but hearing one is the clearest sign
#: that someone is there.
VOICE = frozenset(
    {
        "Speech",
        "Male speech, man speaking",
        "Female speech, woman speaking",
        "Conversation",
        "Narration, monologue",
    }
)

#: Sounds a person makes just by being there and doing things. None of them is
#: speech, so someone sitting silently at the desk still shows up.
ACTIVITY = frozenset(
    {
        "Typing",
        "Computer keyboard",
        "Typewriter",
        "Clicking",
        "Clickety-clack",
        "Mouse",
        "Writing",
        "Walk, footsteps",
        "Shuffle",
        "Cough",
        "Throat clearing",
        "Sneeze",
        "Snort",
        "Sniff",
        "Breathing",
        "Snoring",
        "Sigh",
        "Gasp",
        "Burping, eructation",
        "Hiccup",
        "Humming",
        "Whistling",
        "Laughter",
        "Chuckle, chortle",
        "Finger snapping",
        "Clapping",
        "Rustle",
        "Zipper (clothing)",
        "Door",
        "Sliding door",
        "Cupboard open or close",
        "Drawer open or close",
        "Dishes, pots, and pans",
        "Cutlery, silverware",
        "Water tap, faucet",
        "Toilet flush",
        "Pour",
        "Microwave oven",
    }
)
#: Sounds worth interrupting a quiet room for: something at the door, a pet in
#: distress, an alarm, something breaking. Deliberately short - the point of a
#: spoken heads-up is that it is rare.
NOTABLE = frozenset(
    {
        "Smoke detector, smoke alarm",
        "Fire alarm",
        "Doorbell",
        "Knock",
        "Bark",
        "Howl",
        "Whimper (dog)",
        "Baby cry, infant cry",
        "Glass",
        "Shatter",
        "Breaking",
        "Crying, sobbing",
        "Telephone bell ringing",
    }
)
#: Sounds a body makes, which the model scores low even when they are real
#: (a snort or a sniff in a quiet room came back at 0.2). They are counted from
#: a lower floor, but still have to be heard twice, so one stray guess is not
#: enough.
BODY = frozenset(
    {
        "Snort",
        "Sniff",
        "Breathing",
        "Sigh",
        "Snoring",
        "Throat clearing",
        "Cough",
        "Sneeze",
        "Gasp",
        "Hiccup",
        "Burping, eructation",
        "Pant",
    }
)
_BODY_CONFIDENCE = 0.2

#: A notable sound has to be at least this sure to be spoken about.
_NOTABLE_CONFIDENCE = 0.6
#: Speech at least this likely counts as a voice.
_VOICE_CONFIDENCE = 0.5

#: A window is analysed at most this often; the model takes ~15 ms on a CPU.
_WINDOW_S = 3.0
_HOP_S = 0.5
#: A short window as well as the long one: a cough or a clap lasts a fraction of
#: a second, and in three seconds of otherwise ordinary room it is too diluted
#: for the model to be sure. The short window sees it nearly on its own.
_SHORT_S = 1.0
#: How recent a sound has to be to count as going on now.
_NOW_S = 4.0
#: A sound that goes on has to turn up in several windows close together, not
#: once here and once there: the model's stray guesses are scattered, a real
#: keyboard or kettle is in every window while it lasts.
_SUSTAIN_S = 4.0
_SUSTAIN_HITS = 3
#: Brief sounds that happen once and are gone. One clear detection is enough:
#: asking for a second would mean it never confirms, because by the next
#: window the sound is over.
TRANSIENT = frozenset(
    {
        "Cough",
        "Throat clearing",
        "Sneeze",
        "Clapping",
        "Finger snapping",
        "Knock",
        "Door",
        "Slam",
        "Thump, thud",
        "Doorbell",
        "Bark",
        "Gasp",
        "Hiccup",
        "Burping, eructation",
        "Glass",
        "Shatter",
        "Breaking",
        "Cupboard open or close",
        "Drawer open or close",
    }
)
_TRANSIENT_CONFIDENCE = 0.4
#: Sure enough on its own, however brief.
_STRONG_CONFIDENCE = 0.6

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
        ignore: tuple[str, ...] = (),
        window_s: float = _WINDOW_S,
        hop_s: float = _HOP_S,
        playback_active: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_confidence = min_confidence
        self._ignore = {x.strip().lower() for x in ignore if x and x.strip()}
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
        self._recent: dict[str, deque[tuple[float, float]]] = {}
        self._last_voice: float | None = None
        self._tick = 0

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

    def _take_window(self, seconds: float | None = None) -> np.ndarray | None:
        need = int(SAMPLE_RATE * (self.window_s if seconds is None else seconds))
        with self._lock:
            if self._buffered < need:
                return None
            joined = np.concatenate(list(self._buffer))
        return joined[-need:]

    # ----------------------------------------------------------- the log

    def _corroborated(self, label: str, prob: float, hist) -> bool:
        """Is this label real enough to log, given the windows just before?"""
        if prob >= _STRONG_CONFIDENCE:
            return True
        if label in TRANSIENT and prob >= _TRANSIENT_CONFIDENCE:
            return True
        needed = 2 if label in BODY else _SUSTAIN_HITS
        return len(hist) >= needed

    def ingest(self, detections: list[tuple[str, float]], now: float) -> None:
        """Fold one tick's labels into the event log."""
        for label, prob in detections:
            if label in VOICE and prob >= _VOICE_CONFIDENCE:
                if self._last_voice is None or now - self._last_voice > _MERGE_GAP_S:
                    logger.info("ambient: heard a voice")
                self._last_voice = now
            floor = self.min_confidence
            if label in BODY:
                floor = min(floor, _BODY_CONFIDENCE)
            if prob < floor or label in IGNORED:
                continue
            if (
                label.lower() in self._ignore
                or short_name(label).lower() in self._ignore
            ):
                continue

            hist = self._recent.setdefault(label, deque())
            hist.append((now, prob))
            while hist and hist[0][0] < now - _SUSTAIN_S:
                hist.popleft()
            if not self._corroborated(label, prob, hist):
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
                # One line when a sound is first counted, so `tail -f` on the
                # log shows what the room is being heard as.
                logger.info(f"ambient: heard {short_name(label)} ({prob:.2f})")
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
        for e in tuple(self._events):
            if e.last >= since:
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
                    "going_on_now": now - last <= _NOW_S,
                    "confidence": round(max(e.peak for e in events), 2),
                }
            )
        sounds.sort(key=lambda s: s["last_seconds_ago"])

        recent = [(t, ok) for t, ok in tuple(self._windows) if t >= since]
        listened = sum(1 for _, ok in recent if ok)
        coverage = listened / len(recent) if recent else 0.0
        return {
            "window_minutes": round(minutes, 1),
            "presence": self.presence(now),
            "sounds": sounds,
            "listened_fraction": round(coverage, 2),
            "listening": self.enabled,
        }

    @property
    def last_voice(self) -> float | None:
        """When a voice was last heard, on this object's clock."""
        return self._last_voice

    def notable_since(self, since: float) -> list[Event]:
        """Confirmed sounds from the NOTABLE list heard after `since`."""
        return [
            e
            for e in tuple(self._events)
            if e.label in NOTABLE and e.peak >= _NOTABLE_CONFIDENCE and e.last > since
        ]

    def presence(self, now: float | None = None) -> dict:
        """When someone was last audibly around: a voice, or just doing things.

        Silence is not absence - reading, thinking and sleeping make no sound -
        so this reports when the last sign was, not whether anyone left.
        """
        now = self._clock() if now is None else now
        last, what = None, None
        for e in tuple(self._events):
            if e.label in ACTIVITY and (last is None or e.last > last):
                last, what = e.last, short_name(e.label)
        if self._last_voice is not None and (last is None or self._last_voice > last):
            last, what = self._last_voice, "a voice"
        if last is None:
            return {
                "last_sign_seconds_ago": None,
                "last_sign": None,
                "state": "no sign yet",
            }
        ago = int(now - last)
        if ago <= 20:
            state = "active right now"
        elif ago <= 180:
            state = "active a moment ago"
        else:
            state = "no sound of anyone for a while"
        return {"last_sign_seconds_ago": ago, "last_sign": what, "state": state}

    def now_line(self, now: float | None = None) -> str:
        """A few words for the screen: what is being heard right now."""
        now = self._clock() if now is None else now
        if not self.enabled:
            return ""
        sounds = self.heard(1.0, now)["sounds"]
        parts = []
        if self._last_voice is not None and now - self._last_voice <= _NOW_S:
            parts.append("a voice")
        parts += [s["sound"] for s in sounds if s["going_on_now"]]
        if parts:
            return "Hearing: " + " · ".join(parts[:4])
        if sounds:
            return f"Just heard: {sounds[0]['sound']}"
        return ""

    def describe(self, minutes: float = 10.0, now: float | None = None) -> str:
        """The same thing as a sentence or two, for a briefing."""
        data = self.heard(minutes, now)
        if not data["listening"]:
            return "Ambient sound awareness is not running."
        who = data["presence"]
        around = ""
        if who["last_sign"]:
            around = f" Last sign of someone around: {who['last_sign']}, {ago_text(who['last_sign_seconds_ago'])}."
        if not data["sounds"]:
            return (
                f"Nothing but quiet or speech in the last {minutes:g} minutes.{around}"
            )
        parts = []
        for s in data["sounds"][:6]:
            if s["going_on_now"]:
                parts.append(f"{s['sound']} (happening now)")
            else:
                parts.append(f"{s['sound']} ({ago_text(s['last_seconds_ago'])})")
        return "Background sounds lately: " + ", ".join(parts) + "." + around

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
        """Analyse the latest audio, unless it cannot be trusted.

        Every tick looks at the last second; every third tick also at the last
        three, which suits sounds that go on (typing, a kettle, music).
        """
        now = self._clock()
        self._tick += 1
        scales = [_SHORT_S]
        if self._tick % 3 == 1:
            scales.append(self.window_s)

        best: dict[str, float] = {}
        analysed = masked = False
        for seconds in scales:
            window = self._take_window(seconds)
            if window is None:
                continue
            # The assistant talking, or music the app is playing, is not the room.
            if now - self._last_playback < seconds:
                masked = True
                continue
            analysed = True
            if float(np.sqrt(np.mean(window * window))) < _QUIET_RMS:
                continue
            stream = self._tagger.create_stream()
            stream.accept_waveform(SAMPLE_RATE, window)
            for e in self._tagger.compute(stream):
                best[e.name] = max(best.get(e.name, 0.0), float(e.prob))

        if analysed:
            self.note_window(now, True)
        elif masked:
            self.note_window(now, False)
        if best:
            if logger.isEnabledFor(10):  # DEBUG
                top = sorted(best.items(), key=lambda kv: -kv[1])[:4]
                logger.debug(
                    "ambient raw: " + ", ".join(f"{n} {p:.2f}" for n, p in top)
                )
            self.ingest(list(best.items()), now)


def ago_text(seconds: int) -> str:
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
