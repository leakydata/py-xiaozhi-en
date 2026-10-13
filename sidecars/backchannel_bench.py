"""How often would the assistant say "mm-hm" while Nathan talks, and where?

Replays Nathan's longer stretches of talk from the Boswell archive tick by
tick, through the real models, and applies turn_judge.backchannel_due with its
spacing. Prints the rate and every spot it would murmur, so the placement can
be read rather than trusted.

    ~/Documents/electronics/boswell_server/.venv/bin/python backchannel_bench.py --n 20
"""

import argparse
import glob
import json
import os
import random

import soundfile as sf
from turn_bench import DATA, ME, SR, TurnEngine, judge, load


def stretches(n, seed=3):
    out = []
    files = sorted(glob.glob(os.path.join(DATA, "transcripts", "omi_*.json")))
    random.Random(seed).shuffle(files)
    for f in files:
        if len(out) >= n:
            break
        d = json.load(open(f))
        wav = os.path.join(DATA, d.get("clip", ""))
        mine = {k for k, v in (d.get("speakers") or {}).items() if v.get("name") == ME}
        segs = sorted(d.get("segments") or [], key=lambda s: s["start"])
        if not mine or not os.path.exists(wav):
            continue
        # A run of Nathan's own segments with short gaps: one long turn.
        run = []
        for s in segs + [None]:
            if (
                s
                and s["speaker"] in mine
                and (not run or s["start"] - run[-1]["end"] < 1.5)
            ):
                run.append(s)
                continue
            if (
                run
                and run[-1]["end"] - run[0]["start"] >= 12
                and sf.info(wav).duration >= run[-1]["end"]
            ):
                out.append((wav, run[0]["start"], run[-1]["end"]))
                break
            run = [s] if s and s["speaker"] in mine else []
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    eng = TurnEngine()
    total_s, fired = 0.0, []
    for wav, start, end in stretches(a.n):
        audio = load(wav)
        t, last = start + 1.0, -1e9
        while t <= end:
            tk = eng.tick(audio[int(start * SR) : int(t * SR)])
            if judge.backchannel_due(
                tk["text"],
                tk["silence_words_s"],
                tk["speech_s"],
                t - last,
                speaking=tk["speaking"],
            ):
                last = t
                fired.append(tk["text"][-60:])
            t += 0.3
        total_s += end - start
    print(
        f"\n{total_s / 60:.1f} min of Nathan talking, {len(fired)} murmurs "
        f"= one every {total_s / max(len(fired), 1):.0f} s"
    )
    for f in fired:
        print(f"  mm-hm after ...{f!r}")


if __name__ == "__main__":
    main()
