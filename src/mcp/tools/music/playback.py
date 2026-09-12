"""Playback engine: the decode queue, start/stop/pause/resume/seek, and writing to AudioCodec.

Owned by MusicPlayer. It does not reach into the host's own attributes - timing and context arrive through the hook callbacks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

import numpy as np

from src.audio_codecs.music_decoder import MusicDecoder, is_http_url
from src.constants.constants import AudioConfig
from src.logging import get_logger

if TYPE_CHECKING:
    from src.audio_codecs.audio_codec import AudioCodec
    from src.mcp.tools.music.cache import MusicCache
    from src.mcp.tools.music.download import MusicDownloader
    from src.mcp.tools.music.local_library import LocalLibrary

logger = get_logger()


class PlaybackHooks(Protocol):
    """The callbacks MusicPlayer hands to the engine."""

    def prepare_for_io(self) -> None: ...

    def is_speaking(self) -> bool: ...

    def format_time(self, seconds: float) -> str: ...

    async def tick_lyrics(self) -> None: ...

    async def emit_state_change(
        self,
        state: str,
        song_name: str | None = None,
        position: float | None = None,
    ) -> None: ...


@dataclass
class PlaybackDeps:
    cache: MusicCache
    downloader: MusicDownloader
    library: LocalLibrary
    hooks: PlaybackHooks


class PlaybackEngine:
    """The playback state machine; the state lives on this instance."""

    def __init__(self, deps: PlaybackDeps) -> None:
        self._cache = deps.cache
        self._downloader = deps.downloader
        self._library = deps.library
        self._hooks = deps.hooks

        self.audio_codec: AudioCodec | None = None
        self.decoder: MusicDecoder | None = None
        self._music_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._playback_task: asyncio.Task | None = None

        self.current_song = ""
        self.song_id = ""
        self.total_duration = 0.0
        self.is_playing = False
        self.paused = False
        self.current_position = 0.0
        self.start_play_time = 0.0
        self.pause_source: str | None = None
        self._current_source: str | Path | None = None
        self._stream_headers: dict[str, str] | None = None
        # the online direct-link template; it can be re-resolved for a fresh CDN once TTS finishes
        self.api_url: str | None = None
        self.current_lyric_index = -1
        self.last_lyric_tick = 0.0

    def _get_audio_codec(self) -> AudioCodec | None:
        if self.audio_codec is None:
            logger.warning("AudioCodec is not set, music playback is unavailable")
        return self.audio_codec

    async def _clear_music_queue(self) -> int:
        count = 0
        while not self._music_queue.empty():
            try:
                self._music_queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        return count

    async def _cancel_playback_task(self) -> None:
        task = self._playback_task
        if task is None or task.done():
            self._playback_task = None
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"error while waiting for the playback task to finish: {e}")
        self._playback_task = None

    async def stop(self) -> dict:
        try:
            if not self.is_playing:
                return {"status": "info", "message": "Nothing is playing"}

            current_song = self.current_song
            if self.decoder:
                await self.decoder.stop()
                self.decoder = None

            await self._cancel_playback_task()
            cleared = await self._clear_music_queue()
            audio_codec = self._get_audio_codec()
            if audio_codec:
                await audio_codec.clear_music_queue()
            logger.debug(f"cleared {cleared} music frames on stop")

            self.is_playing = False
            self.paused = False
            self.pause_source = None
            self.current_position = 0
            self.current_lyric_index = -1
            self.api_url = None

            await self._hooks.emit_state_change("stopped", current_song)
            logger.info(f"stopped: {current_song}")
            return {"status": "success", "message": "Stopped"}
        except Exception as e:
            logger.error(f"failed to stop playback: {e}", exc_info=True)
            return {"status": "error", "message": f"Could not stop: {str(e)}"}

    async def pause(self, source: str = "manual") -> dict:
        try:
            if not self.is_playing:
                return {"status": "info", "message": "Nothing is playing"}

            if self.paused:
                if self.pause_source != source:
                    old = self.pause_source
                    self.pause_source = source
                    logger.info(f"pause source updated: {old} -> {source}")
                return {"status": "info", "message": "Already paused"}

            self.paused = True
            self.pause_source = source
            if self.start_play_time > 0:
                self.current_position = time.time() - self.start_play_time

            fmt = self._hooks.format_time

            if source == "tts":
                # per-sentence TTS ducking: the decoder and queue are kept (the decoder simply
                # blocks on a full queue), so resuming costs nothing and ffmpeg is not restarted per sentence
                logger.info(
                    f"paused (tts, decoder kept): {self.current_song} "
                    f"at {fmt(self.current_position)}"
                )
                return {"status": "success", "message": "Paused"}

            if self.decoder:
                await self.decoder.stop()
                self.decoder = None

            cleared = await self._clear_music_queue()
            audio_codec = self._get_audio_codec()
            if audio_codec:
                # a manual pause must go silent at once, so drop the music still buffered in the codec
                await audio_codec.clear_music_queue()
            logger.info(
                f"paused: {self.current_song} at {fmt(self.current_position)}, "
                f"source: {source}, cleared {cleared} frames from the music queue"
            )
            return {"status": "success", "message": "Paused"}
        except Exception as e:
            logger.error(f"failed to pause playback: {e}", exc_info=True)
            return {"status": "error", "message": f"Could not pause: {str(e)}"}

    async def resume(self) -> dict:
        try:
            if not self.is_playing:
                return {"status": "info", "message": "Nothing is playing"}
            if not self.paused:
                return {"status": "info", "message": "Not currently paused"}

            if (
                self.decoder is not None
                and self.pause_source == "tts"
                and self._playback_task is not None
                and not self._playback_task.done()
            ):
                # fast resume (the TTS ducking path): the decoder and consumer loop are still up, so just carry on consuming
                self.paused = False
                self.pause_source = None
                self.start_play_time = time.time() - self.current_position
                self.last_lyric_tick = 0.0
                logger.info(
                    f"resumed (tts, decoder still attached): {self.current_song} from "
                    f"{self._hooks.format_time(self.current_position)}"
                )
                await self._hooks.emit_state_change("playing", self.current_song)
                return {"status": "success", "message": "Resumed"}

            if self.api_url:
                if not await self._refresh_stream_source():
                    return {
                        "status": "error",
                        "message": self._downloader.last_error or "Could not refresh the stream URL",
                    }
            elif not self._current_source:
                return {"status": "error", "message": "There is no source to resume from"}
            elif not is_http_url(self._current_source) and not Path(
                self._current_source
            ).exists():
                return {"status": "error", "message": "Could not find the audio file"}

            fmt = self._hooks.format_time
            logger.info(
                f"resumed: {self.current_song} from {fmt(self.current_position)}"
            )

            await self._cancel_playback_task()
            cleared = await self._clear_music_queue()
            if cleared > 0:
                logger.debug(f"cleared {cleared} leftover frames before resuming")

            if self.decoder:
                await self.decoder.stop()
                self.decoder = None

            self.decoder = MusicDecoder(
                sample_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
                channels=AudioConfig.CHANNELS,
            )
            if is_http_url(self._current_source) and self.song_id:
                self._downloader.start_prefetch(
                    str(self._current_source),
                    self.song_id,
                    self._stream_headers,
                )

            success = await self.decoder.start_decode(
                self._current_source,
                self._music_queue,
                self.current_position,
                headers=self._stream_headers,
            )
            if not success:
                return {"status": "error", "message": "Could not resume playback"}

            self.paused = False
            self.pause_source = None
            self.start_play_time = time.time() - self.current_position
            self.last_lyric_tick = 0.0
            self._playback_task = asyncio.create_task(
                self._playback_loop(), name="music:playback"
            )
            await self._hooks.emit_state_change("playing", self.current_song)
            return {"status": "success", "message": "Resumed"}
        except Exception as e:
            logger.error(f"failed to resume playback: {e}", exc_info=True)
            return {"status": "error", "message": f"Could not resume: {str(e)}"}

    async def seek(
        self,
        position: float | None = None,
        percent: float | None = None,
    ) -> dict:
        """Seek. position is in seconds; percent is 0-100 (converted using total_duration)."""
        try:
            if not self.is_playing:
                return {"status": "error", "message": "Nothing is playing"}
            if not self._current_source:
                return {"status": "error", "message": "There is no source to seek in"}
            if not is_http_url(self._current_source) and not Path(
                self._current_source
            ).exists():
                return {"status": "error", "message": "Could not find the audio file"}

            if self.total_duration <= 0 and not is_http_url(self._current_source):
                duration = await MusicDecoder.get_duration(self._current_source)
                if duration > 0:
                    self.total_duration = duration

            target: float | None = None
            fmt = self._hooks.format_time
            if percent is not None and percent >= 0:
                if self.total_duration <= 0:
                    return {
                        "status": "error",
                        "message": "The track length is unknown, so seeking by percentage is not possible",
                    }
                p = max(0.0, min(100.0, float(percent)))
                target = self.total_duration * (p / 100.0)
                logger.info(
                    f"seeking by percentage: {p:.0f}% -> {fmt(target)} "
                    f"(total {fmt(self.total_duration)})"
                )
            elif position is not None and position >= 0:
                target = float(position)
            else:
                return {
                    "status": "error",
                    "message": "Give either position (in seconds) or percent (0-100)",
                }

            if target < 0:
                target = 0
            if self.total_duration > 0 and target >= self.total_duration:
                target = max(0.0, self.total_duration - 1)

            if self.decoder:
                await self.decoder.stop()
                self.decoder = None

            await asyncio.sleep(0.05)
            cleared = await self._clear_music_queue()
            audio_codec = self._get_audio_codec()
            if audio_codec:
                # only the music queue is cleared; the TTS queue is separate and a seek does not touch it
                await audio_codec.clear_music_queue()

            logger.info(f"seeked to {fmt(target)}, cleared {cleared} music frames")
            success = await self.start_playback(
                self._current_source,
                target,
                headers=self._stream_headers,
            )
            if success:
                return {
                    "status": "success",
                    "message": (
                        f"Jumped to {fmt(target)}"
                        + (
                            f" (about {percent:.0f}%)"
                            if percent is not None and percent >= 0
                            else ""
                        )
                    ),
                }
            return {"status": "error", "message": "Could not seek"}
        except Exception as e:
            logger.error(f"seek failed: {e}", exc_info=True)
            return {"status": "error", "message": f"Could not seek: {str(e)}"}

    async def get_position(self):
        if not self.is_playing or self.paused:
            return self.current_position
        current_pos = min(self.total_duration, time.time() - self.start_play_time)
        if current_pos >= self.total_duration and self.total_duration > 0:
            await self._handle_playback_finished()
        return current_pos

    async def get_progress(self):
        if self.total_duration <= 0:
            return 0
        position = await self.get_position()
        return round(position * 100 / self.total_duration, 1)

    async def _refresh_stream_source(self) -> bool:
        if not self.api_url:
            return bool(self._current_source)
        self._hooks.prepare_for_io()
        media_url = await self._downloader.resolve_play_url(
            self.api_url, song_id=self.song_id or None
        )
        if not media_url:
            logger.error(
                f"failed to refresh the stream URL: {self._downloader.last_error or 'unknown'}"
            )
            return False
        self._current_source = media_url
        self._stream_headers = self._downloader.media_headers(media_url)
        host = urlparse(media_url).hostname or media_url[:48]
        logger.info(f"stream URL refreshed: {host}")
        if self.song_id:
            self._downloader.start_prefetch(
                media_url, self.song_id, self._stream_headers
            )
        return True

    async def play_url(self, api_url: str) -> bool:
        try:
            if not self._get_audio_codec():
                logger.error("could not get the AudioCodec, playback failed")
                return False

            if self.is_playing:
                await self.stop()

            self._hooks.prepare_for_io()
            self.api_url = api_url

            if self.song_id:
                cached = self._cache.find_song_file(self.song_id)
                if cached is not None:
                    logger.info(f"playing from the local cache: {cached}")
                    self.api_url = None
                    duration = await MusicDecoder.get_duration(cached)
                    if duration > 0:
                        self.total_duration = duration
                    return await self.start_playback(cached)

            if self._hooks.is_speaking():
                logger.info("TTS is speaking; the playback session is reserved and the stream opens once it finishes")
                self._current_source = None
                self._stream_headers = None
                self.is_playing = True
                self.paused = True
                self.pause_source = "tts"
                self.current_position = 0.0
                self.start_play_time = 0.0
                self.current_lyric_index = -1
                self.last_lyric_tick = 0.0
                await self._cancel_playback_task()
                if self.decoder:
                    await self.decoder.stop()
                    self.decoder = None
                await self._clear_music_queue()
                return True

            media_url = await self._downloader.resolve_play_url(
                api_url, song_id=self.song_id or None
            )
            if not media_url:
                detail = self._downloader.last_error or "could not resolve the stream URL"
                logger.error(f"failed to get the stream URL: {detail}")
                return False

            headers = self._downloader.media_headers(media_url)
            if self.total_duration <= 0:
                duration = await MusicDecoder.get_duration(media_url, headers=headers)
                if duration > 0:
                    self.total_duration = duration
                    logger.info(f"duration probed from the stream: {duration:.2f}s")
                else:
                    logger.warning("could not get the stream duration, falling back to the lyrics duration or 0")

            host = urlparse(media_url).hostname or media_url[:48]
            logger.info(f"streaming: {host}")
            if self.song_id:
                self._downloader.start_prefetch(media_url, self.song_id, headers)
            return await self.start_playback(media_url, headers=headers)
        except Exception as e:
            logger.error(f"playback failed: {e}", exc_info=True)
            return False

    async def start_playback(
        self,
        source: str | Path,
        start_position: float = 0.0,
        headers: dict[str, str] | None = None,
    ) -> bool:
        try:
            self._current_source = source
            self._stream_headers = headers if is_http_url(source) else None

            if self._hooks.is_speaking():
                logger.info("TTS is speaking; the local source is ready and playback starts once it finishes")
                if self.decoder:
                    await self.decoder.stop()
                    self.decoder = None
                await self._cancel_playback_task()
                await self._clear_music_queue()
                self.is_playing = True
                self.paused = True
                self.pause_source = "tts"
                self.current_position = start_position
                self.start_play_time = 0.0
                self.current_lyric_index = -1
                return True

            if self.decoder:
                await self.decoder.stop()
                self.decoder = None

            await self._cancel_playback_task()
            cleared = await self._clear_music_queue()
            if cleared > 0:
                logger.debug(f"cleared {cleared} music frames before starting playback")

            self.decoder = MusicDecoder(
                sample_rate=AudioConfig.OUTPUT_SAMPLE_RATE,
                channels=AudioConfig.CHANNELS,
            )
            success = await self.decoder.start_decode(
                source,
                self._music_queue,
                start_position,
                headers=self._stream_headers,
            )
            if not success:
                logger.error("failed to start the audio decoder")
                return False

            self.is_playing = True
            self.paused = False
            self.pause_source = None
            self.current_position = start_position
            self.start_play_time = time.time() - start_position
            self.current_lyric_index = -1
            self.last_lyric_tick = 0.0

            self._playback_task = asyncio.create_task(
                self._playback_loop(), name="music:playback"
            )

            position_info = f" from {start_position:.1f}s" if start_position > 0 else ""
            logger.info(f"now playing: {self.current_song}{position_info}")
            await self._hooks.emit_state_change(
                "playing", self.current_song, start_position
            )
            return True
        except Exception as e:
            logger.error(f"failed to start playback: {e}", exc_info=True)
            return False

    async def _playback_loop(self):
        try:
            while self.is_playing:
                if self.paused:
                    await asyncio.sleep(0.1)
                    continue

                await self._hooks.tick_lyrics()

                try:
                    audio_data = await asyncio.wait_for(
                        self._music_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("timed out reading the music queue")
                    continue

                if audio_data is None:
                    logger.info("music playback finished")
                    await self._handle_playback_finished()
                    break

                await self._write_to_audio_codec(audio_data)
        except asyncio.CancelledError:
            logger.debug("the playback loop was cancelled")
        except Exception as e:
            logger.error(f"the playback loop raised: {e}", exc_info=True)

    async def _write_to_audio_codec(self, pcm_data: np.ndarray):
        try:
            audio_codec = self._get_audio_codec()
            if not audio_codec:
                return
            if pcm_data.ndim > 1:
                pcm_data = pcm_data.mean(axis=1, dtype=np.float32)
            if pcm_data.dtype != np.float32:
                pcm_data = pcm_data.astype(np.float32)
            await audio_codec.write_pcm_direct(pcm_data)
        except Exception as e:
            logger.error(f"failed to write to AudioCodec: {e}", exc_info=True)

    async def _handle_playback_finished(self):
        if not self.is_playing:
            return
        logger.info(f"track finished: {self.current_song}")
        if self.decoder:
            await self.decoder.stop()
            self.decoder = None
        if self.song_id and self._cache.find_song_file(self.song_id):
            self._library.invalidate()
            logger.debug(f"playback finished, the local cache is available: {self.song_id}")

        if self._playback_task and not self._playback_task.done():
            if self._playback_task is not asyncio.current_task():
                await self._cancel_playback_task()
            else:
                self._playback_task = None

        self.is_playing = False
        self.paused = False
        self.current_position = self.total_duration
        self.current_lyric_index = -1
        await self._hooks.emit_state_change("completed", self.current_song)

    def cancel_prefetch(self) -> None:
        try:
            self._downloader.cancel_prefetch()
        except Exception:
            pass
