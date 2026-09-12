"""Sandboxed system-inspection commands.

"Let it check things on my computer" without handing a voice channel a shell.

The caller chain is microphone -> a third-party LLM -> here, on a machine with
passwordless sudo, so this is an ALLOWLIST of read-only diagnostics rather than
a general-purpose bash tool. Three rules make that hold:

  1. Only the base commands in ALLOWED may run. Anything else is refused.
  2. No shell. Arguments are split with shlex and passed to exec directly, so
     `;`, `|`, `&&`, backticks, `$(...)` and redirection have no meaning - they
     are rejected outright rather than interpreted.
  3. No writes. Every allowed command reports state; none modify it. Paths that
     look like an attempt to read outside the workspace are refused, so
     `cat /etc/shadow` cannot be smuggled through a path argument.

Adding a command that writes, installs, or takes a shell-ish argument (sh, env,
xargs, find -exec, awk system()) defeats all of this. Do not extend casually.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from pathlib import Path

from src.logging import get_logger

logger = get_logger()

TIMEOUT = 20.0
MAX_OUTPUT = 20_000

# Read-only system state. Deliberately no cat/head/tail/find - file reading is
# the filesystem tool's job, and it is workspace-scoped.
ALLOWED: dict[str, str] = {
    "df": "disk space", "du": "directory sizes", "free": "memory use",
    "uptime": "load and uptime", "date": "current date/time",
    "hostname": "machine name", "whoami": "current user", "uname": "kernel info",
    "ps": "running processes", "pgrep": "find processes by name",
    "lsblk": "block devices", "lsusb": "USB devices", "lspci": "PCI devices",
    "lscpu": "CPU info", "sensors": "temperatures", "nvidia-smi": "GPU status",
    "ip": "network interfaces", "ss": "network sockets", "ping": "reachability",
    "systemctl": "service status", "journalctl": "system logs",
    "pactl": "audio devices", "arecord": "capture devices",
    "aplay": "playback devices", "bluetoothctl": "bluetooth status",
    "uptime": "uptime", "who": "logged-in users", "id": "user and groups",
    "printenv": "environment variables", "which": "locate a program",
    "nmcli": "network manager status",
}

# Even inside an allowed command, these subcommands change state.
FORBIDDEN_ARGS = {
    "start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask",
    "kill", "poweroff", "reboot", "halt", "shutdown", "isolate", "set-property",
    "edit", "remove", "delete", "connect", "disconnect", "pair", "unpair",
    "set-default-sink", "set-default-source", "set-card-profile", "suspend",
    "load-module", "unload-module", "vacuum", "rotate", "flush",
    "move-sink", "set-sink", "set-source", "add", "modify", "write",
}

# Shell metacharacters: their presence means the caller expects a shell, and
# there isn't one. Refuse rather than silently treat them as literal text.
METACHARS = ("|", ";", "&", ">", "<", "`", "$(", "\n", "\r")


def _looks_like_outside_path(token: str) -> bool:
    """Reject absolute/parent paths so file reads cannot be smuggled in."""
    if token.startswith("-"):
        return False
    if token.startswith("/"):
        # a few read-only pseudo-filesystems are fine and genuinely useful
        return not token.startswith(("/proc/", "/sys/", "/dev/null"))
    return token.startswith("~") or ".." in token.split("/")


def check(command: str) -> tuple[bool, str, list[str]]:
    """Validate a command. Returns (ok, reason, argv)."""
    raw = (command or "").strip()
    if not raw:
        return False, "No command given.", []
    for meta in METACHARS:
        if meta in raw:
            return False, (
                f"{meta!r} is not allowed - there is no shell here, so pipes, "
                "redirection and chaining do not work. Run one simple command."
            ), []
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return False, f"Could not parse the command: {e}", []
    if not argv:
        return False, "No command given.", []

    base = os.path.basename(argv[0])
    if base not in ALLOWED:
        return False, (
            f"{base!r} is not permitted. Allowed: {', '.join(sorted(ALLOWED))}."
        ), []
    if shutil.which(base) is None:
        return False, f"{base!r} is not installed on this machine.", []
    for token in argv[1:]:
        # Normalise "--vacuum-time=1d" to "vacuum-time" before checking, and match
        # on substring: an exact-equality check let --vacuum-time=1d through, and
        # that deletes system logs.
        norm = token.lstrip("-").split("=", 1)[0].lower()
        if norm in FORBIDDEN_ARGS or any(bad in norm for bad in FORBIDDEN_ARGS):
            return False, f"{token!r} would change system state; only status is allowed.", []
        if _looks_like_outside_path(token):
            return False, (
                f"{token!r} points outside the workspace. Use the file tools to "
                "read files."
            ), []
    return True, "", argv


async def run(command: str, workdir: Path) -> dict:
    ok, why, argv = check(command)
    if not ok:
        return {"ok": False, "error": why}

    logger.info(f"[Shell] {' '.join(argv)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Could not run it: {e}"}
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "error": f"Timed out after {TIMEOUT:.0f}s"}

    text = (out or b"").decode("utf-8", "replace")
    truncated = len(text) > MAX_OUTPUT
    return {
        "ok": True,
        "command": " ".join(argv),
        "exit_code": proc.returncode,
        "output": text[:MAX_OUTPUT],
        "truncated": truncated,
    }
