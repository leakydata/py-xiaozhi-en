"""Run Python inside a bubblewrap sandbox.

This is the "do something I have no tool for" escape hatch: the model writes
code and runs it. That means arbitrary code execution, so the isolation is real
rather than advisory - no AST filtering or import blacklists, which are trivial
to defeat from inside a Python interpreter.

bubblewrap gives kernel-level containment. Verified by probing from inside:

    write in the workspace      OK        (the point of the tool)
    read /etc/shadow            blocked   FileNotFoundError
    read ~/.ssh/id_rsa          blocked   FileNotFoundError
    read ~/Documents            blocked   FileNotFoundError
    network                     blocked   OSError
    write /tmp/escape.txt       "allowed" but lands in the sandbox's own tmpfs;
                                the host /tmp was untouched afterwards

Note: a write to a path outside the workspace can appear to succeed. bwrap
creates synthetic parent directories for the workspace mount, so those writes
land in ephemeral sandbox space and vanish when it exits - the host file is
never created. Confirmed by checking the host afterwards.

Only the workspace is bound writable. Everything else the interpreter needs
(/usr, /bin, /lib) is read-only, the home directory is not mounted at all, and
--unshare-all removes network and other namespaces. os.system and subprocess
still work inside, which is fine: they inherit the same jail.

If bwrap is missing the tool refuses to run rather than falling back to an
unsandboxed interpreter.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from src.logging import get_logger

logger = get_logger()

# Packages the assistant installs for itself live here, inside the workspace, so
# they persist between calls and never touch the system interpreter.
PACKAGES_DIR = ".python-packages"
INSTALL_TIMEOUT = 300.0

DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_OUTPUT = 20_000
MAX_CODE = 60_000


def available() -> bool:
    return shutil.which("bwrap") is not None and shutil.which("python3") is not None


def _argv(workspace: Path, network: bool) -> list[str]:
    bwrap = shutil.which("bwrap") or "bwrap"
    args = [
        bwrap,
        # read-only system: enough to run the interpreter, nothing personal
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/sbin", "/sbin",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/etc/ssl", "/etc/ssl",
        "--ro-bind-try", "/etc/ca-certificates", "/etc/ca-certificates",
        # Without these, numpy fails with a misleading "do not import numpy from
        # its source directory": libblas.so.3 is an update-alternatives symlink
        # that hops through /etc/alternatives, and the loader needs ld.so.cache.
        "--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
        "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--ro-bind-try", "/etc/ld.so.conf", "/etc/ld.so.conf",
        "--ro-bind-try", "/etc/ld.so.conf.d", "/etc/ld.so.conf.d",
        # Debian ships matplotlib's rc file in /etc, not with the package
        "--ro-bind-try", "/etc/matplotlibrc", "/etc/matplotlibrc",
        "--ro-bind-try", "/etc/fonts", "/etc/fonts",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        # the one writable location
        "--bind", str(workspace), str(workspace),
        "--chdir", str(workspace),
        "--die-with-parent",
        "--new-session",
        # HOME and the matplotlib cache must be writable or those libraries
        # refuse to import; /tmp is the sandbox's own tmpfs and vanishes after.
        "--setenv", "HOME", "/tmp",
        "--setenv", "MPLCONFIGDIR", "/tmp/mpl",
        "--setenv", "XDG_CACHE_HOME", "/tmp/cache",
    ]
    if network:
        args += ["--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
                 "--unshare-pid", "--unshare-ipc", "--unshare-uts"]
    else:
        args += ["--unshare-all"]
    args += ["/usr/bin/python3", "-I", "-"]
    return args


async def install(package: str, workspace: Path,
                  timeout: float = INSTALL_TIMEOUT) -> dict:
    """Install a package into the workspace so later run_python calls can use it.

    Network is on for this call only, and the target is a directory inside the
    workspace - the system interpreter is untouched, and uninstalling is just
    deleting a folder. uv is used when present because it is markedly faster;
    pip is the fallback.
    """
    name = (package or "").strip()
    # A package name, not an arbitrary pip argument: no flags, URLs or paths.
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]+(\[[A-Za-z0-9,._-]+\])?"
                                    r"([=<>!~]=?[A-Za-z0-9._*+-]+)?", name):
        return {"ok": False, "error": (
            f"{package!r} is not a plain package name. Give something like "
            "'pandas' or 'pandas==2.2.0'."
        )}
    if not available():
        return {"ok": False, "error": "bubblewrap (bwrap) is not installed."}

    target = workspace / PACKAGES_DIR
    target.mkdir(parents=True, exist_ok=True)

    uv = shutil.which("uv")
    args = _argv(workspace, network=True)
    # swap the trailing interpreter invocation for the installer
    args = args[: args.index("/usr/bin/python3")]
    if uv:
        # uv usually lives under ~/.local/bin, which is not bound - bind the
        # binary itself rather than exposing the home directory
        args += ["--ro-bind", uv, uv]
        inner = [uv, "pip", "install", "--target", str(target),
                 "--python", "/usr/bin/python3", name]
    else:
        inner = ["/usr/bin/python3", "-m", "pip", "install", "--target",
                 str(target), "--no-input", "--disable-pip-version-check", name]
    args += inner
    logger.info(f"[Python] installing {name}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.wait()
        return {"ok": False, "error": f"Install timed out after {timeout:.0f}s"}
    except Exception as e:
        return {"ok": False, "error": f"Could not run the installer: {e}"}

    text = (out or b"").decode("utf-8", "replace")
    ok = proc.returncode == 0
    return {"ok": ok, "package": name,
            "output": text[-1500:] if not ok else text[-400:],
            "note": ("Installed. It is importable from run_python straight away."
                     if ok else "Install failed - see output.")}


async def run(
    code: str,
    workspace: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    network: bool = False,
) -> dict:
    if not code or not code.strip():
        return {"ok": False, "error": "No code given."}
    if len(code) > MAX_CODE:
        return {"ok": False, "error": f"Code too long ({len(code)} chars)."}
    if not available():
        return {"ok": False, "error": (
            "Cannot run Python safely: bubblewrap (bwrap) is not installed. "
            "Install it with: sudo apt install bubblewrap"
        )}

    # -I ignores PYTHONPATH, so self-installed packages are put on sys.path
    # explicitly rather than through the environment.
    pkg_dir = workspace / PACKAGES_DIR
    if pkg_dir.is_dir():
        code = (f"import sys; sys.path.insert(0, {str(pkg_dir)!r})\n" + code)

    budget = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info(f"[Python] running {len(code)} chars, {budget:.0f}s, network={network}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *_argv(workspace, network),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Could not start the sandbox: {e}"}

    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(code.encode("utf-8")), timeout=budget
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "error": f"Timed out after {budget:.0f}s. "
                                      "Long loops and waiting on input will do this."}

    text = (out or b"").decode("utf-8", "replace")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": text[:MAX_OUTPUT] or "(no output - remember to print() results)",
        "truncated": len(text) > MAX_OUTPUT,
    }
