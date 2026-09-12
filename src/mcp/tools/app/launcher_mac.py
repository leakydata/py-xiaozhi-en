"""Application launcher for macOS.

Starts applications on macOS.
Every subprocess call passes a list; none use shell=True.
"""

import os
import subprocess

from src.logging import get_logger

logger = get_logger()


def launch_application(app_name: str) -> bool:
    """Start an application on macOS.

    Args:
        app_name: the application name

    Returns:
        bool: whether it started
    """
    try:
        logger.info(f"[MacLauncher] starting: {app_name}")

        # 1: open -a (passed as a list, so it is safe)
        try:
            subprocess.Popen(
                ["open", "-a", app_name],
                start_new_session=True,
            )
            logger.info(f"[MacLauncher] started with open -a: {app_name}")
            return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(f"[MacLauncher] open -a did not start it: {app_name}")

        # 2: run the application name directly
        try:
            subprocess.Popen(
                [app_name],
                start_new_session=True,
            )
            logger.info(f"[MacLauncher] started directly: {app_name}")
            return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(f"[MacLauncher] could not start it directly: {app_name}")

        # 3: try the Applications directory
        app_path = f"/Applications/{app_name}.app"
        if os.path.exists(app_path):
            subprocess.Popen(
                ["open", app_path],
                start_new_session=True,
            )
            logger.info(
                f"[MacLauncher] started from the Applications directory: {app_name}"
            )
            return True

        # 4: open -a once more as a last resort (osascript is deliberately not used)
        # an earlier version built an osascript command with an f-string, which was an AppleScript injection hole; that is gone
        try:
            subprocess.Popen(
                ["open", "-a", app_name, "--background"],
                start_new_session=True,
            )
            logger.info(
                f"[MacLauncher] started with open -a in the background: {app_name}"
            )
            return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(
                f"[MacLauncher] open -a in the background did not start it: {app_name}"
            )

        logger.warning(f"[MacLauncher] every launch method failed: {app_name}")
        return False

    except Exception as e:
        logger.error(f"[MacLauncher] launch failed: {e}", exc_info=True)
        return False
