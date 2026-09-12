import asyncio
import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from src.audio_codecs import audio_levels
from src.audio_codecs.audio_buffer import PcmFifo
from src.audio_codecs.audio_converter import AudioConverter
from src.audio_codecs.opus_codec import OpusCodec, parse_opus_toc
from src.audio_codecs.stream_manager import AudioStreamManager
from src.constants.constants import AudioConfig
from src.logging import get_logger
from src.utils.audio_device import AudioDeviceManager, DeviceConfig
from src.utils.config_manager import get_config

logger = get_logger()

# TTS the mix gain applied to music while ducking, and how long it is held (in 20ms blocks)
_MUSIC_DUCK_GAIN = 0.35
_DUCK_HOLD_CHUNKS = 10
# target watermark for write-side backpressure on music, in seconds: smaller is more responsive to pause/barge-in, larger is more robust to jitter
_MUSIC_BACKLOG_TARGET_S = 0.30
# TTS / music FIFO capacity in seconds; the oldest data is dropped past this
_TTS_FIFO_MAX_S = 10.0
_MUSIC_FIFO_MAX_S = 2.0


class AudioListener(Protocol):
    """audio listener protocol"""

    def on_audio_data(self, audio_data: np.ndarray) -> None:
        """receive audio data

        Args:
            audio_data: float32 audio data
        """
        ...


class AudioCodec:
    """Audio codec - coordinator pattern

    Composes the individual components and coordinates the data flow

    data flow:
    - input: device (float32) -> downmix + resample (float32) -> Opus encode (float32 -> bytes) -> network
    - output: network -> Opus decode (bytes -> float32) -> resample + upmix (float32) -> device (float32)
    """

    def __init__(self):
        """initialise the audio codec"""
        # refresh the protocol config, so changes made in the Settings UI take effect
        AudioConfig.reload()

        # components (dependency injection)
        self.device_manager = AudioDeviceManager(get_config())
        self.opus_codec = OpusCodec(
            input_sample_rate=AudioConfig.INPUT_SAMPLE_RATE,
            output_sample_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
            channels=AudioConfig.CHANNELS,
        )
        self.converter = AudioConverter()
        self.stream_manager = None

        # TTS kept separate from music: each has its own FIFO and they are mixed in the output callback, so neither blocks the other
        self._tts_fifo = PcmFifo(int(AudioConfig.OUTPUT_SAMPLE_RATE * _TTS_FIFO_MAX_S))
        self._music_fifo = PcmFifo(
            int(AudioConfig.OUTPUT_SAMPLE_RATE * _MUSIC_FIFO_MAX_S)
        )
        self._mix_chunk = int(AudioConfig.OUTPUT_SAMPLE_RATE * 0.02)  # 20ms
        self._duck_hold = 0

        # listeners (thread-safe)
        self._encoded_callback: Callable | None = None
        self._audio_listeners: list[AudioListener] = []
        self._listeners_lock = threading.Lock()

        # device config (filled in after initialisation)
        self.device_config: DeviceConfig | None = None

        # AEC(Self far: using the final PCM from the playback callback as the reference), created from config during initialize
        self._aec = None

        # state flags
        self._is_closing = False
        self._closed = False
        self._server_opus_logged = False
        self._last_output_status_log = 0.0

    async def initialize(self):
        """initialise every component

        Flow:
        1. load or detect devices
        2. refresh the protocol config and initialise Opus
        3. configure the format conversion pipeline
        4. create the audio streams
        5. start the audio streams
        """
        try:
            # 1. load or detect devices
            self.device_config = self.device_manager.load_or_detect_devices()

            # 2. refresh the protocol config and initialise Opus
            AudioConfig.reload()
            self.opus_codec.close()
            self.opus_codec = OpusCodec(
                input_sample_rate=AudioConfig.INPUT_SAMPLE_RATE,
                output_sample_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
                channels=AudioConfig.CHANNELS,
            )
            self.opus_codec.initialize()

            # 3. configure the format conversion pipeline
            self._configure_pipeline()

            # 4. create the AEC from config (self far); bypass automatically on failure
            self._setup_aec()

            # 5. create the audio streams
            self.stream_manager = AudioStreamManager(self.device_config)
            self.stream_manager.create_streams(
                input_callback=self._input_callback,
                output_callback=self._output_callback,
            )

            # 6. start the audio streams
            self.stream_manager.start()

            logger.info("AudioCodec initialised")

        except Exception as e:
            logger.error(f"Failed to initialise the audio devices: {e}", exc_info=True)
            await self.close()
            raise

    def _input_callback(self, indata, frames, time_info, status):
        """input callback: device -> encode -> send

        data flow: multi-channel / high rate -> downmix -> resample -> Opus encode -> network

        Args:
            indata: float32 audio data, shape (frames, channels)
            frames: frame count
            time_info: timing information
            status: status flags
        """
        if status and "overflow" not in str(status).lower():
            logger.warning(f"input stream status: {status}")

        if self._is_closing:
            return

        try:
            # 1. format conversion (downmix + resample)
            # keep indata's (frames, channels) shape so downmix_to_mono mixes correctly
            audio_converted = self.converter.convert_input(
                indata, AudioConfig.INPUT_FRAME_SIZE
            )
            if audio_converted is None:
                return  # not enough data, wait for the next frame

            # 1.5 AEC: cancel echo using the far reference taken from the playback callback (returned unchanged when bypassed)
            if self._aec is not None and self._aec.active:
                audio_converted = self._aec.process_near(audio_converted)

            # 2. Opus encode (float32 input)
            if self._encoded_callback:
                try:
                    opus_data = self.opus_codec.encode(
                        audio_converted, AudioConfig.INPUT_FRAME_SIZE
                    )
                    self._encoded_callback(opus_data)
                except Exception as e:
                    logger.warning(f"Encoding failed: {e}", exc_info=True)

            # 2.5 UI levels (mouth shape / volume ring), non-blocking
            audio_levels.feed_input(audio_converted)

            # 3. notify listeners (thread-safe)
            with self._listeners_lock:
                for listener in self._audio_listeners:
                    try:
                        listener.on_audio_data(audio_converted.copy())
                    except Exception as e:
                        logger.warning(f"Listener failed: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"input callback error: {e}", exc_info=True)

    def _output_callback(self, outdata, frames, time_info, status):
        """output callback: decode -> convert -> play

        data flow: queue -> resample -> upmix -> device

        loop pulling chunks from the queue into convert_output, until the resampler's
        until the internal buffer has enough frames or the queue runs dry. This fixes the stutter when the sample rate does not divide evenly
        (e.g. 16kHz -> 44100Hz) or when the server frame length does not match.

        Args:
            outdata: float32 output buffer, shape (frames, channels)
            frames: frame count
            time_info: timing information
            status: status flags
        """
        if status:
            # rate-limited: logging from a callback is file I/O and makes underruns worse, so at most one line every 2 seconds
            now = time.monotonic()
            if now - self._last_output_status_log > 2.0:
                self._last_output_status_log = now
                logger.warning(f"output stream status: {status}")

        try:
            audio_converted = None

            while audio_converted is None:
                audio_data = self._pull_mixed(self._mix_chunk)
                if audio_data is None:
                    break
                audio_converted = self.converter.convert_output(audio_data, frames)

            if audio_converted is None:
                audio_converted = self.converter.drain_output_buffer(frames)

            if audio_converted is None or len(audio_converted) < frames:
                outdata.fill(0.0)
                if audio_converted is not None and len(audio_converted) > 0:
                    outdata[: len(audio_converted)] = audio_converted
            else:
                outdata[:] = audio_converted[:frames]

            # AEC far: the final PCM actually written to the device (TTS + music mixed, with silence keeping it continuous)
            if self._aec is not None and self._aec.active:
                self._aec.feed_far(outdata)

            # UI levels: take the PCM actually written to the device, so the mouth shape matches what is heard
            audio_levels.feed_output(outdata)

        except Exception as e:
            logger.error(f"output callback error: {e}", exc_info=True)
            outdata.fill(0.0)

    def _configure_pipeline(self):
        """Configure the format conversion pipeline (device <-> protocol).

        Build the input and output conversion chains from the device's native parameters and what the protocol requires.
        input: device (f32, device_rate, device_ch) -> protocol (f32, 16kHz, 1ch)
        output: protocol (f32, opus_out_rate, 1ch) -> device (f32, device_rate, device_ch)
        """
        self.converter.setup_input_converter(
            from_rate=self.device_config.input_sample_rate,
            to_rate=AudioConfig.INPUT_SAMPLE_RATE,
            from_channels=self.device_config.input_channels,
            to_channels=1,
        )
        self.converter.setup_output_converter(
            from_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
            to_rate=self.device_config.output_sample_rate,
            from_channels=1,
            to_channels=self.device_config.output_channels,
        )

        # the protocol output rate can change on a config hot-reload, so the FIFO and mix blocks are rebuilt with it
        # (the streams are stopped here, so there is no concurrent reader)
        self._tts_fifo = PcmFifo(int(AudioConfig.OUTPUT_SAMPLE_RATE * _TTS_FIFO_MAX_S))
        self._music_fifo = PcmFifo(
            int(AudioConfig.OUTPUT_SAMPLE_RATE * _MUSIC_FIFO_MAX_S)
        )
        self._mix_chunk = int(AudioConfig.OUTPUT_SAMPLE_RATE * 0.02)
        self._duck_hold = 0

    def _pull_mixed(self, n: int) -> np.ndarray | None:
        """Output callback thread: take n samples from each of the TTS and music FIFOs and mix them.

        Rules:
        - both empty -> None (the caller takes the silence/underrun path)
        - TTS when present, music ducks by _MUSIC_DUCK_GAIN, and during TTS
          held for several blocks across the frame gap, so the duck gain does not chatter
        """
        tts = self._tts_fifo.pull(n)
        music = self._music_fifo.pull(n)

        if tts is None and music is None:
            return None

        if tts is not None:
            self._duck_hold = _DUCK_HOLD_CHUNKS
        elif self._duck_hold > 0:
            self._duck_hold -= 1

        if music is None:
            return tts
        if tts is None:
            if self._duck_hold > 0:
                music *= _MUSIC_DUCK_GAIN
            return music
        return np.clip(tts + music * _MUSIC_DUCK_GAIN, -1.0, 1.0)

    def _setup_aec(self):
        """Create or rebuild the AEC engine per AEC_OPTIONS.ENABLED (self far reference).

        the far sample rate can change after a device hot reload, so it must be rebuilt with device_config;
        A failure here does not raise; the engine bypasses itself (active=False).
        """
        if self._aec is not None:
            self._aec.close()
            self._aec = None

        try:
            config = get_config()
            if not bool(config.get_config("AEC_OPTIONS.ENABLED", False)):
                logger.info("AEC not enabled (AEC_OPTIONS.ENABLED=false)")
                return

            from src.audio_processing.aec_engine import AecEngine

            frame_delay = config.get_config("AEC_OPTIONS.FRAME_DELAY", 3)
            self._aec = AecEngine(
                near_rate=AudioConfig.INPUT_SAMPLE_RATE,
                far_rate=self.device_config.output_sample_rate,
                # FRAME_DELAY measured in protocol frames, converted to milliseconds and added to the base output latency
                delay_ms=40 + int(frame_delay) * AudioConfig.FRAME_DURATION,
                enable_preprocess=bool(
                    config.get_config("AEC_OPTIONS.ENABLE_PREPROCESS", True)
                ),
            )
        except Exception as e:
            logger.warning(
                f"Failed to create the AEC engine, bypassed: {e}", exc_info=True
            )
            self._aec = None

    # === public interface (kept for compatibility) ===

    @property
    def aec_active(self) -> bool:
        """AEC Whether the engine is present and running (the parallel-music strategy depends on this)."""
        aec = self._aec
        return bool(aec is not None and aec.active)

    def set_encoded_callback(self, callback: Callable[[bytes], None]):
        """set the encode callback

        Args:
            callback: callback receiving Opus-encoded data
        """
        self._encoded_callback = callback
        if callback:
            logger.info("encoded-audio callback set")
        else:
            logger.info("encoded-audio callback cleared")

    def add_audio_listener(self, listener: AudioListener):
        """add an audio listener (thread-safe)

        Args:
            listener: a listener implementing the AudioListener protocol
        """
        with self._listeners_lock:
            if listener not in self._audio_listeners:
                self._audio_listeners.append(listener)
                logger.info(f"Audio listener added: {listener.__class__.__name__}")

    def remove_audio_listener(self, listener: AudioListener):
        """Remove an audio listener (thread-safe)

        Args:
            listener: the listener object to remove
        """
        with self._listeners_lock:
            if listener in self._audio_listeners:
                self._audio_listeners.remove(listener)
                logger.info(f"Audio listener removed: {listener.__class__.__name__}")

    async def write_audio(self, opus_data: bytes):
        """decode and play audio (Opus -> speaker)

        The frame length is detected from the Opus TOC byte, so no client-side config is needed.

        Args:
            opus_data: Opus-encoded data
        """
        try:
            toc_info = parse_opus_toc(opus_data)
            if toc_info is None:
                return

            if not self._server_opus_logged:
                self._server_opus_logged = True
                logger.info(
                    f"server Opus parameters: "
                    f"{toc_info['mode']} {toc_info['bandwidth_hz']} | "
                    f"frame length {toc_info['duration_ms']}ms "
                    f"({toc_info['frame_ms']}ms×{toc_info['num_frames']})"
                )

            frame_size = int(
                AudioConfig.OUTPUT_SAMPLE_RATE * toc_info["duration_ms"] / 1000
            )
            audio_float32 = self.opus_codec.decode(opus_data, frame_size)

            self._tts_fifo.push(audio_float32)

        except Exception as e:
            logger.warning(f"Audio write failed: {e}", exc_info=True)

    async def write_pcm_direct(self, pcm_float32: np.ndarray):
        """Write music PCM (float32, used by MusicPlayer) with watermark backpressure.

        after writing, wait for playback to drain if the music buffer is above the target watermark - this is the music path
        the only timing source (the decoder clock drifts after a pause and cannot be relied on).
        Backpressure gives up after 2 seconds as a backstop, and the FIFO drops the oldest data so it cannot grow without bound.
        """
        self._music_fifo.push(pcm_float32)

        target = int(AudioConfig.OUTPUT_SAMPLE_RATE * _MUSIC_BACKLOG_TARGET_S)
        for _ in range(100):
            if self._is_closing or self._music_fifo.size <= target:
                break
            await asyncio.sleep(0.02)

    async def clear_audio_queue(self):
        """Clear the TTS playback queue (used on interrupt/abort; the music queue is untouched)."""
        self._server_opus_logged = False
        self.converter.clear_output_buffer()
        count = self._tts_fifo.clear()
        if count > 0:
            logger.info(f"cleared the TTS queue, discarding {count} samples")

    async def clear_music_queue(self):
        """Clear the music playback queue (used on stop/seek; the TTS queue is untouched)."""
        count = self._music_fifo.clear()
        if count > 0:
            logger.info(f"cleared the music queue, discarding {count} samples")

    async def reinitialize_stream(self, is_input: bool = True):
        """rebuild the audio streams (supports hot-plug)

        Args:
            is_input: True=input stream, False = output stream

        Returns:
            bool: whether it succeeded
        """
        if not self.stream_manager:
            return False

        if is_input:
            return self.stream_manager.reinitialize_stream(
                is_input=True, input_callback=self._input_callback
            )
        else:
            return self.stream_manager.reinitialize_stream(
                is_input=False, output_callback=self._output_callback
            )

    def stop_streams_for_enumeration(self) -> None:
        """Stop the sounddevice streams this codec holds, before re-enumerating for hot-plug.

        After calling this you must either ``reload_devices()`` or ``create_streams`` yourself, or there is no capture or playback.
        """
        if self.stream_manager:
            self.stream_manager.stop()
            logger.info("AudioCodec: audio streams stopped (for device enumeration)")

    async def reload_devices(self, *, reenumerate: bool = True):
        """Hot-reload the audio device configuration

        Flow:
        1. stop the current audio streams
        2. (optionally reinitialise PortAudio and re-enumerate, which helps a Bluetooth device connected later show up
        3. reload the device config and the protocol config
        4. rebuild the format converters and the Opus codec
        5. recreate and start the audio streams

        Args:
            reenumerate: whether to force a PortAudio device-table refresh after stopping the streams

        Returns:
            bool: whether it succeeded
        """
        logger.info("AudioCodec: starting audio device hot reload...")

        try:
            # 1. stop the current streams (required before a PortAudio reinit)
            if self.stream_manager:
                self.stream_manager.stop()
                logger.debug("AudioCodec: current audio streams stopped")

            # 2. hot-plug: rebuild the PortAudio context, then match by name
            if reenumerate:
                from src.utils.audio_utils import refresh_portaudio_devices

                refresh_portaudio_devices(reinitialize=True)

            # 3. reload the device config
            self.device_manager.config.reload_config()
            self.device_config = self.device_manager.load_or_detect_devices()
            logger.info(
                "AudioCodec: new device config - input ID: "
                f"{self.device_config.input_device_id}, output ID: "
                f"{self.device_config.output_device_id}"
            )

            # 4. refresh the protocol config and rebuild the Opus codec
            AudioConfig.reload()
            self.opus_codec.close()
            self.opus_codec = OpusCodec(
                input_sample_rate=AudioConfig.INPUT_SAMPLE_RATE,
                output_sample_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
                channels=AudioConfig.CHANNELS,
            )
            self.opus_codec.initialize()

            # 5. rebuild the format converters
            self.converter.clear_buffers()
            self._configure_pipeline()

            # 5.5 rebuild the AEC (far rate follows the new output device, filter state cleared)
            self._setup_aec()

            # 6. recreate the audio streams
            self.stream_manager = AudioStreamManager(self.device_config)
            self.stream_manager.create_streams(
                input_callback=self._input_callback,
                output_callback=self._output_callback,
            )

            # 7. start the audio streams
            self.stream_manager.start()

            logger.info("AudioCodec: audio device hot reload complete")
            return True

        except Exception as e:
            logger.error(
                f"AudioCodec: audio device hot reload failed: {e}", exc_info=True
            )
            return False

    async def close(self):
        """close the audio codec"""
        self._is_closing = True

        try:
            # 1. stop the audio streams
            if self.stream_manager:
                self.stream_manager.stop()

            # 2. clear the queues
            await self.clear_audio_queue()
            await self.clear_music_queue()

            # 2.5 release the AEC (must happen after the streams stop)
            if self._aec is not None:
                self._aec.close()
                self._aec = None

            # 3. release the converters (including the soxr resampler)
            self.converter.close()

            # 4. release Opus
            self.opus_codec.close()

            # 5. clear listeners
            with self._listeners_lock:
                self._audio_listeners.clear()

            logger.info("AudioCodec closed")
            self._closed = True

        except Exception as e:
            logger.error(f"Failed to close the audio codec: {e}", exc_info=True)
        finally:
            self._is_closing = False

    def __del__(self):
        """destructor - synchronous cleanup"""
        # skip if already closed or closing
        if getattr(self, "_closed", False) or getattr(self, "_is_closing", False):
            return

        logger.warning(
            "AudioCodec was not closed properly; running emergency cleanup (prefer async close())"
        )

        try:
            # 1. stop the audio streams (synchronous)
            if self.stream_manager:
                self.stream_manager.stop()

            # 2. clear the queues (synchronous version)
            count = self._tts_fifo.clear() + self._music_fifo.clear()
            if count > 0:
                logger.debug(f"destructor discarded {count} audio samples")

            # 3. release the converters (synchronous, including the soxr resampler)
            if self.converter:
                self.converter.close()

            # 4. release Opus (synchronous)
            if self.opus_codec:
                self.opus_codec.close()

            # 5. clear listeners (synchronous)
            try:
                with self._listeners_lock:
                    self._audio_listeners.clear()
            except Exception as e:
                logger.warning(
                    f"Failed to clear audio listeners (the lock may be broken): {e}",
                    exc_info=True,
                )

            logger.debug("AudioCodec destructor cleanup complete")

        except Exception as e:
            logger.error(f"destructor cleanup failed: {e}", exc_info=True)
