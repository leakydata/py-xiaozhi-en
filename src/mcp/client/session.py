"""One conversation with one MCP server.

This is the client half of MCP, which py-xiaozhi did not have: it could only
*be* a server, exposing local Python functions over the tenclass socket. A
session here does the other side - handshake, discover what a server offers,
and call it - so the assistant can use tools it did not implement.

The sequence is fixed by the spec and every server expects it in order:

    initialize            -> capabilities, serverInfo, optional instructions
    notifications/initialized  (no reply)
    tools/list            -> the tools, each with real JSON Schema
    tools/call            -> content blocks

Connecting is lazy and survives failure. A server that is not running when the
assistant starts must not stop the assistant starting, and one that dies later
must not take a conversation down with it - so the failure of any single server
is contained and reported, never raised into the app.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.logging import get_logger

from .transport import DEFAULT_TIMEOUT, Transport, TransportError, build_transport

logger = get_logger()

#: What we tell a server we speak. Servers negotiate down, and every server
#: seen in the wild accepts this.
PROTOCOL_VERSION = "2024-11-05"

CLIENT_INFO = {"name": "py-xiaozhi", "version": "1.0"}


class McpServerSession:
    """A connection to one MCP server, made when first needed."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        self.spec = spec
        self.timeout = float(spec.get("timeout", DEFAULT_TIMEOUT))
        self._transport: Transport | None = None
        self._next_id = 0
        self._connect_lock = asyncio.Lock()
        self._tools: list[dict[str, Any]] = []
        self.instructions: str = ""
        self.server_info: dict[str, Any] = {}
        #: Why the last attempt failed, for the diagnostics tool. Kept rather
        #: than only logged, so "why is Boswell missing" has an answer the
        #: assistant can actually say out loud.
        self.last_error: str = ""

    @property
    def connected(self) -> bool:
        return self._transport is not None and self._transport.alive

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    def _rpc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def connect(self) -> bool:
        """Connect and discover the tools. False if the server is unusable."""
        async with self._connect_lock:
            if self.connected:
                return True
            await self._teardown()
            try:
                transport = build_transport(self.spec)
                await transport.start()
                self._transport = transport
                await self._handshake()
                self._tools = await self._list_tools()
            except TransportError as e:
                self.last_error = str(e)
                logger.warning(f"[mcp:{self.name}] {e}")
                await self._teardown()
                return False
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"[mcp:{self.name}] could not connect: {e}", exc_info=True
                )
                await self._teardown()
                return False

            self.last_error = ""
            logger.info(
                f"[mcp:{self.name}] connected, {len(self._tools)} tools available"
            )
            return True

    async def _handshake(self) -> None:
        assert self._transport is not None
        reply = await self._transport.request(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            },
            self.timeout,
        )
        if "error" in reply:
            raise TransportError(f"initialize refused: {reply['error']}")
        result = reply.get("result", {})
        self.server_info = result.get("serverInfo", {})
        # Servers may describe themselves here. It is worth keeping: it is the
        # server telling the model how it expects to be used.
        self.instructions = (result.get("instructions") or "").strip()
        await self._transport.notify(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

    async def _list_tools(self) -> list[dict[str, Any]]:
        assert self._transport is not None
        tools: list[dict[str, Any]] = []
        cursor = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            reply = await self._transport.request(
                {
                    "jsonrpc": "2.0",
                    "id": self._rpc_id(),
                    "method": "tools/list",
                    "params": params,
                },
                self.timeout,
            )
            if "error" in reply:
                raise TransportError(f"tools/list refused: {reply['error']}")
            result = reply.get("result", {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call(self, tool: str, arguments: dict[str, Any]) -> str:
        """Call one tool and return its content as text.

        Reconnects once if the server died since the last call, which for a
        stdio server is routine - it may have been restarted underneath us.
        """
        if not self.connected and not await self.connect():
            return f"{self.name} is unavailable: {self.last_error or 'not connected'}"

        try:
            return await self._call_once(tool, arguments)
        except TransportError as e:
            logger.info(f"[mcp:{self.name}] {e} - reconnecting and retrying once")
            await self._teardown()
            if not await self.connect():
                return (
                    f"{self.name} is unavailable: {self.last_error or 'not connected'}"
                )
            try:
                return await self._call_once(tool, arguments)
            except Exception as e2:
                return f"{self.name}.{tool} failed: {e2}"
        except Exception as e:
            logger.error(f"[mcp:{self.name}] {tool} failed: {e}", exc_info=True)
            return f"{self.name}.{tool} failed: {e}"

    async def _call_once(self, tool: str, arguments: dict[str, Any]) -> str:
        assert self._transport is not None
        reply = await self._transport.request(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id(),
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
            self.timeout,
        )
        if "error" in reply:
            err = reply["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            return f"{self.name}.{tool} refused: {message}"
        return _content_to_text(reply.get("result", {}))

    async def _teardown(self) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                pass

    async def close(self) -> None:
        await self._teardown()
        self._tools = []


def _content_to_text(result: dict[str, Any]) -> str:
    """Flatten an MCP result into something speakable.

    Tool results arrive as content blocks. Text blocks are what matter; images
    and audio are described rather than inlined, because this reply is heading
    for a text-to-speech pipeline and a base64 blob would be both useless and
    enormous.
    """
    if not isinstance(result, dict):
        return str(result)

    blocks = result.get("content")
    if blocks is None:
        # Some servers answer with structured content and no blocks at all.
        structured = result.get("structuredContent")
        if structured is not None:
            return json.dumps(structured, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    parts: list[str] = []
    for block in blocks if isinstance(blocks, list) else [blocks]:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} returned, {block.get('mimeType', 'unknown type')}]")
        elif kind == "resource":
            resource = block.get("resource", {})
            parts.append(
                resource.get("text") or f"[resource {resource.get('uri', '')}]"
            )
        else:
            parts.append(json.dumps(block, ensure_ascii=False))

    text = "\n".join(p for p in parts if p).strip()
    if result.get("isError"):
        return f"error: {text}" if text else "the tool reported an error"
    return text or "(no output)"
