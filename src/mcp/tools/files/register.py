"""Filesystem and system-inspection MCP tool registration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from . import shell, store

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

    for t in tools:
        add_tool(t)
    logger.info("Registered %d file/system MCP tools (workspace: %s)", len(tools), ws)
