"""TUI settings: the editable fields, and reading and writing them (through ConfigManager and CONFIG_CHANGED)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.logging import get_logger
from src.utils.config_manager import get_config

logger = get_logger()


@dataclass(frozen=True)
class SettingField:
    """One editable setting."""

    path: str
    label: str
    kind: str = "str"  # str | int | bool | choice
    choices: tuple[str, ...] = ()
    help: str = ""


# first pass: system / audio / camera / wake word
SETTING_SECTIONS: list[tuple[str, list[SettingField]]] = [
    (
        "System",
        [
            SettingField(
                "SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL",
                "OTA URL",
                help="The OTA / activation config URL",
            ),
            SettingField(
                "SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL",
                "WebSocket URL",
                help="The WebSocket server URL",
            ),
            SettingField(
                "SYSTEM_OPTIONS.DEVICE_ID",
                "Device ID",
                help="Device-Id (usually the MAC address)",
            ),
            SettingField(
                "SYSTEM_OPTIONS.CLIENT_ID",
                "Client ID",
                help="Client-Id",
            ),
        ],
    ),
    (
        "Audio",
        [
            SettingField(
                "AUDIO_DEVICES.input_device_name",
                "Input device name",
                help="Matches the microphone by name; IDs change when devices are plugged in",
            ),
            SettingField(
                "AUDIO_DEVICES.output_device_name",
                "Output device name",
                help="Matches the speaker or headphones by name",
            ),
            SettingField(
                "AUDIO_DEVICES.opus_output_sample_rate",
                "Opus output sample rate",
                kind="choice",
                choices=("24000", "16000"),
                help="24000 for the official server; third-party ones are often 16000",
            ),
            SettingField(
                "AUDIO_DEVICES.frame_duration",
                "Frame length (ms)",
                kind="choice",
                choices=("20", "40", "60"),
                help="20 for low latency, 60 for low CPU",
            ),
        ],
    ),
    (
        "Camera",
        [
            SettingField(
                "CAMERA.backend",
                "Capture backend",
                kind="choice",
                choices=("auto", "opencv", "picamera2"),
                help="auto tries OpenCV first, then the Pi CSI camera",
            ),
            SettingField(
                "CAMERA.device",
                "Device path",
                help="e.g. /dev/video0; when set it wins over the index",
            ),
            SettingField(
                "CAMERA.camera_index",
                "Device index",
                kind="int",
                help="The numeric OpenCV index",
            ),
            SettingField(
                "CAMERA.frame_width",
                "Width",
                kind="int",
            ),
            SettingField(
                "CAMERA.frame_height",
                "Height",
                kind="int",
            ),
        ],
    ),
    (
        "Wake word",
        [
            SettingField(
                "WAKE_WORD_OPTIONS.USE_WAKE_WORD",
                "Enable the wake word",
                kind="bool",
            ),
            SettingField(
                "WAKE_WORD_OPTIONS.WAKE_WORD",
                "Wake word",
                help="e.g. hey computer",
            ),
            SettingField(
                "WAKE_WORD_OPTIONS.WAKE_WORD_LANG",
                "Language",
                kind="choice",
                choices=("zh", "en"),
            ),
        ],
    ),
]


def load_setting_values() -> dict[str, str]:
    """Read the current configuration as strings (path -> displayed value)."""
    cfg = get_config()
    values: dict[str, str] = {}
    for _section, fields in SETTING_SECTIONS:
        for f in fields:
            raw = cfg.get_config(f.path, "")
            if f.kind == "bool":
                values[f.path] = "true" if bool(raw) else "false"
            elif raw is None:
                values[f.path] = ""
            else:
                values[f.path] = str(raw)
    return values


def parse_field_value(field: SettingField, text: str) -> Any:
    """Turn what was typed into a configuration value."""
    s = (text or "").strip()
    if field.kind == "int":
        if s == "":
            return 0
        return int(s)
    if field.kind == "bool":
        return s.lower() in ("1", "true", "yes", "on")
    if field.kind == "choice":
        if field.choices and s not in field.choices:
            # write what they typed anyway; the caller validates and warns
            return s
        if field.path.endswith("opus_output_sample_rate") or field.path.endswith(
            "frame_duration"
        ):
            try:
                return int(s)
            except ValueError:
                return s
        return s
    return s


def save_settings(values: dict[str, str]) -> tuple[bool, str]:
    """Write several settings at once and save them.

    Returns:
        (ok, message)
    """
    cfg = get_config()
    updates: dict[str, Any] = {}
    try:
        for _section, fields in SETTING_SECTIONS:
            for f in fields:
                if f.path not in values:
                    continue
                updates[f.path] = parse_field_value(f, values[f.path])
        if not updates:
            return True, "No changes"
        ok = cfg.update_configs(updates)
        if not ok:
            return False, "Could not save (write error)"
        logger.info(f"TUI saved {len(updates)} settings")
        return True, f"Saved {len(updates)} settings"
    except Exception as e:
        logger.error(f"TUI failed to save the settings: {e}", exc_info=True)
        return False, f"Could not save: {e}"
