"""The music tools.

- music_player: the playback session, created by the container and injected into MCP - the only public entry point
- playback / bus: PlaybackEngine and MusicEventBridge, composed internally - not a public API
- cache / download / lyrics: the cache, the direct links, and the lyrics
- online_search / local_library / metadata: searching online, and the local library
- register_music_tools: registers the tools with McpServer, the closures holding the player
"""

from .register import register_music_tools
from .music_player import MusicPlayer

__all__ = [
    "MusicPlayer",
    "register_music_tools",
]
