"""
Shared MCP tooling primitives (Property schema + tool wrapper).
"""

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from src.logging import get_logger

logger = get_logger()

# the return type
ReturnValue = Union[bool, int, str]


class PropertyType(Enum):
    """
    The property types.
    """

    BOOLEAN = "boolean"
    INTEGER = "integer"
    STRING = "string"


@dataclass
class Property:
    """
    One property of an MCP tool.
    """

    name: str
    type: PropertyType
    default_value: Optional[Any] = None
    min_value: Optional[int] = None
    max_value: Optional[int] = None

    @property
    def has_default_value(self) -> bool:
        return self.default_value is not None

    @property
    def has_range(self) -> bool:
        return self.min_value is not None and self.max_value is not None

    def value(self, value: Any) -> Any:
        """
        Validate the value and return it.
        """
        if self.type == PropertyType.INTEGER and self.has_range:
            if value < self.min_value:
                raise ValueError(
                    f"Value {value} is below minimum allowed: {self.min_value}"
                )
            if value > self.max_value:
                raise ValueError(
                    f"Value {value} exceeds maximum allowed: {self.max_value}"
                )
        return value

    def to_json(self) -> Dict[str, Any]:
        """
        Convert to JSON.
        """
        result = {"type": self.type.value}

        if self.has_default_value:
            result["default"] = self.default_value

        if self.type == PropertyType.INTEGER:
            if self.min_value is not None:
                result["minimum"] = self.min_value
            if self.max_value is not None:
                result["maximum"] = self.max_value

        return result


@dataclass
class PropertyList:
    """
    A list of properties.
    """

    properties: List[Property] = field(default_factory=list)

    def __init__(self, properties: Optional[List[Property]] = None):
        """
        Initialise the property list.
        """
        self.properties = properties or []

    def add_property(self, prop: Property):
        self.properties.append(prop)

    def __getitem__(self, name: str) -> Property:
        for prop in self.properties:
            if prop.name == name:
                return prop
        raise KeyError(f"Property not found: {name}")

    def get_required(self) -> List[str]:
        """
        The names of the required properties.
        """
        return [p.name for p in self.properties if not p.has_default_value]

    def to_json(self) -> Dict[str, Any]:
        """
        Convert to JSON.
        """
        return {prop.name: prop.to_json() for prop in self.properties}

    def parse_arguments(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Parse and validate the arguments.
        """
        result = {}

        for prop in self.properties:
            if arguments and prop.name in arguments:
                value = arguments[prop.name]
                # type check
                if prop.type == PropertyType.BOOLEAN and isinstance(value, bool):
                    result[prop.name] = value
                elif prop.type == PropertyType.INTEGER and isinstance(
                    value, (int, float)
                ):
                    result[prop.name] = prop.value(int(value))
                elif prop.type == PropertyType.STRING and isinstance(value, str):
                    result[prop.name] = value
                else:
                    raise ValueError(f"Invalid type for property {prop.name}")
            elif prop.has_default_value:
                result[prop.name] = prop.default_value
            else:
                raise ValueError(f"Missing required argument: {prop.name}")

        return result


@dataclass
class McpTool:
    """
    An MCP tool.
    """

    name: str
    description: str
    properties: PropertyList
    callback: Callable[[Dict[str, Any]], ReturnValue]

    def to_json(self) -> Dict[str, Any]:
        """
        Convert to JSON.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties.to_json(),
                "required": self.properties.get_required(),
            },
        }

    async def call(self, arguments: Dict[str, Any]) -> str:
        """
        Call the tool.
        """
        try:
            # parse the arguments
            parsed_args = self.properties.parse_arguments(arguments)

            # call the callback
            if asyncio.iscoroutinefunction(self.callback):
                result = await self.callback(parsed_args)
            else:
                result = self.callback(parsed_args)

            # format the return value
            if isinstance(result, bool):
                text = "true" if result else "false"
            elif isinstance(result, int):
                text = str(result)
            else:
                text = str(result)

            return json.dumps(
                {"content": [{"type": "text", "text": text}], "isError": False}
            )

        except Exception as e:
            logger.error(f"Error calling tool {self.name}: {e}", exc_info=True)
            return json.dumps(
                {"content": [{"type": "text", "text": str(e)}], "isError": True}
            )
