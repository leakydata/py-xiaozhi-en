"""The interface every front end implements - gui, cli, tui and gpio alike."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ViewPort(Protocol):
    """The methods used to drive a front end."""

    async def start(self, mode: str = "cli") -> None:
        """Start."""
        ...

    async def close(self) -> None:
        """Shut down."""
        ...

    def set_status(self, status: str, connected: bool = True) -> None:
        """The status line."""
        ...

    def set_emotion(self, emotion: str) -> None:
        """The emotion name; each front end resolves it to its own asset."""
        ...

    def set_chat_text(self, text: str) -> None:
        """What was said, either spoken or heard."""
        ...

    def set_music_line(self, text: str) -> None:
        """The music state, or the current line of lyrics."""
        ...

    def set_button_text(self, text: str) -> None:
        """The main button's label; a front end without buttons can leave this empty."""
        ...

    def set_auto_mode(self, auto_mode: bool) -> None:
        """Refresh the auto/manual indicator (the real state lives in the Session)."""
        ...

    def is_auto_mode(self) -> bool:
        """The mode as the front end has it (the GPIO button handling reads this, for one)."""
        ...
