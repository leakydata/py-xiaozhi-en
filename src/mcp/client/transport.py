"""How to reach an MCP server.

Two transports, because that is what real servers actually offer:

- **stdio** launches the server as a child process and speaks newline-delimited
  JSON-RPC over its pipes. This is what a `.mcp.json` entry with a `command`
  means, and what Boswell and most local servers use.
- **streamable HTTP** POSTs JSON-RPC to a URL. The reply is either plain JSON or
  an SSE stream carrying one `data:` line, and servers pick between the two
  freely, so both are handled on every response.

Everything here is transport only: framing bytes, nothing about what the
messages mean. The session layer above owns the protocol.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.logging import get_logger

logger = get_logger()

#: A server that has not answered in this long is treated as wedged. Generous,
#: because a cold local server may be loading a model on the first call.
DEFAULT_TIMEOUT = 60.0


class TransportError(RuntimeError):
    """The server could not be reached, or broke the framing."""


#: Variables that tie a process to *our* Python environment. A child MCP server
#: has its own, and inheriting these silently points it at ours instead.
#: py-xiaozhi is normally started with `uv run`, so VIRTUAL_ENV is set; a server
#: launched as `uv run ...` then resolves against py-xiaozhi's venv and dies on
#: an import it would have found in its own. Clearing these makes a child start
#: as it would from a fresh shell.
_ENV_TO_DROP = (
    "VIRTUAL_ENV",
    "UV_PROJECT_ENVIRONMENT",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONEXECUTABLE",
)


def _child_environment(overrides: dict[str, str] | None) -> dict[str, str]:
    """The environment a child server should see."""
    import os

    env = dict(os.environ)
    venv = env.get("VIRTUAL_ENV")
    for name in _ENV_TO_DROP:
        env.pop(name, None)

    # Take the active venv's bin off PATH too, the way `deactivate` would.
    # Leaving it there would keep shadowing `python` with ours.
    if venv:
        venv_bin = os.path.join(venv, "bin")
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p != venv_bin]
        env["PATH"] = os.pathsep.join(parts)

    # An explicit env in the server's config is deliberate, so it wins.
    if overrides:
        env.update(overrides)
    return env


class Transport:
    """What a transport has to provide."""

    async def start(self) -> None:
        raise NotImplementedError

    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for its reply."""
        raise NotImplementedError

    async def notify(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC notification, which has no reply."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        raise NotImplementedError


class StdioTransport(Transport):
    """An MCP server running as a child process.

    One request is in flight at a time, held by a lock. MCP allows interleaving
    by id, but a voice assistant issues tool calls one at a time anyway, and
    serialising means a confused server cannot mismatch a reply to the wrong
    caller.
    """

    def __init__(
        self,
        command: str,
        args: list | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.cwd = cwd
        self.env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        environment = _child_environment(self.env)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=environment,
            )
        except FileNotFoundError as e:
            raise TransportError(f"cannot run {self.command!r}: {e}") from e
        except OSError as e:
            raise TransportError(f"could not start {self.command!r}: {e}") from e

        # Drain stderr continuously. A server that logs heavily will otherwise
        # fill the pipe buffer and block forever mid-call, which looks exactly
        # like a hang and is miserable to diagnose.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", "replace").rstrip()
                if text:
                    logger.debug(f"[mcp:{self.command}] {text}")
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _write(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise TransportError("the server process is not running")
        proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        async with self._lock:
            await self._write(message)
            proc = self._proc
            assert proc is not None and proc.stdout is not None
            want = message.get("id")
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TransportError(f"no reply within {timeout:.0f}s")
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=remaining
                    )
                except asyncio.TimeoutError:
                    raise TransportError(f"no reply within {timeout:.0f}s") from None
                if not line:
                    raise TransportError("the server closed its output")
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    # Some servers print banners to stdout before settling
                    # down. Skip anything that is not JSON rather than dying.
                    logger.debug(f"[mcp:{self.command}] non-JSON stdout: {text[:120]}")
                    continue
                # Ignore notifications and any reply to an earlier, abandoned
                # request; keep reading until the id we are waiting on shows up.
                if payload.get("id") == want:
                    return payload

    async def notify(self, message: dict[str, Any]) -> None:
        async with self._lock:
            await self._write(message)

    async def close(self) -> None:
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        except Exception as e:
            logger.debug(f"error stopping {self.command}: {e}")


class HttpTransport(Transport):
    """An MCP server behind a URL, speaking streamable HTTP."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"
        self._session = None
        #: Streamable HTTP hands back a session id on initialize, and some
        #: servers require it on every later call.
        self._mcp_session_id: str | None = None

    @property
    def alive(self) -> bool:
        return self._session is not None and not self._session.closed

    async def start(self) -> None:
        import aiohttp

        self._session = aiohttp.ClientSession()

    async def _post(self, message: dict[str, Any], timeout: float):
        import aiohttp

        if self._session is None:
            raise TransportError("the HTTP session is not open")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        try:
            return await self._session.post(
                self.url,
                json=message,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )
        except asyncio.TimeoutError:
            raise TransportError(f"no reply within {timeout:.0f}s") from None
        except aiohttp.ClientError as e:
            raise TransportError(f"{self.url} unreachable: {e}") from e

    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        resp = await self._post(message, timeout)
        async with resp:
            if resp.status == 401:
                raise TransportError("rejected the credentials (HTTP 401)")
            if resp.status >= 400:
                body = (await resp.text())[:200]
                raise TransportError(f"HTTP {resp.status}: {body}")
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._mcp_session_id = sid
            raw = await resp.text()

        # Plain JSON, or SSE with the payload on a data: line - servers choose
        # per response, so accept either shape every time.
        raw = raw.strip()
        if not raw:
            raise TransportError("empty reply")
        if raw.startswith("{"):
            return json.loads(raw)
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise TransportError(f"could not parse the reply: {raw[:160]}")

    async def notify(self, message: dict[str, Any]) -> None:
        try:
            resp = await self._post(message, DEFAULT_TIMEOUT)
            async with resp:
                await resp.read()
        except TransportError:
            # A notification has no reply to miss, so a failure here is not
            # worth breaking the session over.
            pass

    async def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            await session.close()


def build_transport(spec: dict[str, Any]) -> Transport:
    """Build the transport a server entry describes.

    The entry follows the same shape as `.mcp.json`, so a server already
    configured for another tool can be pasted straight across.
    """
    if spec.get("url"):
        return HttpTransport(
            spec["url"],
            headers=spec.get("headers"),
            bearer_token=spec.get("token") or spec.get("bearer_token"),
        )
    if spec.get("command"):
        return StdioTransport(
            spec["command"],
            args=spec.get("args"),
            cwd=spec.get("cwd"),
            env=spec.get("env"),
        )
    raise TransportError("a server entry needs either a command or a url")
