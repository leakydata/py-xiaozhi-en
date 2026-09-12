"""The runtime registry for external MCP plugins: who owns what, and unloading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.logging import get_logger

if TYPE_CHECKING:
    from src.mcp.mcp_server import McpServer

logger = get_logger()


@dataclass
class PluginRegistry:
    """Maps tool_name -> plugin_id, so a plugin's tools can be pulled out of McpServer by id."""

    tool_owner: dict[str, str] = field(default_factory=dict)

    def register_ownership(self, plugin_id: str, tool_names: list[str]) -> None:
        for name in tool_names:
            self.tool_owner[name] = plugin_id

    def tools_for_plugin(self, plugin_id: str) -> list[str]:
        return [n for n, p in self.tool_owner.items() if p == plugin_id]

    def unload_plugin(self, server: "McpServer", plugin_id: str) -> int:
        """Remove the tools this plugin registered from server.tools, returning how many went."""
        try:
            from src.mcp.plugins.subprocess_runtime import drop_session

            drop_session(plugin_id)
        except Exception:
            pass
        names = set(self.tools_for_plugin(plugin_id))
        if not names:
            logger.info(
                "[MCP plugin] unloading %s: it had no registered tools", plugin_id
            )
            return 0
        before = len(server.tools)
        server.tools = [t for t in server.tools if t.name not in names]
        removed = before - len(server.tools)
        for n in names:
            self.tool_owner.pop(n, None)
        logger.info(
            "[MCP plugin] unloaded %s: removed %d tools %s",
            plugin_id,
            removed,
            sorted(names),
        )
        return removed

    def clear(self) -> None:
        self.tool_owner.clear()


# an optional in-process shared instance (McpServer owning one is clearer; this is for the simple cases)
_default_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = PluginRegistry()
    return _default_registry
