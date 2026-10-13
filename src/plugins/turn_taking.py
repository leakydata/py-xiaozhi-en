"""Natural turn-taking: end the user's turn from what they said, and let them cut in.

Off by default (TURN_TAKING.ENABLED, or the switch in Settings > System). When
it is on:

- While listening, the words so far and the length of the pause decide when
  the user has finished (turn_judge.py). "I'm looking for my..." waits; "Where
  did I leave the hammer?" answers after ~0.7 s. The server is asked for
  "manual" mode, so it waits for the client's word instead of guessing from
  silence.
- While the assistant is talking, real words cut it off; "yeah" or "mm-hm" do
  not, and nor do the assistant's own words coming back through the speakers.

Words and speech detection come from the home server's models, through a
sidecar in its environment (sidecars/turn_sidecar.py). Measured on 80 real
moments from the Boswell archive: 10/40 cut-offs against 29/40 for a fixed
0.8 s silence and 15/40 for the phone's 1.5 s, and finished turns noticed in a
median 0.9 s against the phone's 1.5 s.

If the sidecar is not ready - still loading, missing, or crashed - nothing
changes: the server decides, exactly as before.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import numpy as np

from src.audio_processing.turn_judge import (
    TurnSettings,
    is_interruption,
    turn_over,
)
from src.constants.constants import AbortReason, DeviceState
from src.logging import get_logger
from src.plugins.base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()

#: How much of what the assistant just said to keep for spotting its own echo.
_ECHO_SENTENCES = 3


class TurnTakingPlugin(Plugin):
    name = "turn_taking"
    priority = 35
    requires = ["audio"]

    def __init__(self) -> None:
        super().__init__()
        self._sidecar = None
        self._starting: asyncio.Task | None = None
        self._loop_task: asyncio.Task | None = None
        self._listening_on = None  # the codec we are attached to
        self._buf: list[np.ndarray] = []
        self._buf_lock = threading.Lock()
        self._phase: DeviceState | None = None
        self._assistant_said: list[str] = []
        self._enabled = False

    # ------------------------------------------------------------ settings

    def _cfg(self, key, default=None):
        return self.ctx.get_config().get_config(f"TURN_TAKING.{key}", default)

    def _settings(self) -> TurnSettings:
        return TurnSettings(
            complete_s=float(self._cfg("COMPLETE_S", 0.7)),
            neutral_s=float(self._cfg("NEUTRAL_S", 1.2)),
            incomplete_s=float(self._cfg("INCOMPLETE_S", 3.0)),
            barge_in_words=int(self._cfg("BARGE_IN_WORDS", 2)),
        )

    @property
    def _audio_plugin(self):
        return self.get_dep("audio")

    async def setup(self, ctx: PluginContext, cmd: PluginCommands) -> None:
        await super().setup(ctx, cmd)
        from src.core.event_bus import Events

        ctx.event_bus.on(Events.CONFIG_CHANGED, self._on_config_changed)

    async def start(self) -> None:
        await self._apply()

    async def _on_config_changed(self, _data=None) -> None:
        await self._apply()

    async def _apply(self) -> None:
        """Bring the running state in line with the switch."""
        want = bool(self._cfg("ENABLED", False))
        if want == self._enabled:
            return
        self._enabled = want
        if want:
            logger.info("turn-taking: switched on, loading the home server's models")
            self._starting = asyncio.create_task(self._bring_up())
        else:
            logger.info("turn-taking: switched off, the server decides turns again")
            await self._take_down()

    # ------------------------------------------------------------ lifecycle

    async def _bring_up(self) -> None:
        from src.audio_processing.turn_sidecar_client import TurnSidecar

        sidecar = TurnSidecar(
            self._cfg("BOSWELL_SERVER_DIR", "~/Documents/electronics/boswell_server"),
            self._cfg("SIDECAR_PYTHON", ""),
        )
        if not await sidecar.start():
            # Stays switched on in config; the next settings save retries.
            self._enabled = False
            return
        if not self._enabled:  # switched off again while it loaded
            await sidecar.close()
            return
        await sidecar.hotwords(list(self._cfg("HOTWORDS", []) or []))
        self._sidecar = sidecar

        codec = self._audio_plugin.codec if self._audio_plugin else None
        if codec is None:
            logger.warning("turn-taking: no audio codec to listen to")
            await self._take_down()
            return
        codec.add_audio_listener(self)
        self._listening_on = codec
        self._loop_task = asyncio.create_task(self._loop())
        # Only now, with the models up, does the server get told to wait for us.
        self.cmd.set_client_endpointing(True)

    async def _take_down(self) -> None:
        self.cmd.set_client_endpointing(False)
        for task in (self._starting, self._loop_task):
            if task and not task.done():
                task.cancel()
        self._starting = self._loop_task = None
        if self._listening_on is not None:
            try:
                self._listening_on.remove_audio_listener(self)
            except Exception:
                pass
            self._listening_on = None
        if self._sidecar is not None:
            await self._sidecar.close()
            self._sidecar = None
        with self._buf_lock:
            self._buf.clear()

    async def stop(self) -> None:
        await self._take_down()

    def register_resources(self, pool) -> None:
        pool.register("turn_taking", self._take_down)

    # ------------------------------------------------------------ audio in

    def on_audio_data(self, audio_data: np.ndarray) -> None:
        """Called from the audio thread with 16 kHz mono frames."""
        with self._buf_lock:
            self._buf.append(np.asarray(audio_data, dtype=np.float32).reshape(-1))

    def _take_audio(self) -> np.ndarray | None:
        with self._buf_lock:
            if not self._buf:
                return None
            chunk = np.concatenate(self._buf)
            self._buf.clear()
        return chunk

    # ------------------------------------------------------------ assistant speech

    async def on_incoming_json(self, message) -> None:
        if not isinstance(message, dict) or message.get("type") != "tts":
            return
        if message.get("state") == "sentence_start" and message.get("text"):
            self._assistant_said.append(message["text"])
            del self._assistant_said[:-_ECHO_SENTENCES]

    # ------------------------------------------------------------ the loop

    async def _loop(self) -> None:
        tick_s = float(self._cfg("TICK_S", 0.3))
        while self._enabled and self._sidecar is not None:
            await asyncio.sleep(tick_s)
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"turn-taking: tick failed: {e}", exc_info=True)

    async def _step(self) -> None:
        state = self.ctx.get_device_state()
        if state != self._phase:
            # A new phase is a new turn: what was heard before is not part of it.
            self._phase = state
            self._take_audio()
            await self._sidecar.reset()
            if state == DeviceState.SPEAKING:
                pass  # keep _assistant_said: sentence_start may precede this
            elif state == DeviceState.LISTENING:
                self._assistant_said.clear()

        if state == DeviceState.IDLE:
            self._take_audio()  # nothing is being judged; don't let it pile up
            return

        if state == DeviceState.LISTENING:
            if self.ctx.is_turn_ended():
                self._take_audio()
                return
            tick = await self._sidecar.tick(self._take_audio())
            if tick and turn_over(
                tick["text"],
                tick.get("silence_words_s", tick["silence_s"]),
                tick["speech_s"],
                self._settings(),
                speaking=tick["speaking"],
                vad_silence_s=tick["silence_s"],
            ):
                logger.info(f"turn-taking: turn over after {tick['text'][-60:]!r}")
                await self.cmd.end_user_turn()
            return

        if state == DeviceState.SPEAKING:
            if not self._cfg("INTERRUPTIONS", True):
                self._take_audio()
                return
            tick = await self._sidecar.tick(self._take_audio())
            if tick and is_interruption(
                tick["text"], " ".join(self._assistant_said), self._settings()
            ):
                logger.info(f"turn-taking: interrupted by {tick['text'][-60:]!r}")
                await self.cmd.abort_speaking(AbortReason.USER_INTERRUPTION)
