"""Application launcher for Windows.

Starts applications on Windows.
Every subprocess call passes a list; none use shell=True.
"""

import base64
import os
import subprocess

from src.logging import get_logger

logger = get_logger()

# the Windows process-creation flags (only available on Windows)
_DETACHED_PROCESS = 0x00000008


def launch_application(app_name: str) -> bool:
    """Start an application on Windows.

    Args:
        app_name: the application name

    Returns:
        bool: whether it started
    """
    try:
        logger.info(f"[WindowsLauncher] starting: {app_name}")

        # try the launch methods in order of preference
        launch_methods = [
            ("PowerShell Start-Process", _try_powershell_start),
            ("os.startfile", _try_os_startfile),
            ("registry lookup", _try_registry_launch),
            ("common paths", _try_common_paths),
            ("the where command", _try_where_command),
            ("UWP app", _try_uwp_launch),
        ]

        for method_name, method_func in launch_methods:
            try:
                if method_func(app_name):
                    logger.info(
                        f"[WindowsLauncher] {method_name} started it: {app_name}"
                    )
                    return True
                else:
                    logger.debug(
                        f"[WindowsLauncher] {method_name} did not start it: {app_name}"
                    )
            except Exception as e:
                logger.debug(f"[WindowsLauncher] {method_name} raised: {e}")

        logger.warning(f"[WindowsLauncher] every launch method failed: {app_name}")
        return False

    except Exception as e:
        logger.error(f"[WindowsLauncher] launch raised: {e}", exc_info=True)
        return False


def launch_uwp_app_by_path(uwp_path: str) -> bool:
    """Start an application from its UWP path.

    Args:
        uwp_path: the UWP application path (shell:AppsFolder\\... form)

    Returns:
        bool: whether it started
    """
    try:
        if uwp_path.startswith("shell:AppsFolder\\"):
            subprocess.Popen(
                ["explorer.exe", uwp_path],
                creationflags=_DETACHED_PROCESS,
            )
            logger.info(f"[WindowsLauncher] UWP app started: {uwp_path}")
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"[WindowsLauncher] UWP app failed to start: {e}", exc_info=True)
        return False


def launch_shortcut(shortcut_path: str) -> bool:
    """Start a shortcut file.

    Args:
        shortcut_path: the path to the shortcut

    Returns:
        bool: whether it started
    """
    try:
        os.startfile(shortcut_path)
        logger.info(f"[WindowsLauncher] shortcut started: {shortcut_path}")
        return True
    except Exception as e:
        logger.error(f"[WindowsLauncher] shortcut failed to start: {e}", exc_info=True)
        return False


def _try_powershell_start(app_name: str) -> bool:
    """Try starting it with PowerShell Start-Process."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Start-Process", "-FilePath", app_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _try_os_startfile(app_name: str) -> bool:
    """Try starting it with os.startfile."""
    try:
        os.startfile(app_name)
        return True
    except OSError:
        return False


def _try_registry_launch(app_name: str) -> bool:
    """Try finding it in the registry and starting it."""
    try:
        executable_path = _find_executable_in_registry(app_name)
        if executable_path:
            subprocess.Popen(
                [executable_path],
                creationflags=_DETACHED_PROCESS,
            )
            return True
    except Exception as e:
        logger.debug(f"[WindowsLauncher] registry lookup failed: {e}")
    return False


def _try_common_paths(app_name: str) -> bool:
    """Try the common application paths."""
    username = os.getenv("USERNAME", "")
    common_paths = [
        f"C:\\Program Files\\{app_name}\\{app_name}.exe",
        f"C:\\Program Files (x86)\\{app_name}\\{app_name}.exe",
        f"C:\\Users\\{username}\\AppData\\Local\\Programs\\{app_name}\\{app_name}.exe",
        f"C:\\Users\\{username}\\AppData\\Local\\{app_name}\\{app_name}.exe",
        f"C:\\Users\\{username}\\AppData\\Roaming\\{app_name}\\{app_name}.exe",
    ]

    for path in common_paths:
        if os.path.exists(path):
            try:
                subprocess.Popen(
                    [path],
                    creationflags=_DETACHED_PROCESS,
                )
                return True
            except Exception:
                continue
    return False


def _try_where_command(app_name: str) -> bool:
    """Try finding it with the where command and starting it."""
    try:
        result = subprocess.run(
            ["where", app_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            exe_path = result.stdout.strip().split("\n")[0]
            if exe_path and os.path.exists(exe_path):
                subprocess.Popen(
                    [exe_path],
                    creationflags=_DETACHED_PROCESS,
                )
                return True
    except Exception as e:
        logger.debug(f"[WindowsLauncher] where.exe lookup failed: {e}")
    return False


def _try_uwp_launch(app_name: str) -> bool:
    """Try starting it as a UWP app."""
    try:
        return _launch_uwp_app(app_name)
    except Exception:
        return False


def _find_executable_in_registry(app_name: str) -> str | None:
    """Find an application's executable path in the registry.

    Args:
        app_name: the application name

    Returns:
        the application path, or None when it is not found
    """
    try:
        import winreg

        registry_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]

        for registry_path in registry_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                try:
                                    display_name = winreg.QueryValueEx(
                                        subkey, "DisplayName"
                                    )[0]
                                    if app_name.lower() in display_name.lower():
                                        try:
                                            install_location = winreg.QueryValueEx(
                                                subkey, "InstallLocation"
                                            )[0]
                                            if install_location and os.path.exists(
                                                install_location
                                            ):
                                                for root, _dirs, files in os.walk(
                                                    install_location
                                                ):
                                                    for file in files:
                                                        if (
                                                            file.lower().endswith(
                                                                ".exe"
                                                            )
                                                            and app_name.lower()
                                                            in file.lower()
                                                        ):
                                                            return os.path.join(
                                                                root, file
                                                            )
                                        except FileNotFoundError:
                                            pass

                                        try:
                                            display_icon = winreg.QueryValueEx(
                                                subkey, "DisplayIcon"
                                            )[0]
                                            if (
                                                display_icon
                                                and display_icon.endswith(".exe")
                                                and os.path.exists(display_icon)
                                            ):
                                                return display_icon
                                        except FileNotFoundError:
                                            pass

                                except FileNotFoundError:
                                    continue
                        except Exception:
                            continue
            except Exception:
                continue

        return None

    except ImportError:
        logger.debug(
            "[WindowsLauncher] the winreg module is unavailable, skipping the registry lookup"
        )
        return None
    except Exception as e:
        logger.debug(f"[WindowsLauncher] registry lookup failed: {e}")
        return None


def _launch_uwp_app(app_name: str) -> bool:
    """Try starting a UWP (Windows Store) application.

    The application name goes through the $env:_APP_QUERY environment variable,
    so user input is never interpolated into the PowerShell script.

    Args:
        app_name: the application name

    Returns:
        whether it started
    """
    try:
        # the script reads the query from the environment; no user input is embedded in it
        powershell_script = (
            "$q = $env:_APP_QUERY\n"
            "$app = Get-AppxPackage "
            '| Where-Object {$_.Name -like "*$q*" '
            '-or $_.PackageFullName -like "*$q*"} '
            "| Select-Object -First 1\n"
            "if ($app) {\n"
            "    $manifest = Get-AppxPackageManifest $app.PackageFullName\n"
            "    $appId = $manifest.Package.Applications.Application.Id\n"
            "    if ($appId) {\n"
            '        Start-Process "shell:AppsFolder\\$($app.PackageFullName)!$appId"\n'
            '        Write-Output "Success"\n'
            "    }\n"
            "}"
        )

        encoded = base64.b64encode(powershell_script.encode("utf-16-le")).decode(
            "ascii"
        )

        env = os.environ.copy()
        env["_APP_QUERY"] = app_name

        result = subprocess.run(
            ["powershell", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        if result.returncode == 0 and "Success" in result.stdout:
            return True

    except Exception as e:
        logger.debug(f"[WindowsLauncher] UWP launch raised: {e}")

    return False
