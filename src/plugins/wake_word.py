"""The wake word plugin.

Listens for the wake word and starts a conversation.
"""

from typing import TYPE_CHECKING, Optional

from src.constants.constants import AbortReason
from src.logging import get_logger
from src.plugins.base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()


class WakeWordPlugin(Plugin):
    name = "wake_word"
    priority = 30
    requires = ["audio"]

    def __init__(self) -> None:
        super().__init__()
        self.detector = None

    @property
    def _audio_plugin(self):
        """Get the AudioPlugin through dependency injection."""
        return self.get_dep("audio")

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        await super().setup(ctx, cmd)
        # subscribe to configuration changes (cheap; no model is loaded here)
        from src.core.event_bus import Events

        ctx.event_bus.on(Events.CONFIG_CHANGED, self._on_config_changed)

    async def _on_config_changed(self, data=None):
        """Reload the wake word model when the configuration changes."""
        logger.info(
            "WakeWordPlugin: configuration changed, reloading the wake word model"
        )
        await self.reload_model()

    async def start(self) -> None:
        try:
            # the model loads in start() rather than setup(), which avoids clashing with the PortAudio DLL
            if self.detector is None:
                from src.audio_processing.wake_word_detect import WakeWordDetector

                self.detector = WakeWordDetector()
                if not await self.detector.initialize():
                    logger.info(
                        "the wake word detector is disabled, or failed to initialise"
                    )
                    self.detector = None
                    return
                self.detector.on_detected(self._on_detected)
                self.detector.on_error = self._on_error

            if not self._audio_plugin or not self._audio_plugin.codec:
                logger.warning("no audio_codec, so wake word detection cannot start")
                return
            await self.detector.start(self._audio_plugin.codec)
        except ImportError as e:
            logger.error(f"could not import the wake word detector: {e}", exc_info=True)
            self.detector = None
        except Exception as e:
            logger.error(f"failed to start the wake word detector: {e}", exc_info=True)

    async def stop(self) -> None:
        if self.detector:
            try:
                await self.detector.stop()
            except Exception as e:
                logger.warning(
                    f"failed to stop the wake word detector: {e}", exc_info=True
                )

    def register_resources(self, pool) -> None:
        detector = self.detector
        if detector:
            pool.register("wake_word.detector", detector.shutdown)

    async def reload_model(self, model_path: Optional[str] = None) -> bool:
        """Hot-reload the wake word model.

        Args:
            model_path: the new model path (e.g. "models/en"). None reads it from the configuration.

        Returns:
            whether it reloaded
        """
        if not self.detector:
            logger.warning("the detector is not initialised, so it cannot be reloaded")
            return False

        try:
            return await self.detector.reload(model_path)
        except Exception as e:
            logger.error(
                f"failed to hot-reload the wake word model: {e}", exc_info=True
            )
            return False

    async def _on_detected(self, wake_word, full_text):
        """
        Called when the wake word is detected.
        """
        try:
            if self._ctx.is_speaking():
                await self._cmd.abort_speaking(AbortReason.WAKE_WORD_DETECTED)
                if self._audio_plugin and self._audio_plugin.codec:
                    await self._audio_plugin.codec.clear_audio_queue()
            else:
                # start the auto conversation
                await self._cmd.connect_protocol()
                from src.constants.constants import ListeningMode

                mode = (
                    ListeningMode.REALTIME
                    if self._ctx.get_config().get_config("AEC_OPTIONS.ENABLED", True)
                    else ListeningMode.AUTO_STOP
                )
                await self._cmd.start_listening(mode)
        except Exception as e:
            logger.error(
                f"failed to handle the wake word detection: {e}", exc_info=True
            )

    async def _on_error(self, error):
        """
        Called when wake word detection errors.
        """
        logger.error(f"wake word detection error: {error}", exc_info=True)
