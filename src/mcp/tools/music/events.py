"""The event payloads the music player uses.

These are the structures carried over the EventBus.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MusicStateData:
    """Payload for a music state change.

    Attributes:
        state: the playback state ("playing", "paused", "stopped", "completed")
        song: the track name
        position: how far in, in seconds
        duration: the track length, in seconds
        pause_source: what paused it ("tts", "manual", "external", None)
    """

    state: str
    song: str
    position: float
    duration: float
    pause_source: Optional[str] = None


@dataclass
class MusicLyricsData:
    """Payload for a lyrics update.

    Attributes:
        text: the line of lyrics
        time_sec: its timestamp, in seconds
        song_id: the track id (optional)
    """

    text: str
    time_sec: float
    song_id: Optional[str] = None


@dataclass
class MusicControlRequest:
    """Payload for a music control request.

    Attributes:
        source: what asked for it ("tts", "manual", "external", and so on)
    """

    source: str = "external"
