"""Persistent Python sessions inside the sandbox.

A one-shot process per call means every multi-step task starts from nothing:
load a CSV, then in the next call load it again to plot it. Here the interpreter
stays alive between calls, so state carries over the way a notebook kernel does,
and the assistant decides when to start fresh rather than that being forced on
it every time.

Each session is a bubblewrap-jailed interpreter running a small driver that
reads JSON-line requests from stdin and writes one JSON-line result per exec.
JSON lines rather than sentinel markers, because user code can print anything -
including whatever delimiter we chose.

Timeouts are the awkward part: there is no safe way to interrupt a blocking exec
in another process. A call that overruns therefore kills the session and says
so, rather than leaving a wedged interpreter that quietly fails every later
call. State is lost, which is the honest outcome and is reported as such.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from src.logging import get_logger

logger = get_logger()

MAX_SESSIONS = 4
MAX_OUTPUT = 20_000

# Runs INSIDE the jail. Keeps one namespace alive across execs and reports
# stdout, stderr and the traceback for each one separately.
_DRIVER = r"""
import sys, json, io, traceback, contextlib
ns = {"__name__": "__main__"}
sys.stdin.reconfigure(encoding="utf-8")
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    out, err = io.StringIO(), io.StringIO()
    failed = False
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(req.get("code", ""), "<session>", "exec"), ns)
    except SystemExit:
        pass
    except BaseException:
        failed = True
        # print_exc writes to sys.stderr, which is not the redirected buffer -
        # without file=err the traceback vanished and errors looked like silence
        traceback.print_exc(file=err)
    sys.__stdout__.write(json.dumps({
        "out": out.getvalue(), "err": err.getvalue(), "failed": failed,
    }) + "\n")
    sys.__stdout__.flush()
"""


class Session:
    def __init__(self, name: str, network: bool) -> None:
        self.name = name
        self.network = network
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.lock = asyncio.Lock()
        self.execs = 0

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, workspace: Path) -> None:
        from . import python_exec

        args = python_exec._argv(workspace, self.network)
        # swap "-I -" (read a program from stdin) for the driver
        args = args[: args.index("-I")] + ["-I", "-c", _DRIVER]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.execs = 0
        logger.info(f"[PySession] started {self.name!r} (network={self.network})")

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
                await self.proc.wait()
            except Exception:
                pass
        self.proc = None

    async def execute(self, code: str, timeout: float, workspace: Path) -> dict:
        async with self.lock:
            if not self.alive:
                await self.start(workspace)
            assert self.proc and self.proc.stdin and self.proc.stdout

            # self-installed packages, same as the one-shot path
            from . import python_exec

            if self.execs == 0:
                pkg = workspace / python_exec.PACKAGES_DIR
                if pkg.is_dir():
                    code = f"import sys; sys.path.insert(0, {str(pkg)!r})\n" + code

            try:
                self.proc.stdin.write(
                    (json.dumps({"code": code}) + "\n").encode("utf-8")
                )
                await self.proc.stdin.drain()
                line = await asyncio.wait_for(
                    self.proc.stdout.readline(), timeout=timeout
                )
            except asyncio.TimeoutError:
                await self.stop()
                return {
                    "ok": False,
                    "session": self.name,
                    "state_lost": True,
                    "error": (
                        f"Timed out after {timeout:.0f}s. The session "
                        "was restarted, so variables from before are "
                        "gone - a blocking call cannot be interrupted "
                        "safely."
                    ),
                }
            except Exception as e:
                await self.stop()
                return {
                    "ok": False,
                    "session": self.name,
                    "state_lost": True,
                    "error": f"Session failed: {e}",
                }

            if not line:
                await self.stop()
                return {
                    "ok": False,
                    "session": self.name,
                    "state_lost": True,
                    "error": "The interpreter exited (a hard crash, or "
                    "os._exit / quit() in the code).",
                }

            self.execs += 1
            try:
                res = json.loads(line.decode("utf-8", "replace"))
            except Exception as e:
                return {
                    "ok": False,
                    "session": self.name,
                    "error": f"Could not read the result: {e}",
                }

            text = (res.get("out") or "") + (res.get("err") or "")
            return {
                "ok": not res.get("failed"),
                "session": self.name,
                "execs": self.execs,
                "output": text[:MAX_OUTPUT]
                or "(no output - remember to print() results)",
                "truncated": len(text) > MAX_OUTPUT,
            }


_sessions: dict[str, Session] = {}


async def execute(
    code: str,
    workspace: Path,
    *,
    session: str = "default",
    fresh: bool = False,
    timeout: float = 30.0,
    network: bool = False,
) -> dict:
    from . import python_exec

    if not code or not code.strip():
        return {"ok": False, "error": "No code given."}
    if not python_exec.available():
        return {
            "ok": False,
            "error": (
                "Cannot run Python safely: bubblewrap (bwrap) is not installed. "
                "Install it with: sudo apt install bubblewrap"
            ),
        }

    name = (session or "default").strip() or "default"
    workspace.mkdir(parents=True, exist_ok=True)

    existing = _sessions.get(name)
    # Network is fixed when the jail is created, so a change of mind means a
    # new interpreter - say so rather than silently ignoring the request.
    if existing and existing.network != network:
        await existing.stop()
        existing = None
        fresh = True
    if fresh and existing:
        await existing.stop()
        existing = None
    if existing is None:
        if len(_sessions) >= MAX_SESSIONS and name not in _sessions:
            oldest = next(iter(_sessions))
            await _sessions.pop(oldest).stop()
            logger.info(f"[PySession] evicted {oldest!r} (limit {MAX_SESSIONS})")
        existing = Session(name, network)
        _sessions[name] = existing

    return await existing.execute(code, timeout, workspace)


async def reset(session: str = "") -> dict:
    """Drop one session, or all of them."""
    name = (session or "").strip()
    if name:
        s = _sessions.pop(name, None)
        if not s:
            return {"ok": True, "note": f"No session named {name!r} was running."}
        await s.stop()
        return {"ok": True, "reset": name}
    names = list(_sessions)
    for n in names:
        await _sessions.pop(n).stop()
    return {"ok": True, "reset": names or "nothing was running"}


def status() -> list[dict]:
    return [
        {"session": s.name, "alive": s.alive, "execs": s.execs, "network": s.network}
        for s in _sessions.values()
    ]


async def shutdown() -> None:
    await reset()
