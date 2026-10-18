"""The ambient sound log: what is kept, what is dropped, what is reported."""

import json

import numpy as np

from src.audio_processing.ambient_sounds import (
    IGNORED,
    AmbientSounds,
    short_name,
)
from src.mcp import briefing


def sounds(**kw):
    clock = {"t": 1000.0}
    a = AmbientSounds(clock=lambda: clock["t"], **kw)
    a.enabled = True
    return a, clock


def test_speech_is_never_logged():
    a, _ = sounds()
    a.ingest([("Speech", 0.95), ("Male speech, man speaking", 0.9)], 1000.0)
    a.ingest([("Speech", 0.95)], 1001.5)
    assert a.heard(10, now=1002.0)["sounds"] == []


def test_every_room_descriptor_in_the_ignore_list_is_dropped():
    a, _ = sounds()
    a.ingest([(label, 0.9) for label in IGNORED], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []


def test_a_lone_weak_detection_is_a_flicker_not_an_event():
    a, _ = sounds()
    a.ingest([("Dog", 0.4)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []


def test_a_strong_detection_counts_at_once():
    a, _ = sounds()
    a.ingest([("Smoke detector, smoke alarm", 0.9)], 1000.0)
    got = a.heard(10, now=1002.0)["sounds"]
    assert got[0]["sound"] == "Smoke detector"
    assert got[0]["going_on_now"] is True


def test_a_weak_detection_seen_twice_counts():
    a, _ = sounds()
    a.ingest([("Typing", 0.4)], 1000.0)
    a.ingest([("Typing", 0.45)], 1001.5)
    assert a.heard(10, now=1002.0)["sounds"][0]["sound"] == "Typing"


def test_below_the_confidence_floor_is_ignored():
    a, _ = sounds(min_confidence=0.5)
    a.ingest([("Dog", 0.45)], 1000.0)
    a.ingest([("Dog", 0.45)], 1001.5)
    assert a.heard(10, now=1002.0)["sounds"] == []


def test_one_sound_going_on_is_one_event_not_many():
    a, _ = sounds()
    for i in range(20):
        a.ingest([("Typing", 0.7)], 1000.0 + i * 1.5)
    got = a.heard(10, now=1030.0)["sounds"]
    assert len(got) == 1 and got[0]["times"] == 1


def test_a_sound_after_a_long_gap_is_a_second_occurrence():
    a, _ = sounds()
    a.ingest([("Dog", 0.8)], 1000.0)
    a.ingest([("Dog", 0.8)], 1100.0)
    got = a.heard(10, now=1101.0)["sounds"]
    assert got[0]["times"] == 2


def test_old_sounds_fall_out_of_the_window_and_are_not_going_on():
    a, _ = sounds()
    a.ingest([("Doorbell", 0.9)], 1000.0)
    assert a.heard(1, now=1200.0)["sounds"] == []
    got = a.heard(10, now=1200.0)["sounds"][0]
    assert got["going_on_now"] is False
    assert got["last_seconds_ago"] == 200


def test_newest_sound_comes_first():
    a, _ = sounds()
    a.ingest([("Dog", 0.9)], 1000.0)
    a.ingest([("Doorbell", 0.9)], 1100.0)
    names = [s["sound"] for s in a.heard(10, now=1101.0)["sounds"]]
    assert names == ["Doorbell", "Dog"]


def test_it_says_how_much_of_the_time_it_could_not_listen():
    a, _ = sounds()
    for i in range(4):
        a.note_window(1000.0 + i, analysed=False)
    a.note_window(1004.0, analysed=True)
    assert a.heard(10, now=1005.0)["listened_fraction"] == 0.2


def test_short_name_takes_the_first_of_audiosets_aliases():
    assert short_name("Smoke detector, smoke alarm") == "Smoke detector"
    assert short_name("Typing") == "Typing"


def test_describe_when_nothing_is_running():
    a = AmbientSounds()
    assert "not running" in a.describe()


def test_describe_lists_what_is_happening_now():
    a, _ = sounds()
    a.ingest([("Typing", 0.8)], 1000.0)
    assert "Typing (happening now)" in a.describe(10, now=1001.0)


def test_the_audio_thread_only_buffers_and_stays_bounded():
    a, _ = sounds()
    for _ in range(2000):
        a.on_audio_data(np.zeros(320, dtype=np.float32))
    assert a._buffered < 16_000 * 6
    assert a._take_window() is not None


def test_a_window_that_overlaps_playback_is_not_analysed():
    playing = {"on": True}
    a, clock = sounds(playback_active=lambda: playing["on"])

    class Boom:
        def create_stream(self):
            raise AssertionError("the assistant's own voice was analysed")

    a._tagger = Boom()
    for _ in range(200):
        a.on_audio_data(np.full(320, 0.1, dtype=np.float32))
    clock["t"] += 0.5
    a.step()
    assert a.heard(10, now=clock["t"])["listened_fraction"] == 0.0


def test_a_quiet_room_is_listened_to_but_not_run_through_the_model():
    a, clock = sounds()

    class Boom:
        def create_stream(self):
            raise AssertionError("silence went to the model")

    a._tagger = Boom()
    for _ in range(200):
        a.on_audio_data(np.zeros(320, dtype=np.float32))
    a.step()
    assert a.heard(10, now=clock["t"])["listened_fraction"] == 1.0


def test_the_tool_says_so_when_it_is_off():
    import asyncio

    from src.audio_processing.ambient_sounds import set_ambient
    from src.mcp.tools.ambient.register import ambient_sounds_payload

    set_ambient(None)
    out = json.loads(asyncio.run(ambient_sounds_payload({})))
    assert out["listening"] is False


def test_the_tool_reports_what_was_heard():
    import asyncio

    from src.audio_processing.ambient_sounds import set_ambient
    from src.mcp.tools.ambient.register import ambient_sounds_payload

    a, clock = sounds()
    a.ingest([("Dog", 0.9)], clock["t"] - 30)
    set_ambient(a)
    try:
        out = json.loads(asyncio.run(ambient_sounds_payload({"minutes": 5})))
    finally:
        set_ambient(None)
    assert out["sounds"][0]["sound"] == "Dog"
    assert out["sounds"][0]["last_seconds_ago"] == 30


def test_the_briefing_explains_the_sounds_only_when_the_tool_exists():
    class T:
        def __init__(self, name):
            self.name = name

    without = briefing.build([T("recall")])
    with_it = briefing.build([T("recall"), T("ambient_sounds")])
    assert "What you can hear besides speech" not in without
    assert "What you can hear besides speech" in with_it
    assert "ambient_sounds" in with_it
