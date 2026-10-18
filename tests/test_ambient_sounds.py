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


def test_a_weak_detection_seen_in_several_windows_in_a_row_counts():
    a, _ = sounds()
    for i, p in enumerate((0.4, 0.45, 0.4)):
        a.ingest([("Typing", p)], 1000.0 + i * 0.5)
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


# ---------------------------------------------------------------- presence


def test_typing_counts_as_someone_being_around_without_a_word_said():
    a, _ = sounds()
    a.ingest([("Typing", 0.8)], 1000.0)
    p = a.presence(now=1005.0)
    assert p["last_sign"] == "Typing"
    assert p["state"] == "active right now"


def test_a_voice_counts_as_presence_but_is_not_logged_as_a_sound():
    a, _ = sounds()
    a.ingest([("Speech", 0.9)], 1000.0)
    assert a.presence(now=1010.0)["last_sign"] == "a voice"
    assert a.heard(10, now=1010.0)["sounds"] == []


def test_a_faint_voice_is_not_enough():
    a, _ = sounds()
    a.ingest([("Speech", 0.3)], 1000.0)
    assert a.presence(now=1005.0)["last_sign"] is None


def test_the_dog_or_the_kettle_is_not_a_sign_of_a_person():
    a, _ = sounds()
    a.ingest(
        [("Dog", 0.9), ("Whimper (dog)", 0.9), ("Smoke detector, smoke alarm", 0.9)],
        1000.0,
    )
    assert a.presence(now=1005.0)["last_sign"] is None


def test_presence_fades_to_a_while_ago_not_to_gone():
    a, _ = sounds()
    a.ingest([("Walk, footsteps", 0.8)], 1000.0)
    assert a.presence(now=1060.0)["state"] == "active a moment ago"
    later = a.presence(now=1600.0)
    assert later["state"] == "no sound of anyone for a while"
    assert later["last_sign_seconds_ago"] == 600


def test_the_most_recent_sign_wins():
    a, _ = sounds()
    a.ingest([("Typing", 0.8)], 1000.0)
    a.ingest([("Speech", 0.9)], 1100.0)
    assert a.presence(now=1101.0)["last_sign"] == "a voice"


def test_no_sign_yet_is_said_plainly():
    a, _ = sounds()
    assert a.presence(now=1000.0)["state"] == "no sign yet"


def test_describe_mentions_who_was_last_around():
    a, _ = sounds()
    a.ingest([("Typing", 0.8)], 1000.0)
    assert "Last sign of someone around: Typing" in a.describe(10, now=1010.0)


# ---------------------------------------------------------------- on screen


def test_the_screen_line_shows_what_is_going_on_now():
    a, _ = sounds()
    a.ingest([("Typing", 0.8), ("Dog", 0.9)], 1000.0)
    line = a.now_line(now=1001.0)
    assert line.startswith("Hearing:") and "Typing" in line and "Dog" in line


def test_a_voice_is_shown_as_a_voice_never_as_words():
    a, _ = sounds()
    a.ingest([("Speech", 0.9)], 1000.0)
    assert a.now_line(now=1001.0) == "Hearing: a voice"


def test_a_sound_just_gone_is_shown_as_just_heard():
    a, _ = sounds()
    a.ingest([("Doorbell", 0.9)], 1000.0)
    assert a.now_line(now=1020.0) == "Just heard: Doorbell"


def test_the_screen_line_is_blank_when_nothing_or_when_off():
    a, _ = sounds()
    assert a.now_line(now=1000.0) == ""
    a.ingest([("Typing", 0.8)], 1000.0)
    a.enabled = False
    assert a.now_line(now=1001.0) == ""


# ---------------------------------------------------------------- brief sounds


def test_a_cough_counts_on_one_clear_detection():
    a, _ = sounds()
    a.ingest([("Cough", 0.45)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"][0]["sound"] == "Cough"


def test_a_sound_that_goes_on_still_needs_more_than_one_weak_detection():
    a, _ = sounds()
    a.ingest([("Typing", 0.45)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []


def test_a_faint_cough_is_still_not_enough():
    a, _ = sounds()
    a.ingest([("Cough", 0.36)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []


def test_the_short_window_catches_what_the_long_one_would_dilute():
    """Both scales are run each tick and the better score for a label wins."""
    a, clock = sounds()
    seen = {}

    class Tagger:
        def create_stream(self):
            class S:
                def accept_waveform(s, rate, w):
                    seen[len(seen)] = w.size

            return S()

        def compute(self, stream):
            n = seen[len(seen) - 1]

            class E:
                def __init__(s, name, prob):
                    s.name, s.prob = name, prob

            # strong only in the one-second window
            return [E("Clapping", 0.8 if n == 16_000 else 0.1)]

    a._tagger = Tagger()
    for _ in range(400):
        a.on_audio_data(np.full(320, 0.05, dtype=np.float32))
    a.step()
    assert sorted(seen.values()) == [16_000, 48_000]
    assert a.heard(10, now=clock["t"])["sounds"][0]["sound"] == "Clapping"


# ---------------------------------------------------------------- body sounds


def test_a_snort_the_model_is_only_a_fifth_sure_of_counts_when_it_repeats():
    a, _ = sounds()
    a.ingest([("Snort", 0.22)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []  # once is a guess
    a.ingest([("Snort", 0.21)], 1003.0)
    assert a.heard(10, now=1004.0)["sounds"][0]["sound"] == "Snort"


def test_the_low_floor_is_only_for_body_sounds():
    a, _ = sounds()
    a.ingest([("Tick", 0.22)], 1000.0)
    a.ingest([("Tick", 0.22)], 1003.0)
    assert a.heard(10, now=1004.0)["sounds"] == []


def test_a_snort_is_a_sign_someone_is_there():
    a, _ = sounds()
    a.ingest([("Snort", 0.25)], 1000.0)
    a.ingest([("Snort", 0.25)], 1002.0)
    assert a.presence(now=1005.0)["last_sign"] == "Snort"


# ---------------------------------------------------------------- consistency


def test_scattered_guesses_do_not_add_up_to_a_sound():
    """A hallucination turns up once here, once there; seen three times in
    twelve seconds it is still never three times in four."""
    a, _ = sounds(min_confidence=0.25)
    for t in (1000.0, 1004.5, 1009.0, 1013.5, 1018.0):
        a.ingest([("Tick-tock", 0.3)], t)
    assert a.heard(10, now=1019.0)["sounds"] == []


def test_a_sound_that_stays_in_the_windows_counts():
    a, _ = sounds(min_confidence=0.25)
    for i in range(6):
        a.ingest([("Tick-tock", 0.3)], 1000.0 + i * 0.5)
    assert a.heard(10, now=1003.0)["sounds"][0]["sound"] == "Tick-tock"


def test_two_in_a_row_is_not_yet_a_sustained_sound():
    a, _ = sounds(min_confidence=0.25)
    a.ingest([("Typing", 0.3)], 1000.0)
    a.ingest([("Typing", 0.3)], 1000.5)
    assert a.heard(10, now=1001.0)["sounds"] == []


def test_a_label_on_the_ignore_list_never_counts():
    a, _ = sounds(ignore=("Tick-tock", "tick"))
    for i in range(6):
        a.ingest([("Tick-tock", 0.9), ("Tick", 0.9)], 1000.0 + i * 0.5)
    assert a.heard(10, now=1003.0)["sounds"] == []


def test_the_ignore_list_matches_the_short_name_too():
    a, _ = sounds(ignore=("smoke detector",))
    a.ingest([("Smoke detector, smoke alarm", 0.95)], 1000.0)
    assert a.heard(10, now=1001.0)["sounds"] == []
