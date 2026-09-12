"""Application launcher for Linux.

Starts applications on Linux.
Every subprocess call passes a list; none use shell=True.
"""

import os
import subprocess

from src.logging import get_logger

logger = get_logger()


def launch_application(app_name: str) -> bool:
    """Start an application on Linux.

    Args:
        app_name: the application name

    Returns:
        bool: whether it started
    """
    try:
        logger.info(f"[LinuxLauncher] starting: {app_name}")

        # 1: run the application name directly
        try:
            subprocess.Popen(
                [app_name],
                start_new_session=True,
            )
            logger.info(f"[LinuxLauncher] started directly: {app_name}")
            return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(f"[LinuxLauncher] could not start it directly: {app_name}")

        # 2: find its path with which
        try:
            result = subprocess.run(
                ["which", app_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                app_path = result.stdout.strip()
                subprocess.Popen(
                    [app_path],
                    start_new_session=True,
                )
                logger.info(f"[LinuxLauncher] started via which: {app_name}")
                return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(f"[LinuxLauncher] which did not start it: {app_name}")

        # 3: xdg-open (for desktop environments)
        try:
            subprocess.Popen(
                ["xdg-open", app_name],
                start_new_session=True,
            )
            logger.info(f"[LinuxLauncher] started via xdg-open: {app_name}")
            return True
        except (OSError, subprocess.SubprocessError):
            logger.debug(f"[LinuxLauncher] xdg-open did not start it: {app_name}")

        # 4: try the common application paths
        common_paths = [
            f"/usr/bin/{app_name}",
            f"/usr/local/bin/{app_name}",
            f"/opt/{app_name}/{app_name}",
            f"/snap/bin/{app_name}",
        ]

        for path in common_paths:
            if os.path.exists(path):
                subprocess.Popen(
                    [path],
                    start_new_session=True,
                )
                logger.info(
                    f"[LinuxLauncher] started from a common path: {app_name} ({path})"
                )
                return True

        # 5: try the .desktop file
        desktop_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            os.path.expanduser("~/.local/share/applications"),
        ]

        for desktop_dir in desktop_dirs:
            desktop_file = os.path.join(desktop_dir, f"{app_name}.desktop")
            if os.path.exists(desktop_file):
                subprocess.Popen(
                    ["gtk-launch", f"{app_name}.desktop"],
                    start_new_session=True,
                )
                logger.info(
                    f"[LinuxLauncher] started via its .desktop file: {app_name}"
                )
                return True

        logger.warning(f"[LinuxLauncher] every launch method failed: {app_name}")
        return False

    except Exception as e:
        logger.error(f"[LinuxLauncher] launch failed: {e}", exc_info=True)
        return False
