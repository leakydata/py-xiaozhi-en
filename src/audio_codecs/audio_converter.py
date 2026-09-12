from collections import deque

import numpy as np
import soxr

from src.logging import get_logger
from src.utils.audio_utils import downmix_to_mono, upmix_mono_to_channels

logger = get_logger()


class AudioConverter:
    """Audio format converter

    Handles sample-rate and channel conversion, buffering internally until it has a full target frame.
    """

    def __init__(self):
        """Initialise the converter"""
        self.input_resampler = None
        self.output_resampler = None
        self._input_buffer = deque()
        self._output_buffer = deque()
        self.needs_input_downmix = False
        self.needs_output_upmix = False
        self.input_channels = 1
        self.output_channels = 1

    def setup_input_converter(
        self, from_rate: int, to_rate: int, from_channels: int, to_channels: int = 1
    ):
        """Configure the input chain (device -> protocol)

        Args:
            from_rate: the device sample rate
            to_rate: the protocol sample rate (usually 16kHz)
            from_channels: the device channel count
            to_channels: the protocol channel count (usually 1)
        """
        self.input_channels = from_channels
        self.needs_input_downmix = from_channels > to_channels

        if self.needs_input_downmix:
            logger.info(f"input downmix: {from_channels}ch -> {to_channels}ch")

        if from_rate != to_rate:
            self.input_resampler = soxr.ResampleStream(
                from_rate,
                to_rate,
                num_channels=to_channels,  # the channel count after downmixing
                dtype="float32",
                quality="QQ",  # the fast setting, which suits realtime
            )
            logger.info(f"input resample: {from_rate}Hz -> {to_rate}Hz")

    def setup_output_converter(
        self, from_rate: int, to_rate: int, from_channels: int = 1, to_channels: int = 2
    ):
        """Configure the output chain (protocol -> device)

        Args:
            from_rate: the protocol sample rate (usually 24kHz)
            to_rate: the device sample rate
            from_channels: the protocol channel count (usually 1)
            to_channels: the device channel count
        """
        self.output_channels = to_channels
        self.needs_output_upmix = to_channels > from_channels

        if from_rate != to_rate:
            self.output_resampler = soxr.ResampleStream(
                from_rate,
                to_rate,
                num_channels=from_channels,  # the channel count before upmixing
                dtype="float32",
                quality="QQ",
            )
            logger.info(f"output resample: {from_rate}Hz -> {to_rate}Hz")

        if self.needs_output_upmix:
            logger.info(f"output upmix: {from_channels}ch -> {to_channels}ch")

    def convert_input(self, audio: np.ndarray, target_size: int) -> np.ndarray | None:
        """Input conversion: multi-channel at a high rate -> mono at 16kHz

        Args:
            audio: the float32 audio data
            target_size: the sample count wanted

        Returns:
            the converted float32 data, or None when there is not enough of it
        """
        # 1. downmix (via audio_utils)
        if self.needs_input_downmix:
            audio = downmix_to_mono(audio, keepdims=False)
        else:
            audio = audio.flatten()

        # 2. resample
        if self.input_resampler:
            resampled = self.input_resampler.resample_chunk(audio, last=False)
            if len(resampled) > 0:
                self._input_buffer.extend(resampled)

            # accumulate until there is a full target frame
            if len(self._input_buffer) < target_size:
                return None

            # take one frame
            frame_data = [self._input_buffer.popleft() for _ in range(target_size)]
            return np.array(frame_data, dtype=np.float32)

        return audio

    def convert_output(
        self, audio: np.ndarray, target_frames: int
    ) -> np.ndarray | None:
        """Output conversion: mono at 24kHz -> multi-channel at a higher rate

        Args:
            audio: the float32 audio data
            target_frames: the frame count wanted

        Returns:
            the converted float32 data
        """
        # 1. resample
        if self.output_resampler:
            resampled = self.output_resampler.resample_chunk(audio, last=False)
            if len(resampled) > 0:
                self._output_buffer.extend(resampled)

            # take the frames wanted
            if len(self._output_buffer) < target_frames:
                return None

            frame_data = [self._output_buffer.popleft() for _ in range(target_frames)]
            audio = np.array(frame_data, dtype=np.float32)

        # 2. upmix (via audio_utils)
        if self.needs_output_upmix:
            audio = upmix_mono_to_channels(audio, self.output_channels)
        else:
            audio = audio.reshape(-1, 1)

        return audio

    def drain_output_buffer(self, target_frames: int) -> np.ndarray | None:
        """Drain whatever is left in the resampler buffer, upmixing it.

        Used when the queue has run dry and the buffer is a few samples short, so a whole frame of silence is avoided.
        """
        available = min(len(self._output_buffer), target_frames)
        if available == 0:
            return None

        frame_data = [self._output_buffer.popleft() for _ in range(available)]
        audio = np.array(frame_data, dtype=np.float32)

        if self.needs_output_upmix:
            audio = upmix_mono_to_channels(audio, self.output_channels)
        else:
            audio = audio.reshape(-1, 1)

        return audio

    def clear_output_buffer(self):
        """Clear only the output buffer (used on a TTS stop to prevent echo; the input pipeline is untouched)"""
        self._output_buffer.clear()

    def clear_buffers(self):
        """Clear the buffers"""
        self._input_buffer.clear()
        self._output_buffer.clear()
        logger.debug("audio converter buffers cleared")

    def close(self):
        """Release the soxr resamplers, so the nanobind C++ objects do not leak."""
        self.clear_buffers()
        self.input_resampler = None
        self.output_resampler = None
