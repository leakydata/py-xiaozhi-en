"""The ambient sounds plugin.

Feeds the microphone to the sound tagger so the assistant can be told what is
going on in the room besides speech. See src/audio_processing/ambient_sounds.py.
"""

import asyncio
from typing import TYPE_CHECKING

from src.audio_processing import ambient_sounds
from src.audio_processing.echo_gate import get_gate
from src.logging import get_logger
from src.plugins.base import Plugin
from src.utils.resource_finder import get_app_root

if TYPE_CHECKING:
    pass

logger = get_logger()


class AmbientSoundsPlugin(Plugin):
    name = "ambient"
    priority = 40
    requires = ["audio"]

    def __init__(self) -> None:
        super().__init__()
        self._sounds = None

    def _cfg(self, key: str, default):
        return self._ctx.get_config().get_config(f"AMBIENT_SOUNDS.{key}", default)

    async def start(self) -> None:
        try:
            if not self._cfg("ENABLED", True):
                logger.info("ambient sounds are switched off in the config")
                return
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
        except Exception as e:
            logger.error(f"failed to start ambient sounds: {e}", exc_info=True)

    async def stop(self) -> None:
        sounds, self._sounds = self._sounds, None
        if sounds is None:
            return
        ambient_sounds.set_ambient(None)
        audio = self.get_dep("audio")
        if audio and audio.codec:
            audio.codec.remove_audio_listener(sounds)
        await asyncio.to_thread(sounds.stop)
