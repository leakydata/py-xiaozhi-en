"""Plugin manager.

Manages the plugin lifecycle, with declared dependencies and topological ordering.
"""

from typing import TYPE_CHECKING, Any, List, Optional

from src.logging import get_logger

from .base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()


class PluginManager:
    """Plugin manager.

    Responsibilities:
    - order the plugins topologically by their dependencies
    - inject each plugin's dependencies automatically
    - broadcast setup/start/stop from one place
    - isolate errors, so one failing plugin does not take the others down
    - mark failures, and skip anything downstream of a failed dependency
    """

    def __init__(self) -> None:
        self._plugins: List[Plugin] = []
        self._by_name: dict[str, Plugin] = {}
        self._sorted: bool = False

    def register(self, *plugins: Plugin) -> None:
        """Register a plugin.

        Sorted by priority here; setup_all later re-orders them topologically by dependency.
        """
        sorted_plugins = sorted(plugins, key=lambda p: getattr(p, "priority", 50))
        for p in sorted_plugins:
            if p not in self._plugins:
                self._plugins.append(p)
                try:
                    name = getattr(p, "name", None)
                    if isinstance(name, str) and name:
                        self._by_name[name] = p
                except Exception as e:
                    logger.error(f"plugin registration failed: {e}", exc_info=True)
        self._sorted = False

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a plugin instance by name."""
        return self._by_name.get(name)

    def is_failed(self, name: str) -> bool:
        """Whether the plugin has failed (an unregistered one counts as failed)."""
        plugin = self._by_name.get(name)
        return plugin is None or plugin.failed

    def failed_plugins(self) -> List[str]:
        """The names of every plugin that has failed."""
        return [
            p.name
            for p in self._plugins
            if getattr(p, "name", None) and p.failed
        ]

    def _dependencies_ok(self, plugin: Plugin) -> bool:
        """Whether every dependency a plugin declares is available (registered and not failed)."""
        requires = getattr(plugin, "requires", []) or []
        for dep_name in requires:
            dep = self._by_name.get(dep_name)
            if dep is None:
                logger.warning(
                    f"plugin {getattr(plugin, 'name', 'unknown')} depends on {dep_name}, which is not registered"
                )
                return False
            if dep.failed:
                logger.warning(
                    f"plugin {getattr(plugin, 'name', 'unknown')} depends on {dep_name}, which has failed - skipping"
                )
                return False
        return True

    def _active_plugins(self) -> List[Plugin]:
        """The plugins that have not failed."""
        return [p for p in self._plugins if not p.failed]

    def _topological_sort(self) -> List[Plugin]:
        """Sort the plugins topologically, so a dependency is initialised before its dependents.

        Returns:
            the sorted plugin list

        Raises:
            ValueError: there is a dependency cycle
        """
        # build the dependency graph
        in_degree: dict[str, int] = {}
        dependents: dict[str, List[str]] = {}  # who depends on this

        for p in self._plugins:
            name = getattr(p, "name", "")
            if name:
                in_degree[name] = 0
                dependents[name] = []

        for p in self._plugins:
            name = getattr(p, "name", "")
            requires = getattr(p, "requires", []) or []
            for dep in requires:
                if dep in self._by_name:
                    in_degree[name] = in_degree.get(name, 0) + 1
                    dependents[dep].append(name)
                else:
                    logger.warning(f"plugin {name} declares a dependency on {dep}, which is not registered - ignoring it")

        # Kahn's algorithm
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result: List[Plugin] = []

        while queue:
            # among the nodes with in-degree 0, take the one with the lowest priority number
            queue.sort(
                key=lambda n: getattr(self._by_name.get(n), "priority", 50)
            )
            current = queue.pop(0)
            plugin = self._by_name.get(current)
            if plugin:
                result.append(plugin)

            for dependent in dependents.get(current, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len([p for p in self._plugins if getattr(p, "name", "")]):
            raise ValueError("the plugins have a dependency cycle")

        # append the plugins that have no name
        unnamed = [p for p in self._plugins if not getattr(p, "name", "")]
        result.extend(unnamed)

        return result

    def _inject_dependencies(self) -> None:
        """Inject each plugin's declared dependencies."""
        for p in self._plugins:
            requires = getattr(p, "requires", []) or []
            for dep_name in requires:
                dep_plugin = self._by_name.get(dep_name)
                if dep_plugin:
                    p._inject_dependency(dep_name, dep_plugin)
                    logger.debug(f"injected dependency: {p.name} <- {dep_name}")

    async def setup_all(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        """Initialise every plugin.

        They are initialised in topological order, with their dependencies injected.
        A plugin whose setup fails, or whose dependency failed, is marked failed and skips the rest of the lifecycle.

        Args:
            ctx: the plugin context
            cmd: the plugin command interface
        """
        # topological sort
        if not self._sorted:
            try:
                self._plugins = self._topological_sort()
                self._sorted = True
                logger.info(
                    f"plugins sorted topologically: {[p.name for p in self._plugins if hasattr(p, 'name')]}"
                )
            except ValueError as e:
                logger.error(f"plugin sorting failed: {e}", exc_info=True)
                # fall back to sorting by priority
                self._plugins.sort(key=lambda p: getattr(p, "priority", 50))

        # inject the dependencies
        self._inject_dependencies()

        # initialise
        for p in list(self._plugins):
            name = getattr(p, "name", "unknown")
            if p.failed:
                continue
            if not self._dependencies_ok(p):
                p.mark_failed()
                logger.error(f"plugin {name} skipped setup because a dependency failed")
                continue
            try:
                await p.setup(ctx, cmd)
            except Exception as e:
                p.mark_failed()
                logger.error(f"plugin {name} failed during setup: {e}", exc_info=True)

    async def start_all(self) -> None:
        """Start every plugin that has not failed."""
        for p in list(self._plugins):
            if p.failed:
                continue
            if not self._dependencies_ok(p):
                p.mark_failed()
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} skipped start because a dependency failed"
                )
                continue
            try:
                await p.start()
            except Exception as e:
                p.mark_failed()
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed during start: {e}",
                    exc_info=True,
                )

    async def notify_protocol_connected(self, protocol: Any) -> None:
        """Notify the plugins that the protocol connected."""
        for p in self._active_plugins():
            try:
                if p.on_protocol_connected:
                    await p.on_protocol_connected(protocol)
            except Exception as e:
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed in on_protocol_connected: {e}",
                    exc_info=True,
                )

    async def notify_incoming_json(self, message: Any) -> None:
        """Notify the plugins that a JSON message arrived."""
        for p in self._active_plugins():
            try:
                await p.on_incoming_json(message)
            except Exception as e:
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed in on_incoming_json: {e}",
                    exc_info=True,
                )

    async def notify_incoming_audio(self, data: bytes) -> None:
        """Notify the plugins that audio data arrived."""
        for p in self._active_plugins():
            try:
                await p.on_incoming_audio(data)
            except Exception as e:
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed in on_incoming_audio: {e}",
                    exc_info=True,
                )

    async def notify_device_state_changed(self, state: Any) -> None:
        """Notify the plugins that the device state changed."""
        for p in self._active_plugins():
            try:
                await p.on_device_state_changed(state)
            except Exception as e:
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed in on_device_state_changed: {e}",
                    exc_info=True,
                )

    async def stop_all(self) -> None:
        """Stop every plugin (in reverse order; a failed plugin is still stopped so it can clean up)."""
        for p in reversed(self._plugins):
            try:
                await p.stop()
            except Exception as e:
                logger.error(
                    f"plugin {getattr(p, 'name', 'unknown')} failed during stop: {e}",
                    exc_info=True,
                )
