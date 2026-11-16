"""A voice in the room while idle starts the conversation, if switched on."""

import asyncio
import time

from src.audio_processing.ambient_sounds import AmbientSounds
from src.constants.constants import DeviceState
from src.plugins.ambient import AmbientSoundsPlugin


class Cfg:
    def __init__(self, on=True):
        self.on = on

    def get_config(self, key, default=None):
        if key == "AMBIENT_SOUNDS.WAKE_ON_VOICE":
            return self.on
        return default


class Ctx:
    def __init__(self, cfg, state=DeviceState.IDLE, opened=False):
        self._cfg, self.state, self.opened = cfg, state, opened

    def get_config(self):
        return self._cfg

    def get_device_state(self):
        return self.state

    def is_audio_channel_opened(self):
        return self.opened


class Cmd:
    def __init__(self):
        self.calls = []

    async def connect_protocol(self):
        self.calls.append("connect")
        return True

    async def start_listening(self, mode):
        self.calls.append("listen")


def make(on=True, state=DeviceState.IDLE, voices=3, opened=False):
    p = AmbientSoundsPlugin()
    p._ctx, p._cmd = Ctx(Cfg(on), state, opened), Cmd()
    p._sounds = AmbientSounds()
    p._sounds.enabled = True
    now = time.monotonic()
    for i in range(voices):
        p._sounds.ingest([("Speech", 0.9)], now - 0.5 * i)
    return p


def run(p):
    asyncio.run(p._maybe_wake_on_voice())
    return p._cmd.calls


def test_a_voice_while_idle_starts_the_conversation():
    assert run(make()) == ["connect", "listen"]


def test_it_does_nothing_when_switched_off():
    assert run(make(on=False)) == []


def test_one_blip_of_voice_is_not_enough():
    assert run(make(voices=1)) == []


def test_it_does_not_interrupt_a_conversation():
    assert run(make(state=DeviceState.LISTENING)) == []
    assert run(make(opened=True)) == []


def test_it_does_not_restart_straight_after_starting():
    p = make()
    assert run(p) == ["connect", "listen"]
    assert run(p) == ["connect", "listen"]  # nothing added: the gap holds


def test_the_setting_defaults_to_off():
    from src.utils.config_manager import ConfigManager

    assert ConfigManager.DEFAULT_CONFIG["AMBIENT_SOUNDS"]["WAKE_ON_VOICE"] is False
