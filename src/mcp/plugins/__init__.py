"""External MCP plugins: the host API and the loader."""

from .host import McpHost
from .loader import PluginLoader, default_plugins_dir
from .registry import PluginRegistry, get_plugin_registry

__all__ = [
    "McpHost",
    "PluginLoader",
    "PluginRegistry",
    "default_plugins_dir",
    "get_plugin_registry",
]
