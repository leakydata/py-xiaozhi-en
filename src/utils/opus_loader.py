"""The Opus loader - makes sure opuslib can find the opus shared library."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

from src.logging import get_logger
from src.utils.resource_finder import get_lib_path

logger = get_logger()

_opus_loaded = False


def _find_system_opus() -> str | None:
    """Find the opus library installed on the system."""
    if sys.platform == "win32":
        return None

    if sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/lib/libopus.dylib",
            "/usr/local/lib/libopus.dylib",
        ]
    else:
        candidates = [
            "/usr/lib/libopus.so.0",
            "/usr/lib/x86_64-linux-gnu/libopus.so.0",
            "/usr/lib/aarch64-linux-gnu/libopus.so.0",
            "/usr/local/lib/libopus.so",
        ]

    for path in candidates:
        if Path(path).exists():
            return path

    return ctypes.util.find_library("opus")


def _try_load(path: str | Path) -> bool:
    """Try to load a shared library."""
    try:
        ctypes.CDLL(str(path))
        return True
    except OSError:
        return False


def _patch_find_library(lib_path: str):
    """Patch ctypes.util.find_library so opuslib can find opus."""
    original = ctypes.util.find_library

    def patched(name: str) -> str | None:
        if name == "opus":
            return lib_path
        return original(name)

    ctypes.util.find_library = patched


def setup_opus() -> bool:
    """Set up the opus library for opuslib.

    Search order:
    1. the bundled opus (libs/libopus/) - a known version, consistent wherever it is deployed
    2. the system opus (brew/apt) - the fallback

    Returns:
        whether it loaded
    """
    global _opus_loaded
    if _opus_loaded:
        return True

    # 1. prefer the bundled opus
    bundled_path = get_lib_path("libopus")
    if bundled_path and bundled_path.exists():
        if sys.platform == "win32":
            lib_dir = str(bundled_path.parent)
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(lib_dir)
            os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")

        if _try_load(bundled_path):
            logger.debug(f"using the bundled opus: {bundled_path}")
            _patch_find_library(str(bundled_path))
            _opus_loaded = True
            return True

    # 2. fall back to the system opus
    system_path = _find_system_opus()
    if system_path and _try_load(system_path):
        logger.debug(f"using the system opus: {system_path}")
        _patch_find_library(system_path)
        _opus_loaded = True
        return True

    logger.warning(
        "No opus library found, so audio encoding and decoding may not work. "
        "On Linux or macOS install it with your package manager: brew install opus / apt install libopus0"
    )
    return False
