"""Music downloads: resolve the direct link, then prefetch the whole track into the local cache with an FFmpeg copy in the background."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from src.logging import get_logger
from src.utils.resource_finder import get_ffmpeg_path

from .cache import MusicCache

logger = get_logger()

# when the direct link fails, fall back to Kuwo's own preview endpoint
_KUWO_PLAYURL = "https://wapi.kuwo.cn/api/v1/www/music/playUrl"
_QUALITY_FALLBACKS = ("320k", "128k")

_SUBPROCESS_KW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)


class MusicDownloader:
    """Resolve the stream URL, and optionally copy the whole track into the cache in the background (as fast as the network allows, not in step with playback)."""

    def __init__(self, cache: MusicCache, config: dict[str, Any] | None = None) -> None:
        self._cache = cache
        self._config = config or {}
        # why the last attempt failed, so the caller can say something useful
        self.last_error: str | None = None
        self._prefetch_task: asyncio.Task | None = None
        self._prefetch_song_id: str | None = None

    def set_config(self, config: dict[str, Any]) -> None:
        self._config = config

    async def get_or_download(
        self,
        song_id: str,
        api_url: str,
        *,
        filename: str | None = None,
    ) -> Path | None:
        """Use the cache when there is one, download otherwise."""
        self._cache.prepare()
        name = filename or f"{song_id}.mp3"
        hit = self._cache.find_song_file(song_id)
        if hit is not None:
            logger.info(f"using the cache: {hit}")
            return hit

        cache_path = self._cache.root / name
        if cache_path.exists():
            logger.info(f"using the cache: {cache_path}")
            return cache_path

        return await self.download(api_url, name, song_id=song_id)

    @staticmethod
    def _extract_url_from_payload(data: Any) -> str | None:
        # every provider names its JSON fields differently, so dig the url out however we can
        if not isinstance(data, dict):
            return None

        real_url = data.get("url")
        if isinstance(real_url, str) and real_url.startswith("http"):
            return real_url

        inner = data.get("data")
        if isinstance(inner, dict):
            nested = inner.get("url")
            if isinstance(nested, str) and nested.startswith("http"):
                return nested
        elif isinstance(inner, str) and inner.startswith("http"):
            return inner

        return None

    @staticmethod
    def _is_ip_blocked(data: Any) -> bool:
        """Whether the API is refusing this IP.

        The upstream API answers in Chinese, so these needles stay in Chinese -
        they are matched against its response, not read by anyone.
        """
        if not isinstance(data, dict):
            return False
        code = data.get("code")
        msg = str(data.get("msg") or data.get("message") or "").strip()
        return code == 1 or "禁止批量下载" in msg or "block ip" in msg.lower()

    @classmethod
    def _describe_api_failure(cls, data: Any) -> str:
        if not isinstance(data, dict):
            return "The direct-link API returned data that could not be parsed"

        code = data.get("code")
        msg = str(data.get("msg") or data.get("message") or "").strip()

        # the codes lx-music-api commonly returns
        if cls._is_ip_blocked(data):
            return (
                "The direct-link API has blocked this IP (bulk downloading is "
                "refused). Try a different network or IP, or change MUSIC.URL_API "
                "in the settings"
            )
        if code == 5 or "too many" in msg.lower():
            return "The direct-link API is rate-limiting us, try again shortly"
        if code == 2:
            return "The direct-link API could not get a stream URL (no source in its library, or it failed to resolve)"
        if code == 4:
            return "The direct-link API hit an internal error"
        if code == 6:
            return "The direct-link API rejected the parameters"

        if msg:
            return f"The direct-link API failed: {msg}"
        return f"The direct-link API returned no stream URL: {data}"

    def _lx_headers(self) -> dict[str, str]:
        # matching Huibq/keep-alive render_api.js: it only accepts a Key plus a UA
        return {
            "X-Request-Key": self._config.get("URL_API_KEY", "share-v3"),
            "User-Agent": "lx-music-request",
            "Content-Type": "application/json",
        }

    def _browser_headers(self) -> dict[str, str]:
        # used by Kuwo's own playUrl endpoint
        headers = dict(self._config.get("HEADERS") or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        headers.setdefault("Referer", "https://www.kuwo.cn/")
        headers.setdefault("Accept", "application/json, text/plain, */*")
        return headers

    def media_headers(self, media_url: str) -> dict[str, str]:
        """The headers for CDN / FFmpeg streaming (not the ones the JSON API wants)."""
        host = (urlparse(media_url).hostname or "").lower()
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        if "kuwo" in host or "sycdn" in host or "bd-lv" in host:
            headers["Referer"] = "https://www.kuwo.cn/"
            headers["Origin"] = "https://www.kuwo.cn"
        return headers

    # legacy name
    def _download_headers(self, download_url: str) -> dict[str, str]:
        return self.media_headers(download_url)

    async def _fetch_json(
        self, url: str, headers: dict[str, str], *, timeout: int = 15
    ) -> Any | None:
        try:
            response = await asyncio.to_thread(
                requests.get, url, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(
                f"request failed for {urlparse(url).netloc}: {e}", exc_info=True
            )
            return None

    def _candidate_lx_urls(self, api_url: str) -> list[str]:
        # try the configured bitrate first, then 128k
        urls = [api_url]
        m = re.search(r"/url/[^/]+/[^/]+/([^/?#]+)", api_url)
        if not m:
            return urls
        current_quality = m.group(1)
        for q in _QUALITY_FALLBACKS:
            if q == current_quality:
                continue
            alt = re.sub(
                r"(/url/[^/]+/[^/]+/)[^/?#]+",
                rf"\g<1>{q}",
                api_url,
                count=1,
            )
            if alt not in urls:
                urls.append(alt)
        return urls

    async def _resolve_via_lx_api(self, api_url: str) -> tuple[str | None, str | None]:
        last_reason: str | None = None
        headers = self._lx_headers()

        for candidate in self._candidate_lx_urls(api_url):
            logger.debug(f"trying the direct-link API: {candidate}")
            data = await self._fetch_json(candidate, headers)
            if data is None:
                last_reason = "The direct-link API request failed"
                continue

            real_url = self._extract_url_from_payload(data)
            if real_url:
                logger.info(f"the direct-link API resolved it: {real_url[:80]}...")
                return real_url, None

            last_reason = self._describe_api_failure(data)
            logger.warning(f"the direct-link API returned no URL: {data}")

            # a different bitrate will not help once the IP itself is blocked
            if self._is_ip_blocked(data):
                break

        return None, last_reason

    async def _resolve_via_kuwo_official(
        self, song_id: str
    ) -> tuple[str | None, str | None]:
        # free tracks play; for paid ones the official endpoint simply says no
        if not song_id or song_id == "unknown":
            return None, "No track ID, so the official endpoint cannot be used as a fallback"

        headers = self._browser_headers()
        last_reason: str | None = None

        for br in ("320kmp3", "128kmp3"):
            url = f"{_KUWO_PLAYURL}?mid={song_id}&type=music&httpsStatus=1&br={br}"
            logger.debug(f"trying Kuwo's own playUrl: mid={song_id} br={br}")
            data = await self._fetch_json(url, headers)
            if data is None:
                last_reason = "The request to Kuwo's own endpoint failed"
                continue

            real_url = self._extract_url_from_payload(data)
            if real_url:
                logger.info(f"Kuwo's own endpoint resolved it: {real_url[:80]}...")
                return real_url, None

            msg = ""
            if isinstance(data, dict):
                msg = str(data.get("msg") or data.get("message") or "").strip()
            # again, matched against the API's Chinese response text
            if "付费" in msg:
                last_reason = f"This track is paid content, the official endpoint will not preview it ({msg})"
                break
            last_reason = msg or f"Kuwo's own endpoint returned no URL: {data}"
            logger.warning(last_reason)

        return None, last_reason

    async def resolve_play_url(
        self, api_url: str, *, song_id: str | None = None
    ) -> str | None:
        # direct link -> lower bitrate -> the official endpoint
        self.last_error = None
        reasons: list[str] = []

        try:
            real_url, reason = await self._resolve_via_lx_api(api_url)
            if real_url:
                return real_url
            if reason:
                reasons.append(reason)

            # with no song_id given, pull it out of the url path
            sid = song_id
            if not sid or sid == "unknown":
                m = re.search(r"/url/[^/]+/([^/]+)/", api_url)
                if m:
                    sid = m.group(1)

            if sid:
                real_url, reason = await self._resolve_via_kuwo_official(sid)
                if real_url:
                    return real_url
                if reason:
                    reasons.append(reason)

            self.last_error = "; ".join(reasons) if reasons else "Could not resolve a stream URL"
            logger.error(f"could not resolve a stream URL: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = f"Error while resolving the stream URL: {e}"
            logger.error(self.last_error, exc_info=True)
            return None

    def _sync_download(
        self, download_url: str, headers: dict, temp_path: Path, cache_path: Path
    ) -> Path:
        # the CDN throws the occasional RemoteDisconnected, so retry a couple of times
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                if temp_path.exists():
                    temp_path.unlink()
                with requests.get(
                    download_url,
                    headers=headers,
                    stream=True,
                    timeout=45,
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                f.write(chunk)
                if temp_path.stat().st_size <= 0:
                    raise IOError("the downloaded file is empty")
                shutil.move(str(temp_path), str(cache_path))
                return cache_path
            except (requests.RequestException, OSError) as e:
                last_err = e
                logger.warning(
                    f"download attempt {attempt + 1}/3 failed: {e}"
                )
        assert last_err is not None
        raise last_err

    async def download(
        self, api_url: str, filename: str, *, song_id: str | None = None
    ) -> Path | None:
        """Download the track and write it into the cache directory."""
        self._cache.prepare()
        temp_path = None
        try:
            download_url = await self.resolve_play_url(api_url, song_id=song_id)
            if not download_url:
                return None

            temp_path = self._cache.temp_path(filename)
            cache_path = self._cache.root / filename
            headers = self.media_headers(download_url)
            logger.debug(
                f"starting the audio download: host={urlparse(download_url).hostname}"
            )

            result = await asyncio.to_thread(
                self._sync_download,
                download_url,
                headers,
                temp_path,
                cache_path,
            )
            logger.info(f"download finished and cached: {result}")
            return result
        except Exception as e:
            self.last_error = f"Download failed: {e}"
            logger.error(self.last_error, exc_info=True)
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception as cleanup_e:
                    logger.debug(f"failed to remove the temporary file: {cleanup_e}")
            return None

    def start_prefetch(
        self,
        media_url: str,
        song_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Copy the whole track to disk in the background with FFmpeg -c copy, as fast as the network allows rather than in step with playback.

        Much like an HTML audio element buffering: it pulls the whole file down while the track plays, so it is often fully cached before the track ends.
        Changing track cancels the previous prefetch; pausing or stopping the current one does not (it keeps buffering).
        """
        if not song_id or song_id == "unknown":
            return
        self._cache.prepare()
        if self._cache.find_song_file(song_id) is not None:
            logger.debug(f"already cached, skipping the prefetch: {song_id}")
            return

        # this track is already being prefetched
        if (
            self._prefetch_task
            and not self._prefetch_task.done()
            and self._prefetch_song_id == song_id
        ):
            return

        self.cancel_prefetch()
        hdrs = dict(headers or self.media_headers(media_url))
        self._prefetch_song_id = song_id
        self._prefetch_task = asyncio.create_task(
            self._prefetch_copy_loop(media_url, song_id, hdrs),
            name=f"music:prefetch:{song_id}",
        )
        logger.info(f"prefetching in the background: song_id={song_id}")

    def cancel_prefetch(self) -> None:
        """Cancel the background prefetch (on a track change)."""
        task = self._prefetch_task
        self._prefetch_task = None
        self._prefetch_song_id = None
        if task and not task.done():
            task.cancel()

    async def _prefetch_copy_loop(
        self, media_url: str, song_id: str, headers: dict[str, str]
    ) -> None:
        final = self._cache.path_for_song(song_id)
        part = final.with_name(f"{final.stem}.part{final.suffix}")
        try:
            if part.exists():
                part.unlink()
        except Exception:
            pass

        try:
            ok = await self._ffmpeg_copy_url(media_url, part, headers)
            if not ok:
                return
            if not part.exists() or part.stat().st_size <= 1024:
                logger.warning(f"the prefetched file is too small, discarding it: {part.name}")
                if part.exists():
                    part.unlink()
                return
            if final.exists():
                final.unlink()
            part.replace(final)
            logger.info(
                f"background prefetch complete (it can play locally now): {final.name} ({final.stat().st_size} bytes)"
            )
        except asyncio.CancelledError:
            logger.debug(f"background prefetch cancelled: {song_id}")
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.warning(f"background prefetch failed for {song_id}: {e}", exc_info=True)
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
        finally:
            if self._prefetch_song_id == song_id:
                self._prefetch_task = None
                self._prefetch_song_id = None

    async def _ffmpeg_copy_url(
        self, media_url: str, out_path: Path, headers: dict[str, str]
    ) -> bool:
        """Pull the whole track with FFmpeg -c copy at network speed - no decoding, and not throttled to playback."""
        from src.audio_codecs.music_decoder import _ffmpeg_header_args

        ffmpeg = get_ffmpeg_path()
        cmd = [
            ffmpeg,
            "-y",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
        ]
        cmd.extend(_ffmpeg_header_args(headers))
        cmd.extend(
            [
                "-i",
                media_url,
                "-vn",
                "-c:a",
                "copy",
                "-loglevel",
                "error",
                str(out_path),
            ]
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **_SUBPROCESS_KW,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = (stderr or b"").decode("utf-8", errors="ignore").strip()
                logger.warning(
                    f"FFmpeg copy prefetch failed rc={proc.returncode}: {err[:300]}"
                )
                return False
            return True
        except FileNotFoundError:
            logger.warning("FFmpeg is unavailable, skipping the background prefetch")
            return False
        except Exception as e:
            logger.warning(f"FFmpeg copy prefetch raised: {e}", exc_info=True)
            return False
