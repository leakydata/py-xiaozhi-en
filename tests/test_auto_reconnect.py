"""A dropped connection should redial itself.

Before this, a network error set the device idle and nothing else happened:
no retry anywhere, so the app sat silent until someone pressed a button. The
wake word could not rescue it either, because what a wake word needs is the
connection that just went away.
"""

import asyncio

import pytest

from src.bootstrap.session import ConversationSession
from src.constants.constants import DeviceState


class FakeState:
    def __init__(self):
        self.keep_listening = True
        self.device_state = DeviceState.LISTENING

    def set_keep_listening(self, value):
        self.keep_listening = value

    def is_idle(self):
        return self.device_state == DeviceState.IDLE

    async def set_device_state(self, state):
        self.device_state = state


class FakeProtocol:
    """A protocol that refuses to connect until told otherwise."""

    def __init__(self, succeed_after=1):
        self.attempts = 0
        self.succeed_after = succeed_after
        self.opened = False
        self.protocol = object()

    def is_audio_channel_opened(self):
        return self.opened

    async def connect(self):
        self.attempts += 1
        if self.attempts >= self.succeed_after:
            self.opened = True
        return self.opened


class FakePlugins:
    async def notify_protocol_connected(self, _):
        pass


def _session(protocol):
    s = ConversationSession(FakeState(), protocol, FakePlugins())
    # Keep the test quick: the real backoff starts at two seconds.
    s._reconnect_settings = lambda: (True, 0.02, 0)
    return s


@pytest.mark.asyncio
async def test_network_error_starts_a_redial():
    protocol = FakeProtocol(succeed_after=3)
    session = _session(protocol)

    await session._on_network_error("connection check failed")
    assert session._reconnect_task is not None

    await asyncio.wait_for(session._reconnect_task, timeout=5)
    assert protocol.opened
    assert protocol.attempts == 3


@pytest.mark.asyncio
async def test_redial_stops_once_connected():
    protocol = FakeProtocol(succeed_after=1)
    session = _session(protocol)

    await session._on_network_error("dropped")
    await asyncio.wait_for(session._reconnect_task, timeout=5)

    attempts = protocol.attempts
    await asyncio.sleep(0.1)
    assert protocol.attempts == attempts, "kept redialing after it was connected"


@pytest.mark.asyncio
async def test_a_reconnect_comes_back_idle_not_listening():
    """The drop interrupted whatever was being said.

    Opening a live microphone on a reconnect nobody asked for is the wrong
    answer, so the channel-opened handler must be told to stay idle.
    """
    protocol = FakeProtocol(succeed_after=1)
    session = _session(protocol)
    session.state.device_state = DeviceState.LISTENING

    await session._on_network_error("dropped")
    assert session.state.device_state == DeviceState.IDLE

    await asyncio.wait_for(session._reconnect_task, timeout=5)
    assert session.state.device_state == DeviceState.IDLE


@pytest.mark.asyncio
async def test_auto_reconnect_can_be_turned_off():
    protocol = FakeProtocol(succeed_after=1)
    session = ConversationSession(FakeState(), protocol, FakePlugins())
    session._reconnect_settings = lambda: (False, 0.02, 0)

    await session._on_network_error("dropped")
    assert session._reconnect_task is None
    assert protocol.attempts == 0


@pytest.mark.asyncio
async def test_it_gives_up_after_the_configured_attempts():
    protocol = FakeProtocol(succeed_after=99)
    session = ConversationSession(FakeState(), protocol, FakePlugins())
    session._reconnect_settings = lambda: (True, 0.01, 3)

    await session._on_network_error("dropped")
    await asyncio.wait_for(session._reconnect_task, timeout=5)
    assert protocol.attempts == 3


@pytest.mark.asyncio
async def test_only_one_redial_runs_at_a_time():
    protocol = FakeProtocol(succeed_after=4)
    session = _session(protocol)

    await session._on_network_error("dropped")
    first = session._reconnect_task
    await session._on_network_error("dropped again")
    assert session._reconnect_task is first

    await asyncio.wait_for(session._reconnect_task, timeout=5)
    assert protocol.attempts == 4
