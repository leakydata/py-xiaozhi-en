"""Talks to the turn-taking sidecar (sidecars/turn_sidecar.py).

The sidecar runs under the home server's environment, where Parakeet and
pyannote already live, so py-xiaozhi does not have to carry NeMo and torch.
This is the py-xiaozhi end of its stdin/stdout protocol: send audio, ask for a
tick, get back how long it has been quiet and what has been said.

Nothing here is allowed to break a conversation. A sidecar that is missing,
slow or dead makes `tick()` return None, and the caller falls back to letting
the server decide, as it did before this feature existed.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
from pathlib import Path
from typing import Any

import numpy as np

from src.logging import get_logger

logger = get_logger()

#: NeMo takes ~30 s to load Parakeet; the first start can be slower still.
READY_TIMEOUT_S = 180.0
#: A tick costs ~90 ms (p95 ~115 ms, measured). Past this it is late enough to
#: be useless, and the next tick will have fresher audio anyway.
TICK_TIMEOUT_S = 1.0


def _sidecar_script() -> Path:
    from src.utils.resource_finder import get_app_root

    return Path(get_app_root()) / "sidecars" / "turn_sidecar.py"


class TurnSidecar:
    def __init__(self, server_dir: str, python: str = "") -> None:
        self.server_dir = os.path.expanduser(server_dir)
        self.python = (
            os.path.expanduser(python)
            if python
            else os.path.join(self.server_dir, ".venv", "bin", "python")
        )
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None
        self.ready = False
        self.last_error = ""

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> bool:
        """Launch the sidecar and wait until its models are loaded."""
        script = _sidecar_script()
        if not os.path.exists(self.python):
            self.last_error = f"no Python at {self.python} - is boswell_server set up?"
            logger.warning(f"turn-taking: {self.last_error}")
            return False
        if not script.exists():
            self.last_error = f"missing {script}"
            logger.warning(f"turn-taking: {self.last_error}")
            return False

        # The sidecar has its own environment; ours must not leak into it,
        # the same trap the MCP client fell into with `uv run`.
        from src.mcp.client.transport import _child_environment

        env = _child_environment({"BOSWELL_SERVER_DIR": self.server_dir})
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.python,
                str(script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=4 * 1024 * 1024,
            )
        except OSError as e:
            self.last_error = f"could not start the sidecar: {e}"
            logger.warning(f"turn-taking: {self.last_error}")
            return False

        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            while True:
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=READY_TIMEOUT_S
                )
                if not line:
                    raise RuntimeError("the sidecar exited while loading")
                try:
                    if json.loads(line).get("ready"):
                        break
                except ValueError:
                    continue  # a library printing to stdout while loading
        except Exception as e:
            self.last_error = f"sidecar did not come up: {e}"
            logger.warning(f"turn-taking: {self.last_error}")
            await self.close()
            return False

        self.ready = True
        self.last_error = ""
        logger.info("turn-taking: sidecar ready (Parakeet v3 + pyannote)")
        return True

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
                if text.startswith("[turn-sidecar]"):
                    logger.info(text)
                elif text:
                    logger.debug(f"[turn-sidecar] {text}")
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _send(self, kind: bytes, payload: bytes = b"") -> None:
        if not self.alive or self._proc.stdin is None:
            raise RuntimeError("the sidecar is not running")
        self._proc.stdin.write(kind + struct.pack(">I", len(payload)) + payload)
        await self._proc.stdin.drain()

    async def reset(self) -> None:
        async with self._lock:
            try:
                await self._send(b"R")
            except Exception as e:
                logger.debug(f"turn-taking: reset failed: {e}")

    async def hotwords(self, phrases: list[str]) -> None:
        async with self._lock:
            try:
                await self._send(b"H", "\n".join(phrases).encode("utf-8"))
            except Exception as e:
                logger.debug(f"turn-taking: hotwords failed: {e}")

    async def tick(self, audio: np.ndarray | None) -> dict[str, Any] | None:
        """Send any new audio, then ask for the state of the turn."""
        if not self.ready:
            return None
        async with self._lock:
            try:
                if audio is not None and len(audio):
                    await self._send(b"A", audio.astype(np.float32).tobytes())
                await self._send(b"T")
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=TICK_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                # The reply will still arrive; read it next time rather than
                # mismatching it with a later tick.
                logger.debug("turn-taking: tick was late")
                self._late += 1
                return None
            except Exception as e:
                logger.warning(f"turn-taking: tick failed: {e}")
                self.ready = False
                return None
            # Discard replies to ticks that timed out earlier.
            while self._late and line:
                self._late -= 1
                try:
                    line = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=TICK_TIMEOUT_S
                    )
                except asyncio.TimeoutError:
                    return None
        if not line:
            self.ready = False
            return None
        try:
            reply = json.loads(line)
        except ValueError:
            return None
        return None if "error" in reply else reply

    _late = 0

    async def close(self) -> None:
        self.ready = False
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(b"Q" + struct.pack(">I", 0))
                await proc.stdin.drain()
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
