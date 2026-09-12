"""AEC engine: a realtime wrapper around libs/webrtc_apm (P0, self far reference).

Data flow:
- near: the capture frame (16kHz mono float32) -> ProcessStream -> sent upstream with the echo removed
- far: the final PCM actually written to the device (TTS + music mixed, at the device's rate and channel count)
       -> downmix -> resample to 16kHz -> ProcessReverseStream

Threading (this matters):
- the output callback thread only downmixes and copies into a queue (feed_far - microseconds, lock-free);
  the resampling and every APM call happen on the capture thread (process_near drains the far queue first).
  The two realtime callbacks share no lock, so the output callback cannot be dragged down when the input side holds one and the GIL stalls.

Constraints:
- any load or processing failure bypasses the engine (active=False) rather than breaking the call path
- the WebRTC APM works in 10ms frames; the protocol's 20/40/60ms frames are all whole multiples of that
"""

import ctypes
import sys
import threading
from collections import deque

import numpy as np

from src.logging import get_logger

logger = get_logger()

# after this many consecutive failures the engine bypasses itself, so a broken library cannot drag the audio callbacks down
_MAX_CONSECUTIVE_FAILURES = 5
# the cap on the pending far queue (in output-callback blocks, roughly 20ms each -> 0.5s);
# it stops a backlog building if the capture thread stalls, dropping the oldest past the limit
_FAR_PENDING_MAX_BLOCKS = 25


def _import_webrtc_apm():
    """Import libs.webrtc_apm, with a path fallback for both source and packaged layouts."""
    try:
        from libs import webrtc_apm

        return webrtc_apm
    except ImportError:
        from src.utils.resource_finder import get_app_root

        root = str(get_app_root())
        if root not in sys.path:
            sys.path.insert(0, root)
        from libs import webrtc_apm

        return webrtc_apm


class AecEngine:
    """A WebRTC APM wrapper: AEC plus optional noise suppression and a high-pass filter, over the near and far streams."""

    def __init__(
        self,
        near_rate: int = 16000,
        far_rate: int = 48000,
        delay_ms: int = 60,
        enable_preprocess: bool = True,
    ):
        """Initialise and load the APM; on failure active stays False and the engine is bypassed.

        Args:
            near_rate: the capture/protocol sample rate (16kHz)
            far_rate: the device output rate (what the far side resamples from)
            delay_ms: the estimated playback-to-capture delay
            enable_preprocess: whether to also enable the high-pass filter and noise suppression
        """
        self._near_rate = int(near_rate)
        self._far_rate = int(far_rate)
        self._delay_ms = int(delay_ms)
        self._frame = self._near_rate // 100  # 10ms
        self._lock = threading.Lock()
        self._active = False
        self._closed = False
        self._fail_count = 0
        self._near_misaligned_logged = False

        self._apm = None
        self._stream_cfg = None
        # two-stage far buffering: the output callback writes into pending (a copy, nothing more),
        # and buffer holds the 16k samples left over after the capture thread resamples
        self._far_pending: deque = deque()
        self._far_buffer = np.empty(0, dtype=np.float32)
        self._far_resampler = None
        self._far_dropped = 0

        # a reused ctypes frame buffer (10ms of int16)
        self._near_in = (ctypes.c_short * self._frame)()
        self._near_out = (ctypes.c_short * self._frame)()
        self._far_in = (ctypes.c_short * self._frame)()
        self._far_out = (ctypes.c_short * self._frame)()

        try:
            self._init_apm(enable_preprocess)
            if self._far_rate != self._near_rate:
                import soxr

                self._far_resampler = soxr.ResampleStream(
                    self._far_rate,
                    self._near_rate,
                    num_channels=1,
                    dtype="float32",
                    quality="QQ",
                )
            self._active = True
            logger.info(
                f"AEC engine enabled | near {self._near_rate}Hz, "
                f"far {self._far_rate}Hz→{self._near_rate}Hz, "
                f"delay {self._delay_ms}ms, preprocess={enable_preprocess}"
            )
        except Exception as e:
            logger.warning(f"AEC engine initialisation failed, bypassed: {e}")
            self._release()

    def _init_apm(self, enable_preprocess: bool) -> None:
        """Load the shared library, apply the config and build the stream config."""
        apm_mod = _import_webrtc_apm()

        self._apm = apm_mod.WebRTCAudioProcessing()

        config = apm_mod.create_default_config()
        config.echo.enabled = True
        config.echo.mobile_mode = False
        if enable_preprocess:
            config.high_pass.enabled = True
            config.noise_suppress.enabled = True
            config.noise_suppress.noise_level = apm_mod.NoiseSuppressionLevel.MODERATE

        ret = self._apm.apply_config(config)
        if ret != 0:
            raise RuntimeError(f"apply_config returned {ret}")

        # near and far are both 16kHz mono, so they share one stream config
        self._stream_cfg = self._apm.create_stream_config(self._near_rate, 1)
        self._apm.set_stream_delay_ms(self._delay_ms)

    @property
    def active(self) -> bool:
        return self._active

    def process_near(self, block: np.ndarray) -> np.ndarray:
        """Process a capture frame (16kHz mono float32) and return the same length with the echo removed.

        Any failure returns the original data; enough consecutive failures bypass the engine.
        """
        if not self._active:
            return block

        n = block.shape[0]
        if n % self._frame != 0:
            if not self._near_misaligned_logged:
                self._near_misaligned_logged = True
                logger.warning(
                    f"capture frame length {n} is not a whole number of 10ms frames, AEC bypasses this path"
                )
            return block

        try:
            i16 = self._float_to_i16(block)
            out = np.empty(n, dtype=np.float32)

            with self._lock:
                if not self._active:
                    return block
                # far before near: drain the reference data the output callback has queued, keeping cause before effect
                self._drain_far_locked()
                self._apm.set_stream_delay_ms(self._delay_ms)
                for off in range(0, n, self._frame):
                    ctypes.memmove(
                        self._near_in,
                        i16[off : off + self._frame].ctypes.data,
                        self._frame * 2,
                    )
                    ret = self._apm.process_stream(
                        self._near_in,
                        self._stream_cfg,
                        self._stream_cfg,
                        self._near_out,
                    )
                    if ret != 0:
                        raise RuntimeError(f"process_stream returned {ret}")
                    out[off : off + self._frame] = (
                        np.frombuffer(self._near_out, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )

            self._fail_count = 0
            return out
        except Exception as e:
            self._on_failure("near", e)
            return block

    def feed_far(self, outdata: np.ndarray) -> None:
        """Called on the output callback thread: downmix and copy into the queue, nothing more - no resampling, no APM, and it returns in microseconds.

        Silent frames must be fed too, to keep the far stream continuous; the heavy work happens in process_near on the capture thread.
        """
        if not self._active:
            return

        try:
            if outdata.ndim > 1 and outdata.shape[1] > 1:
                mono = outdata.mean(axis=1, dtype=np.float32)
            else:
                # PortAudio reuses the outdata memory, so this has to be a copy
                mono = np.array(outdata, dtype=np.float32).ravel()

            self._far_pending.append(mono)
            # deque operations are atomic under the GIL; past the limit the oldest is dropped, so a stalled capture thread cannot build a backlog
            while len(self._far_pending) > _FAR_PENDING_MAX_BLOCKS:
                self._far_pending.popleft()
                self._far_dropped += 1
        except Exception:
            pass  # the output path must never raise

    def _drain_far_locked(self) -> None:
        """Capture thread (lock already held): resample the far queue and feed it to ProcessReverseStream."""
        while self._far_pending:
            mono = self._far_pending.popleft()
            if self._far_resampler is not None:
                mono = self._far_resampler.resample_chunk(mono, last=False)
            if len(mono):
                self._far_buffer = np.concatenate((self._far_buffer, mono))

        n_frames = len(self._far_buffer) // self._frame
        if n_frames == 0:
            return

        usable = n_frames * self._frame
        i16 = self._float_to_i16(self._far_buffer[:usable])
        self._far_buffer = self._far_buffer[usable:]

        for off in range(0, usable, self._frame):
            ctypes.memmove(
                self._far_in, i16[off : off + self._frame].ctypes.data, self._frame * 2
            )
            ret = self._apm.process_reverse_stream(
                self._far_in, self._stream_cfg, self._stream_cfg, self._far_out
            )
            if ret != 0:
                raise RuntimeError(f"process_reverse_stream returned {ret}")

    def set_delay_ms(self, delay_ms: int) -> None:
        self._delay_ms = int(delay_ms)

    def close(self) -> None:
        """Release the APM resources; this must happen after the audio streams stop."""
        if self._closed:
            return
        self._closed = True
        with self._lock:
            self._active = False
            self._release()
        logger.info("AEC engine closed")

    def _release(self) -> None:
        self._active = False
        try:
            if self._apm is not None and self._stream_cfg is not None:
                self._apm.destroy_stream_config(self._stream_cfg)
        except Exception:
            pass
        self._stream_cfg = None
        self._apm = None
        self._far_resampler = None
        self._far_pending.clear()
        self._far_buffer = np.empty(0, dtype=np.float32)
        if self._far_dropped:
            logger.debug(f"AEC far has dropped {self._far_dropped} blocks in total")

    def _on_failure(self, side: str, err: Exception) -> None:
        self._fail_count += 1
        if self._fail_count >= _MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"AEC {side} failed {self._fail_count} times in a row, bypassing: {err}",
                exc_info=True,
            )
            with self._lock:
                self._release()
        else:
            logger.debug(f"AEC {side} processing failed ({self._fail_count}): {err}")

    @staticmethod
    def _float_to_i16(x: np.ndarray) -> np.ndarray:
        return np.clip(x * 32768.0, -32768.0, 32767.0).astype(np.int16)
