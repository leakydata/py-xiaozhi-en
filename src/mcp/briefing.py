"""Startup briefing handed to the model, so it knows what it can do.

Sent as the `instructions` field of the MCP initialize result. That field exists
in the spec precisely for this: the host may fold it into the system prompt. It
arrives once per session and is NOT a conversational turn, so the assistant does
not answer it out loud - which is the whole point compared with pushing text
through the listen/detect path.

Two sources are combined:

  1. A summary generated from the live tool registry, so it can never drift out
     of date as tools are added or removed.
  2. Optional user text from ASSISTANT.md in the CONFIG directory - a place to
     say "call me X, be brief, always check memory first" without touching code.
     It lives beside config.json rather than in the workspace: the workspace is
     the assistant's own scratch space with full write access, so standing
     instructions kept there could be overwritten by its own code.

Whether the backend honours `instructions` is up to the backend. If it ignores
it, the same text is available through the what_can_you_do tool, and the
authoritative channel remains the agent's system prompt in the web console.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from src.logging import get_logger

if TYPE_CHECKING:
    from src.mcp.tooling import McpTool

logger = get_logger()

BRIEFING_FILE = "ASSISTANT.md"

# Grouped so the model gets a map rather than a flat list of 39 names.
_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Memory - things said in past conversations",
     ("remember", "recall", "memory_topics")),
    ("Reminders - you announce these out loud when they come due",
     ("set_reminder", "list_reminders", "complete_reminder", "get_current_time")),
    ("The web",
     ("web_search", "fetch_page")),
    ("Deeper reasoning - a stronger model, for hard questions",
     ("ask_claude", "ask_claude_background")),
    ("Files - your own workspace folder",
     ("list_files", "read_file", "write_file", "make_folder", "move_path",
      "delete_path", "find_files", "search_in_files")),
    ("Running code - for anything with no dedicated tool. The interpreter "
     "stays alive between calls, so build work up over several of them",
     ("run_python", "install_python_package", "reset_python")),
    ("This computer",
     ("system_status", "top_processes", "run_command", "recent_actions",
      "what_can_you_do")),
    ("Hardware and media",
     ("list_serial_ports", "serial_monitor", "image_info", "edit_image",
      "media_info", "convert_media")),
]

_HABITS = """How to work:
- Call recall before saying you do not know something personal. If it returns
  nothing, say you have no record rather than guessing.
- Call remember when the user tells you something worth keeping.
- Call get_current_time before working out any relative date.
- Prefer a tool over guessing: web_search for current facts, run_command for the
  state of this machine, run_python for anything you can compute.
- run_python keeps its state between calls like a notebook, so load data once
  and reuse it. Pass fresh=true to start clean.
- If an import fails, call install_python_package and carry on. Do not tell the
  user a library is unavailable without trying.
- The workspace is yours: create, edit and delete files there freely.
- ask_claude for hard reasoning; ask_claude_background when it may take a while,
  then tell the user you will report back.
- Keep spoken replies short. This is voice: a sentence or two, not an essay.
- You are not in a conversation with this briefing. Do not reply to it."""


def _workspace_extra() -> str:
    """User-authored instructions from ASSISTANT.md, if present."""
    try:
        from src.utils.resource_finder import get_user_data_dir

        path = get_user_data_dir() / "config" / BRIEFING_FILE
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text[:4000]
    except Exception as e:
        logger.debug(f"briefing: no workspace file ({e})")
    return ""


def build(tools: Iterable["McpTool"]) -> str:
    names = {t.name for t in tools}
    lines: list[str] = [
        "You are a voice assistant running on the user's own computer, with "
        "tools that act on it directly. This is startup context, not a message "
        "to answer.",
        "",
        "What you can do:",
    ]

    listed: set[str] = set()
    for heading, group in _GROUPS:
        present = [n for n in group if n in names]
        if not present:
            continue
        listed.update(present)
        lines.append(f"- {heading}: {', '.join(present)}")

    extras = sorted(n for n in names if n not in listed)
    if extras:
        lines.append(f"- Also available: {', '.join(extras)}")

    try:
        from src.mcp.tools.files import store

        lines += ["", f"Your workspace folder is {store.root()}. File tools are "
                      "confined to it, and run_python runs inside it."]
    except Exception:
        pass

    lines += ["", _HABITS]

    extra = _workspace_extra()
    if extra:
        lines += ["", f"Instructions from the user ({BRIEFING_FILE}):", extra]

    return "\n".join(lines)
