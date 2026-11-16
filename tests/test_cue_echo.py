"""The server reports an accepted cue as stt; that is not the user talking."""

import asyncio

from src.core import presence_state
from src.memory.conversation_log import ConversationLog
from src.protocols import cues


def test_our_cue_coming_back_is_an_echo():
    cues.note_sent(cues.STILL_THERE)
    assert cues.is_echo("Ask if I'm here.")
    assert not cues.is_echo("ask if I'm here and also something else")


def test_typed_text_is_never_an_echo():
    cues.note_sent("what's for dinner")
    assert not cues.is_echo("what's for dinner")


def test_an_old_cue_is_not_an_echo(monkeypatch):
    cues.note_sent(cues.REMINDER)
    monkeypatch.setattr(cues, "_last_sent_at", cues._last_sent_at - 60)
    assert not cues.is_echo(cues.REMINDER)


def test_the_echo_does_not_count_as_the_user_speaking():
    from tests.test_stay_connected import session

    presence_state.reset()
    s = session(None)
    s.plugins = type(
        "P", (), {"notify_incoming_json": staticmethod(lambda m: asyncio.sleep(0))}
    )()
    cues.note_sent(cues.STILL_THERE)
    asyncio.run(s._on_incoming_json({"type": "stt", "text": cues.STILL_THERE}))
    assert presence_state.last_user_speech() < 0 and s._last_user_text == ""
    asyncio.run(s._on_incoming_json({"type": "stt", "text": "yes I'm here"}))
    assert presence_state.last_user_speech() > 0 and s._last_user_text == "yes I'm here"
    presence_state.reset()


def test_the_echo_is_not_logged_as_the_user(tmp_path):
    lg = ConversationLog(tmp_path)
    cues.note_sent(cues.STILL_THERE)
    lg.on_message({"type": "stt", "text": cues.STILL_THERE})
    lg.on_message({"type": "tts", "state": "sentence_start", "text": "Are you there?"})
    assert lg.flush() == ("", "Are you there?")
