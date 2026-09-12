import asyncio
import os
import re
import sys
from typing import Any

import numpy as np
import sounddevice as sd

from src.logging import get_logger

logger = get_logger()


class ALSAErrorSuppressor:
    """
    Suppresses ALSA error output.

    On Linux the ALSA library writes a great deal of warning and error text to
    stderr, which clutters the terminal. This context manager silences it temporarily.

    Usage:
        with ALSAErrorSuppressor():
            # initialise PyAudio and so on
            audio = pyaudio.PyAudio()

    Notes:
        - only has an effect on Linux
        - a no-op on Windows and macOS
        - stderr is restored when the context exits
    """

    def __init__(self):
        self._old_stderr = None
        self._devnull = None
        self._is_linux = sys.platform.startswith("linux")

    def __enter__(self):
        if not self._is_linux:
            return self

        try:
            self._old_stderr = os.dup(2)
            self._devnull = os.open("/dev/null", os.O_WRONLY)
            os.dup2(self._devnull, 2)
        except OSError:
            # fail silently if the file descriptors cannot be manipulated
            self._old_stderr = None
            self._devnull = None

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._is_linux:
            return False

        if self._old_stderr is not None:
            try:
                os.dup2(self._old_stderr, 2)
                os.close(self._old_stderr)
            except OSError:
                pass

        if self._devnull is not None:
            try:
                os.close(self._devnull)
            except OSError:
                pass

        return False  # do not swallow exceptions


def suppress_alsa_errors():
    """Return the ALSA error suppression context manager."""
    return ALSAErrorSuppressor()


# optional: skip the common virtual/aggregate devices (not chosen by default)
_VIRTUAL_PATTERNS = [
    r"blackhole",
    r"aggregate",
    r"multi[-\s]?output",  # macOS
    r"monitor",
    r"echo[-\s]?cancel",  # Linux Pulse/PipeWire
    r"vb[-\s]?cable",
    r"voicemeeter",
    r"cable (input|output)",  # Windows
    r"loopback",
]


def _is_virtual(name: str) -> bool:
    n = name.casefold()
    return any(re.search(pat, n) for pat in _VIRTUAL_PATTERNS)


def downmix_to_mono(
    pcm: np.ndarray | bytes,
    *,
    keepdims: bool = True,
    dtype: np.dtype | str = np.int16,
    in_channels: int | None = None,
) -> np.ndarray | bytes:
    """Downmix audio in any supported format to mono.

    Two input forms are accepted:
    1. np.ndarray: a PCM array of shape (N,) or (N, C)
    2. bytes: a PCM byte stream (dtype and in_channels must be given)

    Args:
        pcm: the input audio (ndarray or bytes)
        keepdims: True returns (N,1), False returns (N,) (ndarray input only)
        dtype: the PCM data type (used for bytes input only)
        in_channels: the number of input channels (required for bytes input)

    Returns:
        mono audio data (the same type as the input)

    Examples:
        >>> # ndarray input
        >>> stereo = np.random.randint(-32768, 32767, (1000, 2), dtype=np.int16)
        >>> mono = downmix_to_mono(stereo, keepdims=False)  # shape: (1000,)

        >>> # bytes input
        >>> stereo_bytes = b'...'  # stereo PCM data
        >>> mono_bytes = downmix_to_mono(stereo_bytes, dtype=np.int16, in_channels=2)
    """
    # bytes input: convert -> process -> convert back to bytes
    if isinstance(pcm, bytes):
        if in_channels is None:
            raise ValueError("in_channels must be given for bytes input")
        arr = np.frombuffer(pcm, dtype=dtype).reshape(-1, in_channels)
        mono_arr = downmix_to_mono(
            arr, keepdims=False
        )  # keepdims is irrelevant for bytes output
        return mono_arr.tobytes()

    # ndarray input: processed directly
    x = np.asarray(pcm)
    if x.ndim == 1:
        return x[:, None] if keepdims else x

    # already mono
    if x.shape[1] == 1:
        return x if keepdims else x[:, 0]

    # multi-channel downmix
    if np.issubdtype(x.dtype, np.integer):
        # average in floating point, then round back to the original integer type, to avoid overflow
        y = np.rint(x.astype(np.float32).mean(axis=1))
        info = np.iinfo(x.dtype)
        y = np.clip(y, info.min, info.max).astype(x.dtype)
    else:
        # float: keep the original dtype (float32, say) rather than defaulting to float64
        y = x.mean(axis=1, dtype=x.dtype)

    return y[:, None] if keepdims else y


def safe_queue_put(
    queue: asyncio.Queue, item: Any, replace_oldest: bool = True
) -> bool:
    """Put an item on a queue safely, optionally dropping the oldest item when full.

    Args:
        queue: the asyncio.Queue
        item: the item to enqueue
        replace_oldest: True drops the oldest item to make room, False drops the new one

    Returns:
        True if it was enqueued, False if the queue was full and it was not
    """
    try:
        queue.put_nowait(item)
        return True
    except asyncio.QueueFull:
        if replace_oldest:
            try:
                queue.get_nowait()  # drop the oldest
                queue.put_nowait(item)  # enqueue the new item
                return True
            except asyncio.QueueEmpty:
                # should not happen, but guard anyway
                queue.put_nowait(item)
                return True
        return False


def upmix_mono_to_channels(mono_data: np.ndarray, num_channels: int) -> np.ndarray:
    """Upmix mono audio to multiple channels (copied to every channel)

    Args:
        mono_data: mono audio data of shape (N,)
        num_channels: the target channel count

    Returns:
        multi-channel audio data of shape (N, num_channels)
    """
    if num_channels == 1:
        return mono_data.reshape(-1, 1)

    # copy the mono signal into every channel
    return np.tile(mono_data.reshape(-1, 1), (1, num_channels))


def _valid(devs: list[dict], idx: int, kind: str, include_virtual: bool) -> bool:
    if not isinstance(idx, int) or idx < 0 or idx >= len(devs):
        return False
    d = devs[idx]
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    if int(d.get(key, 0)) <= 0:
        return False
    if not include_virtual and _is_virtual(d.get("name", "")):
        return False
    return True


def refresh_portaudio_devices(*, reinitialize: bool = True) -> list[dict]:
    """Re-enumerate the PortAudio device list (hot-plug friendly).

    The caller must stop every sounddevice stream in this process first;
    ``sd._terminate`` is not safe while a stream is active.

    Args:
        reinitialize: when True, try ``_terminate`` + ``_initialize`` to force a rebuild of
            the PortAudio context (this helps a Bluetooth device connected later show up on macOS).
            On failure it falls back to a plain ``query_devices``.

    Returns:
        a list of device dicts (the same shape as ``list(sd.query_devices())``)
    """
    if reinitialize:
        terminate = getattr(sd, "_terminate", None)
        initialize = getattr(sd, "_initialize", None)
        if callable(terminate) and callable(initialize):
            try:
                terminate()
                initialize()
                logger.info(
                    "PortAudio reinitialised, about to re-enumerate the devices"
                )
            except Exception as e:
                logger.warning(
                    f"PortAudio reinitialisation failed, falling back to a plain enumeration: {e}",
                    exc_info=True,
                )
        else:
            logger.debug(
                "this sounddevice build has no _terminate/_initialize, skipping the reinitialisation"
            )

    try:
        devices = list(sd.query_devices())
    except Exception as e:
        logger.error(f"query_devices failed: {e}", exc_info=True)
        return []

    logger.info(f"audio device enumeration complete: {len(devices)} found")
    return devices


def list_audio_devices(
    *, include_virtual: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """List the input and output devices (for the settings page and debugging).

    PortAudio is not reinitialised here; for a hot-plug refresh call
    ``refresh_portaudio_devices()`` first, then this function.

    Returns:
        ``{"input": [...], "output": [...]}``, each entry holding index/name/sample_rate/channels
    """
    try:
        devices = list(sd.query_devices())
    except Exception as e:
        logger.error(f"Failed to list the audio devices: {e}", exc_info=True)
        return {"input": [], "output": []}

    default_input = None
    default_output = None
    try:
        if sd.default.device is not None:
            default_input = sd.default.device[0]
            default_output = sd.default.device[1]
    except Exception:
        pass

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []

    for i, d in enumerate(devices):
        name = d.get("name", "Unknown")
        if not include_virtual and _is_virtual(name):
            continue
        sr = d.get("default_samplerate", 48000)
        sample_rate = int(sr) if isinstance(sr, (int, float)) else 48000
        idx = int(d.get("index", i))

        in_ch = int(d.get("max_input_channels", 0) or 0)
        out_ch = int(d.get("max_output_channels", 0) or 0)

        if in_ch > 0:
            mark = " (default)" if idx == default_input else ""
            inputs.append(
                {
                    "index": idx,
                    "name": name + mark,
                    "raw_name": name,
                    "sample_rate": sample_rate,
                    "channels": in_ch,
                }
            )
        if out_ch > 0:
            mark = " (default)" if idx == default_output else ""
            outputs.append(
                {
                    "index": idx,
                    "name": name + mark,
                    "raw_name": name,
                    "sample_rate": sample_rate,
                    "channels": out_ch,
                }
            )

    return {"input": inputs, "output": outputs}


def find_device_by_name(
    kind: str, device_name: str, *, include_virtual: bool = False
) -> dict[str, Any] | None:
    """Find a device by name (fuzzy match)

    Args:
        kind: "input" or "output"
        device_name: the device name (partial matches allowed)
        include_virtual: whether to include virtual devices

    Returns:
        the device dict, or None
    """
    assert kind in ("input", "output")

    try:
        devices = list(sd.query_devices())
    except Exception:
        return None

    key_channels = "max_input_channels" if kind == "input" else "max_output_channels"
    search_name = device_name.casefold().strip()

    # 1. exact match (case-insensitive)
    for i, d in enumerate(devices):
        if not _valid(devices, i, kind, include_virtual):
            continue
        if d.get("name", "").casefold().strip() == search_name:
            sr = d.get("default_samplerate", None)
            return {
                "index": int(d.get("index", i)),
                "name": d.get("name", "Unknown"),
                "sample_rate": int(sr) if isinstance(sr, (int, float)) else None,
                "channels": int(d.get(key_channels, 0)),
            }

    # 2. fuzzy match (substring)
    for i, d in enumerate(devices):
        if not _valid(devices, i, kind, include_virtual):
            continue
        device_full_name = d.get("name", "").casefold()
        if search_name in device_full_name or device_full_name in search_name:
            sr = d.get("default_samplerate", None)
            return {
                "index": int(d.get("index", i)),
                "name": d.get("name", "Unknown"),
                "sample_rate": int(sr) if isinstance(sr, (int, float)) else None,
                "channels": int(d.get(key_channels, 0)),
            }

    return None


def select_audio_device(
    kind: str, *, include_virtual: bool = False
) -> dict[str, Any] | None:
    """Pick an audio device automatically (simplified)

    Strategy:
    1. the system default device (as recommended by sounddevice)
    2. the first usable non-virtual device

    Args:
        kind: "input" or "output"
        include_virtual: whether to include virtual devices

    Returns:
        {index, name, sample_rate, channels}, or None
    """
    assert kind in ("input", "output")

    try:
        devices = list(sd.query_devices())
    except Exception:
        return None

    key_channels = "max_input_channels" if kind == "input" else "max_output_channels"

    def pack(idx: int, base: dict | None = None) -> dict[str, Any] | None:
        if base is None:
            if not _valid(devices, idx, kind, include_virtual):
                return None
            d = devices[idx]
        else:
            d = base
            if not include_virtual and _is_virtual(d.get("name", "")):
                return None
        sr = d.get("default_samplerate", None)
        return {
            "index": int(d.get("index", idx)),
            "name": d.get("name", "Unknown"),
            "sample_rate": int(sr) if isinstance(sr, (int, float)) else None,
            "channels": int(d.get(key_channels, 0)),
        }

    # 1. the sounddevice system default (most reliable)
    try:
        info = sd.query_devices(kind=kind)
        packed = pack(int(info.get("index")), base=info)
        if packed:
            return packed
    except Exception:
        logger.debug(f"Failed to query the system default {kind} device, falling back")

    # 2. fallback: the first usable non-virtual device
    for i, _d in enumerate(devices):
        if _valid(devices, i, kind, include_virtual):
            return pack(i)

    return None
