"""Listening sounds: when "mm-hm" is played, and how it is learned in the assistant's voice."""

import time

import numpy as np
import pytest

import src.audio_processing.backchannel as bc
from src.audio_processing.turn_judge import BackchannelSettings, backchannel_due

RATE = 24_000

# ---------------------------------------------------------------- when


def due(text, silence=0.6, speech=5.0, since=30.0, **kw):
    return backchannel_due(text, silence, speech, since, **kw)


def test_murmurs_in_a_pause_mid_story():
    assert due("So I went down to the garage and the door was open,")
    assert due("so then the dog runs off")  # no clear ending either way


def test_answers_rather_than_murmurs_after_a_finished_sentence_or_question():
    assert not due("I went to the garage.")
    assert not due("Where did I leave the hammer?")


def test_stays_quiet_while_someone_searches_for_a_word():
    assert not due("I'm looking for my")
    assert not due("and the")


def test_not_until_they_have_been_talking_a_while():
    assert not due("so then the dog runs off", speech=2.0)


def test_never_too_often():
    assert not due("so then the dog runs off", since=3.0)
    assert due(
        "so then the dog runs off",
        since=3.0,
        settings=BackchannelSettings(min_gap_s=2.0),
    )


def test_only_inside_the_pause_window():
    assert not due("so then the dog runs off", silence=0.2)  # not a pause yet
    assert not due(
        "so then the dog runs off", silence=1.5
    )  # too late to read as a reaction


def test_never_right_before_the_turn_would_end():
    # Neutral endings end at 1.2 s; 1.0 s is too close to murmur and then answer.
    assert not due("so then the dog runs off", silence=1.0)


def test_not_while_they_are_still_making_sound():
    assert not due("so then the dog runs off", speaking=True)


# ---------------------------------------------------------------- what


@pytest.mark.parametrize(
    "text, name",
    [
        ("Mm-hm.", "mm-hm"),
        ("Mhm", "mm-hm"),
        ("Mm hmm.", "mm-hm"),
        ("Uh huh.", "uh-huh"),
        ("Yeah.", "yeah"),
        ("Right.", "right"),
        ("OK.", "okay"),
        ("I see.", "i-see"),
    ],
)
def test_filler_names(text, name):
    assert bc.filler_name(text) == name


@pytest.mark.parametrize(
    "text", ["Yeah, that's right.", "Sure, here they are:", "", "Right away."]
)
def test_anything_more_than_a_filler_is_not_one(text):
    assert bc.filler_name(text) is None


def _tone(seconds, amp=0.5):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _silence(seconds):
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def test_trim_cuts_silence_and_levels_quietly():
    clip = bc.trim(
        np.concatenate([_silence(0.4), _tone(0.3, 0.9), _silence(0.5)]), RATE
    )
    assert clip is not None
    assert 0.3 <= len(clip) / RATE <= 0.4
    assert abs(float(np.max(np.abs(clip))) - 0.35) < 0.01


def test_trim_rejects_nothing_and_rambling():
    assert bc.trim(_silence(1.0), RATE) is None
    assert bc.trim(_tone(3.0), RATE) is None


def test_harvester_cuts_each_filler_out_of_one_reply():
    pcm = np.concatenate(
        [
            _tone(0.8),
            _silence(0.4),
            _tone(0.3),
            _silence(0.4),
            _tone(0.25),
            _silence(0.4),
        ]
    )
    h = bc.Harvester()
    h.mark(0, "Sure, here they are:")
    h.mark(int(1.2 * RATE), "Mm-hm.")
    h.mark(int(1.9 * RATE), "Yeah.")
    parts = h.split(pcm, RATE)
    assert set(parts) == {"mm-hm", "yeah"}
    assert abs(len(bc.trim(parts["mm-hm"], RATE)) / RATE - 0.3) < 0.1


def test_store_round_trip_and_no_repeats(tmp_path):
    store = bc.BackchannelStore(tmp_path)
    assert store.pick(RATE) is None
    assert store.save("mm-hm", _tone(0.3), RATE)
    assert store.save("yeah", _tone(0.25), RATE)
    assert store.names() == ["mm-hm", "yeah"]
    picks = {store._last_played for _ in range(6) if store.pick(RATE) is not None}
    assert picks == {"mm-hm", "yeah"}
    a = store.pick(RATE)
    first = store._last_played
    store.pick(RATE)
    assert store._last_played != first and a is not None


def test_store_resamples_to_the_playback_rate(tmp_path):
    store = bc.BackchannelStore(tmp_path)
    store.save("mm-hm", _tone(0.3), RATE)
    clip = store.pick(48_000)
    assert abs(len(clip) / 48_000 - len(store.clips()["mm-hm"][0]) / RATE) < 0.01


def test_arming_expires(tmp_path):
    store = bc.BackchannelStore(tmp_path)
    store.arm(0.05)
    assert store.armed
    time.sleep(0.08)
    assert not store.armed


# ---------------------------------------------------------------- muting


def test_muting_holds_the_microphone_back_briefly():
    from src.constants.constants import DeviceState
    from src.core.event_bus import EventBus
    from src.core.state_manager import StateManager

    st = StateManager(EventBus(), aec_enabled=False)
    st._device_state = DeviceState.LISTENING
    st.mute_capture(0.05)
    assert not st.should_capture_audio()
    time.sleep(0.07)
    assert st.should_capture_audio()


# ---------------------------------------------------------------- the plugin


class FakeCodec:
    def __init__(self):
        self.played = []
        self._cap = None

    def play_local(self, pcm):
        self.played.append(pcm)

    def start_tts_capture(self):
        self._cap = []

    def tts_captured_samples(self):
        return sum(len(f) for f in self._cap) if self._cap else 0

    def stop_tts_capture(self):
        frames, self._cap = self._cap, None
        return np.concatenate(frames) if frames else None

    def feed(self, pcm):  # what write_audio would do while capturing
        if self._cap is not None:
            self._cap.append(pcm)


class FakeAudioPlugin:
    def __init__(self, codec):
        self.codec = codec


class Cfg:
    def __init__(self, values):
        self.values = values

    def get_config(self, key, default=None):
        return self.values.get(key, default)


class Ctx:
    def __init__(self, values):
        self.cfg = Cfg(values)

    def get_config(self):
        return self.cfg


class Cmd:
    def __init__(self):
        self.muted = []

    def mute_capture(self, s):
        self.muted.append(s)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = bc.BackchannelStore(tmp_path)
    monkeypatch.setattr(bc, "_store", s)
    return s


def _plugin(codec, **cfg):
    from src.plugins.turn_taking import TurnTakingPlugin

    p = TurnTakingPlugin()
    p._ctx = Ctx(
        {f"TURN_TAKING.{k}": v for k, v in cfg.items()} | cfg.pop("_extra", {})
    )
    p._cmd = Cmd()
    p.get_dep = lambda name: FakeAudioPlugin(codec)
    return p


TICK = {
    "text": "so then the dog runs off",
    "silence_s": 0.6,
    "silence_words_s": 0.6,
    "speech_s": 5.0,
    "speaking": False,
}


def test_plugin_murmurs_and_mutes_without_echo_cancellation(store):
    store.save("mm-hm", _tone(0.3), RATE)
    codec = FakeCodec()
    p = _plugin(codec, BACKCHANNELS=True)
    p._maybe_backchannel(TICK)
    assert len(codec.played) == 1
    assert p.cmd.muted and p.cmd.muted[0] > 0.3


def test_plugin_does_not_mute_when_echo_cancellation_removes_it(store):
    store.save("mm-hm", _tone(0.3), RATE)
    codec = FakeCodec()
    p = _plugin(codec, BACKCHANNELS=True)
    p._ctx.cfg.values["AEC_OPTIONS.ENABLED"] = True
    p._maybe_backchannel(TICK)
    assert len(codec.played) == 1 and p.cmd.muted == []


def test_plugin_is_silent_when_switched_off_or_untaught(store):
    codec = FakeCodec()
    _plugin(codec, BACKCHANNELS=True)._maybe_backchannel(TICK)  # nothing learned
    store.save("mm-hm", _tone(0.3), RATE)
    _plugin(codec, BACKCHANNELS=False)._maybe_backchannel(TICK)
    assert codec.played == []


def test_plugin_waits_between_murmurs(store):
    store.save("mm-hm", _tone(0.3), RATE)
    codec = FakeCodec()
    p = _plugin(codec, BACKCHANNELS=True)
    p._maybe_backchannel(TICK)
    p._maybe_backchannel(TICK)
    assert len(codec.played) == 1


@pytest.mark.asyncio
async def test_plugin_learns_fillers_from_a_reply(store, monkeypatch):
    from src.constants.constants import AudioConfig

    monkeypatch.setattr(AudioConfig, "OUTPUT_SAMPLE_RATE", RATE, raising=False)
    codec = FakeCodec()
    p = _plugin(codec)
    store.arm(30)

    await p.on_incoming_json({"type": "tts", "state": "start"})
    for text, audio in [
        ("Sure, here they are:", _tone(0.8)),
        ("Mm-hm.", _tone(0.3)),
        ("Uh-huh.", _tone(0.3)),
        ("Yeah.", _tone(0.25)),
    ]:
        await p.on_incoming_json(
            {"type": "tts", "state": "sentence_start", "text": text}
        )
        codec.feed(audio)
        codec.feed(_silence(0.4))
    await p.on_incoming_json({"type": "tts", "state": "stop"})

    assert store.names() == ["mm-hm", "uh-huh", "yeah"]
    assert not store.armed


@pytest.mark.asyncio
async def test_plugin_records_nothing_unless_asked(store):
    codec = FakeCodec()
    p = _plugin(codec)
    await p.on_incoming_json({"type": "tts", "state": "start"})
    await p.on_incoming_json(
        {"type": "tts", "state": "sentence_start", "text": "Mm-hm."}
    )
    codec.feed(_tone(0.3))
    await p.on_incoming_json({"type": "tts", "state": "stop"})
    assert store.names() == []


# ---------------------------------------------------------------- long tellings


def test_in_a_long_telling_a_full_stop_gets_a_murmur_not_an_answer():
    from src.audio_processing.turn_judge import turn_over

    text = "So I took the truck down to the yard."
    assert due(text, silence=0.6, speech=10.0)
    assert not turn_over(text, 0.8, 10.0)  # held longer than in a short turn
    assert turn_over(text, 1.3, 10.0)


def test_a_question_is_always_answered_promptly():
    from src.audio_processing.turn_judge import turn_over

    text = "Where did I leave the hammer?"
    assert not due(text, silence=0.6, speech=10.0)
    assert turn_over(text, 0.7, 10.0)


def test_a_short_turn_still_answers_a_statement_promptly():
    from src.audio_processing.turn_judge import turn_over

    assert turn_over("Turn on the kitchen light.", 0.7, 2.0)
    assert not due("Turn on the kitchen light.", silence=0.6, speech=2.0)
