"""Reminder scheduling: speaking a reminder when it comes due.

Reminder scheduler. Polls the local store and, when something is due, speaks it
unprompted - the piece that makes reminders actually fire rather than only
answering "what are my reminders?".

Announcing goes through send_wake_word_detected, which is the same text-in path
the GUI's Send button uses: {"type":"listen","state":"detect","text":...}. The
server treats it as an utterance and replies in the assistant's own voice, so
no separate TTS voice is needed. xiaozhi.me refuses long text (over ~21 characters)
there, so the text is the short cue "read due reminders" (src/protocols/cues.py),
which the assistant is told to answer by listing and announcing what is due.

Two guards matter more than the timing:
  - never fire on a closed channel, or the reminder is spoken into the void
  - never fire mid-conversation, or it talks over the user
In both cases the reminder is left due and retried on the next tick, so nothing
is silently lost.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

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
        self._task: asyncio.Task | None = None
        self._running = False
        self._poll = _DEFAULT_POLL
        self._enabled = True
        #: After the server refuses the cue, wait before trying again rather
        #: than sending it every poll.
        self._cue_backoff_until = 0.0
        #: reminder id -> (when last raised, how many times), so one that
        #: has been raised is not raised again every poll
        self._cued: dict[int, tuple[float, int]] = {}

    async def setup(self, ctx: PluginContext, cmd: PluginCommands) -> None:
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

        from src.core import presence_state

        # Not over the assistant, and not over the user mid-sentence. With the
        # session kept open the device is LISTENING most of the time, so
        # "idle" alone would starve reminders; a quiet stretch will do.
        if self._ctx.is_speaking():
            return
        now = time.monotonic()
        if not self._ctx.is_idle():
            quiet = now - max(
                presence_state.last_activity(), presence_state.last_user_speech()
            )
            if quiet < 20:
                logger.debug(f"{len(due)} reminders are due; waiting for a pause")
                return

        fresh = [
            r for r in due if now - self._cued.get(int(r["id"]), (-1e9, 0))[0] > 600
        ]
        if not fresh:
            return  # all were raised in the last ten minutes
        await self._announce(fresh[0], fresh)

    async def _announce(self, item: dict, due: list | None = None) -> None:
        due_at_cue = list(due or [item])
        text = (item.get("text") or "").strip()
        if not text:
            get_memory_safe_complete(item)
            return

        from src.constants.constants import ListeningMode
        from src.core import presence_state
        from src.protocols import cues

        if time.monotonic() < self._cue_backoff_until:
            return
        # The server refuses a sentence sent this way, so send the short cue:
        # the assistant knows to list the due reminders, announce them and
        # mark them done herself.
        try:
            if not self._ctx.is_listening():
                # a detect straight from idle is often dropped by the server
                if not await self._cmd.connect_protocol():
                    logger.warning(
                        "could not announce the reminder: no connection; it stays due"
                    )
                    return
                mode = (
                    ListeningMode.REALTIME
                    if self._ctx.get_config().get_config("AEC_OPTIONS.ENABLED", True)
                    else ListeningMode.AUTO_STOP
                )
                await self._cmd.start_listening(mode)
            sent_at = cues.note_sent(cues.REMINDER)
            await self._cmd.send_wake_word_detected(cues.REMINDER)
            replied = False
            for _ in range(20):
                await asyncio.sleep(1.0)
                if cues.rejected_since(sent_at):
                    break
                if presence_state.last_activity() > sent_at:
                    replied = True
                    break
        except Exception as e:
            logger.warning(f"could not announce the reminder, leaving it due: {e}")
            return

        if not replied:
            refused = cues.rejected_since(sent_at)
            self._cue_backoff_until = time.monotonic() + (600 if refused else 120)
            logger.warning(
                f"the reminder cue was {'refused' if refused else 'not answered'}; "
                f"{len(due_at_cue)} reminder(s) stay due"
            )
            return

        now = time.monotonic()
        for row in due_at_cue:
            nid = int(row["id"])
            count = self._cued.get(nid, (0, 0))[1] + 1
            self._cued[nid] = (now, count)
            if count >= 3:
                # raised three times and answered each time, but never marked
                # done: she has said it, so close it rather than nag forever
                get_memory_safe_complete(row)
        logger.info(f"cued {len(due_at_cue)} due reminder(s), first #{item.get('id')}")


def get_memory_safe_complete(item: dict) -> None:
    """Drop a malformed row so it cannot wedge the queue."""
    try:
        from src.memory.store import get_memory

        get_memory().complete(int(item["id"]))
    except Exception:
        pass
