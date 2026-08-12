"""Web MCP tool registration (search + page reader)."""

from __future__ import annotations

from collections.abc import Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .reader import fetch_page_payload
from .search import web_search_payload

logger = get_logger()


def register_web_tools(add_tool: Callable[[McpTool], None]) -> None:
    """Register web search and page reading tools on the McpServer."""

    tools: list[McpTool] = [
        McpTool(
            "web_search",
            (
                "Search the web and return ranked results with titles, URLs and "
                "snippets. Use this for current information, facts you are unsure "
                "of, prices, news, or anything time-sensitive. Follow up with "
                "fetch_page on a result URL to read the full article. "
                "Args: query - what to search for; max_results - 1-10 (default 5)."
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
                ]
            ),
            web_search_payload,
        ),
        McpTool(
            "fetch_page",
            (
                "Fetch a web page and return its readable text content. Use after "
                "web_search to read a result in full, or when the user gives a URL. "
                "Args: url - the page address; max_length - characters to return "
                "(200-20000, default 8000)."
            ),
            PropertyList(
                [
                    Property("url", PropertyType.STRING, default_value=""),
                    Property(
                        "max_length",
                        PropertyType.INTEGER,
                        default_value=8000,
                        min_value=200,
                        max_value=20000,
                    ),
                ]
            ),
            fetch_page_payload,
        ),
    ]

    for tool in tools:
        add_tool(tool)
    logger.info("Registered %d web MCP tools (search + reader)", len(tools))
