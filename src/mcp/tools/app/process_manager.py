"""Cross-platform process management, built on psutil.

psutil replaces every platform-specific subprocess call for listing and killing
processes, which removes the command-injection risk those carried.
"""

import sys

import psutil

from src.logging import get_logger

from .utils import AppMatcher

logger = get_logger()

# Electron/Chromium child-process suffixes - these are internal children of the main app
_HELPER_SUFFIXES = (
    " helper",
    " helper (gpu)",
    " helper (renderer)",
    " helper (plugin)",
    "_crashpad_handler",
)

# macOS system path prefixes; anything under these is a system daemon
_MACOS_SYSTEM_PREFIXES = (
    "/usr/libexec/",
    "/usr/sbin/",
    "/System/Library/",
    "/Library/Apple/",
)

# Windows system process names (lowercase, without .exe)
_WINDOWS_SYSTEM_NAMES: set[str] = {
    "dwm",
    "winlogon",
    "csrss",
    "smss",
    "wininit",
    "services",
    "lsass",
    "svchost",
    "spoolsv",
    "taskhostw",
    "fontdrvhost",
    "dllhost",
    "ctfmon",
    "audiodg",
    "conhost",
    "sihost",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "runtimebroker",
    "applicationframehost",
    "searchui",
    "lockapp",
    "explorer",
}


def _is_user_application(name: str, exe: str) -> bool:
    """Whether this process is an application the user can see."""
    name_lower = name.lower()
    exe_lower = exe.lower()

    # exclude the Electron/Chromium children (Helper, Renderer, GPU)
    if any(name_lower.endswith(suffix) for suffix in _HELPER_SUFFIXES):
        return False

    if sys.platform == "darwin":
        # macOS: keep only the main .app process under /Applications/
        if "/Applications/" in exe and ".app/" in exe:
            # exclude the nested .apps inside one (Framework/Helpers/ and the like)
            app_path = exe[: exe.index(".app/") + 5]
            remaining = exe[len(app_path) :]
            if ".app/" in remaining:
                return False
            return True
        # outside /Applications but not a system path either (tools under ~/Library/Application Support, say)
        if any(exe_lower.startswith(p) for p in _MACOS_SYSTEM_PREFIXES):
            return False
        # user tools under /Library/Application Support (security software, VPNs)
        if "/Library/Application Support/" in exe and ".app" not in exe:
            return False
        # the other known system process paths
        if exe_lower.startswith("/system/") or exe_lower.startswith("/library/"):
            return False
        return False

    elif sys.platform == "win32":
        if name_lower.replace(".exe", "") in _WINDOWS_SYSTEM_NAMES:
            return False
        # exclude the processes in the Windows system directories
        if "\\windows\\system32\\" in exe_lower:
            return False
        if "\\windows\\syswow64\\" in exe_lower:
            return False
        return True

    else:
        # Linux: exclude the system daemons
        if exe_lower.startswith(("/usr/libexec/", "/usr/sbin/")):
            return False
        if exe_lower.startswith("/usr/bin/") and name_lower in {
            "dbus-daemon",
            "dbus-broker",
            "at-spi-bus-launcher",
            "pulseaudio",
            "pipewire",
            "systemd",
        }:
            return False
        return True


def list_running_applications(filter_name: str = "") -> list[dict]:
    """List the running user applications.

    Only the desktop applications the user can see - no system daemons, no Electron children.

    Args:
        filter_name: an optional name filter; passing one relaxes the filtering (used when matching for a kill)
    """
    apps: list[dict] = []
    filter_lower = filter_name.lower() if filter_name else ""

    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "status"]):
        try:
            info = proc.info
            name = info.get("name") or ""
            exe = info.get("exe") or ""
            pid = info.get("pid", 0)
            if not name or pid <= 4:
                continue

            # relax the conditions when filtering (a kill needs to match the child processes too)
            if filter_lower:
                name_lower = name.lower()
                exe_lower = exe.lower()
                cmd = " ".join(info.get("cmdline") or [])
                cmd_lower = cmd.lower()
                if (
                    filter_lower not in name_lower
                    and filter_lower not in exe_lower
                    and filter_lower not in cmd_lower
                ):
                    continue
                apps.append(
                    {
                        "pid": pid,
                        "name": name,
                        "display_name": name,
                        "exe": exe,
                        "command": cmd,
                        "type": "application",
                    }
                )
            else:
                # without a filter: strictly user applications only
                if not _is_user_application(name, exe):
                    continue
                apps.append(
                    {
                        "pid": pid,
                        "name": name,
                        "display_name": name,
                        "exe": exe,
                        "command": " ".join(info.get("cmdline") or []),
                        "type": "application",
                    }
                )

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # sort by name and de-duplicate
    seen_pids: set[int] = set()
    unique_apps: list[dict] = []
    for app in sorted(apps, key=lambda x: x["name"].lower()):
        if app["pid"] not in seen_pids:
            seen_pids.add(app["pid"])
            unique_apps.append(app)

    return unique_apps


def kill_process(pid: int, force: bool = False) -> bool:
    """Kill the process with this PID.

    Args:
        pid: the process ID
        force: True uses SIGKILL/TerminateProcess, False uses SIGTERM

    Returns:
        whether it was killed
    """
    try:
        proc = psutil.Process(pid)
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                logger.warning(
                    f"[ProcessManager] process {pid} did not exit within the timeout, killing it"
                )
                proc.kill()
        return True
    except psutil.NoSuchProcess:
        logger.warning(f"[ProcessManager] no such process: {pid}")
        return False
    except psutil.AccessDenied as e:
        logger.warning(
            f"[ProcessManager] not permitted to kill process {pid}: {e}", exc_info=True
        )
        return False


def find_matching_processes(app_name: str) -> list[dict]:
    """Find the running processes matching an application name.

    AppMatcher does the matching, aliases and fuzzy matching included.

    Args:
        app_name: the application name to look for

    Returns:
        the matching process records, best match first
    """
    all_apps = list_running_applications()
    matched: list[tuple[int, dict]] = []

    for app in all_apps:
        score = AppMatcher.match_application(app_name, app)
        if score >= 50:
            matched.append((score, app))

    matched.sort(key=lambda x: x[0], reverse=True)
    return [app for _, app in matched]


def kill_application_by_name(app_name: str, force: bool = False) -> bool:
    """Kill an application by name, taking every related process with it.

    Args:
        app_name: the application name
        force: whether to kill rather than terminate

    Returns:
        whether at least one process was killed
    """
    matched = find_matching_processes(app_name)
    if not matched:
        logger.info(f"[ProcessManager] no running process matched: {app_name}")
        return False

    logger.info(f"[ProcessManager] {len(matched)} processes matched: {app_name}")

    # grouped by process group, so the children go before the parent
    success_count = 0
    for app in matched:
        pid = app["pid"]
        try:
            proc = psutil.Process(pid)
            # children first
            children = proc.children(recursive=True)
            for child in children:
                try:
                    if force:
                        child.kill()
                    else:
                        child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # then the main process
            if kill_process(pid, force):
                success_count += 1
                logger.info(f"[ProcessManager] killed: {app['name']} (PID={pid})")
        except psutil.NoSuchProcess:
            logger.debug(f"[ProcessManager] process already gone: PID={pid}")
        except psutil.AccessDenied as e:
            logger.warning(
                f"[ProcessManager] not permitted to act on process PID={pid}: {e}",
                exc_info=True,
            )

    logger.info(
        f"[ProcessManager] kill complete, {success_count}/{len(matched)} processes"
    )
    return success_count > 0
