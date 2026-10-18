"""The ambient sounds plugin.

Feeds the microphone to the sound tagger so the assistant can be told what is
going on in the room besides speech, and whether someone is around. See
src/audio_processing/ambient_sounds.py. Follows the on/off switch in the
settings without a restart.
"""

import asyncio

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

    def _cfg(self, key: str, default):
        return self._ctx.get_config().get_config(f"AMBIENT_SOUNDS.{key}", default)

    async def setup(self, ctx, cmd) -> None:
        await super().setup(ctx, cmd)
        ctx.event_bus.on(Events.CONFIG_CHANGED, self._on_config_changed)

    async def _on_config_changed(self, data=None):
        await self._sync()

    async def start(self) -> None:
        await self._sync()

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
        async with self._lock:
            await self._end()
