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
import shutil
from pathlib import Path

from src.logging import get_logger

logger = get_logger()

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
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        # the one writable location
        "--bind", str(workspace), str(workspace),
        "--chdir", str(workspace),
        "--die-with-parent",
        "--new-session",
    ]
    if network:
        args += ["--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
                 "--unshare-pid", "--unshare-ipc", "--unshare-uts"]
    else:
        args += ["--unshare-all"]
    args += ["/usr/bin/python3", "-I", "-"]
    return args


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
