import asyncio
import json
import logging
import ssl

import websockets

from src.constants.constants import AudioConfig
from src.logging import get_logger
from src.protocols.protocol import Protocol
from src.utils.config_manager import get_config

# the server may use a self-signed certificate, so certificate verification is skipped
# so a non-standard SSL certificate in production does not break the connection
ssl_context = ssl._create_unverified_context()

logger = get_logger()


class WebsocketProtocol(Protocol):
    def __init__(self):
        super().__init__()
        # get the config manager instance
        self.config = get_config()
        self.websocket = None
        self.connected = False
        self.hello_received = None  # starts as None
        # message-task reference, so it can be cancelled on close
        self._message_task = None

        self.WEBSOCKET_URL = self.config.get_config(
            "SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL"
        )
        access_token = self.config.get_config(
            "SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN"
        )
        device_id = self.config.get_config("SYSTEM_OPTIONS.DEVICE_ID")
        client_id = self.config.get_config("SYSTEM_OPTIONS.CLIENT_ID")

        self.HEADERS = {
            "Authorization": f"Bearer {access_token}",
            "Protocol-Version": "1",
            "Device-Id": device_id,  # device MAC address
            "Client-Id": client_id,
        }

    async def connect(self) -> bool:
        """
        Connect to the WebSocket server.
        """
        if self._is_closing:
            logger.warning("connection is closing; abandoning the new attempt")
            return False

        try:
            # create the Event at connect time, so it belongs to the right event loop
            self.hello_received = asyncio.Event()

            # decide whether to use SSL
            current_ssl_context = None
            if self.WEBSOCKET_URL.startswith("wss://"):
                current_ssl_context = ssl_context

            # open the connection (spelling differs between Python versions)
            try:
                # newer form (Python 3.11+)
                self.websocket = await websockets.connect(
                    uri=self.WEBSOCKET_URL,
                    ssl=current_ssl_context,
                    additional_headers=self.HEADERS,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    open_timeout=5,
                    max_size=10 * 1024 * 1024,
                    compression=None,
                    proxy=None,
                )
            except TypeError:
                # older form (earlier Python versions)
                self.websocket = await websockets.connect(
                    self.WEBSOCKET_URL,
                    ssl=current_ssl_context,
                    extra_headers=self.HEADERS,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    open_timeout=5,
                    max_size=10 * 1024 * 1024,
                    compression=None,
                )

            # start the message loop (keep the task reference so it can be cancelled on close)
            self._message_task = asyncio.create_task(self._message_handler())

            # start connection monitoring
            self._start_connection_monitor()

            # send the client hello
            hello_message = {
                "type": "hello",
                "version": 1,
                "features": {
                    "mcp": True,
                },
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": AudioConfig.INPUT_SAMPLE_RATE,
                    "channels": AudioConfig.CHANNELS,
                    "frame_duration": AudioConfig.FRAME_DURATION,
                },
            }
            await self.send_text(json.dumps(hello_message))

            # wait for the server hello
            try:
                await asyncio.wait_for(self.hello_received.wait(), timeout=10.0)
                self.connected = True
                self._reconnect_attempts = 0  # reset the reconnect counter
                logger.info("Connected to the WebSocket server")

                # notify the connection-state change
                if self._on_connection_state_changed:
                    self._on_connection_state_changed(True, "connected")

                return True
            except asyncio.TimeoutError:
                logger.error("Timed out waiting for the server hello")
                await self._do_cleanup()
                if self._on_network_error:
                    await self._on_network_error("timed out waiting for a response")
                return False

        except Exception as e:
            logger.error(f"WebSocketConnection failed: {e}", exc_info=True)
            await self._do_cleanup()
            if self._on_network_error:
                await self._on_network_error(f"Could not reach the service: {str(e)}")
            return False

    # ============ template method implementations ============

    @property
    def _monitor_interval(self) -> float:
        """WSS Connection monitor poll interval, in seconds."""
        return 5.0

    def _is_connected(self) -> bool:
        """Check whether the WebSocket connection is alive."""
        if not self.websocket:
            return False
        return self.websocket.close_code is None

    async def _do_cleanup(self):
        """WebSocket Release protocol-specific resources.

        Clean up the message task, heartbeat task, WebSocket connection and heartbeat timestamps.
        Does not cancel the connection monitor task (the base _handle_connection_loss does).
        """
        # cancel the message-handling task
        if self._message_task and not self._message_task.done():
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Error while cancelling the message task: {e}")
        self._message_task = None

        # close the WebSocket connection
        if self.websocket and self.websocket.close_code is None:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing the WebSocket connection: {e}", exc_info=True)

        self.websocket = None

    def get_connection_info(self) -> dict:
        """Connection information for the WSS link.

        Returns:
            dict: a dict with connection state, reconnect count and related details
        """
        info = super().get_connection_info()
        info.update(
            {
                "connected": self.connected,
                "websocket_closed": (
                    self.websocket.close_code is not None if self.websocket else True
                ),
                "websocket_url": self.WEBSOCKET_URL,
            }
        )
        return info

    async def _message_handler(self):
        """
        Handle incoming WebSocket messages.
        """
        try:
            async for message in self.websocket:
                if self._is_closing:
                    break

                try:
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            if msg_type == "hello":
                                # handle the server hello
                                await self._handle_server_hello(data)
                            else:
                                if self._on_incoming_json:
                                    self._on_incoming_json(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON message: {message}, error: {e}", exc_info=True)
                    elif isinstance(message, bytes):
                        # binary message, most likely audio
                        if self._on_incoming_audio:
                            self._on_incoming_audio(message)
                except Exception as e:
                    # log the error for one message but keep processing the rest
                    logger.error(f"Error handling message: {e}", exc_info=True)
                    continue

        except asyncio.CancelledError:
            logger.debug("message-handling task cancelled")
            return
        except websockets.ConnectionClosedOK as e:
            if not self._is_closing:
                logger.info(f"WebSocketConnection closed cleanly by the server: {e}")
                await self._handle_connection_loss(
                    f"Server closed the connection: {e.code}", clean=True
                )
        except websockets.ConnectionClosedError as e:
            if not self._is_closing:
                logger.info(f"WebSocketConnection closed with an error: {e}")
                await self._handle_connection_loss(f"Connection error: {e.code} {e.reason}")
        except websockets.InvalidState as e:
            logger.error(f"WebSocketInvalid state: {e}", exc_info=True)
            await self._handle_connection_loss("connection state is bad")
        except ConnectionResetError:
            logger.warning("connection reset")
            await self._handle_connection_loss("connection reset")
        except OSError as e:
            logger.error(f"Network I/O error: {e}", exc_info=True)
            await self._handle_connection_loss("network I/O error")
        except Exception as e:
            logger.error(f"Message loop error: {e}", exc_info=True)
            await self._handle_connection_loss(f"Message handling error: {str(e)}")

    async def send_audio(self, data: bytes):
        """
        Send audio data.
        """
        if not self.is_audio_channel_opened():
            return

        try:
            await self.websocket.send(data)
        except websockets.ConnectionClosedOK as e:
            # the server reclaimed the session cleanly (e.g. after TTS finished); not a network error
            logger.info(f"Connection closed cleanly by the server while sending audio: {e}")
            await self._handle_connection_loss(
                f"Server closed while sending audio: {e.code}", clean=True
            )
        except websockets.ConnectionClosedError as e:
            logger.warning(f"Connection closed unexpectedly while sending audio: {e}")
            await self._handle_connection_loss(f"Send audio failed: {e.code} {e.reason}")
        except Exception as e:
            logger.error(f"Failed to send audio data: {e}", exc_info=True)
            # do not fire the network-error callback here; the connection handler owns it
            await self._handle_connection_loss(f"Send audio error: {str(e)}")

    async def send_text(self, message: str):
        """
        Send a text message.
        """
        if not self.websocket or self._is_closing:
            logger.warning("WebSocketnot connected or closing, cannot send the message")
            return

        try:
            close_code = self.websocket.close_code
        except Exception:
            close_code = None
        if close_code is not None:
            # 1000/1001/1005 treated as a clean close (the server reclaimed the session)
            clean = close_code in (1000, 1001, 1005)
            logger.log(
                logging.INFO if clean else logging.WARNING,
                f"WebSocket already closed (code={close_code}), skipping the text send",
            )
            if self.connected:
                await self._handle_connection_loss(
                    f"Send text failed: connection already closed {close_code}", clean=clean
                )
            return

        try:
            await self.websocket.send(message)
        except websockets.ConnectionClosedOK as e:
            # the server reclaimed the session cleanly; not a network error
            logger.info(f"Connection closed cleanly by the server while sending text: {e}")
            if self.connected and not self._is_closing:
                await self._handle_connection_loss(
                    f"Server closed while sending text: {e.code}", clean=True
                )
        except websockets.ConnectionClosedError as e:
            logger.warning(f"Connection closed unexpectedly while sending text: {e}")
            if self.connected and not self._is_closing:
                await self._handle_connection_loss(
                    f"Send text error: {e.code} {e.reason}"
                )
        except Exception as e:
            logger.error(f"Failed to send text message: {e}", exc_info=True)
            if self.connected and not self._is_closing:
                await self._handle_connection_loss(f"Send text error: {str(e)}")

    def is_audio_channel_opened(self) -> bool:
        """Report whether the audio channel is open.

        a more accurate check, including the WebSocket's own state
        """
        if not self.websocket or not self.connected or self._is_closing:
            return False

        # check the WebSocket's own state
        try:
            return self.websocket.close_code is None
        except Exception:
            return False

    async def open_audio_channel(self) -> bool:
        """Open the WebSocket connection.

        open a new WebSocket connection if there is not one already
        Returns:
            bool: whether the connection succeeded
        """
        if not self.is_audio_channel_opened():
            return await self.connect()
        return True

    async def _handle_server_hello(self, data: dict):
        """
        Handle the server's hello message.
        """
        try:
            # validate the transport
            transport = data.get("transport")
            if not transport or transport != "websocket":
                logger.error(f"Unsupported transport: {transport}")
                return

            # set the hello-received event
            self.hello_received.set()

            # notify that the audio channel opened
            if self._on_audio_channel_opened:
                await self._on_audio_channel_opened()

            logger.info("Server hello handled successfully")

        except Exception as e:
            logger.error(f"Error handling the server hello message: {e}", exc_info=True)
            if self._on_network_error:
                await self._on_network_error(f"Failed to handle the server response: {str(e)}")

    async def close_audio_channel(self):
        """
        Close the audio channel.
        """
        self._is_closing = True

        try:
            self.connected = False

            # cancel the connection monitor task (owned by the base class)
            await self._cancel_monitor_task()

            # protocol-specific cleanup
            await self._do_cleanup()

            if self._on_audio_channel_closed:
                await self._on_audio_channel_closed()

        except Exception as e:
            logger.error(f"Failed to close the audio channel: {e}", exc_info=True)
        finally:
            self._is_closing = False
