"""The resource pool.

One place to register and release resources. Anything needing cleanup - C extensions,
audio streams, network connections - registers here, and shutdown releases everything in reverse order, so nothing is freed twice or forgotten.
"""

import asyncio
from typing import Awaitable, Callable, Union

from src.logging import get_logger

logger = get_logger()

CleanupFunc = Callable[[], Union[None, Awaitable[None]]]


class ResourcePool:
    """The resource pool - register cleanup functions, released in reverse order.

    Usage:
        pool = ResourcePool()
        pool.register("opus_codec", opus_codec.close)
        pool.register("audio_stream", stream_manager.stop)
        await pool.shutdown()  # runs every cleanup, newest first
    """

    def __init__(self):
        self._resources: list[tuple[str, CleanupFunc]] = []
        self._shutting_down = False

    def register(self, name: str, cleanup: CleanupFunc) -> None:
        """Register a cleanup function.

        Args:
            name: what the resource is called, for the log and for debugging
            cleanup: the cleanup function, either a plain function or an async one
        """
        if self._shutting_down:
            logger.warning(
                f"the resource pool is shutting down, not registering: {name}"
            )
            return
        self._resources.append((name, cleanup))

    async def shutdown(self) -> None:
        """Release every registered resource, in reverse order of registration."""
        if self._shutting_down:
            return
        self._shutting_down = True

        for name, cleanup in reversed(self._resources):
            try:
                result = cleanup()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"failed to release [{name}]: {e}", exc_info=True)

        self._resources.clear()
        logger.debug("resource pool emptied")
