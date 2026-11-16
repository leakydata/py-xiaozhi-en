"""Due reminders are raised with a short cue; she announces and closes them."""

import asyncio

from src.core import presence_state
from src.plugins import reminders as mod
from src.plugins.reminders import RemindersPlugin
from src.protocols import cues


class Cfg:
    def get_config(self, key, default=None):
        return default


class Ctx:
    def __init__(self, listening=True):
        self.listening = listening

    def is_listening(self):
        return self.listening

    def get_config(self):
        return Cfg()


class Cmd:
    def __init__(self, outcome):
        self.calls, self.outcome = [], outcome

    async def connect_protocol(self):
        self.calls.append("connect")
        return True

    async def start_listening(self, mode):
        self.calls.append("listen")

    async def send_wake_word_detected(self, text):
        self.calls.append(text)
        if self.outcome == "refused":
            cues.note_rejected()
        elif self.outcome == "answered":
            presence_state.activity()


class Mem:
    def __init__(self):
        self.done = []

    def complete(self, nid):
        self.done.append(nid)


DUE = [{"id": 1, "text": "Feed Eli"}, {"id": 2, "text": "Call the vet"}]


def run(monkeypatch, outcome, listening=True, times=1):
    async def instant(_=0):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", instant)
    presence_state.reset()
    mem = Mem()
    import src.memory.store as store

    monkeypatch.setattr(store, "get_memory", lambda: mem)
    p = RemindersPlugin()
    p._ctx, p._cmd = Ctx(listening), Cmd(outcome)
    for _ in range(times):
        asyncio.run(p._announce(DUE[0], DUE))
    return p, mem


def test_the_cue_goes_out_and_she_is_left_to_close_them(monkeypatch):
    p, mem = run(monkeypatch, "answered")
    assert p._cmd.calls == [cues.REMINDER]
    assert mem.done == [] and set(p._cued) == {1, 2}


def test_from_idle_it_starts_listening_first(monkeypatch):
    p, _ = run(monkeypatch, "answered", listening=False)
    assert p._cmd.calls == ["connect", "listen", cues.REMINDER]


def test_a_refused_cue_backs_off_ten_minutes(monkeypatch):
    p, mem = run(monkeypatch, "refused")
    assert mem.done == [] and not p._cued
    assert p._cue_backoff_until - mod.time.monotonic() > 500


def test_an_unanswered_cue_retries_sooner(monkeypatch):
    p, _ = run(monkeypatch, "silent")
    assert 60 < p._cue_backoff_until - mod.time.monotonic() < 200


def test_raised_three_times_without_being_closed_it_is_closed(monkeypatch):
    _, mem = run(monkeypatch, "answered", times=3)
    assert mem.done == [1, 2]
