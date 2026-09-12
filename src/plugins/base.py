"""The plugin base class.

Plugins reach the core services through the PluginContext and PluginCommands interfaces.
"""

import asyncio
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext
    from src.core.resource_pool import ResourcePool


class Plugin:
    """The plugin base class.

    A plugin reads state through PluginContext and acts through PluginCommands.

    Attributes:
        name: the plugin name, used in dependency declarations and the log
        priority: lower runs earlier (1-100)
        requires: the plugin names this depends on; PluginManager injects them

    Usage:
        class MyPlugin(Plugin):
            name = "my_plugin"
            priority = 50
            requires = ["audio"]  # declares a dependency on AudioPlugin

            async def setup(self, ctx, cmd):
                await super().setup(ctx, cmd)
                # self.deps["audio"] is the AudioPlugin instance
    """

    name: str = "plugin"
    priority: int = 50  # lower runs earlier (1-100)
    requires: List[str] = []  # the plugin names this depends on

    def __init__(self) -> None:
        self._started = False
        self._failed = False
        self._ctx: "PluginContext" = None
        self._cmd: "PluginCommands" = None
        self._deps: dict[str, "Plugin"] = {}  # the injected dependency instances

    @property
    def ctx(self) -> "PluginContext":
        """
        The plugin context.
        """
        return self._ctx

    @property
    def cmd(self) -> "PluginCommands":
        """
        The plugin command interface.
        """
        return self._cmd

    @property
    def deps(self) -> dict[str, "Plugin"]:
        """The injected dependency instances."""
        return self._deps

    @property
    def failed(self) -> bool:
        """Whether the plugin is marked failed (its setup or start failed, or a dependency did)."""
        return self._failed

    def mark_failed(self) -> None:
        """Mark the plugin failed; it will be skipped by start and the notifications."""
        self._failed = True

    def get_dep(self, name: str) -> Optional["Plugin"]:
        """Get a dependency by name."""
        return self._deps.get(name)

    def _inject_dependency(self, name: str, plugin: "Plugin") -> None:
        """Inject the dependencies (called by PluginManager)."""
        self._deps[name] = plugin

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        """Prepare the plugin.

        Args:
            ctx: the plugin context (read-only access to state)
            cmd: the plugin command interface (for acting)
        """
        self._ctx = ctx
        self._cmd = cmd
        await asyncio.sleep(0)

    async def start(self) -> None:
        """
        Start the plugin (usually once the protocol has connected).
        """
        self._started = True
        await asyncio.sleep(0)

    async def on_protocol_connected(self, protocol: Any) -> None:
        """
        Called once the protocol channel is up.
        """
        await asyncio.sleep(0)

    async def on_incoming_json(self, message: Any) -> None:
        """
        Called when a JSON message arrives.
        """
        await asyncio.sleep(0)

    async def on_incoming_audio(self, data: bytes) -> None:
        """
        Called when audio data arrives.
        """
        await asyncio.sleep(0)

    async def on_device_state_changed(self, state: Any) -> None:
        """
        Called when the device state changes.
        """
        await asyncio.sleep(0)

    async def stop(self) -> None:
        """
        Stop the plugin.
        """
        self._started = False
        await asyncio.sleep(0)

    def register_resources(self, pool: "ResourcePool") -> None:
        """
        Register cleanup functions with the resource pool. Subclasses override this to register what they need released.
        Resources are released in reverse order of registration.

        Args:
            pool: the resource pool
        """
        pass
