"""Speaking the activation code aloud.

Pre-recorded WAV clips read the activation code out; only used during device activation.
It does not need FFmpeg, so it works on a clean machine with none installed.
"""

import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from src.logging import get_logger
from src.utils.resource_finder import get_app_root

logger = get_logger()

# where the audio lives
_ASSETS_DIR = get_app_root() / "assets" / "sounds"
# the assets' sample rate (matching the WAVs shipped in assets/sounds)
_DEFAULT_SAMPLE_RATE = 24000


class ActivationAnnouncer:
    """Reads the activation code aloud."""

    def __init__(self, locale: str = "en-US"):
        self._locale = locale
        self._stop_flag = threading.Event()
        self._play_thread: threading.Thread | None = None

    def _get_sound_path(self, name: str) -> Path | None:
        """Find the clip for a sound (WAV only)."""
        sound_file = _ASSETS_DIR / self._locale / f"{name}.wav"
        if sound_file.exists():
            return sound_file
        # fall back to en-US
        if self._locale != "en-US":
            fallback = _ASSETS_DIR / "en-US" / f"{name}.wav"
            if fallback.exists():
                return fallback
        return None

    def _load_wav(self, file_path: Path) -> tuple[np.ndarray, int] | None:
        """Load a WAV as float32 mono, returning (samples, sample_rate).

        Args:
            file_path: the path to the WAV.

        Returns:
            (float32 audio, sample rate), or None on failure.
        """
        try:
            with wave.open(str(file_path), "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)

            if sample_width == 2:
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                audio = (
                    np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
                )
            elif sample_width == 1:
                # 8-bit PCM is unsigned
                audio = (
                    np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0
                ) / 128.0
            else:
                logger.error(
                    f"unsupported WAV bit depth: {sample_width * 8} bit ({file_path})"
                )
                return None

            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)

            return audio, sample_rate
        except Exception as e:
            logger.error(f"failed to load the WAV {file_path}: {e}", exc_info=True)
            return None

    def _play_sounds(self, names: list[str]) -> None:
        """Play the sequence of clips (runs on a worker thread)."""
        for name in names:
            if self._stop_flag.is_set():
                logger.debug("the announcement was interrupted")
                break

            sound_path = self._get_sound_path(name)
            if not sound_path:
                logger.warning(f"no such sound clip: {name}")
                continue

            loaded = self._load_wav(sound_path)
            if loaded is None or self._stop_flag.is_set():
                continue

            audio, sample_rate = loaded
            if sample_rate <= 0:
                sample_rate = _DEFAULT_SAMPLE_RATE

            try:
                sd.play(audio, sample_rate)
                # wait in slices, so an interrupt is noticed quickly
                while sd.get_stream().active:
                    if self._stop_flag.is_set():
                        sd.stop()
                        break
                    self._stop_flag.wait(0.05)
            except Exception as e:
                logger.error(f"playback failed: {e}", exc_info=True)

    def announce(self, code: str) -> None:
        """Read the verification code aloud (non-blocking).

        Args:
            code: the code, e.g. "123456"
        """
        if not code or not code.isdigit():
            logger.warning(f"invalid verification code: {code}")
            return

        # stop whatever was being announced
        self.stop()

        # build the sequence: the activation prompt, then each digit
        sounds = ["activation"] + list(code)

        logger.info(f"announcing the verification code: {code}")

        self._stop_flag.clear()
        self._play_thread = threading.Thread(
            target=self._play_sounds,
            args=(sounds,),
            daemon=True,
            name="ActivationAnnouncer",
        )
        self._play_thread.start()

    def stop(self) -> None:
        """Stop the announcement."""
        self._stop_flag.set()

        # stop the playback
        try:
            sd.stop()
        except Exception as e:
            logger.debug(f"failed to stop the playback: {e}")

        # wait for the thread to finish
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1)

        self._play_thread = None


# the module-level instance
_announcer: ActivationAnnouncer | None = None


def announce_activation_code(code: str, locale: str = "en-US") -> None:
    """Read the activation code aloud.

    Args:
        code: the code
        locale: the language code
    """
    global _announcer
    if _announcer is None:
        _announcer = ActivationAnnouncer(locale)
    _announcer.announce(code)


def stop_announcement() -> None:
    """Stop the announcement."""
    global _announcer
    if _announcer:
        _announcer.stop()
