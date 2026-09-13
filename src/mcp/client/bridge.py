"""Putting another server's tools into the assistant's own tool list.

A discovered tool is wrapped in an `McpTool` whose callback forwards the call
back out over the session. From the assistant's side there is then no
difference between `remember` (local Python) and `boswell.search_by_meaning`
(another process entirely) - both are simply tools it can call.

Names are prefixed with the server's name. Two servers offering `search` is
normal, and the prefix also tells the model where an answer came from, which
matters when it is deciding whether to look in the audio archive or the
camera one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .session import McpServerSession

logger = get_logger()

_JSON_TYPES = {
    "string": PropertyType.STRING,
    "integer": PropertyType.INTEGER,
    "number": PropertyType.NUMBER,
    "boolean": PropertyType.BOOLEAN,
    "array": PropertyType.ARRAY,
    "object": PropertyType.OBJECT,
}


def _property_from_schema(
    name: str, schema: dict[str, Any], required: bool
) -> Property:
    """Carry one argument across, keeping the server's own schema."""
    declared = schema.get("type")
    if isinstance(declared, list):
        # A union such as ["string", "null"]: take the first real type and let
        # the passthrough schema carry the full truth.
        declared = next((t for t in declared if t != "null"), "string")
    kind = _JSON_TYPES.get(declared or "string", PropertyType.STRING)
    return Property(
        name=name,
        type=kind,
        default_value=schema.get("default"),
        schema=schema,
        required=required,
    )


def properties_from_input_schema(
    input_schema: dict[str, Any] | None,
) -> PropertyList:
    """Build a PropertyList from a remote tool's inputSchema."""
    schema = input_schema or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return PropertyList(
        [
            _property_from_schema(
                name, sub if isinstance(sub, dict) else {}, name in required
            )
            for name, sub in props.items()
        ]
    )


def _describe(tool: dict[str, Any], server: str) -> str:
    """The description the model reads, with the source made explicit."""
    text = (tool.get("description") or "").strip()
    if not text:
        text = f"The {tool.get('name', 'tool')} tool from {server}."
    return f"[{server}] {text}"


def make_proxy_tool(
    session: McpServerSession, tool: dict[str, Any], prefix: str
) -> McpTool:
    """Wrap one remote tool so the assistant can call it."""
    remote_name = tool["name"]
    local_name = f"{prefix}{remote_name}" if prefix else remote_name

    async def _invoke(arguments: dict[str, Any]) -> str:
        return await session.call(remote_name, arguments or {})

    return McpTool(
        name=local_name,
        description=_describe(tool, session.name),
        properties=properties_from_input_schema(tool.get("inputSchema")),
        callback=_invoke,
    )


def _filtered(
    tools: list[dict[str, Any]], spec: dict[str, Any], server: str
) -> list[dict[str, Any]]:
    """Narrow a server's tools to the ones worth offering.

    A rich server can contribute thirty-odd tools, and several of those at once
    leaves the model choosing from a list long enough to hurt its aim - and the
    whole list is sent on every handshake. `include` keeps only what is named;
    `exclude` drops what is named. Without either, everything is offered.
    """
    include = spec.get("include")
    exclude = set(spec.get("exclude") or [])

    if include:
        wanted = list(include)
        by_name = {t.get("name"): t for t in tools}
        missing = [n for n in wanted if n not in by_name]
        if missing:
            logger.warning(
                f"[mcp:{server}] include names tools this server does not offer: "
                f"{', '.join(missing)}"
            )
        chosen = [by_name[n] for n in wanted if n in by_name]
    else:
        chosen = list(tools)

    if exclude:
        chosen = [t for t in chosen if t.get("name") not in exclude]

    if len(chosen) != len(tools):
        logger.info(f"[mcp:{server}] offering {len(chosen)} of {len(tools)} tools")
    return chosen


class McpClientManager:
    """Owns every outbound MCP connection and the tools they contribute."""

    def __init__(self) -> None:
        self._sessions: dict[str, McpServerSession] = {}
        self._tool_names: dict[str, list[str]] = {}

    @property
    def sessions(self) -> dict[str, McpServerSession]:
        return dict(self._sessions)

    async def connect_all(
        self, servers: dict[str, dict[str, Any]], add_tool: Callable[[McpTool], None]
    ) -> int:
        """Connect to every configured server and register what they offer.

        Servers are dialled concurrently, because one slow or dead server must
        not hold up the rest - and a wedged one costs its whole timeout.
        """
        wanted = {
            name: spec
            for name, spec in (servers or {}).items()
            if isinstance(spec, dict) and spec.get("enabled", True)
        }
        if not wanted:
            return 0

        sessions = {name: McpServerSession(name, spec) for name, spec in wanted.items()}
        results = await asyncio.gather(
            *(s.connect() for s in sessions.values()), return_exceptions=True
        )

        registered = 0
        # Same length by construction: results comes from gather over sessions.
        for (name, session), ok in zip(sessions.items(), results, strict=True):
            if isinstance(ok, Exception):
                logger.warning(f"[mcp:{name}] connect raised: {ok}")
                continue
            if not ok:
                continue
            self._sessions[name] = session
            prefix = session.spec.get("prefix", f"{name}.")
            names: list[str] = []
            for tool in _filtered(session.tools, session.spec, name):
                try:
                    proxy = make_proxy_tool(session, tool, prefix)
                except Exception as e:
                    logger.warning(
                        f"[mcp:{name}] skipping tool {tool.get('name')!r}: {e}"
                    )
                    continue
                add_tool(proxy)
                names.append(proxy.name)
                registered += 1
            self._tool_names[name] = names

        if registered:
            logger.info(
                f"MCP client: {registered} tools from "
                f"{len(self._sessions)} server(s): {', '.join(self._sessions)}"
            )
        return registered

    def status(self) -> list[dict[str, Any]]:
        """What each configured server is doing, for the diagnostics tool."""
        return [
            {
                "server": name,
                "connected": s.connected,
                "tools": len(self._tool_names.get(name, [])),
                "error": s.last_error or None,
                "info": s.server_info.get("name") or None,
            }
            for name, s in self._sessions.items()
        ]

    def instructions(self) -> list[str]:
        """Any self-description the servers offered during initialize."""
        out = []
        for name, session in self._sessions.items():
            if session.instructions:
                out.append(f"{name}: {session.instructions}")
        return out

    async def close(self) -> None:
        for session in self._sessions.values():
            try:
                await session.close()
            except Exception:
                pass
        self._sessions.clear()
        self._tool_names.clear()
