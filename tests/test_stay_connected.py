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
    from src.core.event_bus import EventBus
    from src.core.protocol_manager import ProtocolManager

    # the real manager, so the path to the live protocol is the one the app uses
    s.protocol = ProtocolManager(EventBus())
    s.protocol._transport._protocol = SimpleNamespace(
        server_closed_at=None if closed_ago is None else time.monotonic() - closed_ago
    )
    s._last_stay_connected = 0.0
    s._reconnect_listening = False
    s._last_user_text = ""
    s._last_tts_stop = -1e9
    s._quiet_redials = 0
    s.calls = []
    s._start_reconnect = lambda listening=False: s.calls.append(listening)
    return s


@pytest.fixture(autouse=True)
def fresh_state():
    from src.core import presence_state

    presence_state.reset()
    yield
    presence_state.reset()


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


def test_every_cue_is_wake_word_length():
    from src.protocols import cues

    assert all(len(c) <= cues.MAX_CHARS for c in cues.ALL)


def test_a_goodbye_is_not_undone(monkeypatch):
    for said in ("OK, bye.", "Goodbye!", "That's all for now", "good night"):
        s = session(1.0)
        s._last_user_text = said
        s._last_tts_stop = time.monotonic() - 3  # she replied, then hung up
        s._maybe_stay_connected()
        assert s.calls == [], said


def test_a_goodbye_long_before_the_hangup_is_just_a_timeout():
    s = session(1.0)
    s._last_user_text = "I'm done with the dishes, what next?"
    s._last_tts_stop = time.monotonic() - 60
    s._maybe_stay_connected()
    assert s.calls == [True]


def test_a_goodbye_stands_everything_down():
    from src.core import presence_state

    s = session(1.0)
    s._last_user_text = "bye"
    s._last_tts_stop = time.monotonic() - 3
    s._maybe_stay_connected()
    assert presence_state.standing_down()


def test_a_silent_room_gets_a_few_redials_not_one_a_minute_forever():
    s = session(1.0)
    for _ in range(5):
        s._last_stay_connected -= 100  # the next hang-up, a minute or so later
        s._maybe_stay_connected()
    assert s.calls == [True, True, True]


def test_speaking_renews_the_redials():
    from src.core import presence_state

    s = session(1.0)
    for _ in range(3):
        s._last_stay_connected -= 100
        s._maybe_stay_connected()
    s._last_stay_connected -= 100
    presence_state.user_spoke()
    s._maybe_stay_connected()
    assert s.calls == [True] * 4


def test_ordinary_words_are_not_a_goodbye():
    for said in ("Tell me about the bylaw", "What's the byline?", "Hold on a sec"):
        s = session(1.0)
        s._last_user_text = said
        s._maybe_stay_connected()
        assert s.calls == [True], said


def test_the_decision_is_made_before_the_slow_move_to_idle():
    import asyncio

    s = session(1.0)
    order = []

    class State:
        async def set_device_state(self, st):
            order.append("idle")

    s.state = State()
    s._start_reconnect = lambda listening=False: order.append("redial")
    asyncio.run(s._on_audio_channel_closed())
    assert order == ["redial", "idle"]


def test_a_refused_text_is_recorded():
    import asyncio

    from src.protocols import cues

    s = session(None)
    s.plugins = type(
        "P", (), {"notify_incoming_json": staticmethod(lambda m: asyncio.sleep(0))}
    )()
    sent = cues.note_sent("a long sentence that is far too long")
    asyncio.run(
        s._on_incoming_json(
            {
                "type": "alert",
                "message": "Detect is only for wake words, do not send long texts.",
            }
        )
    )
    assert cues.rejected_since(sent)


def test_nobody_heard_for_a_while_means_standby(monkeypatch):
    s = session(1.0)
    monkeypatch.setattr(
        ConversationSession, "_someone_around", staticmethod(lambda w: False)
    )
    s._maybe_stay_connected()
    assert s.calls == []


def test_someone_heard_recently_keeps_it_connected(monkeypatch):
    s = session(1.0)
    monkeypatch.setattr(
        ConversationSession, "_someone_around", staticmethod(lambda w: True)
    )
    s._maybe_stay_connected()
    assert s.calls == [True]


def _network_error(s):
    import asyncio

    class State:
        def set_keep_listening(self, v):
            pass

        def is_idle(self):
            return True

    s.state = State()
    asyncio.run(s._on_network_error("Connection lost"))


def test_a_drop_mid_conversation_comes_back_listening():
    from src.core import presence_state

    s = session(None)
    presence_state.user_spoke()
    _network_error(s)
    assert s.calls == [True]


def test_a_drop_with_nobody_talking_comes_back_idle():
    s = session(None)
    _network_error(s)
    assert s.calls == [False]


def test_a_drop_after_a_goodbye_comes_back_idle():
    from src.core import presence_state

    s = session(None)
    presence_state.user_spoke()
    presence_state.stand_down(300)
    _network_error(s)
    assert s.calls == [False]
