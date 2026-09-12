"""Filesystem and system-inspection MCP tool registration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from . import python_exec, shell, store

logger = get_logger()


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)}, ensure_ascii=False)


async def list_files_payload(args: dict[str, Any]) -> str:
    try:
        path = str(args.get("path", ".") or ".")
        return json.dumps(
            {"path": path, "workspace": str(store.root()),
             "entries": store.list_dir(path)}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def read_file_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(store.read_file(
            str(args.get("path", "")),
            int(args.get("max_bytes", store.MAX_READ_BYTES) or store.MAX_READ_BYTES),
        ), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def write_file_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(store.write_file(
            str(args.get("path", "")),
            str(args.get("content", "")),
            append=bool(args.get("append", False)),
        ), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def delete_path_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(store.delete(str(args.get("path", ""))), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def make_folder_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(store.make_dir(str(args.get("path", ""))), ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def move_path_payload(args: dict[str, Any]) -> str:
    try:
        return json.dumps(store.move(str(args.get("source", "")),
                                     str(args.get("destination", ""))),
                          ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def find_files_payload(args: dict[str, Any]) -> str:
    try:
        q = str(args.get("query", ""))
        return json.dumps({"query": q, "matches": store.search(q)}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def search_in_files_payload(args: dict[str, Any]) -> str:
    try:
        q = str(args.get("text", ""))
        return json.dumps({"text": q, "matches": store.grep(q)}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def run_python_payload(args: dict[str, Any]) -> str:
    try:
        net = bool(args.get("network", False))
        res = await python_exec.run(
            str(args.get("code", "")), store.root(),
            timeout=float(args.get("timeout", python_exec.DEFAULT_TIMEOUT) or 30),
            network=net,
        )
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def recent_actions_payload(args: dict[str, Any]) -> str:
    try:
        from src.mcp import audit

        return json.dumps({
            "log": str(audit.path()),
            "actions": audit.tail(int(args.get("limit", 20) or 20),
                                  str(args.get("tool", "") or "") or None),
        }, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def what_can_you_do_payload(args: dict[str, Any]) -> str:
    """The same briefing sent at initialize, in case the host ignored it."""
    try:
        from src.mcp import briefing
        from src.mcp.mcp_server import McpServer

        server = (McpServer.get_instance() if hasattr(McpServer, "get_instance")
                  else None)
        tools = getattr(server, "tools", []) if server else []
        return json.dumps({"briefing": briefing.build(tools)}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


async def run_command_payload(args: dict[str, Any]) -> str:
    try:
        res = await shell.run(str(args.get("command", "")), store.root())
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return _err(e)


def register_file_tools(add_tool: Callable[[McpTool], None]) -> None:
    ws = store.root()
    allowed = ", ".join(sorted(shell.ALLOWED))

    tools: list[McpTool] = [
        McpTool(
            "list_files",
            (
                f"List files and folders in the assistant's workspace ({ws}). "
                "All file tools are confined to this folder. "
                "Args: path - a folder relative to the workspace ('.' for the top)."
            ),
            PropertyList([Property("path", PropertyType.STRING, default_value=".")]),
            list_files_payload,
        ),
        McpTool(
            "read_file",
            (
                "Read a text file from the workspace. "
                "Args: path - relative path; max_bytes - how much to read."
            ),
            PropertyList([
                Property("path", PropertyType.STRING, default_value=""),
                Property("max_bytes", PropertyType.INTEGER, default_value=20000,
                         min_value=1, max_value=store.MAX_READ_BYTES),
            ]),
            read_file_payload,
        ),
        McpTool(
            "write_file",
            (
                "Create or overwrite a text file in the workspace. Parent folders "
                "are created automatically. "
                "Args: path - relative path; content - the full text to write; "
                "append - true to add to the end instead of replacing."
            ),
            PropertyList([
                Property("path", PropertyType.STRING, default_value=""),
                Property("content", PropertyType.STRING, default_value=""),
                Property("append", PropertyType.BOOLEAN, default_value=False),
            ]),
            write_file_payload,
        ),
        McpTool(
            "delete_path",
            (
                "Delete a file or folder in the workspace. Deleting a folder "
                "removes everything inside it, so confirm with the user first. "
                "Args: path - relative path."
            ),
            PropertyList([Property("path", PropertyType.STRING, default_value="")]),
            delete_path_payload,
        ),
        McpTool(
            "make_folder",
            "Create a folder in the workspace. Args: path - relative path.",
            PropertyList([Property("path", PropertyType.STRING, default_value="")]),
            make_folder_payload,
        ),
        McpTool(
            "move_path",
            (
                "Move or rename a file or folder inside the workspace. "
                "Args: source, destination - both relative paths."
            ),
            PropertyList([
                Property("source", PropertyType.STRING, default_value=""),
                Property("destination", PropertyType.STRING, default_value=""),
            ]),
            move_path_payload,
        ),
        McpTool(
            "find_files",
            "Find workspace files whose name contains some text. Args: query.",
            PropertyList([Property("query", PropertyType.STRING, default_value="")]),
            find_files_payload,
        ),
        McpTool(
            "search_in_files",
            "Search the contents of workspace text files. Args: text.",
            PropertyList([Property("text", PropertyType.STRING, default_value="")]),
            search_in_files_payload,
        ),
        McpTool(
            "run_command",
            (
                "Check the state of this computer by running one read-only "
                "diagnostic command. Use it for questions about disk space, "
                "memory, temperature, processes, services, network or audio "
                "hardware. There is NO shell: pipes, redirection, chaining and "
                "quoting tricks are rejected, so run one simple command and read "
                "the output yourself. Nothing that changes the system is allowed. "
                f"Permitted commands: {allowed}. "
                "Args: command - e.g. 'df -h', 'free -h', 'sensors', 'ps aux'."
            ),
            PropertyList([Property("command", PropertyType.STRING, default_value="")]),
            run_command_payload,
        ),
    ]

    tools.append(McpTool(
        "what_can_you_do",
        (
            "Get your own startup briefing: everything you can do, your workspace "
            "location, and any standing instructions the user wrote. Call this if "
            "you are unsure what tools you have, or when the user asks what you "
            "are capable of. Takes no arguments."
        ),
        PropertyList([]),
        what_can_you_do_payload,
    ))

    tools.append(McpTool(
        "recent_actions",
        (
            "Review what you have actually done recently - every tool call is "
            "recorded with its arguments, whether it succeeded and how long it "
            "took. Use it when the user asks what you did, what changed, or why "
            "something happened. "
            "Args: limit - how many entries (1-200); tool - optionally filter to "
            "one tool name."
        ),
        PropertyList([
            Property("limit", PropertyType.INTEGER, default_value=20,
                     min_value=1, max_value=200),
            Property("tool", PropertyType.STRING, default_value=""),
        ]),
        recent_actions_payload,
    ))

    if python_exec.available():
        tools.append(McpTool(
            "run_python",
            (
                "Write and run Python 3 code to do something you have no dedicated "
                "tool for: calculations, parsing, converting, generating or "
                "analysing files. The code runs in a locked sandbox where ONLY the "
                "workspace folder is writable - the rest of the computer is "
                "invisible to it - so use it freely. The workspace is the current "
                "directory, so open('notes.txt') just works. Print what you want to "
                "see; nothing is returned otherwise. The standard library is "
                "available (json, csv, math, statistics, datetime, re, sqlite3, "
                "zipfile...) but third-party packages are not. "
                "Args: code - the full program; timeout - seconds (1-120); "
                "network - true only if it must reach the internet (off by default)."
            ),
            PropertyList([
                Property("code", PropertyType.STRING, default_value=""),
                Property("timeout", PropertyType.INTEGER, default_value=30,
                         min_value=1, max_value=int(python_exec.MAX_TIMEOUT)),
                Property("network", PropertyType.BOOLEAN, default_value=False),
            ]),
            run_python_payload,
        ))
    else:
        logger.warning(
            "bubblewrap (bwrap) missing - run_python not registered. "
            "Install with: sudo apt install bubblewrap"
        )

    for t in tools:
        add_tool(t)
    logger.info("Registered %d file/system MCP tools (workspace: %s)", len(tools), ws)
