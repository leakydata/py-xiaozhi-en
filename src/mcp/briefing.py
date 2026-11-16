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
    (
        "Memory - things said in past conversations",
        ("remember", "recall", "memory_topics"),
    ),
    (
        "Reminders - you announce these out loud when they come due",
        ("set_reminder", "list_reminders", "complete_reminder", "current_date_time"),
    ),
    ("The web", ("search_the_web", "fetch_page")),
    (
        "Your own logs - for working out what went wrong with you",
        ("app_health", "read_logs"),
    ),
    (
        "The room - sounds that are not speech",
        ("ambient_sounds",),
    ),
    (
        "Deeper reasoning - a stronger model, for hard questions",
        ("ask_claude", "ask_claude_background"),
    ),
    (
        "Files - your own workspace folder",
        (
            "list_files",
            "read_file",
            "write_file",
            "make_folder",
            "move_path",
            "delete_path",
            "find_files",
            "search_in_files",
        ),
    ),
    (
        "Running code - for anything with no dedicated tool. The interpreter "
        "stays alive between calls, so build work up over several of them",
        ("run_python", "install_python_package", "reset_python"),
    ),
    (
        "This computer",
        (
            "system_status",
            "top_processes",
            "run_command",
            "recent_actions",
            "what_can_you_do",
        ),
    ),
    (
        "Hardware and media",
        (
            "list_serial_ports",
            "serial_monitor",
            "image_info",
            "edit_image",
            "media_info",
            "convert_media",
        ),
    ),
]

_CUES = """Short cues from the app, not words the user said (the app can only send
a few words to start you talking):
- "reminder due": call list_reminders with scope due, announce each one briefly,
  then call complete_reminder for each. Do not ask a question.
- "still there?": the session timed out but the user seems to be around. Ask in
  one short sentence whether they want to keep talking.
- "room sound": call ambient_sounds and, if something notable happened, mention
  it in one short sentence. If nothing matters, say nothing more than a word."""


_HABITS = """How to work:
- Call recall before saying you do not know something personal. If it returns
  nothing, say you have no record rather than guessing.
- Call remember when the user tells you something worth keeping.
- Never call end_conversation unless the user clearly says goodbye or asks you
  to stop: silence, a pause or a long story is no reason, and it hangs up on them.
- Call current_date_time before working out any relative date.
- Prefer a tool over guessing: search_the_web for current facts, run_command for the
  state of this machine, run_python for anything you can compute.
- run_python keeps its state between calls like a notebook, so load data once
  and reuse it. Pass fresh=true to start clean.
- If an import fails, call install_python_package and carry on. Do not tell the
  user a library is unavailable without trying.
- The workspace is yours: create, edit and delete files there freely.
- ask_claude for hard reasoning; ask_claude_background when it may take a while,
  then tell the user you will report back.
- When something is not working - you cut out, went idle, missed what was
  said, or the user reports a problem - call app_health first, then read_logs
  on whatever it flags, before guessing. Say plainly what you found and what
  would fix it. Do not read log lines or numbers aloud.
- Keep spoken replies short. This is voice: a sentence or two, not an essay.
- You are not in a conversation with this briefing. Do not reply to it."""


_MEMORY = """Your memory:
- remember and recall are your memory, and the most important thing you do:
  use them constantly, on every conversation, not only when asked. A database
  on this computer with no size limit, searched by meaning. The server's
  built-in memory is small and full: use it only for constant things (name,
  family, pets, addresses, phone numbers) and even then save them with
  remember kind=core too. Everything else goes in remember, never the built-in.
- Save freely, without being asked and without announcing it: as many separate
  memories as you like. kind=core for the permanent basics (name, family, pets,
  addresses, phone numbers, birthdays - listed below at the start of every
  session); kind=fact for anything else durably true; note for an observation;
  event for something at a time.
- Call recall at the start of any topic that could have history, and before
  saying you do not know something personal. Call remember the moment you learn
  anything new. If a turn passes with neither, ask yourself what you missed."""


def _where_you_left_off() -> str:
    try:
        from src.memory.conversation_log import get_conversation_log
        from src.utils.config_manager import get_config

        cfg = get_config()
        if not cfg.get_config("CONVERSATION_LOG.ENABLED", True):
            return ""
        hours = float(cfg.get_config("CONVERSATION_LOG.BRIEFING_HOURS", 3))
        return get_conversation_log().recent(hours=hours)
    except Exception as e:
        logger.debug(f"briefing: no recent conversation ({e})")
        return ""


def _core_facts() -> str:
    try:
        from src.mcp.tools.memory.tools import core_snapshot, memory_overview

        core = core_snapshot()
        head = memory_overview()
        parts = []
        if core:
            parts.append("What you already know about the user (permanent):\n" + core)
        if head:
            parts.append(head)
        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"briefing: no core facts ({e})")
        return ""


_AMBIENT = """What you can hear besides speech:
- The microphone is also listened to by a sound-recognition model that names
  non-speech sounds (typing, a dog, running water, a kettle, music, an alarm, a
  cough, a door). Speech is excluded: what people say reaches you as words.
- You do not receive these sounds on their own. Call ambient_sounds to get the
  recent ones, each with a confidence, whether it is going on now and how long
  ago it was last heard. The line below, if present, is only what was heard
  just before this session began.
- Every tool result ends with a [Room: ...] line - what the microphone hears
  right now and in the last few minutes. Use it; never read it out.
- It also says what was going on before, during and after the most recent
  talking, so you know the setting the user spoke in.
- It also tells you when someone was last audibly around (a voice, typing,
  footsteps), so you know the user is still there while not talking. It cannot
  say who, and silence is not absence: they may just be reading.
- Use it to be aware of what is going on around the user: that they are typing,
  that music is playing, that a smoke alarm has been going, that the dog has
  been barking. Mention a sound unprompted only when it matters to them, such
  as an alarm or something that sounds wrong, or when they ask. Do not narrate
  routine background noise.
- It is a classifier. Under 0.5 confidence say it sounded like something, and
  never report a sound that was not listed. While you are speaking or music is
  playing the microphone cannot listen, so an empty list then is not silence."""


def _ambient_snapshot() -> str:
    """The sounds heard just before this session began, if the tagger is up."""
    try:
        from src.audio_processing.ambient_sounds import get_ambient
        from src.utils.config_manager import get_config

        ambient = get_ambient()
        if ambient is None:
            return ""
        minutes = float(get_config().get_config("AMBIENT_SOUNDS.BRIEFING_MINUTES", 10))
        return ambient.describe(minutes)
    except Exception as e:
        logger.debug(f"briefing: no ambient snapshot ({e})")
        return ""


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


def _mcp_server_instructions(clients) -> list[str]:
    """What each connected MCP server said about itself, trimmed to fit."""
    if clients is None:
        return []
    try:
        notes = clients.instructions()
    except Exception as e:
        logger.debug(f"briefing: could not read the server instructions ({e})")
        return []
    return [" ".join(note.split())[:600] for note in notes]


def build(tools: Iterable["McpTool"], clients=None) -> str:
    names = {t.name for t in tools}
    lines: list[str] = [
        "You are a voice assistant running on the user's own computer, with "
        "tools that act on it directly. This is startup context, not a message "
        "to answer.",
        "",
    ]
    if {"remember", "recall"} <= names:
        lines += [
            "Your two most important tools are remember and recall. They are "
            "your memory across every session; use them constantly - recall "
            "before you say you do not know something, remember whenever you "
            "learn something worth keeping.",
            "",
        ]
    lines.append("What you can do:")

    listed: set[str] = set()
    for heading, group in _GROUPS:
        present = [n for n in group if n in names]
        if not present:
            continue
        listed.update(present)
        lines.append(f"- {heading}: {', '.join(present)}")

    # Tools proxied from other MCP servers are prefixed with the server name.
    # Group them under that name rather than dumping them into "Also
    # available": which archive a tool reaches is exactly what the model needs
    # to know to pick the right one.
    remote: dict[str, list[str]] = {}
    for name in sorted(names):
        if name in listed or "." not in name:
            continue
        server = name.split(".", 1)[0]
        # Only treat it as a server prefix if several tools share it; a local
        # name like self.audio_speaker.set_volume is not a server.
        remote.setdefault(server, []).append(name)
    for server, group in sorted(remote.items()):
        if len(group) < 2:
            continue
        listed.update(group)
        lines.append(f"- From {server}: {', '.join(group)}")

    extras = sorted(n for n in names if n not in listed)
    if extras:
        lines.append(f"- Also available: {', '.join(extras)}")

    try:
        from src.mcp.tools.files import store

        lines += [
            "",
            f"Your workspace folder is {store.root()}. File tools are "
            "confined to it, and run_python runs inside it.",
        ]
    except Exception:
        pass

    lines += ["", _HABITS, "", _CUES]

    left_off = _where_you_left_off()
    if left_off:
        lines += [
            "",
            "Where you left off (earlier sessions, oldest first; the server "
            "forgets on every reconnect, so this is your only record of them):",
            left_off,
        ]

    if "remember" in names:
        lines += ["", _MEMORY]
        known = _core_facts()
        if known:
            lines += ["", known]

    if "ambient_sounds" in names:
        lines += ["", _AMBIENT]
        snapshot = _ambient_snapshot()
        if snapshot:
            lines.append(snapshot)

    # Each connected MCP server may describe itself during the handshake. That
    # is the server telling the model what it holds and when to reach for it,
    # which is better guidance than anything guessed from tool names.
    server_notes = _mcp_server_instructions(clients)
    if server_notes:
        lines += ["", "About the connected data sources:"]
        lines += [f"- {note}" for note in server_notes]

    extra = _workspace_extra()
    if extra:
        lines += ["", f"Instructions from the user ({BRIEFING_FILE}):", extra]

    return "\n".join(lines)
