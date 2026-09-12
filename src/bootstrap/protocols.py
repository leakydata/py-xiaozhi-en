"""The interface protocols.

The contracts between the plugins, the windows and the core services, keeping them loosely coupled.
"""

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

if TYPE_CHECKING:
    from src.constants.constants import DeviceState, ListeningMode


class PluginContext(Protocol):
    """The read-only context a plugin can see.

    A plugin reads the application state through this, but cannot change it directly.
    """

    def get_device_state(self) -> "DeviceState":
        """
        The current device state.
        """
        ...

    def get_listening_mode(self) -> "ListeningMode":
        """
        The current listening mode.
        """
        ...

    def is_listening(self) -> bool:
        """
        Whether it is listening.
        """
        ...

    def is_speaking(self) -> bool:
        """
        Whether it is speaking.
        """
        ...

    def is_idle(self) -> bool:
        """
        Whether it is idle.
        """
        ...

    def is_audio_channel_opened(self) -> bool:
        """
        Whether the audio channel is open.
        """
        ...

    def should_capture_audio(self) -> bool:
        """
        Whether audio should be captured.
        """
        ...

    def is_keep_listening(self) -> bool:
        """
        Whether it keeps listening continuously.
        """
        ...

    def get_config(self) -> Any:
        """
        The configuration manager.
        """
        ...


class PluginCommands(Protocol):
    """The commands a plugin can issue.

    A plugin acts through this; the core services provide the implementation.
    """

    async def start_listening(self, mode: "ListeningMode") -> None:
        """
        Start listening.
        """
        ...

    async def stop_listening(self) -> None:
        """
        Stop listening.
        """
        ...

    async def abort_speaking(self, reason: str) -> None:
        """
        Abort the speech output.
        """
        ...

    async def send_audio(self, data: bytes) -> None:
        """
        Send audio data.
        """
        ...

    async def send_text(self, text: str) -> None:
        """
        Send a text message.
        """
        ...

    async def send_wake_word_detected(self, text: str) -> None:
        """
        Send detected text (a wake word, or what the user typed).
        """
        ...

    async def send_mcp_message(self, payload: str) -> None:
        """
        Send an MCP message (it is wrapped for you).
        """
        ...

    async def connect_protocol(self) -> bool:
        """
        Open the protocol channel.
        """
        ...

    def spawn(self, coro: Awaitable[Any], name: str) -> Any:
        """
        Create an async task.
        """
        ...

    def schedule_command_nowait(self, fn: Callable, *args, **kwargs) -> None:
        """
        Schedule a command (non-blocking).
        """
        ...

    def request_shutdown(self) -> None:
        """
        Ask the application to shut down.
        """
        ...


class EventHandler(Protocol):
    """
    The event handler protocol.
    """

    async def __call__(self, data: Any = None) -> None:
        """
        Handle an event.
        """
        ...


class EventBusProtocol(Protocol):
    """The event bus protocol.

    For decoupled communication between components.
    """

    def on(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        """
        Register an event handler.
        """
        ...

    def off(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        """
        Remove an event handler.
        """
        ...

    async def emit(self, event: str, data: Any = None) -> None:
        """
        Emit an event.
        """
        ...
