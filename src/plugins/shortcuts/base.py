"""The abstract base class for the shortcut backends."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from src.logging import get_logger

logger = get_logger()


@dataclass
class ShortcutConfig:
    """One shortcut's configuration."""

    modifier: str  # ctrl, alt, shift, cmd
    key: str  # the key
    description: str = ""


class ShortcutBackend(ABC):
    """The abstract base class for the shortcut backends.

    Defines the interface every shortcut backend has to implement.
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        self._loop = loop
        self._running = False
        self._shortcuts: Dict[str, ShortcutConfig] = {}
        self._callbacks: Dict[str, Callable] = {}

    @abstractmethod
    async def start(self) -> bool:
        """Start listening for shortcuts.

        Returns:
            whether it started
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening for shortcuts."""
        pass

    @abstractmethod
    def register(self, name: str, config: ShortcutConfig, callback: Callable) -> bool:
        """Register a shortcut.

        Args:
            name: the shortcut name
            config: the shortcut configuration
            callback: the callback (it takes no arguments)

        Returns:
            whether it was registered
        """
        pass

    @abstractmethod
    def unregister(self, name: str) -> bool:
        """Unregister a shortcut.

        Args:
            name: the shortcut name

        Returns:
            whether it was unregistered
        """
        pass

    def unregister_all(self) -> None:
        """Unregister every shortcut."""
        for name in list(self._shortcuts.keys()):
            self.unregister(name)

    @property
    def is_running(self) -> bool:
        """Whether it is running."""
        return self._running

    def _run_callback(self, name: str) -> None:
        """Run a callback (thread-safe).

        Args:
            name: the shortcut name
        """
        if name not in self._callbacks:
            return

        callback = self._callbacks[name]
        if self._loop and self._loop.is_running():
            if asyncio.iscoroutinefunction(callback):
                asyncio.run_coroutine_threadsafe(callback(), self._loop)
            else:
                self._loop.call_soon_threadsafe(callback)
        else:
            # no event loop, so call it directly
            if asyncio.iscoroutinefunction(callback):
                logger.warning(
                    f"cannot call the async callback {name}, there is no event loop"
                )
            else:
                try:
                    callback()
                except Exception as e:
                    logger.error(
                        f"the shortcut callback {name} failed: {e}", exc_info=True
                    )
