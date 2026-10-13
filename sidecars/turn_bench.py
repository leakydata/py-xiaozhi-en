"""Measure turn-taking on Nathan's own recordings before it goes anywhere near the app.

Two kinds of moment are pulled from the Boswell archive:

  WAIT - Nathan stops on an unfinished phrase ("...for my", "...and", "um")
         and then carries on after a 0.8-3 s gap. Ending the turn in that gap
         is cutting him off.
  END  - Nathan finishes a sentence and then someone else talks, or nobody
         does for a while. Here the question is how quickly it notices.

Each one is replayed tick by tick, the models only ever seeing audio up to
"now", exactly as they would live. Three rules are compared on the same
speech detection: the content-aware one in turn_judge.py, a fixed 0.8 s
silence, and the phone's fixed 1.5 s.

    ~/Documents/electronics/boswell_server/.venv/bin/python turn_bench.py --n 40
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import random
import statistics
import sys
import time

import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from turn_sidecar import SR, TurnEngine  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "turn_judge",
    os.path.join(HERE, "..", "src", "audio_processing", "turn_judge.py"),
)
judge = importlib.util.module_from_spec(_spec)
sys.modules["turn_judge"] = judge  # dataclasses look their module up here
_spec.loader.exec_module(judge)

DATA = os.path.expanduser("~/Documents/electronics/nRF52840/data")
ME = "Nathan Jones"


def load(path):
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        import soxr

        audio = soxr.resample(audio, sr, SR)
    return audio


def examples(n, seed=7):
    wait, end = [], []
    files = sorted(glob.glob(os.path.join(DATA, "transcripts", "omi_*.json")))
    random.Random(seed).shuffle(files)
    for f in files:
        if len(wait) >= n and len(end) >= n:
            break
        try:
            d = json.load(open(f))
        except Exception:
            continue
        wav = os.path.join(DATA, d.get("clip", ""))
        if not os.path.exists(wav):
            continue
        try:
            dur = sf.info(wav).duration
        except Exception:
            continue
        mine = {k for k, v in (d.get("speakers") or {}).items() if v.get("name") == ME}
        segs = sorted(d.get("segments") or [], key=lambda s: s["start"])
        if not mine or len(segs) < 2:
            continue
        for i, a in enumerate(segs):
            if a["speaker"] not in mine or a["end"] - a["start"] < 0.8:
                continue
            b = segs[i + 1] if i + 1 < len(segs) else None
            # Where this turn of Nathan's began: back over his own segments
            # while the gaps between them are short.
            j = i
            while (
                j > 0
                and segs[j - 1]["speaker"] in mine
                and segs[j]["start"] - segs[j - 1]["end"] < 1.0
            ):
                j -= 1
            start = max(segs[j]["start"] - 0.3, a["end"] - 12.0, 0.0)
            kind = judge.ending(a["text"])
            if (
                b is not None
                and b["speaker"] in mine
                and 0.8 <= b["start"] - a["end"] <= 3.0
                and kind == "incomplete"
                and len(wait) < n
            ):
                wait.append(
                    {
                        "wav": wav,
                        "start": start,
                        "last": a["end"],
                        "resume": b["start"],
                        "text": a["text"],
                    }
                )
            elif (
                kind == "complete"
                # Nobody speaks for a while afterwards - as with an assistant
                # that is waiting - and the recording carries on long enough
                # to show it.
                and (b is None or b["start"] - a["end"] >= 3.0)
                and dur >= a["end"] + 3.0
                and len(end) < n
            ):
                end.append(
                    {"wav": wav, "start": start, "last": a["end"], "text": a["text"]}
                )
            # One example per clip keeps a single long recording from dominating.
            break
    return wait, end


RULES = {
    "content": lambda tick, s: judge.turn_over(
        tick["text"], tick["silence_s"], tick["speech_s"], s
    ),
    "content, word timing": lambda tick, s: judge.turn_over(
        tick["text"], tick["silence_words_s"], tick["speech_s"], s
    ),
    "content, words+not speaking": lambda tick, s: (not tick["speaking"])
    and judge.turn_over(tick["text"], tick["silence_words_s"], tick["speech_s"], s),
    "content (final)": lambda tick, s: judge.turn_over(
        tick["text"],
        tick["silence_words_s"],
        tick["speech_s"],
        s,
        speaking=tick["speaking"],
        vad_silence_s=tick["silence_s"],
    ),
    "fixed 0.8s": lambda tick, s: tick["speech_s"] >= s.min_speech_s
    and tick["silence_s"] >= 0.8,
    "fixed 1.5s (phone)": lambda tick, s: tick["speech_s"] >= s.min_speech_s
    and tick["silence_s"] >= 1.5,
}


def replay(engine, ex, step, until):
    audio = load(ex["wav"])
    t = ex["last"] - 0.3
    ticks = []
    while t <= until(ex):
        a = audio[int(ex["start"] * SR) : int(t * SR)]
        if len(a) > SR // 4:
            tick = engine.tick(a)
            tick["t"] = t
            ticks.append(tick)
        t += step
    return ticks


def first_end(ticks, rule, settings):
    for tick in ticks:
        if RULES[rule](tick, settings):
            return tick["t"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--step", type=float, default=0.3)
    ap.add_argument("--show", type=int, default=6, help="examples to print in full")
    ap.add_argument(
        "--explain",
        default="content (final)",
        help="list every cut-off this rule made, with what it heard",
    )
    args = ap.parse_args()

    settings = judge.TurnSettings()
    wait, end = examples(args.n)
    print(
        f"{len(wait)} WAIT moments (Nathan paused mid-thought), {len(end)} END moments (he had finished)"
    )

    engine = TurnEngine()
    lat = {"vad": [], "asr": [], "total": []}

    results = {r: {"cut_off": 0, "end_lat": [], "missed": 0} for r in RULES}
    cutoffs = []
    shown = 0
    t0 = time.time()
    for ex in wait:
        ticks = replay(engine, ex, args.step, lambda e: e["resume"] + 0.3)
        for tk in ticks:
            lat["vad"].append(tk["ms"]["vad"])
            lat["asr"].append(tk["ms"]["asr"])
            lat["total"].append(tk["ms"]["vad"] + tk["ms"]["asr"])
        for r in RULES:
            e = first_end(ticks, r, settings)
            if e is not None and e < ex["resume"]:
                results[r]["cut_off"] += 1
                if r == args.explain:
                    at = next(tk for tk in ticks if tk["t"] == e)
                    cutoffs.append((ex, at))
        if shown < args.show:
            shown += 1
            gap = ex["resume"] - ex["last"]
            heard = ticks[-1]["text"][-70:] if ticks else ""
            verdicts = ", ".join(
                f"{r}: {'CUT OFF' if (first_end(ticks, r, settings) or 1e9) < ex['resume'] else 'waited'}"
                for r in RULES
            )
            print(f"\n  WAIT  pause {gap:.1f}s after {ex['text'][-45:]!r}")
            print(f"        live words at the pause: ...{heard!r}")
            print(f"        {verdicts}")

    shown = 0
    for ex in end:
        ticks = replay(engine, ex, args.step, lambda e: e["last"] + 4.0)
        for tk in ticks:
            lat["vad"].append(tk["ms"]["vad"])
            lat["asr"].append(tk["ms"]["asr"])
            lat["total"].append(tk["ms"]["vad"] + tk["ms"]["asr"])
        # The archive's segment ends run up to half a second early, so measure
        # from the last word the recogniser placed, seen with all audio in.
        ref = ticks[-1]["t"] - ticks[-1]["silence_words_s"] if ticks else ex["last"]
        ex["last"] = ref
        for r in RULES:
            e = first_end(ticks, r, settings)
            if e is None:
                results[r]["missed"] += 1
            else:
                results[r]["end_lat"].append(e - ref)
        if shown < args.show:
            shown += 1
            lats = ", ".join(
                f"{r}: {('%.1fs' % (first_end(ticks, r, settings) - ex['last'])) if first_end(ticks, r, settings) else 'never'}"
                for r in RULES
            )
            print(f"\n  END   after {ex['text'][-50:]!r}")
            print(f"        ended {lats}")

    if cutoffs:
        print(
            f"\n=== every cut-off by {args.explain!r}: what it heard when it ended the turn ==="
        )
        for ex, at in cutoffs:
            print(
                f"  [{judge.ending(at['text']):<10}] silence {at['silence_words_s']:.1f}s  ...{at['text'][-60:]!r}"
            )
            print(f"               he went on after {ex['resume'] - ex['last']:.1f}s")

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else 0

    print(
        f"\n\n=== per tick, {len(lat['total'])} ticks, {time.time() - t0:.0f}s wall ==="
    )
    for k in ("vad", "asr", "total"):
        print(
            f"  {k:<6} median {statistics.median(lat[k]):>4.0f} ms   p95 {pct(lat[k], 95):>4.0f} ms   max {max(lat[k]):>4.0f} ms"
        )

    print(f"\n=== rules: {len(wait)} WAIT, {len(end)} END ===")
    print(
        f"  {'rule':<28} {'cut you off':>12} {'ended a finished turn after':>30} {'never ended':>12}"
    )
    for r, v in results.items():
        el = v["end_lat"]
        med = (
            f"median {statistics.median(el):.1f}s, p90 {pct(el, 90):.1f}s"
            if el
            else "-"
        )
        print(
            f"  {r:<28} {v['cut_off']:>6}/{len(wait):<5} {med:>30} {v['missed']:>6}/{len(end)}"
        )


if __name__ == "__main__":
    main()
