"""A tool for asking which other MCP servers are actually reachable.

Without this, a server that failed to start is invisible: its tools simply are
not in the list, and the assistant has no way to tell the difference between
"there is no such tool" and "the archive is down". Being able to say *why*
something is missing is the difference between a useful answer and a shrug.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, PropertyList

logger = get_logger()


def register_mcp_client_tools(add_tool: Callable, server) -> None:
    """Register the outbound-MCP diagnostics against an McpServer."""

    async def mcp_servers(args: dict[str, Any]) -> str:
        clients = getattr(server, "clients", None)
        if clients is None:
            return (
                "No other MCP servers are configured. They go in MCP_CLIENT.SERVERS, "
                "or point MCP_CLIENT.CONFIG_FILES at an existing .mcp.json."
            )
        rows = clients.status()
        if not rows:
            return "No other MCP servers connected."

        lines = []
        for row in rows:
            if row["connected"]:
                lines.append(f"{row['server']}: connected, {row['tools']} tools")
            else:
                why = row.get("error") or "not connected"
                lines.append(f"{row['server']}: UNAVAILABLE - {why}")
        return "\n".join(lines)

    async def mcp_reconnect(args: dict[str, Any]) -> str:
        """Re-dial everything. Useful after starting a server by hand."""
        try:
            await server.close_mcp_clients()
            count = await server.connect_mcp_clients()
        except Exception as e:
            logger.error(f"MCP reconnect failed: {e}", exc_info=True)
            return f"Reconnecting failed: {e}"
        if not count:
            return "Reconnected, but no server offered any tools."
        return f"Reconnected: {count} tools available again."

    add_tool(
        McpTool(
            "mcp_servers",
            "Which other MCP servers this assistant is connected to, how many "
            "tools each gave it, and why any of them is unavailable. Use it when "
            "a tool you expected is missing, or the user asks whether something "
            "like the audio archive is reachable.",
            PropertyList(),
            mcp_servers,
        )
    )

    add_tool(
        McpTool(
            "mcp_reconnect",
            "Reconnect to the other MCP servers and pick up their tools again. "
            "Use it after the user says they have started one, or when "
            "mcp_servers reports something unavailable that should be running.",
            PropertyList(),
            mcp_reconnect,
        )
    )
