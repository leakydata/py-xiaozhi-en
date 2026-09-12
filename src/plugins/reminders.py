"""Reminder scheduling: speaking a reminder when it comes due.

Reminder scheduler. Polls the local store and, when something is due, speaks it
unprompted - the piece that makes reminders actually fire rather than only
answering "what are my reminders?".

Announcing goes through send_wake_word_detected, which is the same text-in path
the GUI's Send button uses: {"type":"listen","state":"detect","text":...}. The
server treats it as an utterance and replies in the assistant's own voice, so
no separate TTS voice is needed. The text is phrased as an instruction so the
model announces it rather than answering it.

Two guards matter more than the timing:
  - never fire on a closed channel, or the reminder is spoken into the void
  - never fire mid-conversation, or it talks over the user
In both cases the reminder is left due and retried on the next tick, so nothing
is silently lost.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from src.logging import get_logger
from src.plugins.base import Plugin

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()

_DEFAULT_POLL = 20.0
_MIN_POLL = 5.0


class RemindersPlugin(Plugin):
    """Announce the reminders that have come due."""

    name = "reminders"

    def __init__(self) -> None:
        super().__init__()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._poll = _DEFAULT_POLL
        self._enabled = True

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        await super().setup(ctx, cmd)
        try:
            cfg = ctx.get_config()
            self._enabled = bool(cfg.get_config("REMINDERS.ENABLED", True))
            self._poll = max(
                _MIN_POLL,
                float(cfg.get_config("REMINDERS.POLL_SECONDS", _DEFAULT_POLL)),
            )
        except Exception:
            pass

    async def start(self) -> None:
        if not self._enabled:
            logger.info("reminder scheduling is disabled (REMINDERS.ENABLED=false)")
            return
        self._running = True
        self._task = self._cmd.spawn(self._loop(), "reminder_scheduler")
        logger.info(f"reminder scheduling started, polling every {self._poll:.0f}s")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("reminder scheduling stopped")

    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        # let the app finish connecting before the first check
        await asyncio.sleep(min(self._poll, 10.0))
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"the reminder scheduler raised: {e}", exc_info=True)
            await asyncio.sleep(self._poll)

    async def _tick(self) -> None:
        from src.memory.store import get_memory

        due = get_memory().due(limit=5)
        if not due:
            return

        if not self._ctx.is_audio_channel_opened():
            logger.debug(
                f"{len(due)} reminders are due, but the protocol channel is not connected - retrying later"
            )
            return
        if not self._ctx.is_idle():
            logger.debug(
                f"{len(due)} reminders are due, but a conversation is in progress - retrying later"
            )
            return

        # one per tick: several at once would talk over itself
        item = due[0]
        await self._announce(item)

    async def _announce(self, item: dict) -> None:
        text = (item.get("text") or "").strip()
        if not text:
            get_memory_safe_complete(item)
            return

        who = (item.get("speaker") or "").strip()
        target = who if who else "me"
        prompt = (
            f"This is a scheduled reminder that is due now: {text}. "
            f"Announce it to {target} briefly and naturally. "
            f"Do not answer it or ask a question - just deliver the reminder."
        )

        try:
            if not await self._cmd.connect_protocol():
                logger.warning(
                    "could not announce the reminder: the protocol would not connect, so it stays due for the next attempt"
                )
                return
            await self._cmd.send_wake_word_detected(prompt)
        except Exception as e:
            # leave it due; the next tick retries rather than losing it
            logger.warning(
                f"could not announce the reminder, leaving it due to retry: {e}"
            )
            return

        from src.memory.store import get_memory

        try:
            get_memory().complete(int(item["id"]))
        except Exception as e:
            logger.warning(
                f"announced the reminder but could not mark it done #{item.get('id')}: {e}"
            )
        logger.info(f"announced reminder #{item.get('id')}: {text[:60]}")


def get_memory_safe_complete(item: dict) -> None:
    """Drop a malformed row so it cannot wedge the queue."""
    try:
        from src.memory.store import get_memory

        get_memory().complete(int(item["id"]))
    except Exception:
        pass
