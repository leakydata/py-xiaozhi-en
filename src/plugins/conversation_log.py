"""Feeds every exchange into the conversation log (src/memory/conversation_log.py)."""

from __future__ import annotations

import asyncio

from src.core.event_bus import Events
from src.logging import get_logger
from src.memory.conversation_log import get_conversation_log
from src.plugins.base import Plugin

logger = get_logger()


class ConversationLogPlugin(Plugin):
    name = "conversation_log"

    async def setup(self, ctx, cmd) -> None:
        await super().setup(ctx, cmd)
        ctx.event_bus.on(Events.AUDIO_CHANNEL_CLOSED, self._on_channel_closed)

    async def start(self) -> None:
        # Once a day, copy the memory databases somewhere safe.
        try:
            from src.memory.backup import backup_databases
            from src.utils.resource_finder import get_user_data_dir

            await asyncio.to_thread(backup_databases, get_user_data_dir())
        except Exception as e:
            logger.warning(f"memory backup skipped: {e}")

    def _enabled(self) -> bool:
        return bool(self._ctx.get_config().get_config("CONVERSATION_LOG.ENABLED", True))

    async def on_incoming_json(self, message) -> None:
        if not self._enabled():
            return
        try:
            done = get_conversation_log().on_message(message)
            if done:
                await self._save(done)
        except Exception as e:
            logger.warning(f"conversation log: {e}")

    async def _on_channel_closed(self, _data=None) -> None:
        if not self._enabled():
            return
        done = get_conversation_log().flush()
        if done:
            await self._save(done)

    async def stop(self) -> None:
        done = get_conversation_log().flush()
        if done:
            await self._save(done)

    @staticmethod
    async def _save(exchange) -> None:
        # embedding takes a moment; keep it off the event loop
        await asyncio.to_thread(get_conversation_log().save, exchange)
