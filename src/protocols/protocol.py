import asyncio
import json

from src.constants.constants import AbortReason, ListeningMode
from src.logging import get_logger

logger = get_logger()


class Protocol:
    def __init__(self):
        self.session_id = ""
        # callbacks start as None
        self._on_incoming_json = None
        self._on_incoming_audio = None
        self._on_audio_channel_opened = None
        self._on_audio_channel_closed = None
        self._on_network_error = None
        # connection-state-change callback
        self._on_connection_state_changed = None
        self._on_reconnecting = None

        # connection state and auto-reconnect (shared; hoisted from subclasses)
        self._is_closing = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5  # 5 attempts by default
        self._auto_reconnect_enabled = False  # disabled by default
        self._connection_monitor_task = None

    def on_incoming_json(self, callback):
        """
        Set the callback for incoming JSON messages.
        """
        self._on_incoming_json = callback

    def on_incoming_audio(self, callback):
        """
        Set the callback for incoming audio data.
        """
        self._on_incoming_audio = callback

    def on_audio_channel_opened(self, callback):
        """
        Set the audio-channel-opened callback.
        """
        self._on_audio_channel_opened = callback

    def on_audio_channel_closed(self, callback):
        """
        Set the audio-channel-closed callback.
        """
        self._on_audio_channel_closed = callback

    def on_network_error(self, callback):
        """
        Set the network-error callback.
        """
        self._on_network_error = callback

    def on_connection_state_changed(self, callback):
        """Set the connection-state-change callback.

        Args:
            callback: callback taking (connected: bool, reason: str)
        """
        self._on_connection_state_changed = callback

    def on_reconnecting(self, callback):
        """Set the reconnect-attempt callback.

        Args:
            callback: callback taking (attempt: int, max_attempts: int)
        """
        self._on_reconnecting = callback

    async def send_text(self, message):
        """
        Abstract: send a text message. Implemented by subclasses.
        """
        raise NotImplementedError("send_textmust be implemented by a subclass")

    async def send_audio(self, data: bytes):
        """
        Abstract: send audio data. Implemented by subclasses.
        """
        raise NotImplementedError("send_audiomust be implemented by a subclass")

    def is_audio_channel_opened(self) -> bool:
        """
        Abstract: report whether the audio channel is open. Implemented by subclasses.
        """
        raise NotImplementedError("is_audio_channel_openedmust be implemented by a subclass")

    async def open_audio_channel(self) -> bool:
        """
        Abstract: open the audio channel. Implemented by subclasses.
        """
        raise NotImplementedError("open_audio_channelmust be implemented by a subclass")

    async def close_audio_channel(self):
        """
        Abstract: close the audio channel. Implemented by subclasses.
        """
        raise NotImplementedError("close_audio_channelmust be implemented by a subclass")

    async def send_abort_speaking(self, reason):
        """
        Send an abort-speaking message.
        """
        message = {"session_id": self.session_id, "type": "abort"}
        if reason == AbortReason.WAKE_WORD_DETECTED:
            message["reason"] = "wake_word_detected"
        await self.send_text(json.dumps(message))

    async def send_wake_word_detected(self, wake_word):
        """
        Send a wake-word-detected message.
        """
        message = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "detect",
            "text": wake_word,
        }
        await self.send_text(json.dumps(message))

    async def send_start_listening(self, mode):
        """
        Send a start-listening message.
        """
        mode_map = {
            ListeningMode.REALTIME: "realtime",
            ListeningMode.AUTO_STOP: "auto",
            ListeningMode.MANUAL: "manual",
        }
        message = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "start",
            "mode": mode_map[mode],
        }
        await self.send_text(json.dumps(message))

    async def send_stop_listening(self):
        """
        Send a stop-listening message.
        """
        message = {"session_id": self.session_id, "type": "listen", "state": "stop"}
        await self.send_text(json.dumps(message))

    async def send_iot_descriptors(self, descriptors):
        """
        Send IoT device descriptors.
        """
        try:
            # parse the descriptor data
            if isinstance(descriptors, str):
                descriptors_data = json.loads(descriptors)
            else:
                descriptors_data = descriptors

            # check whether it is an array
            if not isinstance(descriptors_data, list):
                logger.error("IoT descriptors should be an array")
                return

            # send a separate message for each descriptor
            for i, descriptor in enumerate(descriptors_data):
                if descriptor is None:
                    logger.error(f"Failed to get IoT descriptor at index {i}")
                    continue

                message = {
                    "session_id": self.session_id,
                    "type": "iot",
                    "update": True,
                    "descriptors": [descriptor],
                }

                try:
                    await self.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(
                        f"Failed to send JSON message for IoT descriptor "
                        f"at index {i}: {e}"
                    )
                    continue

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse IoT descriptors: {e}", exc_info=True)
            return

    async def send_iot_states(self, states):
        """
        Send IoT device states.
        """
        if isinstance(states, str):
            states_data = json.loads(states)
        else:
            states_data = states

        message = {
            "session_id": self.session_id,
            "type": "iot",
            "update": True,
            "states": states_data,
        }
        await self.send_text(json.dumps(message))

    async def send_mcp_message(self, payload):
        """
        Send an MCP message.
        """
        if isinstance(payload, str):
            payload_data = json.loads(payload)
        else:
            payload_data = payload

        message = {
            "session_id": self.session_id,
            "type": "mcp",
            "payload": payload_data,
        }

        await self.send_text(json.dumps(message))

    # ====== connection health check (template method, subclasses implement) ======

    def _is_connected(self) -> bool:
        """Check whether the connection is alive.

        Subclasses must implement this and report whether the link is healthy.

        Returns:
            bool: True if the connection is alive, otherwise False
        """
        raise NotImplementedError("_is_connectedmust be implemented by a subclass")

    # ============ protocol-specific cleanup (template method, subclasses implement) ====

    async def _do_cleanup(self):
        """Release protocol-specific resources (not shared state or the monitor task).

        A subclass implementing this should:
        - close the protocol-specific connection (socket / websocket / mqtt client)
        - cancel protocol-specific background tasks (heartbeat, message handling)
        - reset protocol-specific timestamps and state

        Do NOT do the following in this method:
        - set self.connected = False (the base _handle_connection_loss does it)
        - cancel self._connection_monitor_task (the base _handle_connection_loss does it)
        """
        raise NotImplementedError("_do_cleanupmust be implemented by a subclass")

    # ====== connection monitoring (shared; subclasses may override _monitor_interval) ======

    @property
    def _monitor_interval(self) -> float:
        """Monitor poll interval in seconds; subclasses may override."""
        return 5.0

    def _start_connection_monitor(self):
        """Start the background connection-health monitor."""
        if (
            self._connection_monitor_task is None
            or self._connection_monitor_task.done()
        ):
            self._connection_monitor_task = asyncio.create_task(
                self._connection_monitor()
            )

    async def _connection_monitor(self):
        """Coroutine that watches connection health.

        It polls self._is_connected() in a loop,
        and calls self._handle_connection_loss() when it finds the link is down.
        """
        try:
            while not self._is_closing:
                await asyncio.sleep(self._monitor_interval)

                if not self._is_connected():
                    logger.warning("detected that the connection dropped")
                    await self._handle_connection_loss("connection check failed")
                    break

        except asyncio.CancelledError:
            logger.debug("connection monitor task cancelled")
        except Exception as e:
            logger.error(f"connection monitor error: {e}", exc_info=True)

    # ============ automatic reconnect (shared) ============

    def enable_auto_reconnect(self, enabled: bool = True, max_attempts: int = 5):
        """Enable or disable automatic reconnection.

        Args:
            enabled: whether auto-reconnect is enabled
            max_attempts: maximum reconnect attempts
        """
        self._auto_reconnect_enabled = enabled
        if enabled:
            self._max_reconnect_attempts = max_attempts
            logger.info(f"Auto-reconnect enabled, max attempts: {max_attempts}")
        else:
            self._max_reconnect_attempts = 0
            logger.info("auto-reconnect disabled")

    async def _handle_connection_loss(self, reason: str, *, clean: bool = False):
        """Handle a lost connection (shared logic).

        Flow:
        1. update the connection state
        2. cancel the connection monitor task
        3. call the subclass _do_cleanup() to release protocol-specific resources
        4. notify observers (state change, audio channel closed)
        5. decide from config whether to reconnect automatically

        Args:
            clean: Clean server close (e.g. the session ended). Only the channel is reclaimed,
                   does not trigger auto-reconnect and does not report a network error.
        """
        if clean:
            logger.info(f"Connection closed cleanly by the server: {reason}")
        else:
            logger.warning(f"Connection lost: {reason}")

        was_connected = self.connected
        self.connected = False

        # cancel the connection monitor task
        await self._cancel_monitor_task()

        # notify the connection-state change
        if self._on_connection_state_changed and was_connected:
            try:
                self._on_connection_state_changed(False, reason)
            except Exception as e:
                logger.error(f"connection-state-change callback failed: {e}", exc_info=True)

        # protocol-specific cleanup in the subclass
        await self._do_cleanup()

        # notify that the audio channel closed
        if self._on_audio_channel_closed:
            try:
                await self._on_audio_channel_closed()
            except Exception as e:
                logger.error(f"audio-channel-closed callback failed: {e}", exc_info=True)

        # Clean server close: the session ending is not a failure, so no reconnect and no error,
        # re-open the audio channel on the next interaction as needed
        if clean:
            return

        # decide from config whether to attempt a reconnect
        if (
            not self._is_closing
            and self._auto_reconnect_enabled
            and self._reconnect_attempts < self._max_reconnect_attempts
        ):
            await self._attempt_reconnect(reason)
        else:
            if self._on_network_error:
                if (
                    self._auto_reconnect_enabled
                    and self._reconnect_attempts >= self._max_reconnect_attempts
                ):
                    await self._on_network_error(f"Connection lost and reconnect failed: {reason}")
                else:
                    await self._on_network_error(f"Connection lost: {reason}")

    async def _attempt_reconnect(self, original_reason: str):
        """Attempt an automatic reconnect (shared logic).

        Exponential backoff, calling the subclass connect() to do the real work.
        """
        self._reconnect_attempts += 1

        # notify that a reconnect is starting
        if self._on_reconnecting:
            try:
                self._on_reconnecting(
                    self._reconnect_attempts, self._max_reconnect_attempts
                )
            except Exception as e:
                logger.error(f"reconnect callback failed: {e}", exc_info=True)

        logger.info(
            f"Attempting auto-reconnect ({self._reconnect_attempts}/{self._max_reconnect_attempts})"
        )

        # exponential backoff, capped at 30 seconds
        await asyncio.sleep(min(self._reconnect_attempts * 2, 30))

        try:
            success = await self.connect()
            if success:
                logger.info("Auto-reconnect succeeded")
                if self._on_connection_state_changed:
                    self._on_connection_state_changed(True, "reconnected")
            else:
                logger.warning(
                    f"Auto-reconnect failed ({self._reconnect_attempts}/{self._max_reconnect_attempts})"
                )
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    if self._on_network_error:
                        await self._on_network_error(
                            f"Reconnect failed, maximum attempts reached: {original_reason}"
                        )
        except Exception as e:
            logger.error(f"error while reconnecting: {e}", exc_info=True)
            if self._reconnect_attempts >= self._max_reconnect_attempts:
                if self._on_network_error:
                    await self._on_network_error(f"reconnect error: {str(e)}")

    async def _cancel_monitor_task(self):
        """Cancel the connection monitor task and wait for it to finish."""
        if self._connection_monitor_task and not self._connection_monitor_task.done():
            self._connection_monitor_task.cancel()
            try:
                await self._connection_monitor_task
            except asyncio.CancelledError:
                pass

    def get_connection_info(self) -> dict:
        """Connection information (base implementation; subclasses may extend).

        Returns:
            dict: a dict with connection state, reconnect count and related details
        """
        return {
            "is_closing": self._is_closing,
            "auto_reconnect_enabled": self._auto_reconnect_enabled,
            "reconnect_attempts": self._reconnect_attempts,
            "max_reconnect_attempts": self._max_reconnect_attempts,
        }
