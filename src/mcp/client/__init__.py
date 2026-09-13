"""Using other MCP servers, rather than only being one.

py-xiaozhi has always been an MCP *server*: it exposes local Python functions
as tools over the tenclass socket. This package is the missing other half - a
real MCP *client*, so the assistant can reach servers it did not write.

Servers are listed in config under MCP_CLIENT.SERVERS, in the same shape as a
`.mcp.json` entry, so anything already configured for another tool can be
pasted straight in.
"""

from .bridge import McpClientManager, make_proxy_tool, properties_from_input_schema
from .session import McpServerSession
from .tools import register_mcp_client_tools
from .transport import HttpTransport, StdioTransport, TransportError, build_transport

__all__ = [
    "McpClientManager",
    "McpServerSession",
    "register_mcp_client_tools",
    "HttpTransport",
    "StdioTransport",
    "TransportError",
    "build_transport",
    "make_proxy_tool",
    "properties_from_input_schema",
]
