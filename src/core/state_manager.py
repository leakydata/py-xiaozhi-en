"""State manager.

Centralises device state and broadcasts changes over the event bus.
"""

import asyncio
from typing import TYPE_CHECKING

from src.constants.constants import DeviceState, ListeningMode
from src.core.event_bus import EventBus, Events
from src.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger()


class StateManager:
    """Device state manager.

    Responsibilities:
    - device state (IDLE, LISTENING, SPEAKING)
    - listening mode (REALTIME, AUTO_STOP, MANUAL)
    - session state (keep_listening, aec_enabled)
    - broadcasting state changes over the event bus

    Usage:
        state = StateManager(event_bus)

        # set state (broadcasts automatically)
        await state.set_device_state(DeviceState.LISTENING)

        # read state
        if state.is_listening():
            ...
    """

    def __init__(self, event_bus: EventBus, aec_enabled: bool = True):
        self._event_bus = event_bus
        self._lock = asyncio.Lock()

        # device state
        self._device_state: DeviceState = DeviceState.IDLE

        # AEC configuration
        self._aec_enabled: bool = aec_enabled

        # listening mode: the default depends on the AEC configuration
        self._listening_mode: ListeningMode = (
            ListeningMode.REALTIME if aec_enabled else ListeningMode.AUTO_STOP
        )

        # session state
        self._keep_listening: bool = False

        # abort flag
        self._aborted: bool = False

    # -------------------------
    # device state
    # -------------------------
    @property
    def device_state(self) -> DeviceState:
        """
        Current device state.
        """
        return self._device_state

    async def set_device_state(self, state: DeviceState) -> None:
        """Set the device state.

        Args:
            state: the new device state

        A change is broadcast over the event bus.
        """
        async with self._lock:
            if self._device_state == state:
                return

            old_state = self._device_state
            self._device_state = state
            logger.info(f"device state: {old_state} -> {state}")

            # clear the abort flag
            if state == DeviceState.LISTENING:
                self._aborted = False

        # broadcast outside the lock to avoid a deadlock
        await self._event_bus.emit(
            Events.DEVICE_STATE_CHANGED,
            {"old_state": old_state, "new_state": state},
        )

    def is_idle(self) -> bool:
        """
        Whether the device is idle.
        """
        return self._device_state == DeviceState.IDLE

    def is_listening(self) -> bool:
        """
        Whether the device is listening.
        """
        return self._device_state == DeviceState.LISTENING

    def is_speaking(self) -> bool:
        """
        Whether the device is speaking.
        """
        return self._device_state == DeviceState.SPEAKING

    # -------------------------
    # listening mode
    # -------------------------
    @property
    def listening_mode(self) -> ListeningMode:
        """
        Current listening mode.
        """
        return self._listening_mode

    def set_listening_mode(self, mode: ListeningMode) -> None:
        """
        Set the listening mode.
        """
        self._listening_mode = mode
        logger.debug(f"listening mode set to: {mode}")

    # -------------------------
    # session state
    # -------------------------
    @property
    def keep_listening(self) -> bool:
        """
        Whether continuous listening is kept on.
        """
        return self._keep_listening

    def set_keep_listening(self, value: bool) -> None:
        """
        Set continuous listening.
        """
        self._keep_listening = value
        logger.debug(f"continuous listening: {value}")

    @property
    def aec_enabled(self) -> bool:
        """
        Whether AEC is enabled.
        """
        return self._aec_enabled

    # -------------------------
    # abort state
    # -------------------------
    @property
    def aborted(self) -> bool:
        """
        Whether the session has been aborted.
        """
        return self._aborted

    def set_aborted(self, value: bool) -> None:
        """
        Set the abort flag.
        """
        self._aborted = value

    # -------------------------
    # derived state
    # -------------------------
    def should_capture_audio(self) -> bool:
        """Whether microphone audio should be captured.

        Capture is needed when:
        1. listening and not aborted
        2. speaking, but AEC is on and realtime mode keeps listening
        """
        if self._device_state == DeviceState.LISTENING and not self._aborted:
            return True

        return (
            self._device_state == DeviceState.SPEAKING
            and self._aec_enabled
            and self._keep_listening
            and self._listening_mode == ListeningMode.REALTIME
        )

    def get_snapshot(self) -> dict:
        """Snapshot of all state.

        Returns every current value as a dict, for debugging and logs.
        """
        return {
            "device_state": self._device_state,
            "listening_mode": self._listening_mode,
            "keep_listening": self._keep_listening,
            "aec_enabled": self._aec_enabled,
            "aborted": self._aborted,
        }
