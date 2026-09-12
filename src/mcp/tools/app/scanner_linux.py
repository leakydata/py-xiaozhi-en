"""Linux application scanner.

Scans and manages applications on Linux
"""

import platform
import subprocess
from pathlib import Path
from typing import Dict, List

from src.logging import get_logger

logger = get_logger()


def scan_installed_applications() -> List[Dict[str, str]]:
    """Scan the applications installed on this Linux system.

    Returns:
        List[Dict[str, str]]: the list of applications
    """
    if platform.system() != "Linux":
        return []

    apps = []

    # scan the .desktop files
    desktop_dirs = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        Path.home() / ".local/share/applications",
    ]

    for desktop_dir in desktop_dirs:
        desktop_path = Path(desktop_dir)
        if desktop_path.exists():
            for desktop_file in desktop_path.glob("*.desktop"):
                try:
                    app_info = _parse_desktop_file(desktop_file)
                    if app_info and _should_include_app(app_info["display_name"]):
                        apps.append(app_info)
                except Exception as e:
                    logger.debug(
                        f"[LinuxScanner] failed to parse the desktop file {desktop_file}: {e}"
                    )

    # add the common Linux system applications
    system_apps = [
        {
            "name": "gedit",
            "display_name": "Text Editor",
            "path": "gedit",
            "type": "system",
        },
        {
            "name": "firefox",
            "display_name": "Firefox",
            "path": "firefox",
            "type": "system",
        },
        {
            "name": "gnome-calculator",
            "display_name": "Calculator",
            "path": "gnome-calculator",
            "type": "system",
        },
        {
            "name": "nautilus",
            "display_name": "Files",
            "path": "nautilus",
            "type": "system",
        },
        {
            "name": "gnome-terminal",
            "display_name": "Terminal",
            "path": "gnome-terminal",
            "type": "system",
        },
        {
            "name": "gnome-control-center",
            "display_name": "Settings",
            "path": "gnome-control-center",
            "type": "system",
        },
    ]
    apps.extend(system_apps)

    logger.info(f"[LinuxScanner] scan complete, {len(apps)} applications found")
    return apps


def scan_running_applications() -> List[Dict[str, str]]:
    """Scan the applications currently running on this Linux system.

    Returns:
        List[Dict[str, str]]: the list of running applications
    """
    if platform.system() != "Linux":
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

        logger.info(f"[LinuxScanner] found {len(apps)} running applications")
        return apps

    except Exception as e:
        logger.error(f"[LinuxScanner] scan of running applications failed: {e}", exc_info=True)
        return []


def _parse_desktop_file(desktop_file: Path) -> Dict[str, str]:
    """Parse a .desktop file.

    Args:
        desktop_file: the path to the .desktop file

    Returns:
        Dict[str, str]: the application record
    """
    try:
        with open(desktop_file, "r", encoding="utf-8") as f:
            content = f.read()

        # parse the .desktop file
        name = ""
        display_name = ""
        exec_cmd = ""

        for line in content.split("\n"):
            if line.startswith("Name="):
                display_name = line.split("=", 1)[1]
            elif line.startswith("Exec="):
                exec_cmd = line.split("=", 1)[1].split()[0]  # take the first command

        if display_name and exec_cmd:
            name = clean_app_name(display_name)
            return {
                "name": name,
                "display_name": display_name,
                "path": exec_cmd,
                "type": "desktop",
            }

        return None

    except Exception:
        return None


def _should_include_app(display_name: str) -> bool:
    """Decide whether this application should be included.

    Args:
        display_name: the application's display name

    Returns:
        bool: whether it is included
    """
    if not display_name:
        return False

    # the application patterns to exclude
    exclude_patterns = [
        # system components
        "gnome-",
        "kde-",
        "xfce-",
        "unity-",
        # development tool components
        "gdb",
        "valgrind",
        "strace",
        "ltrace",
        # system tools
        "dconf",
        "gsettings",
        "xdg-",
        "desktop-file-",
        # other system components
        "help",
        "about",
        "preferences",
        "settings",
    ]

    display_lower = display_name.lower()

    # check the exclude patterns
    for pattern in exclude_patterns:
        if pattern in display_lower:
            return False

    return True


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
        # kernel and core processes
        "kthreadd",
        "ksoftirqd",
        "migration",
        "rcu_",
        "watchdog",
        "systemd",
        "init",
        "kernel",
        "kworker",
        "kcompactd",
        # system services
        "dbus",
        "networkd",
        "resolved",
        "logind",
        "udevd",
        "cron",
        "rsyslog",
        "ssh",
        "avahi",
        "cups",
        # desktop environment services
        "gnome-",
        "kde-",
        "xfce-",
        "unity-",
        "compiz",
        "pulseaudio",
        "pipewire",
        "wireplumber",
        # X11/Wayland
        "Xorg",
        "wayland",
        "weston",
        "mutter",
        "kwin",
    }

    # check whether it is a system process
    comm_lower = comm.lower()
    command_lower = command.lower()

    # exclude empty names and system processes
    if not comm or any(proc in comm_lower for proc in system_processes):
        return False

    # exclude processes living under the system paths
    if any(
        path in command_lower
        for path in [
            "/usr/libexec/",
            "/usr/lib/",
            "/lib/",
            "/sbin/",
            "/usr/sbin/",
            "/bin/systemd",
            "/usr/bin/dbus",
        ]
    ):
        return False

    # exclude the obvious system services
    if any(
        keyword in command_lower
        for keyword in ["daemon", "service", "helper", "agent", "monitor"]
    ):
        return False

    # only include user applications
    user_app_indicators = [
        "/usr/bin/",
        "/usr/local/bin/",
        "/opt/",
        "/home/",
        "/snap/",
        "/flatpak/",
    ]

    return any(indicator in command_lower for indicator in user_app_indicators)


def _extract_app_name(comm: str, command: str) -> str:
    """Derive the application name from the process information.

    Args:
        comm: the process name
        command: the full command line

    Returns:
        str: the application name
    """
    # try to get the application name out of the command path
    if "/" in command:
        try:
            # take the executable's file name
            exec_path = command.split()[0]
            app_name = Path(exec_path).name

            # strip the common suffixes
            if app_name.endswith(".py"):
                app_name = app_name[:-3]
            elif app_name.endswith(".sh"):
                app_name = app_name[:-3]

            return app_name
        except (IndexError, AttributeError):
            pass

    # fall back to the process name
    return comm if comm else "Unknown"


from .utils import clean_app_name
