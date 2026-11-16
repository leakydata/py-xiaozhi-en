"""A long turn is handed over before the server drops it."""

import time

from src.plugins.turn_taking import TurnTakingPlugin


def plugin(started_ago, limit=45):
    p = TurnTakingPlugin.__new__(TurnTakingPlugin)
    p._listen_started = time.monotonic() - started_ago
    p._cfg = lambda key, default=None: limit if key == "MAX_TURN_S" else default
    return p


def tick(speaking=False, pause=0.5, speech=30.0):
    return {
        "text": "and then we",
        "speaking": speaking,
        "silence_words_s": pause,
        "silence_s": pause,
        "speech_s": speech,
    }


def test_a_short_turn_is_left_to_the_normal_rules():
    assert not plugin(20)._turn_too_long(tick())


def test_a_long_turn_ends_at_the_next_breath():
    assert plugin(46)._turn_too_long(tick(pause=0.5))


def test_a_long_turn_waits_while_they_are_mid_word():
    assert not plugin(46)._turn_too_long(tick(speaking=True, pause=0.0))


def test_just_short_of_the_limit_it_ends_regardless():
    assert plugin(54)._turn_too_long(tick(speaking=True, pause=0.0))


def test_silence_alone_is_not_a_long_turn():
    assert not plugin(60)._turn_too_long(tick(speech=0.2))


def test_it_can_be_turned_off():
    assert not plugin(60, limit=0)._turn_too_long(tick())


def test_the_clock_restarts_when_a_turn_reopens_without_a_state_change():
    import asyncio

    from src.constants.constants import DeviceState

    p = plugin(100)
    p._phase = DeviceState.LISTENING

    class Ctx:
        def get_device_state(self):
            return DeviceState.LISTENING

        def is_turn_ended(self):
            return True

    p._ctx = Ctx()
    p._take_audio = lambda: None
    asyncio.run(p._step())
    assert not p._turn_too_long(tick())
