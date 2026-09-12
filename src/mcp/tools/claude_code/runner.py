"""Run Claude Code headless as a reasoning tool.

Uses the local `claude` CLI in print mode, which authenticates with the signed-in
Claude subscription (no ANTHROPIC_API_KEY, no per-call API billing).

SECURITY - read this before widening anything.
The prompt reaching this runner originates from speech: microphone -> tenclass's
LLM -> MCP tool call. Anyone within earshot can therefore steer it, and this
machine's global CLAUDE.md grants passwordless sudo. Headless Claude Code with
default settings executes tools with no denials at all (verified: it ran `id`
and returned real output).

Two layers hold it back, both verified:
  1. --disallowedTools. Note --allowedTools does NOT restrict - it is an
     auto-approve list, and Bash still ran when it was omitted from it. The deny
     list must also include Task/Agent, or the model can spawn a subagent that
     still has Bash.
  2. cwd is a dedicated workspace directory. Reads outside it are denied, so a
     prompt asking for /etc/shadow fails even though Read is permitted.

Widening DENY or pointing WORKDIR at the home directory hands voice-level access
to a root-capable agent. Do not do it casually.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from src.logging import get_logger
from src.utils.resource_finder import get_user_data_dir

logger = get_logger()

# Everything that can write, execute, or delegate to something that can.
DENY = [
    "Bash", "BashOutput", "KillShell",
    "Write", "Edit", "NotebookEdit",
    "Task", "Agent",
]

DEFAULT_TIMEOUT = 120.0


def workspace() -> Path:
    d = get_user_data_dir() / "claude_workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def available() -> bool:
    return shutil.which("claude") is not None


async def ask(
    prompt: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    model: Optional[str] = None,
) -> dict:
    """Run one headless turn. Returns {ok, text} or {ok: False, error}."""
    exe = shutil.which("claude")
    if not exe:
        return {"ok": False, "error": "The claude CLI is not installed or not on PATH."}

    cmd = [exe, "-p", prompt, "--output-format", "json", "--disallowedTools", *DENY]
    if model:
        cmd += ["--model", model]

    env = dict(os.environ)
    # Force subscription auth; a stray key would bill the API instead.
    env.pop("ANTHROPIC_API_KEY", None)

    logger.info(f"[ClaudeCode] asking ({timeout:.0f}s budget): {prompt[:80]}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace()),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        return {"ok": False, "error": f"Could not start claude: {e}"}

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning(f"[ClaudeCode] timed out after {timeout:.0f}s")
        return {"ok": False, "error": f"Timed out after {timeout:.0f} seconds."}

    if proc.returncode != 0:
        msg = (err or b"").decode("utf-8", "replace").strip()[:300]
        logger.warning(f"[ClaudeCode] exit {proc.returncode}: {msg}")
        return {"ok": False, "error": f"claude exited {proc.returncode}: {msg}"}

    try:
        data = json.loads((out or b"").decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "error": f"Could not parse claude output: {e}"}

    text = str(data.get("result") or "").strip()
    if not text:
        return {"ok": False, "error": "claude returned an empty result."}
    logger.info(f"[ClaudeCode] answered in {data.get('duration_api_ms', '?')}ms api")
    return {"ok": True, "text": text}
