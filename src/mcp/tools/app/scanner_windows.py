"""Windows application scanner.

Scans and manages applications on Windows
"""

import json
import os
import platform
import subprocess
from typing import Dict, List, Optional

from src.logging import get_logger

logger = get_logger()


def scan_installed_applications() -> List[Dict[str, str]]:
    """Scan the applications installed on this Windows system.

    Returns:
        List[Dict[str, str]]: the list of applications
    """
    if platform.system() != "Windows":
        return []

    apps = []

    # 1. scan the main applications in the Start menu (the most direct route)
    try:
        logger.info("[WindowsScanner] scanning the Start menu for main applications")
        start_menu_apps = _scan_main_start_menu_apps()
        apps.extend(start_menu_apps)
        logger.info(
            f"[WindowsScanner] found {len(start_menu_apps)} main applications in the Start menu"
        )
    except Exception as e:
        logger.warning(f"[WindowsScanner] Start menu scan failed: {e}", exc_info=True)

    # 2. scan the registry for main third-party applications (system components filtered out)
    try:
        logger.info("[WindowsScanner] scanning the installed main applications")
        registry_apps = _scan_main_registry_apps()
        # de-duplicate: do not add Start menu applications twice
        existing_names = {app["display_name"].lower() for app in apps}
        for app in registry_apps:
            if app["display_name"].lower() not in existing_names:
                apps.append(app)
        logger.info(
            f"[WindowsScanner] found {len([a for a in registry_apps if a['display_name'].lower() not in existing_names])} new main applications in the registry"
        )
    except Exception as e:
        logger.warning(f"[WindowsScanner] registry scan failed: {e}", exc_info=True)

    # 3. add the common system applications (only the ones people actually use)
    system_apps = [
        {
            "name": "Calculator",
            "display_name": "Calculator",
            "path": "calc",
            "type": "system",
        },
        {
            "name": "Notepad",
            "display_name": "Notepad",
            "path": "notepad",
            "type": "system",
        },
        {"name": "Paint", "display_name": "Paint", "path": "mspaint", "type": "system"},
        {
            "name": "File Explorer",
            "display_name": "File Explorer",
            "path": "explorer",
            "type": "system",
        },
        {
            "name": "Task Manager",
            "display_name": "Task Manager",
            "path": "taskmgr",
            "type": "system",
        },
        {
            "name": "Control Panel",
            "display_name": "Control Panel",
            "path": "control",
            "type": "system",
        },
        {
            "name": "Settings",
            "display_name": "Settings",
            "path": "ms-settings:",
            "type": "system",
        },
    ]
    apps.extend(system_apps)

    logger.info(
        f"[WindowsScanner] Windows application scan complete, {len(apps)} main applications found"
    )
    return apps


def scan_running_applications() -> List[Dict[str, str]]:
    """Scan the applications currently running on this Windows system.

    Returns:
        List[Dict[str, str]]: the list of running applications
    """
    if platform.system() != "Windows":
        return []

    apps = []

    try:
        # use the tasklist command to get the process information
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/v"], capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[1:]  # skip the header row

            for line in lines:
                try:
                    # parse the CSV format
                    parts = [part.strip('"') for part in line.split('","')]
                    if len(parts) >= 8:
                        image_name = parts[0].strip('"')
                        pid = parts[1]
                        window_title = parts[8] if len(parts) > 8 else ""

                        # filter out the processes we do not want
                        if _should_include_process(image_name, window_title):
                            display_name = _extract_app_name(image_name, window_title)
                            clean_name = clean_app_name(display_name)

                            apps.append(
                                {
                                    "pid": int(pid),
                                    "name": clean_name,
                                    "display_name": display_name,
                                    "command": image_name,
                                    "window_title": window_title,
                                    "type": "application",
                                }
                            )
                except (ValueError, IndexError):
                    continue

        logger.info(f"[WindowsScanner] found {len(apps)} running applications")
        return apps

    except Exception as e:
        logger.error(
            f"[WindowsScanner] scan of running applications failed: {e}", exc_info=True
        )
        return []


def _scan_main_start_menu_apps() -> List[Dict[str, str]]:
    """
    Scan the Start menu for main applications (system components and helper tools filtered out).
    """
    apps = []

    # Start menu directories
    start_menu_paths = [
        os.path.join(
            os.environ.get("PROGRAMDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
        ),
        os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
        ),
    ]

    for start_path in start_menu_paths:
        if os.path.exists(start_path):
            try:
                for root, dirs, files in os.walk(start_path):
                    for file in files:
                        if file.lower().endswith(".lnk"):
                            try:
                                shortcut_path = os.path.join(root, file)
                                display_name = file[:-4]  # strip the .lnk extension

                                # filter out the applications we do not want
                                if _should_include_app(display_name):
                                    clean_name = clean_app_name(display_name)
                                    target_path = _resolve_shortcut_target(
                                        shortcut_path
                                    )

                                    apps.append(
                                        {
                                            "name": clean_name,
                                            "display_name": display_name,
                                            "path": target_path or shortcut_path,
                                            "type": "shortcut",
                                        }
                                    )

                            except Exception as e:
                                logger.debug(
                                    f"[WindowsScanner] failed to handle the shortcut {file}: {e}"
                                )

            except Exception as e:
                logger.debug(
                    f"[WindowsScanner] Start menu scan failed for {start_path}: {e}"
                )

    return apps


def _scan_main_registry_apps() -> List[Dict[str, str]]:
    """
    Scan the registry for main applications (system components filtered out).
    """
    apps = []

    try:
        powershell_cmd = [
            "powershell",
            "-Command",
            "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | "
            "Select-Object DisplayName, InstallLocation, Publisher | "
            "Where-Object {$_.DisplayName -ne $null} | "
            "ConvertTo-Json",
        ]

        result = subprocess.run(
            powershell_cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout:
            try:
                installed_apps = json.loads(result.stdout)
                if isinstance(installed_apps, dict):
                    installed_apps = [installed_apps]

                for app in installed_apps:
                    display_name = app.get("DisplayName", "")
                    publisher = app.get("Publisher", "")

                    if display_name and _should_include_app(display_name, publisher):
                        clean_name = clean_app_name(display_name)
                        apps.append(
                            {
                                "name": clean_name,
                                "display_name": display_name,
                                "path": app.get("InstallLocation", ""),
                                "type": "installed",
                            }
                        )

            except json.JSONDecodeError:
                logger.warning("[WindowsScanner] could not parse the PowerShell output")

    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        logger.warning(f"[WindowsScanner] PowerShell scan failed: {e}", exc_info=True)

    return apps


def _should_include_app(display_name: str, publisher: str = "") -> bool:
    """Decide whether this application should be included.

    Args:
        display_name: the application's display name
        publisher: the publisher (optional)

    Returns:
        bool: whether it should be included
    """
    name_lower = display_name.lower()

    # system components and runtimes that are explicitly excluded
    exclude_keywords = [
        # Microsoft system components
        "microsoft visual c++",
        "microsoft .net",
        "microsoft office",
        "microsoft edge webview",
        "microsoft visual studio",
        "microsoft redistributable",
        "microsoft windows sdk",
        # system tools and drivers
        "uninstall",
        "readme",
        "help",
        "documentation",
        "driver",
        "update",
        "hotfix",
        "patch",
        # development tool components
        "development",
        "sdk",
        "runtime",
        "redistributable",
        "framework",
        "python documentation",
        "python test suite",
        "python executables",
        "java update",
        "java development kit",
        # system services
        "service pack",
        "security update",
        "language pack",
        # useless shortcuts
        "website",
        "web site",
        "online",
        "report",
        "feedback",
    ]

    # check for an exclude keyword
    for keyword in exclude_keywords:
        if keyword in name_lower:
            return False

    # well-known applications that are explicitly included
    include_keywords = [
        # browsers
        "chrome",
        "firefox",
        "edge",
        "safari",
        "opera",
        "brave",
        # office software
        "office",
        "word",
        "excel",
        "powerpoint",
        "outlook",
        "onenote",
        "wps",
        "typora",
        "notion",
        "obsidian",
        # development tools
        "visual studio code",
        "vscode",
        "pycharm",
        "idea",
        "eclipse",
        "git",
        "docker",
        "nodejs",
        "android studio",
        # communication software
        "qq",
        "wechat",
        "skype",
        "zoom",
        "teams",
        "feishu",
        "discord",
        "slack",
        "telegram",
        # media software
        "vlc",
        "potplayer",
        "netease cloud music",
        "spotify",
        "itunes",
        "photoshop",
        "premiere",
        "after effects",
        "illustrator",
        # gaming platforms
        "steam",
        "epic",
        "origin",
        "uplay",
        "battlenet",
        # utilities
        "7-zip",
        "winrar",
        "bandizip",
        "everything",
        "listary",
        "notepad++",
        "sublime",
        "atom",
    ]

    # check for an include keyword
    for keyword in include_keywords:
        if keyword in name_lower:
            return True

    # when a publisher is known, exclude the system components published by Microsoft
    if publisher:
        publisher_lower = publisher.lower()
        if "microsoft corporation" in publisher_lower and any(
            x in name_lower
            for x in [
                "visual c++",
                ".net",
                "redistributable",
                "runtime",
                "framework",
                "update",
            ]
        ):
            return False

    # everything else is included by default (assumed to be user-installed)
    # except the obvious system components
    system_indicators = ["(x64)", "(x86)", "redistributable", "runtime", "framework"]
    if any(indicator in name_lower for indicator in system_indicators):
        return False

    return True


def _should_include_process(image_name: str, window_title: str) -> bool:
    """Decide whether this process should be included.

    Args:
        image_name: the process image name
        window_title: the window title

    Returns:
        bool: whether it is included
    """
    # exclude the system processes
    system_processes = {
        "dwm.exe",
        "winlogon.exe",
        "csrss.exe",
        "smss.exe",
        "lsass.exe",
        "services.exe",
        "svchost.exe",
        "explorer.exe",
        "taskhostw.exe",
        "conhost.exe",
        "dllhost.exe",
        "rundll32.exe",
        "msiexec.exe",
        "wininit.exe",
        "lsm.exe",
        "spoolsv.exe",
        "audiodg.exe",
    }

    image_lower = image_name.lower()

    # exclude the system processes
    if image_lower in system_processes:
        return False

    # exclude processes with no window title (usually background services)
    if not window_title or window_title == "N/A":
        return False

    # only keep meaningful window titles
    if len(window_title.strip()) < 3:
        return False

    return True


def _extract_app_name(image_name: str, window_title: str) -> str:
    """Derive the application name from the process information.

    Args:
        image_name: the process image name
        window_title: the window title

    Returns:
        str: the application name
    """
    # prefer the window title
    if window_title and window_title != "N/A" and len(window_title.strip()) > 0:
        return window_title.strip()

    # otherwise use the process name (with the .exe suffix removed)
    if image_name.lower().endswith(".exe"):
        return image_name[:-4]

    return image_name


def _resolve_shortcut_target(shortcut_path: str) -> Optional[str]:
    """Resolve the target path of a Windows shortcut.

    Args:
        shortcut_path: the path to the shortcut file

    Returns:
        the target path, or None when it cannot be resolved
    """
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        target_path = shortcut.Targetpath

        if target_path and os.path.exists(target_path):
            return target_path

    except ImportError:
        logger.debug(
            "[WindowsScanner] the win32com module is unavailable, cannot resolve shortcuts"
        )
    except Exception as e:
        logger.debug(f"[WindowsScanner] failed to resolve the shortcut: {e}")

    return None


from .utils import clean_app_name
