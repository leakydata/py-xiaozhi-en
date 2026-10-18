"""The ambient sounds plugin.

Feeds the microphone to the sound tagger so the assistant can be told what is
going on in the room besides speech, and whether someone is around. See
src/audio_processing/ambient_sounds.py. Follows the on/off switch in the
settings without a restart.
"""

import asyncio
import time

from src.audio_processing import ambient_sounds
from src.audio_processing.echo_gate import get_gate
from src.core.event_bus import Events
from src.logging import get_logger
from src.plugins.base import Plugin
from src.utils.resource_finder import get_app_root

logger = get_logger()


class AmbientSoundsPlugin(Plugin):
    name = "ambient"
    priority = 40
    requires = ["audio"]

    def __init__(self) -> None:
        super().__init__()
        self._sounds = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._last_talk = time.monotonic()
        self._last_update = time.monotonic()

    def _cfg(self, key: str, default):
        return self._ctx.get_config().get_config(f"AMBIENT_SOUNDS.{key}", default)

    async def setup(self, ctx, cmd) -> None:
        await super().setup(ctx, cmd)
        ctx.event_bus.on(Events.CONFIG_CHANGED, self._on_config_changed)

    async def _on_config_changed(self, data=None):
        await self._sync()

    async def start(self) -> None:
        await self._sync()
        self._task = self._cmd.spawn(self._speak_up_loop(), "ambient_speak_up")

    async def on_incoming_json(self, message) -> None:
        # Any conversation traffic means the room is not quiet.
        if isinstance(message, dict) and message.get("type") in ("stt", "tts", "llm"):
            self._last_talk = time.monotonic()

    # ------------------------------------------------------------------
    # speaking up about a notable sound, once the room has been quiet

    async def _speak_up_loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self._maybe_speak_up()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"ambient speak-up failed: {e}", exc_info=True)
            await asyncio.sleep(10)

    async def _maybe_speak_up(self) -> None:
        sounds = self._sounds
        if sounds is None or not self._cfg("SPEAK_UP", False):
            return
        now = time.monotonic()
        if self._ctx.is_speaking():
            self._last_talk = now
            return
        quiet_for = now - max(
            self._last_talk, sounds.last_voice if sounds.last_voice else 0.0
        )
        if quiet_for < float(self._cfg("QUIET_AFTER_S", 120)):
            return
        if now - self._last_update < float(self._cfg("MIN_GAP_S", 300)):
            return
        events = sounds.notable_since(self._last_update)
        if not events:
            return

        parts = [
            f"{ambient_sounds.short_name(e.label)} "
            f"({ambient_sounds.ago_text(int(now - e.last))})"
            for e in events
        ]
        prompt = (
            "Background update from the room sensors, not from Nathan: "
            + ", ".join(parts)
            + ". If this matters to him, say so in one short, natural sentence, "
            "as if you noticed it yourself. Do not ask a question and do not "
            "mention sensors."
        )
        self._last_update = now
        if not await self._cmd.connect_protocol():
            logger.warning("ambient: could not connect to speak up; will retry later")
            self._last_update = now - float(self._cfg("MIN_GAP_S", 300)) + 30
            return
        logger.info(f"ambient: speaking up after {quiet_for:.0f}s of quiet: {parts}")
        await self._cmd.send_wake_word_detected(prompt)

    async def _sync(self) -> None:
        """Make what is running match the setting."""
        async with self._lock:
            try:
                wanted = bool(self._cfg("ENABLED", True))
                if wanted and self._sounds is None:
                    await self._begin()
                elif not wanted and self._sounds is not None:
                    await self._end()
                    logger.info("ambient sounds switched off")
                elif not wanted:
                    logger.info("ambient sounds are switched off in the config")
            except Exception as e:
                logger.error(
                    f"ambient sounds: could not apply the setting: {e}", exc_info=True
                )

    async def _begin(self) -> None:
        audio = self.get_dep("audio")
        if not audio or not audio.codec:
            logger.warning("no audio codec, so ambient sounds cannot start")
            return
        sounds = ambient_sounds.AmbientSounds(
            min_confidence=float(self._cfg("MIN_CONFIDENCE", 0.35)),
            playback_active=get_gate().playback_active,
        )
        model_dir = get_app_root() / self._cfg("MODEL_PATH", "models/ambient")
        threads = int(self._cfg("NUM_THREADS", 2))
        if not await asyncio.to_thread(sounds.load, model_dir, threads):
            return
        sounds.start()
        audio.codec.add_audio_listener(sounds)
        ambient_sounds.set_ambient(sounds)
        self._sounds = sounds

    async def _end(self) -> None:
        sounds, self._sounds = self._sounds, None
        if sounds is None:
            return
        ambient_sounds.set_ambient(None)
        audio = self.get_dep("audio")
        if audio and audio.codec:
            audio.codec.remove_audio_listener(sounds)
        await asyncio.to_thread(sounds.stop)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
        async with self._lock:
            await self._end()
