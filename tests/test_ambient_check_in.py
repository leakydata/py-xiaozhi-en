"""Checking in when the server ends a session but the room says someone is there."""

import asyncio
import time

from src.audio_processing.ambient_sounds import AmbientSounds
from src.plugins import ambient as ambient_mod
from src.plugins.ambient import AmbientSoundsPlugin


class Cfg:
    def __init__(self, **values):
        self.values = {
            "AMBIENT_SOUNDS.CHECK_IN": True,
            "AMBIENT_SOUNDS.CHECK_IN_PRESENCE_S": 90,
            "AMBIENT_SOUNDS.CHECK_IN_GAP_S": 600,
            "AEC_OPTIONS.ENABLED": True,
            **values,
        }

    def get_config(self, key, default=None):
        return self.values.get(key, default)


class Ctx:
    def __init__(self, cfg):
        self._cfg = cfg
        self.opened = False

    def get_config(self):
        return self._cfg

    def is_audio_channel_opened(self):
        return self.opened


class Cmd:
    def __init__(self, connects=True):
        self.calls, self.connects, self.tasks = [], connects, []

    async def connect_protocol(self):
        self.calls.append("connect")
        return self.connects

    async def start_listening(self, mode):
        self.calls.append("listen")

    async def send_wake_word_detected(self, text):
        self.calls.append(("say", text))

    def spawn(self, coro, name):
        self.tasks.append(coro)
        return None


class Proto:
    def __init__(self, closed_ago=1.0):
        self.server_closed_at = time.monotonic() - closed_ago


def make(monkeypatch, *, closed_ago=1.0, sign=("Typing", 20.0), **cfg):
    async def instant(_):
        return None

    monkeypatch.setattr(ambient_mod.asyncio, "sleep", instant)
    p = AmbientSoundsPlugin()
    p._ctx, p._cmd = Ctx(Cfg(**cfg)), Cmd()
    p._protocol = Proto(closed_ago)
    p._sounds = AmbientSounds()
    p._sounds.enabled = True
    if sign:
        label, ago = sign
        p._sounds.ingest([(label, 0.9)], time.monotonic() - ago)
    return p


def closed(p):
    """The channel closed event, then whatever it scheduled."""

    async def go():
        await p._on_channel_closed()
        for coro in p._cmd.tasks:
            await coro

    asyncio.run(go())
    return p._cmd.calls


def test_the_server_ends_it_and_someone_is_typing_so_she_asks(monkeypatch):
    calls = closed(make(monkeypatch))
    assert calls[:2] == ["connect", "listen"]
    assert "keep talking" in calls[2][1]
    assert "Typing" in calls[2][1]


def test_no_sign_of_anyone_means_quietly_idle(monkeypatch):
    assert closed(make(monkeypatch, sign=None)) == []


def test_a_sign_that_is_too_old_does_not_count(monkeypatch):
    assert closed(make(monkeypatch, sign=("Typing", 300.0))) == []


def test_the_user_ending_it_is_not_checked_in_on(monkeypatch):
    assert closed(make(monkeypatch, closed_ago=60.0)) == []


def test_off_by_switch(monkeypatch):
    p = make(monkeypatch, **{"AMBIENT_SOUNDS.CHECK_IN": False})
    assert closed(p) == []


def test_it_does_not_check_in_twice_in_a_row_without_a_reply(monkeypatch):
    p = make(monkeypatch)
    assert closed(p)
    p._cmd.calls.clear()
    p._cmd.tasks.clear()
    p._last_check_in = time.monotonic() - 10_000  # gap is over, but no reply came
    assert closed(p) == []


def test_our_own_prompt_echoed_back_is_not_a_reply(monkeypatch):
    p = make(monkeypatch)
    closed(p)
    asyncio.run(p.on_incoming_json({"type": "stt", "text": "keep talking?"}))
    assert p._spoke_since_check_in is False
    p._check_in_sent_at -= 30
    asyncio.run(p.on_incoming_json({"type": "stt", "text": "yes please"}))
    assert p._spoke_since_check_in is True


def test_a_failed_reconnect_does_not_loop(monkeypatch):
    p = make(monkeypatch)
    p._cmd.connects = False
    assert closed(p) == ["connect"]


def test_nothing_if_the_channel_already_came_back(monkeypatch):
    p = make(monkeypatch)
    p._ctx.opened = True
    assert closed(p) == []
