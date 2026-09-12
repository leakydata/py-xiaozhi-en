import platform
from enum import Enum


class ListeningMode(str, Enum):
    """
    Listening mode.
    """

    REALTIME = "realtime"
    AUTO_STOP = "auto_stop"
    MANUAL = "manual"


class AbortReason(str, Enum):
    """
    Why it was aborted.
    """

    NONE = "none"
    WAKE_WORD_DETECTED = "wake_word_detected"
    USER_INTERRUPTION = "user_interruption"


class DeviceState(str, Enum):
    """
    Device state.
    """

    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"


class EventType:
    """
    Event type.
    """

    SCHEDULE_EVENT = "schedule_event"
    AUDIO_INPUT_READY_EVENT = "audio_input_ready_event"
    AUDIO_OUTPUT_READY_EVENT = "audio_output_ready_event"


def get_frame_duration() -> int:
    """Get the frame length for this device.

    Read from the loaded configuration when there is one; otherwise detect it from the machine's architecture.
    The configuration is not read at import time.

    Returns:
        int: the frame length in milliseconds; 20, 40 or 60
    """
    try:
        from src.utils.config_manager import get_config

        configured = get_config().get_config("AUDIO_DEVICES.frame_duration")
        if configured in [20, 40, 60]:
            return configured

        # detect it when there is no configuration (kept for backwards compatibility)
        machine = platform.machine().lower()
        arm_archs = ["arm", "aarch64", "armv7l", "armv6l"]
        is_arm_device = any(arch in machine for arch in arm_archs)

        if is_arm_device:
            # ARM machines (a Raspberry Pi, say) use a longer frame to cut CPU load
            return 60
        else:
            # everything else (Windows, macOS, Linux x86) has the headroom for low latency
            return 20

    except Exception:
        # on failure fall back to 20ms, which suits most modern machines
        return 20


class AudioConfig:
    """
    The audio configuration - the protocol-level parameters, separate from the device level (DeviceConfig).

    The defaults are declared in the class body; reload() pulls the live values from ConfigManager.
    There is no reload at import time any more, so importing constants has no side effects.
    """

    # fixed by the server protocol (configuration does not change these)
    INPUT_SAMPLE_RATE = 16000  # the protocol requires 16kHz input
    CHANNELS = 1  # the protocol requires mono

    # the values below are dynamic; reload() re-reads them from the configuration
    OUTPUT_SAMPLE_RATE: int = 24000
    FRAME_DURATION: int = 20
    INPUT_FRAME_SIZE: int = 320

    @classmethod
    def reload(cls):
        """Re-read the protocol audio parameters from ConfigManager, so they can be changed while running.

        After the Settings UI changes opus_output_sample_rate or frame_duration,
        call this so the new values take effect on the next initialize or reload_devices.
        """
        try:
            from src.utils.config_manager import get_config

            config = get_config()
            cls.OUTPUT_SAMPLE_RATE = config.get_config(
                "AUDIO_DEVICES.opus_output_sample_rate", 24000
            )
        except Exception:
            # keep the current or default values when the configuration is unavailable
            pass
        cls.FRAME_DURATION = get_frame_duration()
        cls.INPUT_FRAME_SIZE = int(cls.INPUT_SAMPLE_RATE * (cls.FRAME_DURATION / 1000))
