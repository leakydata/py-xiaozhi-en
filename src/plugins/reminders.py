"""提醒调度：到点主动播报.

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
    """到点播报提醒."""

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
                _MIN_POLL, float(cfg.get_config("REMINDERS.POLL_SECONDS", _DEFAULT_POLL))
            )
        except Exception:
            pass

    async def start(self) -> None:
        if not self._enabled:
            logger.info("提醒调度已禁用 (REMINDERS.ENABLED=false)")
            return
        self._running = True
        self._task = self._cmd.spawn(self._loop(), "reminder_scheduler")
        logger.info(f"提醒调度已启动，轮询间隔 {self._poll:.0f}s")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("提醒调度已停止")

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
                logger.error(f"提醒调度异常: {e}", exc_info=True)
            await asyncio.sleep(self._poll)

    async def _tick(self) -> None:
        from src.memory.store import get_memory

        due = get_memory().due(limit=5)
        if not due:
            return

        if not self._ctx.is_audio_channel_opened():
            logger.debug(f"{len(due)} 条提醒到期，但协议通道未连接，稍后重试")
            return
        if not self._ctx.is_idle():
            logger.debug(f"{len(due)} 条提醒到期，但正在对话中，稍后重试")
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
                logger.warning("提醒播报失败：无法建立协议连接，保留待下次重试")
                return
            await self._cmd.send_wake_word_detected(prompt)
        except Exception as e:
            # leave it due; the next tick retries rather than losing it
            logger.warning(f"提醒播报失败，保留待重试: {e}")
            return

        from src.memory.store import get_memory

        try:
            get_memory().complete(int(item["id"]))
        except Exception as e:
            logger.warning(f"提醒已播报但标记完成失败 #{item.get('id')}: {e}")
        logger.info(f"已播报提醒 #{item.get('id')}: {text[:60]}")


def get_memory_safe_complete(item: dict) -> None:
    """Drop a malformed row so it cannot wedge the queue."""
    try:
        from src.memory.store import get_memory

        get_memory().complete(int(item["id"]))
    except Exception:
        pass
