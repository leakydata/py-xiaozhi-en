"""Long text typed in the chat box reaches her through a short cue and a tool."""

import asyncio
import json

from src.core import typed_messages
from src.mcp.tools.typed.register import typed_message_payload
from src.plugins.ui_session import SessionActions
from src.protocols import cues


class Cmd:
    def __init__(self):
        self.sent = []

    async def send_wake_word_detected(self, text):
        self.sent.append(text)

    async def abort_speaking(self, reason):
        pass


class Ctx:
    def is_speaking(self):
        return False


def plugin():
    p = SessionActions.__new__(SessionActions)
    p._cmd, p._ctx = Cmd(), Ctx()

    async def ok():
        return True

    p._ensure_listen_session = ok
    return p


def test_short_text_goes_straight_through():
    typed_messages.clear()
    p = plugin()
    asyncio.run(p.send_text("what time is it?"))
    assert p._cmd.sent == ["what time is it?"]
    assert typed_messages.take_all() == []


def test_long_text_is_parked_and_a_cue_is_sent():
    typed_messages.clear()
    p = plugin()
    long = "Please remind me to call the garage about the invoice tomorrow morning"
    asyncio.run(p.send_text(long))
    assert p._cmd.sent == [cues.TYPED]
    assert len(cues.TYPED) <= 21
    assert json.loads(asyncio.run(typed_message_payload({})))["messages"] == [long]
    # taken once
    assert json.loads(asyncio.run(typed_message_payload({})))["messages"] == []


def test_the_typed_cue_is_recognised_as_an_echo():
    cues.note_sent(cues.TYPED)
    assert cues.is_echo(cues.TYPED)
