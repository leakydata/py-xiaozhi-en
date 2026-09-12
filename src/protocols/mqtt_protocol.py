"""MQTT + UDP audio protocol.

MQTT carries the control JSON; UDP carries the encrypted audio frames (see mqtt_udp / mqtt_crypto).
"""

from __future__ import annotations

import asyncio
import json
import time

import paho.mqtt.client as mqtt

from src.constants.constants import AudioConfig
from src.logging import get_logger
from src.protocols.mqtt_udp import MqttUdpChannel
from src.protocols.protocol import Protocol
from src.utils.config_manager import get_config

logger = get_logger()


def parse_mqtt_endpoint(endpoint: str) -> tuple[str, int]:
    """Parse an endpoint: hostname, or hostname:port; the default port is 8883."""
    if not endpoint:
        raise ValueError("endpoint must not be empty")

    if ":" in endpoint:
        host, port_str = endpoint.rsplit(":", 1)
        try:
            port = int(port_str)
            if port < 1 or port > 65535:
                raise ValueError(f"the port must be between 1 and 65535: {port}")
        except ValueError as e:
            raise ValueError(f"invalid port: {port_str}") from e
    else:
        host = endpoint
        port = 8883

    return host, port


class MqttProtocol(Protocol):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.config = get_config()
        self.mqtt_client = None
        self.connected = False
        # Futures scheduled from the thread side, so nothing is a fire-and-forget create_task
        self._pending_futures: set = set()

        # MQTT connection activity monitoring
        self._last_activity_time = None
        self._keep_alive_interval = 60
        self._connection_timeout = 120

        # MQTT configuration (injected by OTA)
        self.endpoint = None
        self.client_id = None
        self.username = None
        self.password = None
        self.publish_topic = None
        self.subscribe_topic = None

        # UDP audio channel
        self._udp = MqttUdpChannel(loop)
        self._udp.set_audio_handler(self._on_udp_audio)

        self.server_hello_event = asyncio.Event()

    # ---- legacy attributes kept for compatibility (diagnostics / tests) ----
    @property
    def udp_socket(self):
        return self._udp.socket

    @property
    def udp_running(self) -> bool:
        return self._udp.running

    @property
    def udp_server(self) -> str:
        return self._udp.server

    @property
    def udp_port(self) -> int:
        return self._udp.port

    def _on_udp_audio(self, audio_data: bytes) -> None:
        """On the event loop thread: hand the UDP frame to the protocol's on_incoming_audio."""
        cb = self._on_incoming_audio
        if not cb:
            return
        if asyncio.iscoroutinefunction(cb):
            self.loop.create_task(cb(audio_data))
        else:
            cb(audio_data)

    def _schedule_coro(self, coro, name: str = "mqtt") -> None:
        """Schedule a coroutine onto the event loop from any thread, logging any exception."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        def _track_future(fut) -> None:
            self._pending_futures.add(fut)

            def _done(f) -> None:
                self._pending_futures.discard(f)
                try:
                    exc = f.exception()
                except (asyncio.CancelledError, Exception):
                    return
                if exc:
                    logger.error(
                        f"MQTT scheduled task {name} raised: {exc}", exc_info=exc
                    )

            fut.add_done_callback(_done)

        if running_loop is self.loop:
            try:
                task = self.loop.create_task(coro, name=f"mqtt:{name}")
                _track_future(task)
            except Exception as e:
                logger.error(
                    f"MQTT failed to create the task {name}: {e}", exc_info=True
                )
                if asyncio.iscoroutine(coro):
                    coro.close()
            return

        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
            _track_future(fut)
        except Exception as e:
            logger.error(
                f"MQTT cross-thread scheduling failed for {name}: {e}", exc_info=True
            )
            if asyncio.iscoroutine(coro):
                coro.close()

    async def connect(self):
        """Connect to the MQTT server and open the UDP audio channel."""
        if self._is_closing:
            logger.warning(
                "the connection is shutting down, abandoning the new connection attempt"
            )
            return False

        self.server_hello_event = asyncio.Event()

        try:
            mqtt_config = self.config.get_config("SYSTEM_OPTIONS.NETWORK.MQTT_INFO")
            logger.debug(f"MQTT configuration: {mqtt_config}")
            self.endpoint = mqtt_config.get("endpoint")
            self.client_id = mqtt_config.get("client_id")
            self.username = mqtt_config.get("username")
            self.password = mqtt_config.get("password")
            self.publish_topic = mqtt_config.get("publish_topic")
            self.subscribe_topic = mqtt_config.get("subscribe_topic")
            logger.info(
                f"got the MQTT configuration from the OTA server: {self.endpoint}"
            )
        except Exception as e:
            logger.warning(
                f"failed to get the MQTT configuration from the OTA server: {e}",
                exc_info=True,
            )

        if (
            not self.endpoint
            or not self.username
            or not self.password
            or not self.publish_topic
        ):
            logger.error("the MQTT configuration is incomplete")
            if self._on_network_error:
                await self._on_network_error("the MQTT configuration is incomplete")
            return False

        if self.subscribe_topic == "null":
            self.subscribe_topic = None
            logger.info("the subscribe topic is null, nothing will be subscribed to")

        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.warning(
                    f"error while disconnecting the MQTT client: {e}", exc_info=True
                )

        try:
            host, port = parse_mqtt_endpoint(self.endpoint)
            use_tls = port == 8883
            logger.info(
                f"parsed endpoint: {self.endpoint} -> host: {host}, port: {port}, "
                f"TLS: {use_tls}"
            )
        except ValueError as e:
            logger.error(f"failed to parse the endpoint: {e}", exc_info=True)
            if self._on_network_error:
                await self._on_network_error(f"failed to parse the endpoint: {e}")
            return False

        self.mqtt_client = mqtt.Client(client_id=self.client_id)
        self.mqtt_client.username_pw_set(self.username, self.password)

        if use_tls:
            try:
                self.mqtt_client.tls_set(
                    ca_certs=None,
                    certfile=None,
                    keyfile=None,
                    cert_reqs=mqtt.ssl.CERT_REQUIRED,
                    tls_version=mqtt.ssl.PROTOCOL_TLS,
                )
                logger.info("TLS-encrypted connection configured")
            except Exception as e:
                logger.error(
                    f"TLS configuration failed, cannot connect securely to the MQTT server: {e}",
                    exc_info=True,
                )
                if self._on_network_error:
                    await self._on_network_error(f"TLS configuration failed: {str(e)}")
                return False
        else:
            logger.info("using a plain (non-TLS) connection")

        connect_future = self.loop.create_future()

        def on_connect_callback(client, userdata, flags, rc, properties=None):
            if rc == 0:
                logger.info("connected to the MQTT server")
                self._last_activity_time = time.time()
                self.loop.call_soon_threadsafe(lambda: connect_future.set_result(True))
            else:
                logger.error(f"failed to connect to the MQTT server, return code: {rc}")
                self.loop.call_soon_threadsafe(
                    lambda: connect_future.set_exception(
                        Exception(
                            f"failed to connect to the MQTT server, return code: {rc}"
                        )
                    )
                )

        def on_message_callback(client, userdata, msg):
            try:
                self._last_activity_time = time.time()
                payload = msg.payload.decode("utf-8")
                self._handle_mqtt_message(payload)
            except Exception as e:
                logger.error(
                    f"error while handling an MQTT message: {e}", exc_info=True
                )

        def on_disconnect_callback(client, userdata, rc):
            try:
                if rc == 0:
                    logger.info("MQTT disconnected normally")
                else:
                    logger.warning(f"MQTT disconnected unexpectedly, return code: {rc}")

                was_connected = self.connected
                self.connected = False

                if self._on_connection_state_changed and was_connected:
                    reason = (
                        "normal disconnect"
                        if rc == 0
                        else f"unexpected disconnect (rc={rc})"
                    )
                    self.loop.call_soon_threadsafe(
                        lambda: self._on_connection_state_changed(False, reason)
                    )

                self._udp.stop()

                if (
                    rc != 0
                    and not self._is_closing
                    and self._auto_reconnect_enabled
                    and self._reconnect_attempts < self._max_reconnect_attempts
                ):
                    self._schedule_coro(
                        self._attempt_reconnect(f"MQTT disconnect (rc={rc})"),
                        name=f"reconnect:rc={rc}",
                    )
                else:
                    if self._on_audio_channel_closed:
                        self._schedule_coro(
                            self._on_audio_channel_closed(),
                            name="audio_channel_closed",
                        )
                    if rc != 0 and self._on_network_error:
                        error_msg = f"MQTT connection lost: {rc}"
                        if (
                            self._auto_reconnect_enabled
                            and self._reconnect_attempts >= self._max_reconnect_attempts
                        ):
                            error_msg += " (reconnect failed)"
                        self._schedule_coro(
                            self._on_network_error(error_msg),
                            name="network_error",
                        )
            except Exception as e:
                logger.error(
                    f"failed to handle the MQTT disconnect: {e}", exc_info=True
                )

        def on_publish_callback(client, userdata, mid):
            self._last_activity_time = time.time()

        def on_subscribe_callback(client, userdata, mid, granted_qos):
            logger.info(f"subscribed to topic: {self.subscribe_topic}")
            self._last_activity_time = time.time()

        self.mqtt_client.on_connect = on_connect_callback
        self.mqtt_client.on_message = on_message_callback
        self.mqtt_client.on_disconnect = on_disconnect_callback
        self.mqtt_client.on_publish = on_publish_callback
        self.mqtt_client.on_subscribe = on_subscribe_callback

        try:
            logger.info(f"connecting to the MQTT server: {host}:{port}")
            self.mqtt_client.connect_async(
                host, port, keepalive=self._keep_alive_interval
            )
            self.mqtt_client.loop_start()

            await asyncio.wait_for(connect_future, timeout=10.0)

            if self.subscribe_topic:
                self.mqtt_client.subscribe(self.subscribe_topic, qos=1)

            self._start_connection_monitor()

            hello_message = {
                "type": "hello",
                "version": 3,
                "features": {"mcp": True},
                "transport": "udp",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": AudioConfig.INPUT_SAMPLE_RATE,
                    "channels": AudioConfig.CHANNELS,
                    "frame_duration": AudioConfig.FRAME_DURATION,
                },
            }

            if not await self.send_text(json.dumps(hello_message)):
                logger.error("failed to send the hello message")
                return False

            try:
                await asyncio.wait_for(self.server_hello_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error("timed out waiting for the server hello message")
                if self._on_network_error:
                    await self._on_network_error("timed out waiting for a response")
                return False

            try:
                self._udp.start()
                self.connected = True
                self._reconnect_attempts = 0

                if self._on_connection_state_changed:
                    self._on_connection_state_changed(True, "connected")

                return True
            except Exception as e:
                logger.error(f"failed to create the UDP socket: {e}", exc_info=True)
                if self._on_network_error:
                    await self._on_network_error(
                        f"failed to open the UDP connection: {e}"
                    )
                return False

        except Exception as e:
            logger.error(f"failed to connect to the MQTT server: {e}", exc_info=True)
            if self._on_network_error:
                await self._on_network_error(
                    f"failed to connect to the MQTT server: {e}"
                )
            return False

    def _handle_mqtt_message(self, payload):
        """Handle an MQTT JSON message (thread callback)."""
        try:
            data = json.loads(payload)
            msg_type = data.get("type")

            if msg_type == "goodbye":
                session_id = data.get("session_id")
                if not session_id or session_id == self.session_id:
                    asyncio.run_coroutine_threadsafe(self._handle_goodbye(), self.loop)
                return

            if msg_type == "hello":
                logger.debug(
                    f"the service link returned the initial configuration: {data}"
                )
                transport = data.get("transport")
                if transport != "udp":
                    logger.error(f"unsupported transport: {transport}")
                    return

                self.session_id = data.get("session_id", "")

                udp = data.get("udp")
                if not udp:
                    logger.error("the UDP configuration is missing")
                    return

                self._udp.configure(
                    server=udp.get("server"),
                    port=udp.get("port"),
                    aes_key=udp.get("key"),
                    aes_nonce=udp.get("nonce"),
                )

                logger.info(
                    f"got the server hello response, UDP server: "
                    f"{self._udp.server}:{self._udp.port}"
                )

                self.loop.call_soon_threadsafe(self.server_hello_event.set)

                if self._on_audio_channel_opened:
                    self._schedule_coro(
                        self._on_audio_channel_opened(),
                        name="audio_channel_opened",
                    )
                return

            if self._on_incoming_json:

                def process_json(json_data=data):
                    if asyncio.iscoroutinefunction(self._on_incoming_json):
                        coro = self._on_incoming_json(json_data)
                        if coro is not None:
                            asyncio.run_coroutine_threadsafe(coro, self.loop)
                    else:
                        self._on_incoming_json(json_data)

                self.loop.call_soon_threadsafe(process_json)
        except json.JSONDecodeError:
            logger.error(f"invalid JSON: {payload}")
        except Exception as e:
            logger.error(f"error while handling an MQTT message: {e}", exc_info=True)

    async def send_text(self, message):
        if not self.mqtt_client:
            logger.error("the MQTT client is not initialised")
            return False

        try:
            result = self.mqtt_client.publish(self.publish_topic, message)
            result.wait_for_publish()
            return True
        except Exception as e:
            logger.error(f"failed to send the MQTT message: {e}", exc_info=True)
            if self._on_network_error:
                await self._on_network_error(f"failed to send the MQTT message: {e}")
            return False

    async def send_audio(self, audio_data):
        try:
            return self._udp.send_audio(audio_data)
        except Exception as e:
            logger.error(f"failed to send the audio data: {e}", exc_info=True)
            if self._on_network_error:
                self._schedule_coro(
                    self._on_network_error(f"failed to send the audio data: {e}"),
                    name="send_audio_network_error",
                )
            return False

    async def open_audio_channel(self):
        if not self.connected:
            return await self.connect()
        return True

    async def close_audio_channel(self):
        self._is_closing = True
        try:
            if self.session_id:
                goodbye_msg = {"type": "goodbye", "session_id": self.session_id}
                await self.send_text(json.dumps(goodbye_msg))
            await self._handle_goodbye()
        except Exception as e:
            logger.error(f"error while closing the audio channel: {e}", exc_info=True)
            if self._on_audio_channel_closed:
                await self._on_audio_channel_closed()
        finally:
            self._is_closing = False

    def is_audio_channel_opened(self) -> bool:
        if not self.connected or self._is_closing:
            return False
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            return False
        return self._udp.is_ready()

    async def _handle_goodbye(self):
        try:
            self._udp.reset_session()
            logger.info("the UDP receive thread has stopped")

            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception as e:
                    logger.error(f"failed to disconnect from MQTT: {e}", exc_info=True)
                self.mqtt_client = None

            self.connected = False
            self.session_id = None

            if self._on_audio_channel_closed:
                await self._on_audio_channel_closed()
        except Exception as e:
            logger.error(
                f"error while handling the goodbye message: {e}", exc_info=True
            )

    def _stop_udp_receiver(self):
        """Stop UDP (used by the disconnect callback and similar paths)."""
        self._udp.stop()

    def __del__(self):
        try:
            self._udp.stop()
        except Exception:
            pass
        if getattr(self, "mqtt_client", None):
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.error(f"failed to disconnect from MQTT: {e}", exc_info=True)

    # ============ template method implementations ============

    @property
    def _monitor_interval(self) -> float:
        return 30.0

    def _is_connected(self) -> bool:
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            return False
        if self._last_activity_time:
            if time.time() - self._last_activity_time > self._connection_timeout:
                return False
        return True

    async def _do_cleanup(self):
        self._udp.stop()
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.error(f"error while disconnecting from MQTT: {e}", exc_info=True)
        self._last_activity_time = None

    def get_connection_info(self) -> dict:
        info = super().get_connection_info()
        info.update(
            {
                "connected": self.connected,
                "mqtt_connected": (
                    self.mqtt_client.is_connected() if self.mqtt_client else False
                ),
                "last_activity_time": self._last_activity_time,
                "keep_alive_interval": self._keep_alive_interval,
                "connection_timeout": self._connection_timeout,
                "mqtt_endpoint": self.endpoint,
                "udp_server": (
                    f"{self._udp.server}:{self._udp.port}" if self._udp.server else None
                ),
                "session_id": self.session_id,
            }
        )
        return info
