"""Speaking up about a notable sound: only when quiet, rarely, and never for noise."""

import asyncio
import time

from src.audio_processing.ambient_sounds import AmbientSounds
from src.plugins.ambient import AmbientSoundsPlugin


class Cfg:
    def __init__(self, **values):
        self.values = {
            "SPEAK_UP": True,
            "QUIET_AFTER_S": 120,
            "MIN_GAP_S": 300,
            **values,
        }

    def get_config(self, key, default=None):
        return self.values.get(key.removeprefix("AMBIENT_SOUNDS."), default)


class Ctx:
    def __init__(self, cfg, speaking=False):
        self._cfg, self.speaking = cfg, speaking

    def get_config(self):
        return self._cfg

    def is_speaking(self):
        return self.speaking


class Cmd:
    def __init__(self, connects=True):
        self.sent, self.connects = [], connects

    async def connect_protocol(self):
        return self.connects

    async def send_wake_word_detected(self, text):
        self.sent.append(text)


def plugin(cfg=None, speaking=False, connects=True):
    p = AmbientSoundsPlugin()
    p._ctx = Ctx(cfg or Cfg(), speaking)
    p._cmd = Cmd(connects)
    p._sounds = AmbientSounds()
    p._sounds.enabled = True
    # a long-quiet room, with the last update well in the past
    now = time.monotonic()
    p._last_talk = now - 1000
    p._last_update = now - 1000
    return p


def hear(p, label, prob=0.9, ago=5.0):
    p._sounds.ingest([(label, prob)], time.monotonic() - ago)


def run(p):
    asyncio.run(p._maybe_speak_up())
    return p._cmd.sent


def test_a_notable_sound_in_a_quiet_room_is_spoken_about():
    p = plugin()
    hear(p, "Doorbell")
    sent = run(p)
    assert len(sent) == 1
    assert "Doorbell" in sent[0] and "not from Nathan" in sent[0]


def test_it_is_off_by_default_and_by_switch():
    p = plugin(Cfg(SPEAK_UP=False))
    hear(p, "Doorbell")
    assert run(p) == []


def test_ordinary_noise_is_never_worth_speaking_about():
    p = plugin()
    for label in ("Typing", "Music", "Water tap, faucet", "Walk, footsteps"):
        hear(p, label)
    assert run(p) == []


def test_not_while_a_conversation_is_going_on():
    p = plugin()
    p._last_talk = time.monotonic() - 30
    hear(p, "Doorbell")
    assert run(p) == []


def test_not_while_a_voice_is_in_the_room():
    p = plugin()
    p._sounds.ingest([("Speech", 0.9)], time.monotonic() - 20)
    hear(p, "Doorbell")
    assert run(p) == []


def test_not_while_she_is_speaking():
    p = plugin(speaking=True)
    hear(p, "Doorbell")
    assert run(p) == []


def test_a_faint_detection_is_not_enough():
    p = plugin()
    hear(p, "Doorbell", prob=0.5)
    hear(p, "Doorbell", prob=0.5)
    assert run(p) == []


def test_it_waits_between_updates():
    p = plugin()
    p._last_update = time.monotonic() - 60
    hear(p, "Doorbell")
    assert run(p) == []


def test_each_sound_is_mentioned_once():
    p = plugin()
    hear(p, "Doorbell")
    assert len(run(p)) == 1
    p._ctx._cfg.values["MIN_GAP_S"] = 0  # gap over, but nothing new has happened
    assert len(run(p)) == 1


def test_a_failed_connection_retries_soon_instead_of_losing_it():
    p = plugin(connects=False)
    hear(p, "Doorbell")
    run(p)
    assert p._cmd.sent == []
    assert time.monotonic() - p._last_update > 200  # not marked as done
