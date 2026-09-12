# -*- coding: utf-8 -*-
"""The activation service facade, composing identity, ota, client and side_effects."""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, TypedDict

from src.activation.client import ActivationHttpClient
from src.activation.identity import DeviceIdentity
from src.activation.ota import OtaConfigClient
from src.activation.side_effects import announce_code, apply_code_side_effects
from src.logging import get_logger
from src.utils.config_manager import ConfigManager, get_config

logger = get_logger()


class ActivationResult(TypedDict, total=False):
    """The kind of activation result."""

    success: bool
    need_activation_ui: bool
    message: str
    error: str
    local_activated: bool
    server_activated: bool
    status_consistent: bool
    activation_version: str


class ActivationService:
    """The device activation facade (built by create(); not a singleton)."""

    def __init__(self) -> None:
        self.logger = get_logger()
        self._initialized = False
        self.config_manager = get_config()

        self._identity = DeviceIdentity()
        self._ota = OtaConfigClient(self.config_manager, self._identity)
        self._http = ActivationHttpClient(self.config_manager, self._identity)

        self._activation_data: Optional[Dict] = None
        self._activation_status = {
            "local_activated": False,
            "server_activated": False,
            "status_consistent": True,
        }
        self._activation_task: Optional[asyncio.Task] = None
        self._is_activating = False

    @classmethod
    async def create(cls) -> "ActivationService":
        instance = cls()
        await instance._async_init()
        return instance

    async def _async_init(self) -> None:
        if self._initialized:
            return
        self._identity.init_paths()
        self._identity.ensure_efuse_file()
        await self._ota.ensure_local_ip()
        self._initialized = True
        self.logger.info("ActivationService ready")

    # ---------- public interface ----------

    async def initialize(self) -> ActivationResult:
        self.logger.info("starting system initialisation")
        try:
            serial_number, hmac_key, is_activated = (
                self._identity.ensure_device_identity()
            )
            self._activation_status["local_activated"] = is_activated
            self.logger.info(f"device serial number: {serial_number}")
            self.logger.info(
                f"local activation state: {'activated' if is_activated else 'not activated'}"
            )

            self._ota.initialize_config()
            await self._ota.fetch_ota_config()
            self._activation_data = self._ota.activation_data
            self._activation_status["server_activated"] = self._ota.server_activated

            activation_version = self.config_manager.get_config(
                "SYSTEM_OPTIONS.NETWORK.ACTIVATION_VERSION", "v1"
            )
            self.logger.info(f"activation version: {activation_version}")

            if activation_version == "v1":
                self.logger.info("protocol v1: no activation needed")
                return ActivationResult(
                    success=True,
                    need_activation_ui=False,
                    message="Protocol v1 initialised",
                    local_activated=True,
                    server_activated=True,
                    status_consistent=True,
                    activation_version=activation_version,
                )

            result = self._analyze_activation_status()
            result["activation_version"] = activation_version
            return result
        except Exception as e:
            self.logger.error(
                f"system initialisation failed: {type(e).__name__}: {e}", exc_info=True
            )
            return ActivationResult(
                success=False,
                need_activation_ui=False,
                message="Initialisation failed",
                error=str(e),
            )

    async def activate(self, activation_data: Optional[Dict] = None) -> bool:
        data = activation_data or self._activation_data
        if not data:
            self.logger.error("there is no activation data")
            return False

        challenge = data.get("challenge")
        code = data.get("code")
        if not challenge or not code:
            self.logger.error("the activation data is missing required fields")
            return False

        try:
            self._is_activating = True
            self._activation_task = asyncio.current_task()
            apply_code_side_effects(code, data.get("message"))
            return await self._http.activate(
                challenge,
                code,
                on_retry_announce=announce_code,
            )
        except asyncio.CancelledError:
            self.logger.info("activation was cancelled")
            return False
        finally:
            self._is_activating = False
            self._activation_task = None

    def cancel_activation(self) -> None:
        if self._activation_task and not self._activation_task.done():
            self.logger.info("cancelling the activation task")
            self._activation_task.cancel()

    def get_device_info(self) -> Dict:
        efuse = self._identity.load_efuse_data()
        return {
            "serial_number": efuse.get("serial_number"),
            "mac_address": efuse.get("mac_address"),
        }

    def get_serial_number(self) -> Optional[str]:
        return self._identity.get_serial_number()

    def get_mac_address(self) -> Optional[str]:
        return self._identity.get_mac_address()

    def get_activation_status(self) -> Dict:
        return self._activation_status.copy()

    def get_activation_data(self) -> Optional[Dict]:
        return self._activation_data

    def is_activated(self) -> bool:
        return self._identity.is_activated()

    def is_activating(self) -> bool:
        return self._is_activating

    def get_config_manager(self) -> ConfigManager:
        return self.config_manager

    def _analyze_activation_status(self) -> ActivationResult:
        local = self._activation_status["local_activated"]
        server = self._activation_status["server_activated"]
        consistent = local == server
        self._activation_status["status_consistent"] = consistent
        self.logger.info(f"activation state: local={local}, server={server}")

        if not local and not server:
            return ActivationResult(
                success=True,
                need_activation_ui=True,
                message="This device needs activating",
                local_activated=local,
                server_activated=server,
                status_consistent=consistent,
            )
        if local and server:
            return ActivationResult(
                success=True,
                need_activation_ui=False,
                message="Device activated",
                local_activated=local,
                server_activated=server,
                status_consistent=consistent,
            )
        if not local and server:
            self.logger.warning("repairing the local activation state")
            self._identity.set_activation_status(True)
            return ActivationResult(
                success=True,
                need_activation_ui=False,
                message="Activation state repaired",
                local_activated=True,
                server_activated=server,
                status_consistent=True,
            )

        self.logger.warning(
            "the server revoked authorisation, the device needs activating again"
        )
        if self._activation_data and "code" in self._activation_data:
            return ActivationResult(
                success=True,
                need_activation_ui=True,
                message="The server revoked authorisation - this device needs activating again",
                local_activated=local,
                server_activated=server,
                status_consistent=consistent,
            )
        return ActivationResult(
            success=True,
            need_activation_ui=False,
            message="Keeping the local activation state",
            local_activated=local,
            server_activated=True,
            status_consistent=True,
        )
