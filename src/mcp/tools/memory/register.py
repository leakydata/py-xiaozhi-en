"""Memory MCP tool registration."""

from __future__ import annotations

from collections.abc import Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .tools import (
    complete_reminder_payload,
    core_snapshot,
    memory_overview,
    memory_topics_payload,
    current_time_payload,
    list_reminders_payload,
    recall_payload,
    remember_payload,
    set_reminder_payload,
)

logger = get_logger()


def _known_now() -> str:
    """Appended to recall's description each time the tool list is built, so the
    permanent basics arrive with the function list rather than needing a call."""
    core = core_snapshot()
    parts = []
    if core:
        parts.append("PERMANENT FACTS YOU ALREADY KNOW about the user:\n" + core)
    overview = memory_overview()
    if overview:
        parts.append(overview + " recall searches all of them.")
    return "\n".join(parts)


def register_memory_tools(add_tool: Callable[[McpTool], None]) -> None:
    """Register memory and reminder tools on the McpServer."""

    tools: list[McpTool] = [
        McpTool(
            "remember",
            (
                "Save something to long-term memory. This is your ONLY memory: "
                "a database on the user's own computer with no size limit, "
                "searched by meaning with recall. Never use any built-in or "
                "server-side 'memory' tool - it is small and full. Save as "
                "much as you like, as many separate memories as you like, "
                "without being asked and without announcing it: preferences, "
                "facts about their home, vehicles, equipment, work, people's "
                "names, where things are kept, decisions and why, and anything "
                "they correct you on. Pick the kind: core for the permanent "
                "basics about them - their name, family, pets and their names, "
                "home and work addresses, phone numbers, birthdays - which "
                "you are shown at the start of every session; fact for "
                "anything else durably true; note for an observation; event "
                "for something that happened at a time. Not for reminders "
                "with a time - use set_reminder. "
                "Args: text - what to remember, written as a clear standalone "
                "sentence; kind - core, fact, note or event; speaker - who "
                "said it; tags - optional comma-separated labels."
            ),
            PropertyList(
                [
                    Property("text", PropertyType.STRING, default_value=""),
                    Property("kind", PropertyType.STRING, default_value="note"),
                    Property("speaker", PropertyType.STRING, default_value=""),
                    Property("tags", PropertyType.STRING, default_value=""),
                ]
            ),
            remember_payload,
        ),
        McpTool(
            "recall",
            (
                "Search long-term memory - everything you have ever been told "
                "or chose to keep, across all sessions. Use this BEFORE saying "
                "you do not know something personal, before asking the user "
                "to repeat themselves, and whenever they refer to something "
                "previously discussed ('the part I mentioned', 'that place I "
                "told you about'). Matching is by meaning, so paraphrase "
                "freely. If it returns nothing, say you have no record rather "
                "than guessing. "
                "Args: query - what to look for; max_results - 1-10; kind - "
                "pass core with no query to list every permanent basic."
            ),
            PropertyList(
                [
                    Property("query", PropertyType.STRING, default_value=""),
                    Property(
                        "max_results",
                        PropertyType.INTEGER,
                        default_value=5,
                        min_value=1,
                        max_value=10,
                    ),
                    Property("kind", PropertyType.STRING, default_value=""),
                ]
            ),
            recall_payload,
            dynamic=_known_now,
        ),
        McpTool(
            "set_reminder",
            (
                "Create a reminder for a specific time. The reply contains the "
                "resolved date and time - read it back to the user so they can "
                "correct it. "
                "Args: text - what to remind them about; when - an ISO "
                "timestamp, or a phrase like 'in 30 minutes', 'tomorrow 9am', "
                "'in 2 days'; speaker - who it is for."
            ),
            PropertyList(
                [
                    Property("text", PropertyType.STRING, default_value=""),
                    Property("when", PropertyType.STRING, default_value=""),
                    Property("speaker", PropertyType.STRING, default_value=""),
                ]
            ),
            set_reminder_payload,
        ),
        McpTool(
            "list_reminders",
            (
                "List reminders. Args: scope - 'upcoming' (not yet due), 'due' "
                "(due now and unfinished), or 'all'."
            ),
            PropertyList(
                [
                    Property("scope", PropertyType.STRING, default_value="upcoming"),
                ]
            ),
            list_reminders_payload,
        ),
        McpTool(
            "complete_reminder",
            "Mark a reminder as done. Args: id - the reminder's id.",
            PropertyList(
                [
                    Property("id", PropertyType.INTEGER, default_value=0),
                ]
            ),
            complete_reminder_payload,
        ),
        McpTool(
            "memory_topics",
            (
                "Group everything in long-term memory into themes, so you can tell "
                "the user what they have been talking about or what a project "
                "involves. Grouping is by meaning rather than keywords, and it is "
                "approximate - related notes are sometimes left out of a group, so "
                "present themes as a rough summary, not a complete index. "
                "Takes no arguments."
            ),
            PropertyList([]),
            memory_topics_payload,
        ),
        McpTool(
            "get_current_time",
            (
                "Get the current local date and time. Call this before working "
                "out any relative time so you do not guess the date."
            ),
            PropertyList([]),
            current_time_payload,
        ),
    ]

    for tool in tools:
        add_tool(tool)
    logger.info("Registered %d memory MCP tools", len(tools))
