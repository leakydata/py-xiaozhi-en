"""The echo gate: the user cutting in, against the reply coming back from the speakers."""

import numpy as np
import pytest

from src.audio_processing.echo_gate import EchoGate

RATE = 16_000
BLOCK = RATE // 50  # 20 ms, as the callbacks deliver


def speech(n, amp=0.08, seed=0):
    """A stand-in for a voice: broadband, not a pure tone."""
    rng = np.random.default_rng(seed)
    return (rng.normal(0, amp, n)).astype(np.float32)


def silence(n):
    return np.zeros(n, dtype=np.float32)


def run(gate, blocks, *, start=100.0):
    """Feed (far, near) block pairs on a 20 ms clock and return the verdicts."""
    verdicts = []
    t = start
    for far, near in blocks:
        gate.feed_far(far, now=t)
        gate.feed_near(near, now=t + gate.delay_s)
        verdicts.append(gate.recent_double_talk_at(t + gate.delay_s))
        t += 0.02
    return verdicts


# ---------------------------------------------------------------- echo only


def test_the_reply_coming_back_is_not_a_cut_in():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.2, seed=i) for i in range(150)]
    # The room returns a third of it, delayed.
    pairs = [(b, b * 0.33) for b in reply]
    assert not any(run(gate, pairs)[40:])


def test_loud_speakers_are_still_only_echo():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.5, seed=i) for i in range(150)]
    pairs = [(b, b * 0.6) for b in reply]  # a very live room, volume up
    assert not any(run(gate, pairs)[40:])


def test_it_learns_the_room_rather_than_assuming_one():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.3, seed=i) for i in range(200)]
    run(gate, [(b, b * 0.25) for b in reply])
    assert 0.2 < gate.coupling < 0.32


# ---------------------------------------------------------------- the user


def test_the_user_over_the_top_of_the_reply_does_cut_in():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.2, seed=i) for i in range(150)]
    pairs = [(b, b * 0.3) for b in reply]
    # They start talking half way through, into the same microphone.
    for i in range(80, 150):
        pairs[i] = (reply[i], reply[i] * 0.3 + speech(BLOCK, 0.25, seed=900 + i))
    verdicts = run(gate, pairs)
    assert not any(verdicts[40:70])
    assert any(verdicts[85:])


def test_the_user_in_a_gap_between_sentences_cuts_in():
    gate = EchoGate()
    pairs = [
        (speech(BLOCK, 0.2, seed=i), speech(BLOCK, 0.2, seed=i) * 0.3)
        for i in range(80)
    ]
    # The reply pauses; the user speaks into the quiet.
    pairs += [(silence(BLOCK), speech(BLOCK, 0.1, seed=500 + i)) for i in range(20)]
    verdicts = run(gate, pairs)
    assert not any(verdicts[40:75])
    assert any(verdicts[82:])


def test_headphones_let_anything_through():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.4, seed=i) for i in range(120)]
    # Almost nothing couples back, so a quiet remark still registers.
    pairs = [(b, b * 0.002) for b in reply]
    run(gate, pairs)
    pairs = [(reply[i], speech(BLOCK, 0.08, seed=700 + i)) for i in range(20)]
    assert any(run(gate, pairs, start=200.0))


# ---------------------------------------------------------------- robustness


def test_a_burst_of_the_users_speech_does_not_blind_the_next_one():
    """One interruption must not teach the gate that loud input is the room's
    own echo, or the cut-in after it is missed."""
    gate = EchoGate()
    far = [speech(BLOCK, 0.2, seed=i) for i in range(600)]  # 12 s of reply
    pairs = [(b, b * 0.3) for b in far]

    def talking(i, seed):
        return (far[i], far[i] * 0.3 + speech(BLOCK, 0.3, seed=seed + i))

    for i in range(100, 150):  # they talk over it for a second
        pairs[i] = talking(i, 800)
    for i in range(450, 500):  # and again, seconds later
        pairs[i] = talking(i, 950)

    verdicts = run(gate, pairs)
    assert any(verdicts[105:150]), "the first cut-in was missed"
    assert not any(verdicts[300:445]), "echo alone counted as a cut-in"
    assert any(verdicts[455:500]), "the second cut-in was missed"


def test_talking_over_the_whole_window_is_taken_at_face_value():
    """With no gap in several seconds of speech there is nothing left showing
    the room's echo on its own, so the estimate rises and the gate stops
    firing. Harmless: a cut-in is decided in the first moments, long before
    the window fills, and this is the state where the user really is talking
    throughout."""
    gate = EchoGate()
    far = [speech(BLOCK, 0.2, seed=i) for i in range(400)]
    pairs = [
        (far[i], far[i] * 0.3 + speech(BLOCK, 0.3, seed=800 + i))
        for i in range(len(far))
    ]
    verdicts = run(gate, pairs)
    assert any(verdicts[:60]), "the cut-in has to be caught while it starts"


def test_the_verdict_expires():
    gate = EchoGate()
    for i in range(15):
        gate.feed_far(silence(BLOCK), now=100.0 + i * 0.02)
        gate.feed_near(speech(BLOCK, 0.2, seed=i), now=100.0 + i * 0.02)
    assert gate.recent_double_talk_at(100.5)
    assert not gate.recent_double_talk_at(102.0)


def test_reset_forgets_the_verdict_not_the_room():
    gate = EchoGate()
    reply = [speech(BLOCK, 0.3, seed=i) for i in range(100)]
    run(gate, [(b, b * 0.25) for b in reply])
    learned = gate.coupling
    for i in range(15):
        gate.feed_near(speech(BLOCK, 0.5, seed=i), now=200.0 + i * 0.02)
    assert gate.recent_double_talk_at(200.4)
    gate.reset()
    assert not gate.recent_double_talk_at(200.1)
    assert gate.coupling == pytest.approx(learned, rel=0.5)


def test_silence_everywhere_is_not_a_cut_in():
    gate = EchoGate()
    pairs = [(silence(BLOCK), silence(BLOCK)) for _ in range(50)]
    assert not any(run(gate, pairs))


def test_it_starts_cautious_so_the_first_words_are_safe():
    """Before the room is known, assume a lot comes back: a severed reply is
    worse than a cut-in that has to be repeated."""
    gate = EchoGate()
    far = speech(BLOCK, 0.3)
    gate.feed_far(far, now=100.0)
    gate.feed_near(far * 0.3, now=100.06)
    assert not gate.recent_double_talk_at(100.06)


def test_odd_input_does_not_raise():
    gate = EchoGate()
    for block in (np.array([]), np.array([np.nan, np.inf], dtype=np.float32)):
        gate.feed_far(block, now=100.0)
        gate.feed_near(block, now=100.0)
    assert not gate.recent_double_talk_at(100.0)


# ---------------------------------------------------------------- stray sounds


def test_one_stray_frame_is_not_a_cut_in():
    """A click, a dog's nail or one bad frame from the canceller."""
    gate = EchoGate()
    gate.feed_far(silence(BLOCK), now=100.0)
    gate.feed_near(speech(BLOCK, 0.4), now=100.0)
    assert not gate.recent_double_talk_at(100.1)


def test_a_few_stray_frames_are_not_a_cut_in_either():
    gate = EchoGate()
    for i in range(4):  # 80 ms in all
        gate.feed_far(silence(BLOCK), now=100.0 + i * 0.5)
        gate.feed_near(speech(BLOCK, 0.4, seed=i), now=100.0 + i * 0.5)
    assert not gate.recent_double_talk_at(102.0, within_s=3.0)


def test_a_sustained_voice_is_a_cut_in():
    gate = EchoGate()
    for i in range(20):  # 400 ms
        gate.feed_far(silence(BLOCK), now=100.0 + i * 0.02)
        gate.feed_near(speech(BLOCK, 0.2, seed=i), now=100.0 + i * 0.02)
    assert gate.recent_double_talk_at(100.5)


def test_the_canceller_swinging_to_a_poor_moment_is_not_a_cut_in():
    """Learned coupling collapses to ~0.002 with the canceller on, then the
    residual rises to a few percent of the reply for a stretch. That is the
    canceller, not a person, and must stay under the threshold."""
    gate = EchoGate()
    reply = [speech(BLOCK, 0.2, seed=i) for i in range(300)]
    pairs = [(b, b * 0.002) for b in reply]
    for i in range(200, 260):  # residual climbs to 1.5% of the reply
        pairs[i] = (reply[i], reply[i] * 0.015)
    assert not any(run(gate, pairs)[40:])


def test_a_squashed_noise_floor_does_not_make_the_gate_hair_trigger():
    gate = EchoGate()
    for i in range(300):  # a room the suppressor has made nearly silent
        gate.feed_far(silence(BLOCK), now=100.0 + i * 0.02)
        gate.feed_near(speech(BLOCK, 0.0004, seed=i), now=100.0 + i * 0.02)
    assert gate.noise_floor < 0.002
    for i in range(30):  # then a faint sustained rustle, 0.004 RMS
        t = 110.0 + i * 0.02
        gate.feed_far(silence(BLOCK), now=t)
        gate.feed_near(speech(BLOCK, 0.004, seed=i), now=t)
    assert not gate.recent_double_talk_at(110.6)
