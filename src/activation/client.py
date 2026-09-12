"""The activation HTTP client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Optional

import aiohttp

from src.logging import get_logger

if TYPE_CHECKING:
    from src.activation.identity import DeviceIdentity
    from src.utils.config_manager import ConfigManager

logger = get_logger()


class ActivationHttpClient:
    """Poll the OTA activate endpoint until it succeeds or gives up."""

    def __init__(
        self,
        config_manager: "ConfigManager",
        identity: "DeviceIdentity",
    ) -> None:
        self._config = config_manager
        self._identity = identity

    async def activate(
        self,
        challenge: str,
        code: str,
        *,
        on_retry_announce: Optional[Callable[[str], None]] = None,
    ) -> bool:
        serial_number = self._identity.get_serial_number()
        if not serial_number:
            logger.error("no serial number, so activation cannot proceed")
            return False

        hmac_signature = self._identity.generate_hmac_signature(challenge)
        if not hmac_signature:
            logger.error("could not generate the HMAC signature")
            return False

        payload = {
            "Payload": {
                "algorithm": "hmac-sha256",
                "serial_number": serial_number,
                "challenge": challenge,
                "hmac": hmac_signature,
            }
        }

        ota_url = self._config.get_config("SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL")
        if not ota_url:
            logger.error("no OTA URL is configured")
            return False

        activate_url = f"{ota_url.rstrip('/')}/activate"
        headers = {
            "Activation-Version": "2",
            "Device-Id": self._config.get_config("SYSTEM_OPTIONS.DEVICE_ID"),
            "Client-Id": self._config.get_config("SYSTEM_OPTIONS.CLIENT_ID"),
            "Content-Type": "application/json",
        }
        logger.info(f"activation URL: {activate_url}")

        max_retries = 60
        retry_interval = 5
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(max_retries):
                try:
                    logger.info(f"activation attempt {attempt + 1}/{max_retries}")
                    if attempt > 0 and on_retry_announce:
                        try:
                            on_retry_announce(code)
                        except Exception as e:
                            logger.warning(
                                f"failed to read the activation code aloud: {e}",
                                exc_info=True,
                            )

                    async with session.post(
                        activate_url, headers=headers, json=payload
                    ) as response:
                        logger.debug(f"activation response: HTTP {response.status}")
                        if response.status == 200:
                            logger.info("device activated.")
                            self._identity.set_activation_status(True)
                            return True
                        if response.status == 202:
                            logger.info(
                                "waiting for the verification code to be entered..."
                            )
                            await asyncio.sleep(retry_interval)
                            continue
                        logger.warning(
                            f"the server returned {response.status}, retrying"
                        )
                        await asyncio.sleep(retry_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"the activation request failed: {e} - retrying...",
                        exc_info=True,
                    )
                    await asyncio.sleep(retry_interval)

        logger.error(
            f"activation failed after the maximum number of attempts ({max_retries})"
        )
        return False
