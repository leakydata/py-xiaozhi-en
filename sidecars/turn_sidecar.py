"""Turn-taking sidecar: speech detection and live words, on the home server's models.

Runs under boswell_server's own environment, not py-xiaozhi's, because that is
where the models measured best on this machine already live:

- words:          Parakeet TDT 0.6B v3 through NeMo on the GPU, loaded by the
                  server's own Engine so the settings (including phrase
                  boosting) are identical. 12.5% words wrong on Nathan's
                  corrected lines against 15.0-19.4% for everything else tried.
- speech or not:  pyannote segmentation-3.0 on the GPU, set up as the server's
                  vad_bench.py did it. 385/400 right against Silero's 358/400.

It does no deciding. py-xiaozhi sends it microphone audio and asks, every tick,
"how long since speech, and what has been said this turn?". The rules that turn
that into "they've finished" live in py-xiaozhi (turn_judge.py), where they can
be switched off.

Protocol over stdin/stdout. Requests are a 1-byte kind and a 4-byte big-endian
length, then the payload:

    A  audio: float32 mono 16 kHz samples, appended to this turn
    T  tick:  reply with one JSON line (below)
    R  reset: a new turn starts; forget the audio
    H  hotwords: UTF-8, one phrase per line, boosted while decoding
    Q  quit

A tick reply:

    {"speech_s": 3.1, "silence_s": 0.8, "speaking": false,
     "text": "I'm looking for my", "words": [...], "ms": {"vad": 9, "asr": 41}}

Every reply and every log line goes to stdout as JSON or stderr as text, so the
client never has to guess what it is reading.

    BOSWELL_SERVER_DIR=~/Documents/electronics/boswell_server \\
      ~/Documents/electronics/boswell_server/.venv/bin/python turn_sidecar.py
"""

from __future__ import annotations

import json
import os
import struct
import sys
import time

import numpy as np

SR = 16_000
#: How much of the turn is re-transcribed each tick. Parakeet reads 30 s in
#: ~0.1 s on the 4090, so this is about recognition quality, not cost: enough
#: context that the last words are recognised as part of a sentence.
WINDOW_S = 12.0
#: How much is kept at all. A turn longer than this is long enough that its
#: start no longer matters to whether it has ended.
KEEP_S = 30.0


def log(msg: str) -> None:
    print(f"[turn-sidecar] {msg}", file=sys.stderr, flush=True)


class TurnEngine:
    """The two models, loaded once, and the audio of the current turn."""

    def __init__(self, server_dir: str | None = None, device: str | None = None):
        server_dir = os.path.expanduser(
            server_dir
            or os.environ.get(
                "BOSWELL_SERVER_DIR", "~/Documents/electronics/boswell_server"
            )
        )
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        import torch

        self.torch = torch
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.audio = np.zeros(0, dtype=np.float32)
        self.hotwords: tuple[str, ...] = ()

        t0 = time.time()
        from boswell_server.pipeline import Engine

        self.engine = Engine()
        self.engine.asr()  # NeMo is slow to load; pay it now, not on the first tick
        t1 = time.time()

        from pyannote.audio import Model
        from pyannote.audio.pipelines import VoiceActivityDetection

        seg = Model.from_pretrained("pyannote/segmentation-3.0").to(self.device)
        self.vad = VoiceActivityDetection(segmentation=seg)
        self.vad.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
        t2 = time.time()

        name = (
            torch.cuda.get_device_name(self.device)
            if self.device.type == "cuda"
            else "cpu"
        )
        log(f"ready on {name}: parakeet {t1 - t0:.1f}s, segmentation {t2 - t1:.1f}s")
        # Warm both up, so the first real tick is not the one that pays for
        # CUDA kernels being compiled. Silence alone would skip the recogniser,
        # which only runs once there is speech, so it gets some quiet noise.
        noise = (np.random.default_rng(0).standard_normal(SR * 2) * 0.01).astype(
            np.float32
        )
        self.speech_spans(noise)
        self.engine.transcribe(noise, ())
        self.reset()

    # -------------------------------------------------------------- turn

    def reset(self) -> None:
        self.audio = np.zeros(0, dtype=np.float32)

    def add(self, samples: np.ndarray) -> None:
        self.audio = np.concatenate([self.audio, samples.astype(np.float32)])
        keep = int(KEEP_S * SR)
        if len(self.audio) > keep:
            self.audio = self.audio[-keep:]

    def speech_spans(self, audio: np.ndarray) -> list[tuple[float, float]]:
        if len(audio) < SR // 4:
            return []
        wav = self.torch.from_numpy(np.ascontiguousarray(audio))[None, :]
        ann = self.vad({"waveform": wav, "sample_rate": SR})
        return [(float(s.start), float(s.end)) for s in ann.get_timeline().support()]

    def tick(self, audio: np.ndarray | None = None) -> dict:
        audio = self.audio if audio is None else audio
        total = len(audio) / SR

        t0 = time.time()
        spans = self.speech_spans(audio)
        t1 = time.time()

        speech_s = sum(e - s for s, e in spans)
        last_end = spans[-1][1] if spans else None
        silence_s = total - last_end if last_end is not None else total
        # Still speaking if the last span runs to within a frame of now.
        speaking = last_end is not None and silence_s < 0.1

        words: list[dict] = []
        if speech_s > 0:
            window = audio[-int(WINDOW_S * SR) :]
            offset = total - len(window) / SR
            words = self.engine.transcribe(window, self.hotwords)
            for w in words:
                w["start"] = round(w["start"] + offset, 3)
                w["end"] = round(w["end"] + offset, 3)
        t2 = time.time()

        # A second measure of the pause: time since the recogniser's last word.
        # The speech detector judges the newest audio with the least context
        # on its right, so it can hold on to "speaking" for a while after the
        # words have stopped.
        silence_words = total - words[-1]["end"] if words else silence_s

        return {
            "seconds": round(total, 3),
            "speech_s": round(speech_s, 3),
            "silence_s": round(max(silence_s, 0.0), 3),
            "silence_words_s": round(max(silence_words, 0.0), 3),
            "speaking": speaking,
            "text": " ".join(w["text"] for w in words).strip(),
            "words": words,
            "ms": {"vad": int((t1 - t0) * 1000), "asr": int((t2 - t1) * 1000)},
        }


def _read_exact(stream, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def serve() -> None:
    engine = TurnEngine()
    inp = sys.stdin.buffer
    out = sys.stdout
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    while True:
        head = _read_exact(inp, 5)
        if head is None:
            return
        kind = head[:1]
        (size,) = struct.unpack(">I", head[1:])
        payload = _read_exact(inp, size) if size else b""
        if payload is None:
            return
        try:
            if kind == b"A":
                engine.add(np.frombuffer(payload, dtype=np.float32))
            elif kind == b"T":
                out.write(json.dumps(engine.tick()) + "\n")
                out.flush()
            elif kind == b"R":
                engine.reset()
            elif kind == b"H":
                engine.hotwords = tuple(
                    p.strip() for p in payload.decode("utf-8").splitlines() if p.strip()
                )
            elif kind == b"Q":
                return
        except Exception as e:  # a bad tick must not kill the conversation
            log(f"{kind!r} failed: {type(e).__name__}: {e}")
            if kind == b"T":
                out.write(json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n")
                out.flush()


if __name__ == "__main__":
    serve()
