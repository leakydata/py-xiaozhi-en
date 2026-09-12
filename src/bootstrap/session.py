"""Session control: the listen/speak state machine and what gets sent to the protocol.

Kept apart from the UI's SessionActions (button labels and modes): this is only
the application-level session logic - connect, listen, abort, the TTS loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.constants.constants import DeviceState, ListeningMode
from src.core.event_bus import Events
from src.logging import get_logger

if TYPE_CHECKING:
    from src.core.event_bus import EventBus
    from src.core.protocol_manager import ProtocolManager
    from src.core.state_manager import StateManager
    from src.plugins.manager import PluginManager

logger = get_logger()


class ConversationSession:
    """The application-level session controller."""

    def __init__(
        self,
        state: "StateManager",
        protocol: "ProtocolManager",
        plugins: "PluginManager",
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self.state = state
        self.protocol = protocol
        self.plugins = plugins
        self._event_bus = event_bus
        self._aborted = False
        # for an MCP tool-config reconnect and the like: stay IDLE once the channel opens rather than listening automatically
        self._keep_idle_on_channel_open = False

    # -------------------------
    # event subscriptions
    # -------------------------
    def bind_events(self, event_bus: "EventBus") -> None:
        """Subscribe to the protocol and state events (safe to call again; the last call wins)."""
        self._event_bus = event_bus
        event_bus.on(Events.AUDIO_CHANNEL_OPENED, self._on_audio_channel_opened)
        event_bus.on(Events.AUDIO_CHANNEL_CLOSED, self._on_audio_channel_closed)
        event_bus.on(Events.INCOMING_JSON, self._on_incoming_json)
        # note: INCOMING_AUDIO takes the direct path, no longer the EventBus
        event_bus.on(Events.NETWORK_ERROR, self._on_network_error)
        event_bus.on(Events.DEVICE_STATE_CHANGED, self._on_device_state_changed)
        event_bus.on(
            Events.PROTOCOL_RECONNECT_REQUEST, self._on_protocol_reconnect_request
        )

    # -------------------------
    # event handlers
    # -------------------------
    async def _on_audio_channel_opened(self, _=None) -> None:
        if self._keep_idle_on_channel_open:
            self._keep_idle_on_channel_open = False
            self.state.set_keep_listening(False)
            await self.state.set_device_state(DeviceState.IDLE)
            logger.info(
                "protocol channel opened (a config reconnect): staying idle rather than listening"
            )
            return
        await self.state.set_device_state(DeviceState.LISTENING)

    async def _on_audio_channel_closed(self, _=None) -> None:
        await self.state.set_device_state(DeviceState.IDLE)

    async def _on_network_error(self, error_message: str = None) -> None:
        """On a network error: stop listening continuously and reset the device state to IDLE."""
        self.state.set_keep_listening(False)
        try:
            if not self.state.is_idle():
                await self.state.set_device_state(DeviceState.IDLE)
        except Exception as e:
            logger.error(
                f"failed to reset the device state after the network error: {e}",
                exc_info=True,
            )

    async def _on_device_state_changed(self, data: dict) -> None:
        new_state = data.get("new_state")
        if new_state:
            await self.plugins.notify_device_state_changed(new_state)
            if new_state == DeviceState.LISTENING:
                self._aborted = False

    async def _on_incoming_json(self, json_data: dict) -> None:
        try:
            msg_type = json_data.get("type") if isinstance(json_data, dict) else None
            logger.info(f"JSON message received: type={msg_type}")

            if msg_type == "tts":
                state = json_data.get("state")
                if state == "start":
                    await self._handle_tts_start()
                elif state == "stop":
                    await self._handle_tts_stop()

            await self.plugins.notify_incoming_json(json_data)

        except Exception as e:
            logger.error(f"failed to handle the JSON message: {e}", exc_info=True)

    async def _handle_tts_start(self) -> None:
        if (
            self.state.keep_listening
            and self.state.listening_mode == ListeningMode.REALTIME
        ):
            await self.state.set_device_state(DeviceState.LISTENING)
        else:
            await self.state.set_device_state(DeviceState.SPEAKING)

    async def _handle_tts_stop(self) -> None:
        # when listening is meant to continue, send the listen first, then clear the queue and change state
        if not self.state.keep_listening:
            await self.state.set_device_state(DeviceState.IDLE)
            return

        # with the channel closed there is nothing to listen on (realtime included): setting LISTENING anyway
        # would show "listening" over a dead connection, with the mic light on and the audio going nowhere.
        if not self.protocol.is_audio_channel_opened():
            logger.warning(
                "TTS finished but the protocol channel is closed, not listening again"
            )
            await self.state.set_device_state(DeviceState.IDLE)
            return

        # realtime is usually still listening, so there is no need to send it twice
        if self.state.listening_mode != ListeningMode.REALTIME:
            try:
                await self.protocol.send_start_listening(self.state.listening_mode)
            except Exception as e:
                logger.warning(
                    f"failed to listen again after TTS: {e}",
                    exc_info=True,
                )
                # if listening did not actually start, do not claim that it did
                await self.state.set_device_state(DeviceState.IDLE)
                return

        try:
            audio_plugin = self.plugins.get_plugin("audio")
            if audio_plugin and audio_plugin.codec:
                await audio_plugin.codec.clear_audio_queue()
        except Exception as e:
            logger.warning(f"failed to clear the audio queue: {e}", exc_info=True)

        await self.state.set_device_state(DeviceState.LISTENING)

    # -------------------------
    # actions
    # -------------------------
    async def connect_protocol(self) -> bool:
        if self.protocol.is_audio_channel_opened():
            return True

        opened = await self.protocol.connect()
        if opened:
            await self.plugins.notify_protocol_connected(self.protocol.protocol)
        return opened

    async def _on_protocol_reconnect_request(self, _=None) -> None:
        """The MCP tool list changed when the settings were saved: if connected, drop and reconnect so the server lists them again.

        Only the protocol and tool view is refreshed - the listening session is not resumed, so saving settings does not leave it listening.
        """
        try:
            if not self.protocol.is_audio_channel_opened():
                logger.info(
                    "MCP tool configuration updated (not connected now; it takes effect on the next connection)"
                )
                return
            logger.info("MCP tool configuration updated, reconnecting the protocol...")
            # interrupt any listen/speak in progress, so keep_listening does not carry over the reconnect
            self.state.set_keep_listening(False)
            self._aborted = False
            self._keep_idle_on_channel_open = True
            try:
                await self.protocol.disconnect()
                ok = await self.connect_protocol()
            except Exception:
                self._keep_idle_on_channel_open = False
                raise
            if ok:
                # belt and braces: if the OPENED callbacks arrive out of order, still fall back to idle
                if not self.state.is_idle():
                    await self.state.set_device_state(DeviceState.IDLE)
                logger.info(
                    "protocol reconnected (the new tools/list takes effect at the handshake; staying idle)"
                )
            else:
                self._keep_idle_on_channel_open = False
                logger.warning(
                    "the protocol failed to reconnect, please reconnect manually"
                )
        except Exception as e:
            self._keep_idle_on_channel_open = False
            logger.error(f"protocol reconnect failed: {e}", exc_info=True)

    async def start_listening(self, mode: ListeningMode) -> None:
        ok = await self.connect_protocol()
        if not ok:
            return

        self.state.set_listening_mode(mode)
        self.state.set_keep_listening(mode != ListeningMode.MANUAL)
        await self.protocol.send_start_listening(mode)
        await self.state.set_device_state(DeviceState.LISTENING)

    async def stop_listening(self) -> None:
        self.state.set_keep_listening(False)
        await self.protocol.send_stop_listening()
        await self.state.set_device_state(DeviceState.IDLE)

    async def start_listening_manual(self) -> None:
        ok = await self.connect_protocol()
        if not ok:
            return

        self.state.set_keep_listening(False)

        if self.state.is_speaking():
            logger.info("sending an interrupt while speaking")
            await self.protocol.send_abort_speaking(None)
            await self.state.set_device_state(DeviceState.IDLE)

        await self.protocol.send_start_listening(ListeningMode.MANUAL)
        await self.state.set_device_state(DeviceState.LISTENING)

    async def stop_listening_manual(self) -> None:
        await self.protocol.send_stop_listening()
        await self.state.set_device_state(DeviceState.IDLE)

    async def start_auto_conversation(self) -> None:
        ok = await self.connect_protocol()
        if not ok:
            return

        mode = (
            ListeningMode.REALTIME
            if self.state.aec_enabled
            else ListeningMode.AUTO_STOP
        )
        self.state.set_listening_mode(mode)
        self.state.set_keep_listening(True)

        await self.protocol.send_start_listening(mode)
        await self.state.set_device_state(DeviceState.LISTENING)

    async def abort_speaking(self, reason: str) -> None:
        # with auto-conversation still listening, an interrupt goes back to listening rather than stopping at idle
        if self._aborted:
            logger.debug(f"already aborted, ignoring the repeat request: {reason}")
            return

        logger.info(f"aborting speech output: {reason}")
        self._aborted = True
        self.state.set_aborted(True)
        try:
            if self.protocol.is_audio_channel_opened():
                await self.protocol.send_abort_speaking(reason)
        except Exception as e:
            logger.warning(f"failed to send the abort: {e}", exc_info=True)

        if self.state.keep_listening:
            if self.state.listening_mode != ListeningMode.REALTIME:
                if self.protocol.is_audio_channel_opened():
                    try:
                        await self.protocol.send_start_listening(
                            self.state.listening_mode
                        )
                    except Exception as e:
                        logger.warning(
                            f"failed to listen again after the interrupt: {e}",
                            exc_info=True,
                        )
            await self.state.set_device_state(DeviceState.LISTENING)
            self._aborted = False
            self.state.set_aborted(False)
            logger.debug("continuous listening resumed after the interrupt")
        else:
            await self.state.set_device_state(DeviceState.IDLE)
