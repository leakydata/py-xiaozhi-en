"""The music MCP tools, registered against the MusicPlayer the container injects - no global get_instance."""

from typing import Any, Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .music_player import MusicPlayer

logger = get_logger()


def register_music_tools(
    add_tool: Callable[[McpTool], None], player: MusicPlayer
) -> None:
    """Register the music tools with McpServer (the closures hold the injected player)."""

    async def search_and_play(args: dict[str, Any]) -> str:
        song_name = (args or {}).get("song_name", "")
        result = await player.search_and_play(song_name)
        return result.get("message", "Searched and started playing")

    async def pause(args: dict[str, Any]) -> str:
        # the MCP side defaults to manual; a TTS pause goes through the EventBus, not this tool
        result = await player.pause(source="manual")
        return result.get("message", "Paused")

    async def resume(args: dict[str, Any]) -> str:
        result = await player.resume()
        return result.get("message", "Resumed")

    async def stop(args: dict[str, Any]) -> str:
        result = await player.stop()
        return result.get("message", "Stopped")

    async def seek(args: dict[str, Any]) -> str:
        percent = int(args.get("percent", -1))
        position = int(args.get("position", -1))
        kwargs: dict[str, Any] = {}
        if percent >= 0:
            kwargs["percent"] = percent
        elif position >= 0:
            kwargs["position"] = position
        else:
            return "Give either percent (0-100) or position (in seconds)"
        result = await player.seek(**kwargs)
        return result.get("message", "Jumped")

    async def get_status(args: dict[str, Any]) -> str:
        result = await player.get_status()
        return result.get("message", "Could not read the state")

    async def get_lyrics(args: dict[str, Any]) -> str:
        result = await player.get_lyrics()
        if result.get("status") == "success":
            lyrics = result.get("lyrics", [])
            return "Lyrics:\n" + "\n".join(lyrics)
        return result.get("message", "Could not get the lyrics")

    async def get_local_playlist(args: dict[str, Any]) -> str:
        force_refresh = args.get("force_refresh", False)
        result = await player.get_local_playlist(force_refresh)
        if result.get("status") == "success":
            playlist = result.get("playlist", [])
            total_count = result.get("total_count", 0)
            if playlist:
                text = f"Local music library ({total_count} tracks):\n"
                text += "\n".join(playlist)
                return text
            return "There are no music files in the local cache"
        return result.get("message", "Could not read the local library")

    tools: list[McpTool] = [
        McpTool(
            "music_player.search_and_play",
            (
                "Search for a track and play it. Looks the title up online and starts playing it. "
                "Anything already playing is stopped first. "
                "Use it when the user asks for a particular track, e.g. 'play Nightswimming by REM' or 'put on Blackbird'."
            ),
            PropertyList([Property("song_name", PropertyType.STRING)]),
            search_and_play,
        ),
        McpTool(
            "music_player.pause",
            (
                "Pause whatever is playing, keeping the position so resume can carry on from it. "
                "Call this whenever the user says 'pause the music', 'hold the music a second' or 'music off for a moment'. "
                "Important: call it before replying, or the music resumes by itself once the speech ends."
            ),
            PropertyList(),
            pause,
        ),
        McpTool(
            "music_player.resume",
            (
                "Resume music that was paused, carrying on from where it stopped. "
                "Call it when the user says 'carry on', 'resume the music' or 'put the music back on'. "
                "Note: music pauses on its own while speaking and resumes afterwards, so this is not needed for that. "
                "It is only for resuming after the user themselves paused it."
            ),
            PropertyList(),
            resume,
        ),
        McpTool(
            "music_player.stop",
            (
                "Stop playback completely and reset to the start. "
                "Call this when the user says 'turn the music off', 'stop the music', 'I'm done listening' or 'that's enough'. "
                "The difference from pause: stop shuts it down, pause is temporary and can be resumed."
            ),
            PropertyList(),
            stop,
        ),
        McpTool(
            "music_player.seek",
            (
                "[for seeking only] Jump to a position in the current track. "
                "When the user says 'jump to 30%', 'skip to 20%' or 'go to halfway', use percent (0-100) - "
                "the player converts it to seconds from the track length. Do not read the lyrics or guess a position. "
                "When they say 'jump to 2 minutes', 'go to 90 seconds' or 'back to the start', use position (in seconds, from 0). "
                "For 'skip forward 30 seconds', call get_status for the current position first, then pass position = that + 30. "
                "This has nothing to do with get_lyrics - seeking by percentage needs no lyrics."
            ),
            PropertyList(
                [
                    Property("percent", PropertyType.INTEGER, default_value=-1),
                    Property("position", PropertyType.INTEGER, default_value=-1),
                ]
            ),
            seek,
        ),
        McpTool(
            "music_player.get_status",
            (
                "Read the current playback state: the track, whether it is playing or paused, the length in seconds, the position in seconds, and the progress as a percentage. "
                "Use it for 'where are we in the track', 'how long is this one', or to check the position before skipping. "
                "Do not use it instead of seek - to jump, call seek."
            ),
            PropertyList(),
            get_status,
        ),
        McpTool(
            "music_player.get_lyrics",
            (
                "Only for getting the lyrics of the current track. "
                "Call it when the user asks what the lyrics are, or what the words say. "
                "Never use it for seeking, jumping to a percentage, skipping forward or back, or working out a position - "
                "use music_player.seek for those (percent for a percentage)."
            ),
            PropertyList(),
            get_lyrics,
        ),
        McpTool(
            "music_player.get_local_playlist",
            (
                "Get the local music library - every track that has been downloaded and cached. "
                "Each entry reads 'title - artist', e.g. 'Blackbird - The Beatles'. "
                "Use it when the user asks what tracks they have, for the local list, or what music is cached. "
                "Note: to play something from the list, pass just the title to search_and_play - "
                "for a list entry of 'Blackbird - The Beatles', call search_and_play(song_name='Blackbird')."
            ),
            PropertyList(
                [Property("force_refresh", PropertyType.BOOLEAN, default_value=False)]
            ),
            get_local_playlist,
        ),
    ]

    for tool in tools:
        add_tool(tool)
    logger.info(
        "registered %d music MCP tools (MusicPlayer injected by the container)",
        len(tools),
    )
