# System-wide constants
from enum import Enum


class InitializationStage(Enum):
    """
    The stages of startup.
    """

    DEVICE_FINGERPRINT = "Stage 1: preparing the device identity"
    CONFIG_MANAGEMENT = "Stage 2: initialising configuration management"
    OTA_CONFIG = "Stage 3: fetching the configuration over OTA"
    ACTIVATION = "Stage 4: activation"


class SystemConstants:
    """
    System constants.
    """

    # application identity
    APP_NAME = "py-xiaozhi"  # the ASCII identifier, used for directories, config and the bundle id
    APP_DISPLAY_NAME = (
        "Xiaozhi"  # the name people see: window titles, Launchpad, the installer
    )
    APP_VERSION = "2.1.1"
    BOARD_TYPE = "bread-compact-wifi"

    # default timeouts
    DEFAULT_TIMEOUT = 10
    ACTIVATION_MAX_RETRIES = 60
    ACTIVATION_RETRY_INTERVAL = 5

    # file names
    CONFIG_FILE = "config.json"
    EFUSE_FILE = "efuse.json"
