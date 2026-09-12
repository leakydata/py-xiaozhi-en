"""The plugin protocol adapters.

They expose the state and session capabilities on ServiceContainer as
PluginContext and PluginCommands, so a plugin depends on the protocols rather than the container type.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.constants.constants import DeviceState, ListeningMode
from src.utils.config_manager import ConfigManager

if TYPE_CHECKING:
    from src.bootstrap.container import ServiceContainer


class PluginContextAdapter:
    """The PluginContext adapter."""

    def __init__(self, container: "ServiceContainer"):
        self._container = container

    def get_device_state(self) -> DeviceState:
        return self._container.state.device_state

    def get_listening_mode(self) -> ListeningMode:
        return self._container.state.listening_mode

    def is_listening(self) -> bool:
        return self._container.state.is_listening()

    def is_speaking(self) -> bool:
        return self._container.state.is_speaking()

    def is_idle(self) -> bool:
        return self._container.state.is_idle()

    def is_audio_channel_opened(self) -> bool:
        return self._container.protocol.is_audio_channel_opened()

    def should_capture_audio(self) -> bool:
        return self._container.state.should_capture_audio()

    def is_keep_listening(self) -> bool:
        return self._container.state.keep_listening

    def get_config(self) -> ConfigManager:
        return self._container.config

    @property
    def event_bus(self):
        """The event bus."""
        return self._container.event_bus


class PluginCommandsAdapter:
    """The PluginCommands adapter: commands land on ConversationSession, the protocol, or the task manager."""

    def __init__(self, container: "ServiceContainer"):
        self._container = container

    async def start_listening(self, mode: ListeningMode) -> None:
        await self._container.session.start_listening(mode)

    async def stop_listening(self) -> None:
        await self._container.session.stop_listening()

    async def abort_speaking(self, reason: str) -> None:
        await self._container.session.abort_speaking(reason)

    async def send_audio(self, data: bytes) -> None:
        await self._container.protocol.send_audio(data)

    async def send_text(self, text: str) -> None:
        await self._container.protocol.send_text(text)

    async def send_wake_word_detected(self, text: str) -> None:
        await self._container.protocol.send_wake_word_detected(text)

    async def send_mcp_message(self, payload: str) -> None:
        await self._container.protocol.send_mcp_message(payload)

    async def connect_protocol(self) -> bool:
        return await self._container.session.connect_protocol()

    def spawn(self, coro: Awaitable[Any], name: str) -> Any:
        return self._container.tasks.spawn(coro, name)

    def schedule_command_nowait(self, fn: Callable, *args, **kwargs) -> None:
        self._container.tasks.schedule_nowait(fn, *args, **kwargs)

    def request_shutdown(self) -> None:
        self._container.tasks.request_shutdown()
