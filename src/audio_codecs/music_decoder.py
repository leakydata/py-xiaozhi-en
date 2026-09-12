import asyncio
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from src.constants.constants import AudioConfig
from src.logging import get_logger
from src.utils.resource_finder import get_ffmpeg_path, get_ffprobe_path

logger = get_logger()

_SUBPROCESS_KW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

# a local path or an http(s) stream
AudioSource = str | Path


def is_http_url(source: AudioSource) -> bool:
    text = str(source).strip()
    return text.startswith("http://") or text.startswith("https://")


def _source_label(source: AudioSource) -> str:
    if is_http_url(source):
        host = urlparse(str(source)).hostname or "http"
        return f"stream:{host}"
    path = Path(source)
    return path.name


def _ffmpeg_header_args(headers: Mapping[str, str] | None) -> list[str]:
    """Build the -headers / -user_agent arguments for ffmpeg (HTTP sources usually need them)."""
    if not headers:
        return []
    args: list[str] = []
    ua = None
    lines: list[str] = []
    for key, value in headers.items():
        if not value:
            continue
        if key.lower() == "user-agent":
            ua = str(value)
            continue
        lines.append(f"{key}: {value}")
    if lines:
        blob = "".join(f"{line}\r\n" for line in lines)
        args.extend(["-headers", blob])
    if ua:
        args.extend(["-user_agent", ua])
    return args


class MusicDecoder:
    """Only decodes a source into PCM; the cache prefetch happens elsewhere, so it is not tied to playback progress."""

    @staticmethod
    async def get_duration(
        source: AudioSource,
        headers: Mapping[str, str] | None = None,
    ) -> float:
        """Get the duration with ffprobe; source may be a local file or an http(s) URL."""
        try:
            ffprobe = get_ffprobe_path()
            try:
                check = await asyncio.create_subprocess_exec(
                    ffprobe,
                    "-version",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_SUBPROCESS_KW,
                )
                await check.wait()
            except FileNotFoundError:
                logger.warning(
                    "ffprobe is unavailable (there is no bundled libs/ffmpeg and none on the system PATH), "
                    f"so the audio duration cannot be read. Tried: {ffprobe}"
                )
                return 0
            except OSError as e:
                logger.warning(
                    f"ffprobe failed to start: {ffprobe}: {e}", exc_info=True
                )
                return 0

            cmd = [ffprobe, "-v", "error"]
            if is_http_url(source):
                cmd.extend(_ffmpeg_header_args(headers))
            cmd.extend(
                [
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(source),
                ]
            )

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_SUBPROCESS_KW
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                duration_str = stdout.decode("utf-8").strip()
                duration = float(duration_str)
                logger.debug(
                    f"audio duration: {duration:.2f}s ({_source_label(source)})"
                )
                return duration
            else:
                error_msg = stderr.decode("utf-8", errors="ignore")
                logger.warning(f"ffprobe could not read the duration: {error_msg}")
                return 0

        except Exception as e:
            logger.warning(f"failed to read the audio duration: {e}", exc_info=True)
            return 0

    def __init__(self, sample_rate: int = 24000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._process: subprocess.Process | None = None
        self._decode_task: asyncio.Task | None = None
        self._stopped = False

    async def start_decode(
        self,
        source: AudioSource,
        output_queue: asyncio.Queue,
        start_position: float = 0.0,
        headers: Mapping[str, str] | None = None,
        cache_path: Path | None = None,
    ) -> bool:
        """Start decoding. source is a local path or an http(s) URL.

        cache_path is deprecated and ignored: the cache is copied in the background at network speed, not tied to playback progress.
        """
        _ = cache_path
        http = is_http_url(source)
        if not http:
            path = Path(source)
            if not path.exists():
                logger.error(f"no such audio file: {path}")
                return False
            source = path

        self._stopped = False

        try:
            ffmpeg = get_ffmpeg_path()
            try:
                result = await asyncio.create_subprocess_exec(
                    ffmpeg,
                    "-version",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_SUBPROCESS_KW,
                )
                await result.wait()
                if result.returncode not in (0, None):
                    logger.error(
                        f"FFmpeg would not start (exit code {result.returncode}): {ffmpeg}. "
                        "The installer ships a portable binary; if this still fails, report your version and platform. "
                        "Running from source, either run ./scripts/bundle_ffmpeg.sh or install ffmpeg system-wide"
                    )
                    return False
            except FileNotFoundError:
                logger.error(
                    "FFmpeg is unavailable: there is no bundled libs/ffmpeg/<plat>/<arch>/ffmpeg, "
                    f"and none on the system PATH either. Tried: {ffmpeg}. "
                    "Installer users should not need a system FFmpeg; if it still fails from the installer, "
                    "download the full installer again. Running from source, install ffmpeg or run "
                    "./scripts/bundle_ffmpeg.sh"
                )
                return False
            except OSError as e:
                logger.error(
                    f"FFmpeg failed to start (a shared library may be missing): {ffmpeg}: {e}",
                    exc_info=True,
                )
                return False

            cmd = [ffmpeg]

            if http:
                cmd.extend(
                    [
                        "-reconnect",
                        "1",
                        "-reconnect_streamed",
                        "1",
                        "-reconnect_delay_max",
                        "5",
                    ]
                )
                cmd.extend(_ffmpeg_header_args(headers))

            if start_position > 0.1:
                cmd.extend(["-ss", f"{start_position:.3f}"])

            cmd.extend(
                [
                    "-i",
                    str(source),
                    "-f",
                    "s16le",
                    "-ar",
                    str(self.sample_rate),
                    "-ac",
                    str(self.channels),
                    "-loglevel",
                    "error",
                    "-",
                ]
            )

            self._process = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_SUBPROCESS_KW
            )

            self._decode_task = asyncio.create_task(self._read_pcm_stream(output_queue))

            position_info = f" from {start_position:.1f}s" if start_position > 0 else ""
            mode = "streaming" if http else "file"
            logger.info(
                f"decoding audio ({mode}): {_source_label(source)}{position_info} "
                f"[{self.sample_rate}Hz, {self.channels}ch]"
            )
            return True

        except Exception as e:
            logger.error(f"failed to start the audio decode: {e}", exc_info=True)
            return False

    async def _read_pcm_stream(self, output_queue: asyncio.Queue):
        frame_duration_ms = AudioConfig.FRAME_DURATION
        frame_size_samples = int(self.sample_rate * (frame_duration_ms / 1000))
        frame_size_bytes = frame_size_samples * 2 * self.channels
        logger.info(
            f"decoder settings: frame size={frame_size_samples} samples, "
            f"{frame_size_bytes} bytes, {frame_duration_ms}ms"
        )

        eof_reached = False
        frame_count = 0

        try:
            while not self._stopped:
                chunk = await self._process.stdout.read(frame_size_bytes)

                if not chunk:
                    duration_decoded = frame_count * frame_duration_ms / 1000
                    logger.info(
                        f"audio decode complete, {frame_count} frames, about {duration_decoded:.1f}s"
                    )

                    if self._process:
                        try:
                            await asyncio.wait_for(self._process.wait(), timeout=2.0)
                        except (asyncio.TimeoutError, Exception):
                            pass
                        try:
                            stderr_output = await self._process.stderr.read()
                            if stderr_output:
                                err = stderr_output.decode("utf-8", errors="ignore")
                                if err.strip():
                                    logger.warning(f"FFmpeg: {err.strip()[:300]}")
                        except Exception as e:
                            logger.debug(f"failed to read FFmpeg stderr: {e}")

                    eof_reached = True
                    break

                frame_count += 1

                audio_array_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_array = audio_array_int16.astype(np.float32) / 32768.0

                if self.channels > 1:
                    audio_array = audio_array.reshape(-1, self.channels)

                # the pace comes entirely from downstream backpressure: a full queue blocks at the put
                # (AudioCodec.write_pcm_direct lets it through on the buffer watermark).
                # No longer throttled against wall-clock-since-start: the wall clock keeps running
                # through a pause, so on resume it thinks it is behind and floods the playback queue.
                await output_queue.put(audio_array)

        except asyncio.CancelledError:
            logger.debug("the decode task was cancelled")
        except Exception as e:
            logger.error(f"failed to read the PCM stream: {e}", exc_info=True)
        finally:
            if eof_reached:
                try:
                    await output_queue.put(None)
                except Exception as e:
                    logger.debug(f"failed to send the EOF signal: {e}")

    async def stop(self):
        if self._stopped:
            return

        self._stopped = True
        logger.debug("stopping the audio decoder")

        if self._decode_task and not self._decode_task.done():
            self._decode_task.cancel()
            try:
                await self._decode_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"the decode task raised: {e}", exc_info=True)

        proc = self._process
        self._process = None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as e:
                    logger.debug(f"failed to kill FFmpeg: {e}")
            except ProcessLookupError:
                pass
            except Exception as e:
                if str(e).strip():
                    logger.debug(f"ending the FFmpeg process: {e}")

    def is_running(self) -> bool:
        return (
            not self._stopped
            and self._process is not None
            and self._process.returncode is None
        )

    async def wait_completion(self):
        if self._decode_task and not self._decode_task.done():
            try:
                await self._decode_task
            except Exception as e:
                logger.error(
                    f"failed while waiting for the decode to finish: {e}", exc_info=True
                )
