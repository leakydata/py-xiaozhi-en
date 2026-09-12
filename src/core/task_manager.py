"""Task manager.

One place to create, track and clean up the async tasks.
"""

import asyncio
from typing import Any, Awaitable, Callable, Optional

from src.logging import get_logger

logger = get_logger()


class TaskManager:
    """Async task manager.

    Responsibilities:
    - create and track async tasks
    - cancel every task on shutdown
    - schedule work from other threads safely

    Usage:
        tm = TaskManager()
        tm.set_loop(asyncio.get_running_loop())

        # create a task
        task = tm.spawn(some_coroutine(), "task_name")

        # schedule from another thread
        tm.schedule_nowait(some_function, arg1, arg2)

        # clean up on shutdown
        await tm.cancel_all()
    """

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._running: bool = False

    def initialize(self, loop: asyncio.AbstractEventLoop = None) -> None:
        """Initialise the task manager.

        Args:
            loop: the event loop; None means the one currently running
        """
        self._loop = loop or asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        self._running = True
        logger.debug("TaskManager initialised")

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """
        The event loop.
        """
        return self._loop

    @property
    def running(self) -> bool:
        """
        Whether it is running.
        """
        return self._running

    @property
    def shutdown_event(self) -> Optional[asyncio.Event]:
        """
        The shutdown event.
        """
        return self._shutdown_event

    def spawn(self, coro: Awaitable[Any], name: str) -> Optional[asyncio.Task]:
        """Create an async task and track it.

        Args:
            coro: the coroutine
            name: the task name

        Returns:
            the task, or None if the application is shutting down
        """
        # check whether a shutdown is under way
        if not self._running or (
            self._shutdown_event and self._shutdown_event.is_set()
        ):
            logger.debug(
                f"not creating the task, the application is shutting down: {name}"
            )
            return None

        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        def _on_done(t: asyncio.Task):
            self._tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    # a done callback has no active exception context, so the exception itself must be passed
                    logger.error(
                        f"task {name} ended with an exception: {exc}", exc_info=exc
                    )

        task.add_done_callback(_on_done)
        return task

    def schedule_nowait(self, fn: Callable, *args, **kwargs) -> None:
        """Schedule a callable from any thread.

        If the callable returns a coroutine, a task is created for it.

        Args:
            fn: the callable
            *args: positional arguments
            **kwargs: keyword arguments
        """
        # refuse silently while shutting down
        if not self._running or (
            self._shutdown_event and self._shutdown_event.is_set()
        ):
            return

        if not self._loop or self._loop.is_closed():
            # skip silently during shutdown, without a warning
            return

        def _runner():
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    task = self.spawn(
                        result, name=f"scheduled:{getattr(fn, '__name__', 'anon')}"
                    )
                    if task is None:
                        result.close()
            except Exception as e:
                logger.error(f"the scheduled callable failed: {e}", exc_info=True)

        self._loop.call_soon_threadsafe(_runner)

    async def wait_shutdown(self) -> None:
        """
        Wait for the shutdown signal.
        """
        if self._shutdown_event:
            await self._shutdown_event.wait()

    def request_shutdown(self) -> None:
        """
        Request a shutdown.
        """
        if self._shutdown_event and not self._shutdown_event.is_set():
            self._shutdown_event.set()
            logger.info("shutdown requested")

    async def cancel_all(self) -> None:
        """Cancel every tracked task.

        Waits for them all to finish or be cancelled.
        """
        self._running = False

        if self._shutdown_event:
            self._shutdown_event.set()

        if not self._tasks:
            return

        logger.info(f"cancelling {len(self._tasks)} tasks...")

        # cancel them all
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

        # wait for them all to finish
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        logger.info("every task cancelled")

    def task_count(self) -> int:
        """
        The current number of tasks.
        """
        return len(self._tasks)

    def get_task_names(self) -> list[str]:
        """
        The names of every task.
        """
        return [t.get_name() for t in self._tasks if not t.done()]
