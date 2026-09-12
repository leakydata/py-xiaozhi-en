"""Weather MCP tool registration (Open-Meteo, no API key required)."""

from __future__ import annotations

from collections.abc import Callable

from src.logging import get_logger
from src.mcp.tooling import McpTool, Property, PropertyList, PropertyType

from .service import get_forecast_payload, get_weather_payload

logger = get_logger()


def register_weather_tools(add_tool: Callable[[McpTool], None]) -> None:
    """Register weather tools on the McpServer."""

    tools: list[McpTool] = [
        McpTool(
            "get_weather",
            (
                "Get the current weather for a city. "
                "Args: city - city name (e.g. 'Boston', 'Austin, Texas', 'London'); "
                "units - 'imperial' (default, F/mph) or 'metric' (C/km/h)."
            ),
            PropertyList(
                [
                    Property("city", PropertyType.STRING, default_value=""),
                    Property("units", PropertyType.STRING, default_value="imperial"),
                ]
            ),
            get_weather_payload,
        ),
        McpTool(
            "get_forecast",
            (
                "Get the daily weather forecast for a city. "
                "Args: city - city name; days - number of days (1-7); "
                "units - 'imperial' (default) or 'metric'."
            ),
            PropertyList(
                [
                    Property("city", PropertyType.STRING, default_value=""),
                    Property(
                        "days",
                        PropertyType.INTEGER,
                        default_value=3,
                        min_value=1,
                        max_value=7,
                    ),
                    Property("units", PropertyType.STRING, default_value="imperial"),
                ]
            ),
            get_forecast_payload,
        ),
    ]

    for tool in tools:
        add_tool(tool)
    logger.info("Registered %d weather MCP tools (Open-Meteo)", len(tools))
