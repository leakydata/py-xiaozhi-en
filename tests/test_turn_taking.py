"""Natural turn-taking: the rules, the session's manual mode, and the plugin's decisions.

The models themselves are measured separately on real recordings
(sidecars/turn_bench.py); these check that their output is turned into the
right action, and that nothing changes while the feature is off.
"""

import asyncio

import pytest

from src.audio_processing.turn_judge import (
    TurnSettings,
    ending,
    is_backchannel,
    is_interruption,
    turn_over,
)
from src.bootstrap.session import ConversationSession
from src.constants.constants import AbortReason, DeviceState, ListeningMode

# ---------------------------------------------------------------- the rules


@pytest.mark.parametrize(
    "text, kind",
    [
        ("I'm looking for my", "incomplete"),
        # A recogniser puts a full stop at a pause; the word still wins.
        ("I'm looking for my.", "incomplete"),
        ("Hand me the", "incomplete"),
        ("and um", "incomplete"),
        ("I want to,", "incomplete"),
        ("Where did I leave the hammer?", "complete"),
        # Auxiliaries and pronouns end questions perfectly well.
        ("What else am I gonna do?", "complete"),
        ("I left it somewhere, didn't I?", "complete"),
        # Spoken English strands prepositions all the time.
        ("more than I'm supposed to.", "complete"),
        # Numbers are words: this ends on fifty, not on "for".
        ("I got one for $40, $50.", "complete"),
        ("They look distinctly", "incomplete"),
        ("That's somebody's", "incomplete"),
        ("It's fine", "neutral"),
        ("", "neutral"),
    ],
)
def test_ending(text, kind):
    assert ending(text) == kind


def test_unfinished_phrase_waits_through_a_pause_a_timer_would_end():
    s = TurnSettings()
    assert not turn_over("I'm looking for my", 1.5, 2.0, s)
    assert not turn_over("I'm looking for my", 2.9, 2.0, s)
    assert turn_over("I'm looking for my", 3.0, 2.0, s)


def test_finished_question_answered_quickly():
    s = TurnSettings()
    assert not turn_over("Where's the hammer?", 0.5, 1.5, s)
    assert turn_over("Where's the hammer?", 0.7, 1.5, s)


def test_never_ends_while_a_voice_is_heard():
    # Recognisers drop "uhhh"; the speech detector still hears it.
    assert not turn_over("Where's the hammer?", 2.0, 1.5, speaking=True)


def test_unfinished_uses_the_more_cautious_pause():
    # Word timing said 3.5 s, the speech detector heard something 1 s ago.
    assert not turn_over("They look distinctly", 3.5, 2.0, vad_silence_s=1.0)


def test_no_words_is_not_a_turn_yet():
    s = TurnSettings()
    assert not turn_over("", 1.5, 1.0, s)
    assert turn_over("", 3.0, 1.0, s)


def test_a_cough_does_not_end_a_turn():
    assert not turn_over("Hm.", 5.0, 0.2)


@pytest.mark.parametrize("text", ["yeah", "Mm-hm.", "right, okay", "uh-huh yeah"])
def test_backchannels_are_not_interruptions(text):
    assert is_backchannel(text)
    assert not is_interruption(text)


def test_real_words_interrupt():
    assert is_interruption("wait, stop")
    assert is_interruption("no that's wrong")


def test_one_word_is_not_enough():
    assert not is_interruption("hey")


def test_the_assistants_own_voice_is_not_an_interruption():
    said = "The hammer is in the garage on the shelf"
    # Without echo cancellation the microphone hears this coming back.
    assert not is_interruption("the hammer is in the garage", said)
    assert is_interruption("the hammer is in the truck actually", said)


# ---------------------------------------------------------------- the session


class FakeState:
    def __init__(self, client_endpointing=False):
        self.client_endpointing = client_endpointing
        self.aec_enabled = False
        self.keep_listening = True
        self.listening_mode = ListeningMode.AUTO_STOP
        self.device_state = DeviceState.LISTENING
        self.turn_ended = False

    def set_turn_ended(self, v):
        self.turn_ended = v

    def set_listening_mode(self, m):
        self.listening_mode = m

    def set_keep_listening(self, v):
        self.keep_listening = v

    def is_listening(self):
        return self.device_state == DeviceState.LISTENING

    def is_idle(self):
        return self.device_state == DeviceState.IDLE

    async def set_device_state(self, s):
        if s != self.device_state:
            self.turn_ended = False
        self.device_state = s


class FakeProtocol:
    def __init__(self):
        self.sent = []
        self.protocol = object()

    def is_audio_channel_opened(self):
        return True

    async def connect(self):
        return True

    async def send_start_listening(self, mode):
        self.sent.append(("start", mode))

    async def send_stop_listening(self):
        self.sent.append(("stop",))


class FakePlugins:
    async def notify_protocol_connected(self, _):
        pass


def _session(endpointing):
    return ConversationSession(FakeState(endpointing), FakeProtocol(), FakePlugins())


@pytest.mark.asyncio
async def test_off_means_the_server_decides_as_before():
    s = _session(False)
    await s.start_auto_conversation()
    assert s.protocol.sent[-1] == ("start", ListeningMode.AUTO_STOP)


@pytest.mark.asyncio
async def test_on_asks_the_server_to_wait_for_the_client():
    s = _session(True)
    await s.start_auto_conversation()
    assert s.protocol.sent[-1] == ("start", ListeningMode.MANUAL)
    # Still a conversation: it should listen again after each reply.
    assert s.state.keep_listening


@pytest.mark.asyncio
async def test_ending_a_turn_stops_listening_once():
    s = _session(True)
    await s.end_user_turn()
    await s.end_user_turn()  # a second tick saying the same thing
    assert s.protocol.sent.count(("stop",)) == 1
    assert s.state.turn_ended
    assert s.state.is_listening()  # not IDLE: that would end the UI's session


@pytest.mark.asyncio
async def test_no_reply_hands_the_floor_back():
    s = _session(True)
    s.REPLY_TIMEOUT_S = 0.05
    await s.end_user_turn()
    await asyncio.sleep(0.15)
    assert not s.state.turn_ended
    assert s.protocol.sent[-1] == ("start", ListeningMode.MANUAL)


@pytest.mark.asyncio
async def test_a_reply_cancels_the_watchdog():
    s = _session(True)
    s.REPLY_TIMEOUT_S = 0.05
    await s.end_user_turn()
    await s.state.set_device_state(DeviceState.SPEAKING)
    await asyncio.sleep(0.15)
    assert ("start", ListeningMode.MANUAL) not in s.protocol.sent


@pytest.mark.asyncio
async def test_an_old_watchdog_leaves_a_later_turn_alone():
    s = _session(True)
    s.REPLY_TIMEOUT_S = 0.1
    await s.end_user_turn()
    await asyncio.sleep(0.06)
    # The reply came and went, and a second turn has just ended.
    await s.state.set_device_state(DeviceState.SPEAKING)
    await s.state.set_device_state(DeviceState.LISTENING)
    await s.end_user_turn()
    await asyncio.sleep(0.06)  # the first watchdog fires here
    assert s.state.turn_ended, "a stale watchdog reopened the floor"


def test_capture_stops_once_the_turn_has_ended():
    from src.core.event_bus import EventBus
    from src.core.state_manager import StateManager

    st = StateManager(EventBus(), aec_enabled=False)
    st._device_state = DeviceState.LISTENING
    assert st.should_capture_audio()
    st.set_turn_ended(True)
    assert not st.should_capture_audio()


# ---------------------------------------------------------------- the plugin


class FakeSidecar:
    def __init__(self, ticks):
        self.ticks = list(ticks)
        self.resets = 0

    async def reset(self):
        self.resets += 1

    async def tick(self, audio):
        return self.ticks.pop(0) if self.ticks else None


class FakeCtx:
    def __init__(self, state):
        self.state = state
        self.turn_ended = False
        self.config = {}

    def get_device_state(self):
        return self.state

    def is_turn_ended(self):
        return self.turn_ended

    def get_config(self):
        cfg = self.config

        class C:
            def get_config(self, key, default=None):
                return cfg.get(key, default)

        return C()


class FakeCmd:
    def __init__(self):
        self.ended = 0
        self.aborted = []

    async def end_user_turn(self):
        self.ended += 1

    async def abort_speaking(self, reason):
        self.aborted.append(reason)


def _plugin(state, ticks, **config):
    from src.plugins.turn_taking import TurnTakingPlugin

    p = TurnTakingPlugin()
    p._ctx = FakeCtx(state)
    p._ctx.config = {f"TURN_TAKING.{k}": v for k, v in config.items()}
    p._cmd = FakeCmd()
    p._sidecar = FakeSidecar(ticks)
    return p


def _tick(text, silence, speech=2.0, speaking=False):
    return {
        "text": text,
        "silence_s": silence,
        "silence_words_s": silence,
        "speech_s": speech,
        "speaking": speaking,
    }


@pytest.mark.asyncio
async def test_plugin_waits_through_my_then_answers_hammer():
    p = _plugin(
        DeviceState.LISTENING,
        [
            _tick("I'm looking for my", 1.5),
            _tick("I'm looking for my", 2.4),
            _tick("I'm looking for my hammer.", 0.3, speaking=False),
            _tick("I'm looking for my hammer.", 0.8),
        ],
    )
    for _ in range(3):
        await p._step()
    assert p.cmd.ended == 0
    await p._step()
    assert p.cmd.ended == 1


def _heard_in_the_room(monkeypatch):
    """The echo gate having found sound the speakers cannot account for.

    The gate is fed from the audio callbacks, which these tests do not run, so
    its verdict is set directly.
    """
    from src.audio_processing.echo_gate import get_gate

    monkeypatch.setattr(get_gate(), "recent_double_talk", lambda *a, **k: True)


@pytest.mark.asyncio
async def test_plugin_ignores_mm_hm_but_stops_for_real_words(monkeypatch):
    _heard_in_the_room(monkeypatch)
    p = _plugin(
        DeviceState.SPEAKING,
        [_tick("mm-hm", 0.0), _tick("mm-hm yeah", 0.0), _tick("wait, stop that", 0.0)],
    )
    p._assistant_said = ["The hammer is in the garage."]
    await p._step()
    await p._step()
    assert p.cmd.aborted == []
    await p._step()
    assert p.cmd.aborted == [AbortReason.USER_INTERRUPTION]


@pytest.mark.asyncio
async def test_plugin_holds_on_when_only_the_speakers_can_be_heard():
    """Real words, but nothing in the room the reply does not account for: the
    microphone is hearing the reply itself. This is what cut replies in half
    over speakers - the words arrive mis-transcribed, so matching them against
    what the assistant said cannot catch them."""
    p = _plugin(DeviceState.SPEAKING, [_tick("I'm staying on the street.", 0.0)])
    p._assistant_said = []  # this server sends no sentence_start to compare with
    await p._step()
    assert p.cmd.aborted == []


@pytest.mark.asyncio
async def test_the_guard_can_be_switched_off(monkeypatch):
    p = _plugin(DeviceState.SPEAKING, [_tick("I'm staying on the street.", 0.0)])
    p._ctx.config["TURN_TAKING.ECHO_GUARD"] = False
    await p._step()
    assert p.cmd.aborted == [AbortReason.USER_INTERRUPTION]


@pytest.mark.asyncio
async def test_plugin_does_not_interrupt_itself():
    p = _plugin(DeviceState.SPEAKING, [_tick("the hammer is in the garage", 0.0)])
    p._assistant_said = ["The hammer is in the garage."]
    await p._step()
    assert p.cmd.aborted == []


@pytest.mark.asyncio
async def test_interruptions_can_be_switched_off_alone():
    p = _plugin(
        DeviceState.SPEAKING, [_tick("wait, stop that", 0.0)], INTERRUPTIONS=False
    )
    await p._step()
    assert p.cmd.aborted == []


@pytest.mark.asyncio
async def test_no_tick_no_action():
    # A sidecar that is late or down returns None: nothing happens, and the
    # server's own behaviour is what the user gets.
    p = _plugin(DeviceState.LISTENING, [None, None])
    await p._step()
    await p._step()
    assert p.cmd.ended == 0


@pytest.mark.asyncio
async def test_each_phase_is_a_fresh_turn():
    p = _plugin(DeviceState.LISTENING, [None, None])
    await p._step()
    p.ctx.state = DeviceState.SPEAKING
    await p._step()
    assert p._sidecar.resets == 2
