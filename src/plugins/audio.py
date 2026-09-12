"""The audio plugin.

Handles audio capture, encoding, playback and sending.
The AudioCodec is published through Events.AUDIO_CODEC_CHANGED rather than wired straight into MusicPlayer.
"""

import asyncio
import os
from typing import TYPE_CHECKING

from src.audio_codecs.audio_codec import AudioCodec
from src.logging import get_logger
from src.plugins.base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()

MAX_CONCURRENT_AUDIO_SENDS = 4


class AudioPlugin(Plugin):
    name = "audio"
    priority = 10  # highest priority; the other plugins depend on audio_codec

    def __init__(self) -> None:
        super().__init__()
        self.codec: AudioCodec | None = None
        self._send_sem = asyncio.Semaphore(MAX_CONCURRENT_AUDIO_SENDS)
        self._in_silence_period = False

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        await super().setup(ctx, cmd)

        if os.getenv("XIAOZHI_DISABLE_AUDIO") == "1":
            logger.warning(
                "XIAOZHI_DISABLE_AUDIO=1, the audio plugin is running in disabled mode"
            )
            return

        try:
            self.codec = AudioCodec()
            await self.codec.initialize()
            self.codec.set_encoded_callback(self._on_encoded_audio)

            from src.core.event_bus import Events

            ctx.event_bus.on(Events.CONFIG_CHANGED, self._on_config_changed)
            ctx.event_bus.on(
                Events.AUDIO_DEVICES_REFRESH_REQUEST, self._on_devices_refresh_request
            )
            # the codec is published in start(): MusicPlayer subscribes to the EventBus during McpPlugin.setup

        except Exception as e:
            logger.error(f"audio plugin initialisation failed: {e}", exc_info=True)
            self.codec = None
            self.mark_failed()
            raise

    async def start(self) -> None:
        await super().start()
        if self.codec and not self.failed:
            await self._publish_audio_codec(self.codec)

    async def _publish_audio_codec(self, codec) -> None:
        """Publish the AudioCodec instance, or None, to the subscribers (MusicPlayer among them)."""
        if not self._ctx or not self._ctx.event_bus:
            logger.warning(
                "cannot publish AUDIO_CODEC_CHANGED: the PluginContext / EventBus is not ready"
            )
            return
        from src.core.event_bus import Events

        try:
            await self._ctx.event_bus.emit(Events.AUDIO_CODEC_CHANGED, codec)
        except Exception as e:
            logger.warning(f"failed to publish AUDIO_CODEC_CHANGED: {e}", exc_info=True)

    async def _on_config_changed(self, data=None):
        """Reload the audio devices when the configuration changes (re-enumerating PortAudio too)."""
        if self.codec:
            logger.info(
                "AudioPlugin: configuration changed, reloading the audio devices"
            )
            await self.codec.reload_devices(reenumerate=True)

    async def _on_devices_refresh_request(self, data=None):
        """The settings page asked for a device refresh: stop the streams, re-enumerate, then reopen them.

        The payload may be an asyncio.Future, whose set_result gets the list_audio_devices result.
        """
        from src.utils.audio_utils import list_audio_devices, refresh_portaudio_devices

        future = data if isinstance(data, asyncio.Future) else None
        result = {"input": [], "output": []}
        try:
            if self.codec:
                # PortAudio can only be _terminate'd safely once the streams have stopped
                self.codec.stop_streams_for_enumeration()
                refresh_portaudio_devices(reinitialize=True)
                result = list_audio_devices(include_virtual=True)
                # reopen the streams from the current config (a name match may now point at a new index)
                ok = await self.codec.reload_devices(reenumerate=False)
                if not ok:
                    logger.error(
                        "AudioPlugin: failed to reopen the audio streams after the device refresh"
                    )
            else:
                # with no codec (audio disabled) still try to enumerate, so the settings page has something to show
                refresh_portaudio_devices(reinitialize=True)
                result = list_audio_devices(include_virtual=True)
            logger.info(
                "AudioPlugin: device refresh complete "
                f"in={len(result.get('input', []))} out={len(result.get('output', []))}"
            )
        except Exception as e:
            logger.error(f"AudioPlugin: device refresh failed: {e}", exc_info=True)
        finally:
            if future is not None and not future.done():
                future.set_result(result)

    async def on_device_state_changed(self, state):
        """
        Handle a change of device state.
        """
        if not self.codec:
            return

        from src.constants.constants import DeviceState

        if state == DeviceState.LISTENING:
            self._in_silence_period = True
            try:
                await asyncio.sleep(0.2)
            finally:
                self._in_silence_period = False

    async def on_incoming_json(self, message) -> None:
        """
        Handle a TTS event.
        """
        if not isinstance(message, dict):
            return

        try:
            if message.get("type") == "tts":
                state = message.get("state")
                if state == "start":
                    if self._music_parallel_enabled():
                        logger.debug(
                            "TTS started (parallel mode): the music keeps playing and ducks in the mix"
                        )
                    else:
                        await self._pause_music_for_tts()
                elif state == "stop":
                    # parallel mode sends the resume too, covering a track that started during TTS and was marked tts-paused
                    await self._resume_music_after_tts()
        except Exception as e:
            logger.error(f"failed to handle the TTS event: {e}", exc_info=True)

    def _music_parallel_enabled(self) -> bool:
        """Decide whether to play in parallel: with the AEC engine present and the config allowing it, TTS does not pause the music.

        When the engine is bypassed (a missing library, or it disabled itself after repeated failures) this falls back to pausing,
        so recognition is not polluted by bare parallel playback with no echo cancellation.
        """
        try:
            config = self._ctx.get_config()
            if not bool(config.get_config("AEC_OPTIONS.MUSIC_PARALLEL", True)):
                return False
            return bool(self.codec and self.codec.aec_active)
        except Exception:
            return False

    async def on_incoming_audio(self, data: bytes) -> None:
        """
        Receive audio data and play it.
        """
        if self.codec:
            try:
                await self.codec.write_audio(data)
            except Exception as e:
                logger.debug(f"failed to write the audio data: {e}")

    async def _pause_music_for_tts(self):
        """Pause the music when TTS starts (the two have separate queues and are mixed, so neither drops frames; what is left of the music fades out naturally)."""
        try:
            from src.core.event_bus import Events
            from src.mcp.tools.music.events import MusicControlRequest

            logger.info("TTS started, sending a music pause request")
            await self._ctx.event_bus.emit(
                Events.MUSIC_PAUSE_REQUEST, MusicControlRequest(source="tts")
            )
        except Exception as e:
            logger.warning(
                f"failed to send the music pause request: {e}", exc_info=True
            )

    async def _resume_music_after_tts(self):
        """Resume the music once TTS ends (in parallel mode this is only a backstop - usually nothing was paused)."""
        try:
            from src.core.event_bus import Events
            from src.mcp.tools.music.events import MusicControlRequest

            log = logger.debug if self._music_parallel_enabled() else logger.info
            log("TTS finished, sending a music resume request")
            await self._ctx.event_bus.emit(
                Events.MUSIC_RESUME_REQUEST, MusicControlRequest(source="tts")
            )
        except Exception as e:
            logger.error(f"failed to send the music resume request: {e}", exc_info=True)

    def register_resources(self, pool) -> None:
        codec = self.codec
        if codec:

            async def _cleanup():
                """Full audio codec teardown: tell the subscribers to drop the codec, then close it."""
                import gc

                try:
                    # Music stops itself on receiving None; the full detach is the container's job
                    await self._publish_audio_codec(None)
                except Exception as e:
                    logger.debug(
                        f"failed to publish the codec clear: {e}", exc_info=True
                    )
                gc.collect()
                await codec.close()

            pool.register("audio.codec", _cleanup)

    def _on_encoded_audio(self, encoded_data: bytes) -> None:
        """
        The audio encode callback (called from the audio thread).
        """
        try:
            if not self._cmd:
                return
            self._cmd.schedule_command_nowait(self._send_audio_async, encoded_data)
        except Exception as e:
            logger.error(f"failed to schedule the audio send: {e}", exc_info=True)

    async def _send_audio_async(self, encoded_data: bytes) -> None:
        """
        Send the audio data asynchronously.
        """
        async with self._send_sem:
            try:
                if not self._ctx.is_audio_channel_opened():
                    return
                if self._should_send_microphone_audio():
                    await self._cmd.send_audio(encoded_data)
            except Exception as e:
                logger.error(f"failed to send the audio data: {e}", exc_info=True)

    def _should_send_microphone_audio(self) -> bool:
        """
        Decide whether the microphone audio should be sent.
        """
        try:
            if self._in_silence_period:
                return False
            return self._ctx.should_capture_audio()
        except Exception as e:
            logger.warning(
                f"could not decide whether to send the microphone audio, defaulting to not sending: {e}",
                exc_info=True,
            )
            return False
