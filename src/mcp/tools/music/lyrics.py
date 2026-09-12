"""Fetching and parsing lyrics, and picking the current line from the playback position."""

from __future__ import annotations

import asyncio
from typing import Any

import requests

from src.logging import get_logger

logger = get_logger()

# (seconds, text)
LyricLine = tuple[float, str]

# Credit lines to drop (lyricist, composer, arranger and so on). These stay in
# Chinese: they are matched with startswith() against the lyric text the Kuwo
# API returns, which is Chinese whatever language this client runs in.
_METADATA_PREFIXES = (
    "作词",
    "作曲",
    "编曲",
    "制作",
    "演唱",
    "原唱",
    "翻唱",
)


def lyric_at(
    lyrics: list[LyricLine], current_time: float, *, lead: float = 0.5
) -> tuple[int, str] | None:
    """Find which line of the lyrics belongs to the current playback time.

    Returns (index, text), or None when there are no lyrics.
    """
    if not lyrics:
        return None

    next_lyric_index = None
    for i, (time_sec, _) in enumerate(lyrics):
        if time_sec > current_time - lead:
            next_lyric_index = i
            break

    if next_lyric_index is not None and next_lyric_index > 0:
        idx = next_lyric_index - 1
    elif next_lyric_index is None:
        idx = len(lyrics) - 1
    else:
        idx = 0

    return idx, lyrics[idx][1]


def format_lyric_display(text: str, position: float, duration: float) -> str:
    """Build the lyric line the UI shows, e.g. [00:12/03:45] the words."""
    return f"[{_fmt(position)}/{_fmt(duration)}] {text}"


def _fmt(seconds: float) -> str:
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes:02d}:{secs:02d}"


def parse_kuwo_lrc_list(lrc_list: list[dict]) -> tuple[list[LyricLine], int]:
    """Parse the lrclist the Kuwo API returns.

    Returns (the lyrics, how many credit lines were dropped).
    """
    lyrics: list[LyricLine] = []
    filtered = 0
    for item in lrc_list:
        time_str = item.get("time", "")
        text = (item.get("lineLyric") or "").strip()
        if not text or not time_str:
            continue
        try:
            time_sec = float(time_str)
        except (ValueError, TypeError):
            continue
        if text.startswith(_METADATA_PREFIXES):
            filtered += 1
            continue
        lyrics.append((time_sec, text))
    return lyrics, filtered


async def fetch_kuwo_lyrics(
    song_id: str,
    *,
    lyrics_url: str,
    headers: dict[str, Any] | None = None,
) -> list[LyricLine]:
    """Fetch the lyrics from the Kuwo API and parse them."""
    try:
        logger.info(f"fetching lyrics: ID={song_id}")
        response = await asyncio.to_thread(
            requests.get,
            lyrics_url,
            params={"musicId": song_id},
            headers=headers or {},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != 200:
            logger.info("this track has no lyrics")
            return []

        lrc_list = data.get("data", {}).get("lrclist", [])
        if not lrc_list:
            logger.warning("no lyrics data came back")
            return []

        lyrics, filtered = parse_kuwo_lrc_list(lrc_list)
        logger.info(
            f"got the lyrics: {len(lyrics)} lines ({filtered} credit lines dropped)"
        )
        return lyrics
    except Exception as e:
        logger.error(f"failed to fetch the lyrics: {e}", exc_info=True)
        return []
