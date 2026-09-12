"""Audio stream manager.

Creates the sounddevice streams and manages their lifecycle
"""

from collections.abc import Callable

import numpy as np
import sounddevice as sd

from src.logging import get_logger
from src.utils.audio_device import DeviceConfig
from src.utils.audio_utils import ALSAErrorSuppressor

logger = get_logger()


class AudioStreamManager:
    """Audio stream manager (a sounddevice wrapper)

    Creates the input and output streams and manages their lifecycle.
    """

    def __init__(self, device_config: DeviceConfig):
        """Initialise the stream manager

        Args:
            device_config: the device configuration
        """
        self.device_config = device_config
        self.input_stream = None
        self.output_stream = None
        self._stopped = False

    def create_streams(
        self, input_callback: Callable, output_callback: Callable
    ) -> None:
        """Create the duplex audio streams

        Args:
            input_callback: the input callback
            output_callback: the output callback

        Raises:
            Exception: the streams could not be created
        """
        # create() after stop() is allowed (the hot-reload path)
        self._stopped = False
        try:
            # ALSAErrorSuppressor silences the ALSA warnings on Linux
            with ALSAErrorSuppressor():
                # input stream
                self.input_stream = sd.InputStream(
                    device=self.device_config.input_device_id,
                    samplerate=self.device_config.input_sample_rate,
                    channels=self.device_config.input_channels,
                    dtype=np.float32,  # float32 throughout
                    blocksize=self.device_config.input_frame_size,
                    callback=input_callback,
                    latency="low",
                )

                # output stream
                self.output_stream = sd.OutputStream(
                    device=self.device_config.output_device_id,
                    samplerate=self.device_config.output_sample_rate,
                    channels=self.device_config.output_channels,
                    dtype=np.float32,  # float32 throughout
                    blocksize=self.device_config.output_frame_size,
                    callback=output_callback,
                    latency="low",
                )

            logger.info(
                f"audio streams created | "
                f"input: {self.device_config.input_sample_rate}Hz "
                f"{self.device_config.input_channels}ch | "
                f"output: {self.device_config.output_sample_rate}Hz "
                f"{self.device_config.output_channels}ch"
            )
        except Exception as e:
            logger.error(f"failed to create the audio streams: {e}", exc_info=True)
            raise

    def start(self) -> None:
        """Start the audio streams

        Raises:
            Exception: they could not be started
        """
        try:
            if self.input_stream:
                self.input_stream.start()
            if self.output_stream:
                self.output_stream.start()
            logger.info("audio streams started")
        except Exception as e:
            logger.error(f"failed to start the audio streams: {e}", exc_info=True)
            raise

    def stop(self) -> None:
        """Stop the audio streams; idempotent, so it is safe to call twice."""
        if getattr(self, "_stopped", False):
            return
        self._stopped = True

        try:
            if self.input_stream:
                self.input_stream.stop()
                self.input_stream.close()
                self.input_stream = None

            if self.output_stream:
                self.output_stream.stop()
                self.output_stream.close()
                self.output_stream = None

            logger.info("audio streams stopped")
        except Exception as e:
            logger.error(f"failed to stop the audio streams: {e}", exc_info=True)

    def is_active(self) -> bool:
        """Whether any input or output stream is still open."""
        return bool(self.input_stream or self.output_stream)

    def reinitialize_stream(
        self,
        is_input: bool,
        input_callback: Callable = None,
        output_callback: Callable = None,
    ) -> bool:
        """Rebuild an audio stream (this is what makes hot-plug work)

        Args:
            is_input: True for the input stream, False for the output stream
            input_callback: the input callback (only needed when rebuilding the input stream)
            output_callback: the output callback (only needed when rebuilding the output stream)

        Returns:
            bool: whether it worked
        """
        try:
            # ALSAErrorSuppressor silences the ALSA warnings on Linux
            with ALSAErrorSuppressor():
                if is_input and input_callback:
                    # rebuild the input stream
                    if self.input_stream:
                        self.input_stream.stop()
                        self.input_stream.close()

                    self.input_stream = sd.InputStream(
                        device=self.device_config.input_device_id,
                        samplerate=self.device_config.input_sample_rate,
                        channels=self.device_config.input_channels,
                        dtype=np.float32,
                        blocksize=self.device_config.input_frame_size,
                        callback=input_callback,
                        latency="low",
                    )
                    self.input_stream.start()
                    logger.info("input stream reinitialised")
                    return True

                elif not is_input and output_callback:
                    # rebuild the output stream
                    if self.output_stream:
                        self.output_stream.stop()
                        self.output_stream.close()

                    self.output_stream = sd.OutputStream(
                        device=self.device_config.output_device_id,
                        samplerate=self.device_config.output_sample_rate,
                        channels=self.device_config.output_channels,
                        dtype=np.float32,
                        blocksize=self.device_config.output_frame_size,
                        callback=output_callback,
                        latency="low",
                    )
                    self.output_stream.start()
                    logger.info("output stream reinitialised")
                    return True

            return False

        except Exception as e:
            stream_type = "input" if is_input else "output"
            logger.error(
                f"failed to rebuild the {stream_type} stream: {e}", exc_info=True
            )
            return False
