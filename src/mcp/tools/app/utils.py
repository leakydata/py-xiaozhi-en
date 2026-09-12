"""Shared helpers for application management.

One place for matching, looking up, caching and cleaning application names.
"""

import platform
import re
import time
from typing import Any

from src.logging import get_logger

logger = get_logger()

# global application cache
_cached_applications: list[dict[str, Any]] | None = None
_cache_timestamp: float = 0
_cache_duration = 300  # cache for 5 minutes


def clean_app_name(name: str) -> str:
    """Clean an application name, stripping version numbers and special characters.

    Args:
        name: the raw name

    Returns:
        str: the cleaned name
    """
    if not name:
        return ""

    # strip the common version-number patterns
    name = re.sub(r"\s+v?\d+[\.\d]*", "", name)
    name = re.sub(r"\s*\(\d+\)", "", name)
    name = re.sub(r"\s*\[.*?\]", "", name)

    # collapse the extra whitespace
    name = " ".join(name.split())

    return name.strip()


class AppMatcher:
    """
    The single application matcher.
    """

    # special application-name aliases - kept sorted by length so a short name does not win first
    # The Chinese entries are real app display names used for matching, not translatable text.
    SPECIAL_MAPPINGS = {
        "qq音乐": ["qqmusic", "qq音乐", "qq music"],
        "qqmusic": ["qqmusic", "qq音乐", "qq music"],
        "qq music": ["qqmusic", "qq音乐", "qq music"],
        "tencent meeting": ["tencent meeting", "腾讯会议", "voovmeeting"],
        "腾讯会议": ["tencent meeting", "腾讯会议", "voovmeeting"],
        "google chrome": ["chrome", "googlechrome", "google chrome"],
        "microsoft edge": ["msedge", "edge", "microsoft edge"],
        "microsoft office": [
            "microsoft office",
            "office",
            "word",
            "excel",
            "powerpoint",
        ],
        "microsoft word": ["microsoft word", "word"],
        "microsoft excel": ["microsoft excel", "excel"],
        "microsoft powerpoint": ["microsoft powerpoint", "powerpoint"],
        "visual studio code": ["code", "vscode", "visual studio code"],
        "wps office": ["wps", "wps office"],
        "qq": ["qq", "qqnt", "tencentqq"],
        "wechat": ["wechat", "weixin", "微信"],
        "dingtalk": ["dingtalk", "钉钉", "ding"],
        "钉钉": ["dingtalk", "钉钉", "ding"],
        "chrome": ["chrome", "googlechrome", "google chrome"],
        "firefox": ["firefox", "mozilla"],
        "edge": ["msedge", "edge", "microsoft edge"],
        "safari": ["safari"],
        "notepad": ["notepad", "notepad++"],
        "calculator": ["calc", "calculator", "calculatorapp"],
        "calc": ["calc", "calculator", "calculatorapp"],
        "feishu": ["feishu", "飞书", "lark"],
        "vscode": ["code", "vscode", "visual studio code"],
        "pycharm": ["pycharm", "pycharm64"],
        "cursor": ["cursor"],
        "typora": ["typora"],
        "wps": ["wps", "wps office"],
        "office": ["microsoft office", "office", "word", "excel", "powerpoint"],
        "word": ["microsoft word", "word"],
        "excel": ["microsoft excel", "excel"],
        "powerpoint": ["microsoft powerpoint", "powerpoint"],
        "finder": ["finder"],
        "terminal": ["terminal", "iterm"],
        "iterm": ["iterm", "iterm2"],
    }

    # process grouping (used when closing a group of processes)
    # As above, the Chinese keys are the app names as they appear on the system.
    PROCESS_GROUPS = {
        "chrome": "chrome",
        "googlechrome": "chrome",
        "firefox": "firefox",
        "edge": "edge",
        "msedge": "edge",
        "safari": "safari",
        "qq": "qq",
        "qqnt": "qq",
        "tencentqq": "qq",
        "qqmusic": "qqmusic",
        "QQMUSIC": "QQMUSIC",
        "QQ音乐": "QQ音乐",
        "wechat": "wechat",
        "weixin": "wechat",
        "dingtalk": "dingtalk",
        "钉钉": "dingtalk",
        "feishu": "feishu",
        "飞书": "feishu",
        "lark": "feishu",
        "vscode": "vscode",
        "code": "vscode",
        "cursor": "cursor",
        "pycharm": "pycharm",
        "pycharm64": "pycharm",
        "typora": "typora",
        "calculatorapp": "calculator",
        "calc": "calculator",
        "calculator": "calculator",
        "tencent meeting": "tencent_meeting",
        "腾讯会议": "tencent_meeting",
        "voovmeeting": "tencent_meeting",
        "wps": "wps",
        "word": "word",
        "excel": "excel",
        "powerpoint": "powerpoint",
        "finder": "finder",
        "terminal": "terminal",
        "iterm": "iterm",
        "iterm2": "iterm",
    }

    @classmethod
    def normalize_name(cls, name: str) -> str:
        """
        Normalise an application name.
        """
        if not name:
            return ""

        # strip the .exe suffix
        name = name.lower().replace(".exe", "")

        # strip version numbers and special characters
        name = re.sub(r"\s+v?\d+[\.\d]*", "", name)
        name = re.sub(r"\s*\(\d+\)", "", name)
        name = re.sub(r"\s*\[.*?\]", "", name)
        name = " ".join(name.split())

        return name.strip()

    @classmethod
    def get_process_group(cls, process_name: str) -> str:
        """
        Get the group a process belongs to.
        """
        normalized = cls.normalize_name(process_name)

        # check the direct mapping
        if normalized in cls.PROCESS_GROUPS:
            return cls.PROCESS_GROUPS[normalized]

        # check for a substring relationship
        for key, group in cls.PROCESS_GROUPS.items():
            if key in normalized or normalized in key:
                return group

        return normalized

    @classmethod
    def match_application(cls, target_name: str, app_info: dict[str, Any]) -> int:
        """Match an application and return a match score.

        Args:
            target_name: the application name being looked for
            app_info: the application record

        Returns:
            int: the match score (0-100); 0 means no match
        """
        if not target_name or not app_info:
            return 0

        target_lower = target_name.lower()
        app_name = app_info.get("name", "").lower()
        display_name = app_info.get("display_name", "").lower()
        window_title = app_info.get("window_title", "").lower()
        exe_path = app_info.get("command", "").lower()

        # 1. exact match (100 points)
        if target_lower == app_name or target_lower == display_name:
            return 100

        # 2. alias match (95-98 points) - a more specific keyword wins
        best_special_score = 0

        for key in cls.SPECIAL_MAPPINGS:
            if key in target_lower or target_lower == key:
                # look for a matching alias
                for alias in cls.SPECIAL_MAPPINGS[key]:
                    if alias.lower() in app_name or alias.lower() in display_name:
                        # score it: the more specific the match, the higher the score
                        if target_lower == key:
                            score = 98  # exact match on the alias key
                        elif len(key) > len(target_lower) * 0.8:
                            score = 97  # a match of similar length
                        else:
                            score = 95  # an ordinary alias match

                        if score > best_special_score:
                            best_special_score = score

        if best_special_score > 0:
            return best_special_score

        # 3. normalised-name match (90 points)
        normalized_target = cls.normalize_name(target_name)
        normalized_app = cls.normalize_name(app_info.get("name", ""))
        normalized_display = cls.normalize_name(app_info.get("display_name", ""))

        if (
            normalized_target == normalized_app
            or normalized_target == normalized_display
        ):
            return 90

        # 4. substring match (70-80 points)
        if target_lower in app_name:
            return 80
        if target_lower in display_name:
            return 75
        if app_name and app_name in target_lower:
            # stop a short name from matching a much longer one by accident
            if len(app_name) < len(target_lower) * 0.5:
                return 50  # lower the score
            return 70

        # 5. window-title match (60 points)
        if window_title and target_lower in window_title:
            return 60

        # 6. path match (50 points)
        if exe_path and target_lower in exe_path:
            return 50

        # 7. fuzzy match (30 points)
        if cls._fuzzy_match(target_lower, app_name) or cls._fuzzy_match(
            target_lower, display_name
        ):
            return 30

        return 0

    @classmethod
    def _fuzzy_match(cls, target: str, candidate: str) -> bool:
        """
        Fuzzy match.
        """
        if not target or not candidate:
            return False

        # strip every non-alphanumeric character before comparing
        target_clean = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", target)
        candidate_clean = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", candidate)

        return target_clean in candidate_clean or candidate_clean in target_clean


async def get_cached_applications(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Get the cached application list.

    Args:
        force_refresh: whether to force a cache refresh

    Returns:
        the application list
    """
    global _cached_applications, _cache_timestamp

    current_time = time.time()

    # check whether the cache is still valid
    if (
        not force_refresh
        and _cached_applications is not None
        and (current_time - _cache_timestamp) < _cache_duration
    ):
        logger.debug(
            f"[AppUtils] using the cached application list, cached {int(current_time - _cache_timestamp)}s ago"
        )
        return _cached_applications

    # rescan the applications
    try:
        import json

        from .scanner import scan_installed_applications

        logger.info("[AppUtils] refreshing the application cache")
        result_json = await scan_installed_applications(
            {"force_refresh": force_refresh}
        )
        result = json.loads(result_json)

        if result.get("success", False):
            _cached_applications = result.get("applications", [])
            _cache_timestamp = current_time
            logger.info(
                f"[AppUtils] application cache refreshed, {len(_cached_applications)} applications found"
            )
            return _cached_applications
        else:
            logger.warning(
                f"[AppUtils] application scan failed: {result.get('message', 'unknown error')}"
            )
            return _cached_applications or []

    except Exception as e:
        logger.error(
            f"[AppUtils] failed to refresh the application cache: {e}", exc_info=True
        )
        return _cached_applications or []


async def find_best_matching_app(
    app_name: str, app_type: str = "any"
) -> dict[str, Any] | None:
    """Find the best-matching application.

    Args:
        app_name: the application name
        app_type: which applications to consider ("installed", "running", "any")

    Returns:
        the best-matching application record
    """
    try:
        if app_type == "running":
            # get the running applications
            import asyncio

            from .process_manager import list_running_applications as list_running_sync

            applications = await asyncio.to_thread(list_running_sync)
        else:
            # get the installed applications
            applications = await get_cached_applications()

        if not applications:
            return None

        # score every application
        matches = []
        for app in applications:
            score = AppMatcher.match_application(app_name, app)
            if score > 0:
                matches.append((score, app))

        if not matches:
            return None

        # sort by score and return the best match
        matches.sort(key=lambda x: x[0], reverse=True)
        best_score, best_app = matches[0]

        logger.info(
            f"[AppUtils] best match: {best_app.get('display_name', best_app.get('name', ''))} (score: {best_score})"
        )
        return best_app

    except Exception as e:
        logger.error(
            f"[AppUtils] failed to find a matching application: {e}", exc_info=True
        )
        return None


def clear_app_cache():
    """Clear the application cache."""
    global _cached_applications, _cache_timestamp

    _cached_applications = None
    _cache_timestamp = 0
    logger.info("[AppUtils] application cache cleared")


def get_system_scanner():
    """Get the scanner module for the current platform."""
    system = platform.system()

    if system == "Darwin":
        from . import scanner_mac

        return scanner_mac
    elif system == "Windows":
        from . import scanner_windows

        return scanner_windows
    elif system == "Linux":
        from . import scanner_linux

        return scanner_linux
    else:
        logger.warning(f"[AppUtils] unsupported platform: {system}")
        return None


def get_cache_info() -> dict[str, Any]:
    """
    Get information about the cache.
    """

    current_time = time.time()
    cache_age = current_time - _cache_timestamp if _cache_timestamp > 0 else -1

    return {
        "cached": _cached_applications is not None,
        "count": len(_cached_applications) if _cached_applications else 0,
        "age_seconds": int(cache_age) if cache_age >= 0 else None,
        "valid": cache_age >= 0 and cache_age < _cache_duration,
        "cache_duration": _cache_duration,
    }
