import copy
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from src.logging import get_logger
from src.utils.resource_finder import (
    get_config_dir,
    get_user_data_dir,
)

logger = get_logger()

# The authoritative in-process config: created by initialize_config(), read by
# get_config(). No lazy singleton.
_current: "ConfigManager | None" = None


def initialize_config() -> "ConfigManager":
    """Create or return the initialised config manager (called from the app entry point)."""
    global _current
    if _current is None:
        _current = ConfigManager()
        # apply PATHS overrides and migrate cache/logs/music/keywords (the config directory is not migrated)
        try:
            from src.utils.resource_finder import apply_path_overrides_from_config

            apply_path_overrides_from_config(_current, migrate=True)
        except Exception as e:
            logger.warning(
                "failed to apply the PATHS directory overrides: %s", e, exc_info=True
            )
    return _current


def get_config() -> "ConfigManager":
    """Return the initialised config manager.

    Raises:
        RuntimeError: initialize_config() has not been called
    """
    if _current is None:
        raise RuntimeError(
            "ConfigManager not initialised: call initialize_config() from the entry point"
        )
    return _current


def reset_config() -> None:
    """Drop the process config (tests only)."""
    global _current
    _current = None


class ConfigManager:
    """
    Config manager. A plain instance; initialize_config/get_config hold the authoritative one.
    """

    # current schema version; migrate_config() upgrades to this on load
    CONFIG_VERSION = 1

    # Default config (the full schema). Deep-copied on load so instances never
    # share nested objects with the class.
    DEFAULT_CONFIG = {
        "CONFIG_VERSION": 1,
        "SYSTEM_OPTIONS": {
            "CLIENT_ID": None,
            "DEVICE_ID": None,
            "WINDOW_SIZE_MODE": "default",
            # avatar style: person (cartoon) | simple (abstract disc) | gif (animated emoji)
            "AVATAR_STYLE": "person",
            "NETWORK": {
                "OTA_VERSION_URL": "https://api.tenclass.net/xiaozhi/ota/",
                "WEBSOCKET_URL": None,
                "WEBSOCKET_ACCESS_TOKEN": None,
                "MQTT_INFO": None,
                "ACTIVATION_VERSION": "v2",  # allowed values: v1, v2
                "AUTHORIZATION_URL": "https://xiaozhi.me/",
            },
        },
        # Claude Code as a deeper reasoning tool. Runs on the signed-in
        # subscription, not the API. Always sandboxed read-only - see
        # mcp/tools/claude_code/runner.py for why that is not configurable.
        "CLAUDE_CODE": {
            "ENABLED": True,
            "TIMEOUT_SECONDS": 120,
            "MODEL": "",
        },
        # Workspace the assistant may read and write. Every file tool is
        # confined to this folder; blank = ~/Documents/XiaoZhi
        "FILES": {
            "ROOT": "",
        },
        # Reminders announced out loud when they come due
        "REMINDERS": {
            "ENABLED": True,
            "POLL_SECONDS": 20,
        },
        "WAKE_WORD_OPTIONS": {
            "USE_WAKE_WORD": True,
            "MODEL_PATH": "models/en",
            "NUM_THREADS": 5,
            "PROVIDER": "cpu",
            "MAX_ACTIVE_PATHS": 2,
            "KEYWORDS_SCORE": 1.8,
            "KEYWORDS_THRESHOLD": 0.2,
            "NUM_TRAILING_BLANKS": 1,
            "WAKE_WORD": "hey computer",
            "WAKE_WORD_LANG": "en",
        },
        "CAMERA": {
            "camera_index": 0,
            # a device path beats index, e.g. "/dev/video0" (Raspberry Pi USB/V4L2)
            "device": "",
            # auto | opencv | picamera2; auto OpenCV first, then CSI (picamera2) if that fails
            "backend": "auto",
            "frame_width": 640,
            "frame_height": 480,
            "fps": 30,
            # warm-up frames discarded after opening (the first few are often invalid on USB/Pi)
            "warm_up_frames": 5,
            "Local_VL_url": "https://open.bigmodel.cn/api/paas/v4/",
            "VLapi_key": "",
            "models": "glm-4v-plus",
        },
        "SHORTCUTS": {
            "ENABLED": True,
            "MANUAL_PRESS": {
                "modifier": "ctrl",
                "key": "j",
                "description": "Push to talk",
            },
            "AUTO_TOGGLE": {
                "modifier": "ctrl",
                "key": "k",
                "description": "Auto conversation",
            },
            "ABORT": {
                "modifier": "ctrl",
                "key": "q",
                "description": "Abort conversation",
            },
            "MODE_TOGGLE": {
                "modifier": "ctrl",
                "key": "m",
                "description": "Toggle mode",
            },
            "WINDOW_TOGGLE": {
                "modifier": "ctrl",
                "key": "w",
                "description": "Show/hide window",
            },
        },
        "AEC_OPTIONS": {
            "ENABLED": False,
            # AEC when active, TTS does not pause music - it ducks and plays in parallel (falling back to pausing if the engine is bypassed)
            "MUSIC_PARALLEL": True,
            # delay compensation in protocol frames; actual delay_ms = 40 + N * frame length
            "FRAME_DELAY": 3,
            # noise suppression / high-pass preprocessing
            "ENABLE_PREPROCESS": True,
        },
        # writable directory overrides (config stays in user-data/config; null = default)
        # environment variables take precedence: XIAOZHI_CACHE_DIR / XIAOZHI_LOG_DIR /
        # XIAOZHI_MUSIC_CACHE_DIR / XIAOZHI_KEYWORDS_DIR / XIAOZHI_DATA_DIR
        # after changing CACHE/LOG/MUSIC/KEYWORDS, the next start copies from the old directory to the new one (the old is kept)
        "PATHS": {
            "CACHE_DIR": None,
            "LOG_DIR": None,
            "MUSIC_CACHE_DIR": None,
            "KEYWORDS_DIR": None,
        },
        # external MCP plugins (mcp_plugins in the user directory, bundling their own lib/)
        "MCP_PLUGINS": {
            "ENABLED": True,
            "DIR": None,  # null = {user data}/mcp_plugins
            "ENABLED_IDS": [],  # empty = follow each plugin's enabled_by_default
            "DISABLED_IDS": [],
            "ALLOW_HOST_GET": ["config_readonly", "logger"],
            # strict validation (off by default, so sample packages without platforms/abi still load)
            "ENFORCE_PREFIX": False,
            "REQUIRE_PYTHON_ABI": False,
            "REQUIRE_PLATFORMS": False,
        },
        # MCP tool exposure (blacklist: hidden from tools/list and refused on call)
        "MCP_TOOLS": {
            "DISABLED": [],  # e.g. ["music_player.stop", "self.application.launch"]
        },
        "AUDIO_DEVICES": {
            "input_device_id": None,
            "input_device_name": None,
            "output_device_id": None,
            "output_device_name": None,
            "input_sample_rate": None,
            "output_sample_rate": None,
            "input_channels": None,
            "output_channels": None,
            "opus_output_sample_rate": 24000,  # Opus decode rate: 24000 (official) or 16000 (third-party)
            "frame_duration": 20,  # audio frame length in ms: 20 (low latency) / 40 (balanced) / 60 (low CPU)
        },
        "LOGGING": {
            "LEVEL": "INFO",  # DEBUG, INFO, WARNING, ERROR, CRITICAL
            "FORMAT_TYPE": "colored",  # colored, json, simple
            "ENABLE_CONSOLE": True,
            "ENABLE_FILE": True,
            "ENABLE_ERROR_FILE": True,
            "ENABLE_JSON_FILE": False,
            "ENABLE_ASYNC": False,
            "ENABLE_SENSITIVE_FILTER": True,
            "MAX_BYTES": 10485760,  # 10MB
            "BACKUP_COUNT": 30,
            "ROTATION_WHEN": "midnight",  # midnight, H, D
            "THIRD_PARTY_LEVELS": {
                "urllib3": "WARNING",
                "websockets": "WARNING",
                "asyncio": "WARNING",
                "paho": "WARNING",
                "PIL": "WARNING",
            },
        },
        # music API (empty string = use the built-in default URL at runtime)
        "MUSIC": {
            "SEARCH_URL": "",
            "URL_API": "",
            "URL_API_KEY": "",
            "LYRICS_URL": "",
            "DEFAULT_PLATFORM": "kw",
            "DEFAULT_QUALITY": "320k",
        },
    }

    def __init__(self):
        """Construct the config manager directly; applications should use initialize_config."""
        self._init_config_paths()
        self._config = self._load_config()

    def _init_config_paths(self):
        """
        Set up the config file paths.

        The config lives in the user data directory, so it stays writable once packaged.
        On first run the default config is migrated from the install directory.
        """
        self.config_dir = get_user_data_dir() / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.config_file = self.config_dir / "config.json"

        # if there is no config in the user directory, try migrating one from the install directory
        if not self.config_file.exists():
            install_config = get_config_dir() / "config.json"
            if install_config.exists():
                try:
                    # validate the JSON first, so a corrupt install config is not copied in
                    json.loads(install_config.read_text(encoding="utf-8"))
                    shutil.copy2(install_config, self.config_file)
                    logger.info(
                        f"Migrated config from the install directory: {install_config} -> {self.config_file}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to migrate the config file: {e}; using defaults",
                        exc_info=True,
                    )

        logger.info(f"Config directory: {self.config_dir.absolute()}")
        logger.info(f"Config file: {self.config_file.absolute()}")

    def _default_config_copy(self) -> Dict[str, Any]:
        """Deep-copy the defaults, so instances do not share nested dicts/lists with the class attribute."""
        return copy.deepcopy(self.DEFAULT_CONFIG)

    def _load_config(self) -> Dict[str, Any]:
        """Load the config file, creating it if missing and falling back to defaults (after a backup) if corrupt."""
        try:
            if self.config_file.exists():
                logger.debug(f"Found config file: {self.config_file}")
                try:
                    raw = self.config_file.read_text(encoding="utf-8")
                    config = json.loads(raw)
                except Exception as e:
                    backup = self._backup_corrupt_config(e)
                    logger.error(
                        "Config file was corrupt; backed up to %s and fell back to defaults: %s",
                        f"to {backup}" if backup else "",
                        e,
                        exc_info=True,
                    )
                    defaults = self._default_config_copy()
                    self._save_config(defaults)
                    return defaults

                if not isinstance(config, dict):
                    backup = self._backup_corrupt_config(
                        TypeError(
                            f"the root node must be an object, got {type(config).__name__}"
                        )
                    )
                    logger.error(
                        "Config root node was invalid; backed up to %s and fell back to defaults",
                        f"to {backup}" if backup else "",
                    )
                    defaults = self._default_config_copy()
                    self._save_config(defaults)
                    return defaults

                merged = self._merge_configs(self._default_config_copy(), config)
                # the version comes from the file on disk; a merge would carry the default CONFIG_VERSION and look already-migrated
                try:
                    file_ver = int(config.get("CONFIG_VERSION", 0) or 0)
                except (TypeError, ValueError):
                    file_ver = 0
                return self._migrate_config(merged, from_version=file_ver)

            logger.info("No config file; creating the default one")
            defaults = self._default_config_copy()
            self._save_config(defaults)
            return defaults

        except Exception as e:
            logger.error(f"Config load error: {e}", exc_info=True)
            return self._default_config_copy()

    def _migrate_config(
        self, config: Dict[str, Any], *, from_version: int | None = None
    ) -> Dict[str, Any]:
        """Migrate forward to CONFIG_VERSION, writing back to disk if needed.

        from_version: the version in the file on disk (before merging). If omitted, the field inside config is read
        (if defaults have already been merged it may look current, and the migration would be skipped).

        Convention:
        - a missing or invalid version counts as 0
        - each step applies only low-risk patches (renames, added sections, normalisation)
        - write back at CONFIG_VERSION so the migration is not repeated next time
        """
        if from_version is not None:
            ver = int(from_version)
        else:
            try:
                raw_ver = config.get("CONFIG_VERSION", 0)
                try:
                    ver = int(raw_ver)
                except (TypeError, ValueError):
                    ver = 0
            except Exception:
                ver = 0

        original = ver
        # --- migration steps (append one per version) ---
        if ver < 1:
            # v1: introduce the version number, add MCP_TOOLS, normalise the subscribe_topic string "null"
            config.setdefault("MCP_TOOLS", {"DISABLED": []})
            if not isinstance(config.get("MCP_TOOLS"), dict):
                config["MCP_TOOLS"] = {"DISABLED": []}
            config["MCP_TOOLS"].setdefault("DISABLED", [])

            try:
                net = config.get("SYSTEM_OPTIONS", {}).get("NETWORK", {})
                mqtt = net.get("MQTT_INFO")
                if isinstance(mqtt, dict) and mqtt.get("subscribe_topic") == "null":
                    mqtt["subscribe_topic"] = None
            except Exception:
                pass
            ver = 1

        # later: if ver < 2: ...; ver = 2

        if ver != original or config.get("CONFIG_VERSION") != self.CONFIG_VERSION:
            config["CONFIG_VERSION"] = self.CONFIG_VERSION
            if self._save_config(config):
                logger.info(
                    "Config migrated: v%s -> v%s", original, self.CONFIG_VERSION
                )
            else:
                logger.warning(
                    "Could not write back after migrating (memory is already v%s)",
                    self.CONFIG_VERSION,
                )
        else:
            config["CONFIG_VERSION"] = self.CONFIG_VERSION
        return config

    def _backup_corrupt_config(self, error: Exception) -> str | None:
        """Back up a corrupt config.json as .corrupt-<timestamp> and return the backup path."""
        try:
            if not self.config_file.exists():
                return None
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.config_file.with_name(f"config.json.corrupt-{ts}")
            # avoid a name clash in the unlikely case
            n = 0
            while backup.exists():
                n += 1
                backup = self.config_file.with_name(f"config.json.corrupt-{ts}-{n}")
            shutil.copy2(self.config_file, backup)
            logger.warning("Corrupt config backed up: %s (%s)", backup, error)
            return str(backup)
        except Exception as e:
            logger.error("failed to back up the corrupt config: %s", e, exc_info=True)
            return None

    def _save_config(self, config: dict) -> bool:
        """Write the config atomically (temp file + rename, so an interrupted write cannot corrupt it)."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            tmp_file = self.config_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(tmp_file, self.config_file)
            logger.debug(f"Config saved to: {self.config_file}")
            return True

        except Exception as e:
            logger.error(f"Config save error: {e}", exc_info=True)
            return False

    @staticmethod
    def _merge_configs(default: dict, custom: dict) -> dict:
        """Merge config recursively: default underneath, custom on top, deep-merging where both sides are dicts.

        Note: callers should pass an already deep-copied default, so the class-level DEFAULT_CONFIG is not polluted.
        """
        result = default  # already an independent copy, so merge in place
        for key, value in custom.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = ConfigManager._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def get_config(self, path: str, default: Any = None) -> Any:
        """
        Read a config value by path
        path: dot-separated config path, e.g. "SYSTEM_OPTIONS.NETWORK.MQTT_INFO"
        """
        try:
            value = self._config
            for key in path.split("."):
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def update_config(self, path: str, value: Any, *, save: bool = True) -> bool:
        """
        update a specific config entry
        path: dot-separated config path, e.g. "SYSTEM_OPTIONS.NETWORK.MQTT_INFO"
        save: whether to write to disk now; pass False for batch updates and call save_config()/update_configs at the end

        An intermediate node that is None or not a dict is promoted to a dict first (so defaults like MQTT_INFO: null still work).
        """
        try:
            current: Any = self._config
            *parts, last = path.split(".")
            for part in parts:
                if not isinstance(current, dict):
                    raise TypeError(
                        f"Cannot write {path}: a prefix of the path is not an object (node type {type(current).__name__})"
                    )
                existing = current.get(part, None)
                if not isinstance(existing, dict):
                    # missing key, or None/scalar: create an empty object so we can keep descending
                    existing = {}
                    current[part] = existing
                current = existing
            if not isinstance(current, dict):
                raise TypeError(f"Config path is not writable: {path}")
            current[last] = value
            if not save:
                return True
            return self._save_config(self._config)
        except Exception as e:
            logger.error(f"Config update error at {path}: {e}", exc_info=True)
            return False

    def update_configs(self, updates: Dict[str, Any]) -> bool:
        """Update several config paths at once, writing to disk only once.

        Args:
            updates: path -> value, for example
                {"SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL": "wss://..."}
        """
        if not updates:
            return True
        try:
            for path, value in updates.items():
                if not self.update_config(path, value, save=False):
                    return False
            return self._save_config(self._config)
        except Exception as e:
            logger.error(f"Batch config update error: {e}", exc_info=True)
            return False

    def save_config(self) -> bool:
        """Write the in-memory config to disk."""
        return self._save_config(self._config)

    def reload_config(self, *, apply_paths: bool = True) -> bool:
        """Reload the config file.

        apply_paths: whether to re-apply the PATHS overrides (without migrating directories).
        PATHS Directory migration happens only during initialize_config.
        """
        try:
            self._config = self._load_config()
            if apply_paths:
                try:
                    from src.utils.resource_finder import (
                        apply_path_overrides_from_config,
                    )

                    apply_path_overrides_from_config(self, migrate=False)
                except Exception as e:
                    logger.warning(
                        "reload failed to apply PATHS afterwards: %s", e, exc_info=True
                    )
            logger.info("Config file reloaded")
            return True
        except Exception as e:
            logger.error(f"Config reload failed: {e}", exc_info=True)
            return False

    def generate_uuid(self) -> str:
        """Generate a UUID v4."""
        return str(uuid.uuid4())

    def initialize_client_id(self):
        """Ensure a client ID exists."""
        if not self.get_config("SYSTEM_OPTIONS.CLIENT_ID"):
            client_id = self.generate_uuid()
            success = self.update_config("SYSTEM_OPTIONS.CLIENT_ID", client_id)
            if success:
                logger.info(f"Generated a new client ID: {client_id}")
            else:
                logger.error("Failed to save the new client ID")
