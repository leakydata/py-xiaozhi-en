"""The server hangs up on a quiet session: reconnect and keep listening."""

import time
from types import SimpleNamespace

import pytest

from src.bootstrap.session import ConversationSession


class Cfg:
    def __init__(self, on=True):
        self.on = on

    def get_config(self, key, default=None):
        return self.on if key == "NETWORK_OPTIONS.STAY_CONNECTED" else default


def session(closed_ago):
    s = ConversationSession.__new__(ConversationSession)
    s.protocol = SimpleNamespace(
        _protocol=SimpleNamespace(
            server_closed_at=None
            if closed_ago is None
            else time.monotonic() - closed_ago
        )
    )
    s._last_stay_connected = 0.0
    s._reconnect_listening = False
    s.calls = []
    s._start_reconnect = lambda listening=False: s.calls.append(listening)
    return s


@pytest.fixture(autouse=True)
def config(monkeypatch):
    import src.utils.config_manager as cm

    monkeypatch.setattr(cm, "get_config", lambda: Cfg(True))


def test_a_server_hangup_reconnects_and_listens():
    s = session(1.0)
    s._maybe_stay_connected()
    assert s.calls == [True]


def test_a_close_we_caused_is_left_alone():
    for closed in (None, 60.0):
        s = session(closed)
        s._maybe_stay_connected()
        assert s.calls == []


def test_a_hangup_straight_after_the_last_one_does_not_loop():
    s = session(1.0)
    s._maybe_stay_connected()
    s._maybe_stay_connected()
    assert s.calls == [True]


def test_it_can_be_turned_off(monkeypatch):
    import src.utils.config_manager as cm

    monkeypatch.setattr(cm, "get_config", lambda: Cfg(False))
    s = session(1.0)
    s._maybe_stay_connected()
    assert s.calls == []


def test_the_check_in_and_speak_up_texts_are_short_enough_for_the_server():
    import inspect

    from src.plugins import ambient

    src = inspect.getsource(ambient)
    assert "Nathan is still here. Ask in one short sentence" in src
    assert ")[:150]" in src
