"""The host API external MCP plugins see (a stable contract).

A plugin registers its tools and picks up allow-listed capabilities through McpHost alone; reaching for a global singleton is not allowed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

logger = get_logger()

# the host.get names allowed by default (music_player and the like must be added in the config)
DEFAULT_ALLOW_GET = frozenset({"config_readonly", "logger"})


class McpHost:
    """The host facade, bound to one assembly pass."""

    def __init__(
        self,
        add_tool: Callable[[McpTool], None],
        *,
        capabilities: dict[str, Any] | None = None,
        allow_get: Sequence[str] | None = None,
        plugin_id: str | None = None,
    ) -> None:
        self._add_tool = add_tool
        self._capabilities = dict(capabilities or {})
        self._allow_get = (
            frozenset(allow_get) if allow_get is not None else DEFAULT_ALLOW_GET
        )
        self._plugin_id = plugin_id or "unknown"
        self._registered_names: list[str] = []

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def registered_tool_names(self) -> list[str]:
        return list(self._registered_names)

    def bind_plugin(self, plugin_id: str) -> "McpHost":
        """A view bound to one plugin_id, sharing add_tool and the capabilities."""
        child = McpHost(
            self._add_tool,
            capabilities=self._capabilities,
            allow_get=self._allow_get,
            plugin_id=plugin_id,
        )
        return child

    def add_tool(self, tool: McpTool) -> None:
        """Register a tool, keeping its name for unloading and diagnostics."""
        self._add_tool(tool)
        self._registered_names.append(tool.name)
        logger.info("[MCP plugin:%s] registered tool: %s", self._plugin_id, tool.name)

    def get(self, name: str) -> Any:
        """Return an allow-listed host capability; None when it is not permitted or not provided."""
        if name not in self._allow_get:
            logger.warning(
                "[MCP plugin:%s] host.get(%r) is not in the allow list %s",
                self._plugin_id,
                name,
                sorted(self._allow_get),
            )
            return None
        if name == "logger":
            return get_logger()
        return self._capabilities.get(name)

    def tool(
        self,
        name: str,
        description: str,
        props: Sequence[Property | dict[str, Any]] | None = None,
    ):
        """Decorator: register a function as an McpTool (nothing touches a global registry)."""

        def decorator(func: Callable):
            prop_list = _to_property_list(props)
            self.add_tool(McpTool(name, description, prop_list, func))
            return func

        return decorator


def _to_property_list(
    props: Sequence[Property | dict[str, Any]] | None,
) -> PropertyList:
    if not props:
        return PropertyList()
    converted: list[Property] = []
    for p in props:
        if isinstance(p, Property):
            converted.append(p)
            continue
        if not isinstance(p, dict):
            raise TypeError(
                f"each props entry must be a Property or a dict, got {type(p)}"
            )
        converted.append(_dict_to_property(p))
    return PropertyList(converted)


def _dict_to_property(data: dict[str, Any]) -> Property:
    """Accepts the shorthand dict: {name, type: str|int|bool|string|integer|boolean, ...}."""
    name = data["name"]
    raw_type = data.get("type", "string")
    type_map = {
        "str": PropertyType.STRING,
        "string": PropertyType.STRING,
        "int": PropertyType.INTEGER,
        "integer": PropertyType.INTEGER,
        "bool": PropertyType.BOOLEAN,
        "boolean": PropertyType.BOOLEAN,
        PropertyType.STRING: PropertyType.STRING,
        PropertyType.INTEGER: PropertyType.INTEGER,
        PropertyType.BOOLEAN: PropertyType.BOOLEAN,
    }
    if isinstance(raw_type, PropertyType):
        ptype = raw_type
    else:
        ptype = type_map.get(str(raw_type).lower())
        if ptype is None:
            raise ValueError(f"unknown property type: {raw_type}")
    return Property(
        name,
        ptype,
        default_value=data.get("default", data.get("default_value")),
        min_value=data.get("min", data.get("min_value")),
        max_value=data.get("max", data.get("max_value")),
    )
