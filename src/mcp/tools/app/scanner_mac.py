"""macOS application scanner.

Scans and manages applications on macOS
"""

import platform
import subprocess
from pathlib import Path
from typing import Dict, List

from src.logging import get_logger

logger = get_logger()


def scan_installed_applications() -> List[Dict[str, str]]:
    """Scan the applications installed on this macOS system.

    Returns:
        List[Dict[str, str]]: the list of applications
    """
    if platform.system() != "Darwin":
        return []

    apps = []

    # scan /Applications
    applications_dir = Path("/Applications")
    if applications_dir.exists():
        for app_path in applications_dir.glob("*.app"):
            app_name = app_path.stem
            clean_name = clean_app_name(app_name)
            apps.append(
                {
                    "name": clean_name,
                    "display_name": app_name,
                    "path": str(app_path),
                    "type": "application",
                }
            )

    # scan the user's own Applications directory
    user_apps_dir = Path.home() / "Applications"
    if user_apps_dir.exists():
        for app_path in user_apps_dir.glob("*.app"):
            app_name = app_path.stem
            clean_name = clean_app_name(app_name)
            apps.append(
                {
                    "name": clean_name,
                    "display_name": app_name,
                    "path": str(app_path),
                    "type": "user_application",
                }
            )

    # add the common system applications
    system_apps = [
        {
            "name": "Calculator",
            "display_name": "Calculator",
            "path": "Calculator",
            "type": "system",
        },
        {
            "name": "TextEdit",
            "display_name": "TextEdit",
            "path": "TextEdit",
            "type": "system",
        },
        {
            "name": "Preview",
            "display_name": "Preview",
            "path": "Preview",
            "type": "system",
        },
        {
            "name": "Safari",
            "display_name": "Safari",
            "path": "Safari",
            "type": "system",
        },
        {
            "name": "Finder",
            "display_name": "Finder",
            "path": "Finder",
            "type": "system",
        },
        {
            "name": "Terminal",
            "display_name": "Terminal",
            "path": "Terminal",
            "type": "system",
        },
        {
            "name": "System Preferences",
            "display_name": "System Settings",
            "path": "System Preferences",
            "type": "system",
        },
    ]
    apps.extend(system_apps)

    logger.info(f"[MacScanner] scan complete, {len(apps)} applications found")
    return apps


def scan_running_applications() -> List[Dict[str, str]]:
    """Scan the applications currently running on this macOS system.

    Returns:
        List[Dict[str, str]]: the list of running applications
    """
    if platform.system() != "Darwin":
        return []

    apps = []

    try:
        # use the ps command to get the process information
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,comm,command"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[1:]  # skip the header row

            for line in lines:
                parts = line.strip().split(None, 3)
                if len(parts) >= 4:
                    pid, ppid, comm, command = parts

                    # filter out the processes we do not want
                    if _should_include_process(comm, command):
                        display_name = _extract_app_name(comm, command)
                        clean_name = clean_app_name(display_name)

                        apps.append(
                            {
                                "pid": int(pid),
                                "ppid": int(ppid),
                                "name": clean_name,
                                "display_name": display_name,
                                "command": command,
                                "type": "application",
                            }
                        )

        logger.info(f"[MacScanner] found {len(apps)} running applications")
        return apps

    except Exception as e:
        logger.error(
            f"[MacScanner] scan of running applications failed: {e}", exc_info=True
        )
        return []


def _should_include_process(comm: str, command: str) -> bool:
    """Decide whether this process should be included.

    Args:
        comm: the process name
        command: the full command line

    Returns:
        bool: whether it is included
    """
    # exclude the system processes and services
    system_processes = {
        # core system processes
        "kernel_task",
        "launchd",
        "kextd",
        "UserEventAgent",
        "cfprefsd",
        "loginwindow",
        "WindowServer",
        "SystemUIServer",
        "Dock",
        "Finder",
        "ControlCenter",
        "NotificationCenter",
        "WallpaperAgent",
        "Spotlight",
        "WiFiAgent",
        "CoreLocationAgent",
        "bluetoothd",
        "wirelessproxd",
        # system services
        "com.apple.",
        "suhelperd",
        "softwareupdated",
        "cloudphotod",
        "identityservicesd",
        "imagent",
        "sharingd",
        "remindd",
        "contactsd",
        "accountsd",
        "CallHistorySyncHelper",
        "CallHistoryPluginHelper",
        # drivers and extensions
        "AppleSpell",
        "coreaudiod",
        "audio",
        "webrtc",
        "chrome_crashpad_handler",
        "crashpad_handler",
        "fsnotifier",
        "mdworker",
        "mds",
        "spotlight",
        # other system components
        "automountd",
        "autofsd",
        "aslmanager",
        "syslogd",
        "ntpd",
        "mDNSResponder",
        "distnoted",
        "notifyd",
        "powerd",
        "thermalmonitord",
        "watchdogd",
    }

    # check whether it is a system process
    comm_lower = comm.lower()
    command_lower = command.lower()

    # exclude empty names and system paths
    if not comm or comm_lower in system_processes:
        return False

    # exclude processes living under the system paths
    if any(
        path in command_lower
        for path in [
            "/system/library/",
            "/library/apple/",
            "/usr/libexec/",
            "/system/applications/utilities/",
            "/private/var/",
            "com.apple.",
            ".xpc/",
            ".framework/",
            ".appex/",
            "helper (gpu)",
            "helper (renderer)",
            "helper (plugin)",
            "crashpad_handler",
            "fsnotifier",
        ]
    ):
        return False

    # exclude the obvious system services
    if any(
        keyword in command_lower
        for keyword in [
            "xpcservice",
            "daemon",
            "agent",
            "service",
            "monitor",
            "updater",
            "sync",
            "backup",
            "cache",
            "log",
        ]
    ):
        return False

    # only include user applications
    user_app_indicators = ["/applications/", "/users/", "~/", ".app/contents/macos/"]

    return any(indicator in command_lower for indicator in user_app_indicators)


def _extract_app_name(comm: str, command: str) -> str:
    """Derive the application name from the process information.

    Args:
        comm: the process name
        command: the full command line

    Returns:
        str: the application name
    """
    # try to pull the .app name out of the command path
    if ".app/Contents/MacOS/" in command:
        try:
            app_path = command.split(".app/Contents/MacOS/")[0] + ".app"
            app_name = Path(app_path).name.replace(".app", "")
            return app_name
        except (IndexError, AttributeError):
            pass

    # try the /Applications/ path
    if "/Applications/" in command:
        try:
            parts = command.split("/Applications/")[1].split("/")[0]
            if parts.endswith(".app"):
                return parts.replace(".app", "")
        except (IndexError, AttributeError):
            pass

    # fall back to the process name
    return comm if comm else "Unknown"


from .utils import clean_app_name
