"""Everything said, kept and searchable, so a new session picks up where the last left off.

The server forgets a conversation the moment the connection closes - and it
closes often: a minute of quiet, a restart, a long story. remember/recall hold
what the assistant chose to keep; this holds everything else. Each exchange
(what the user said, and her reply) is stored with an embedding in its own
database, so:

- every new session's briefing carries the last few hours ("where you left off");
- recall searches past conversations alongside memories, by meaning;
- a plain JSONL file per day is written as well, readable without any tooling.

The text comes from the server's own messages - `stt` (the user, as the server
transcribed them) and `tts` (her sentences) - so nothing extra is sent anywhere.
It is a separate database from memory.db on purpose: raw chatter would drown
the curated memories in search results and topics.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging import get_logger
from src.utils.resource_finder import get_user_data_dir

logger = get_logger()

#: Exchanges are cut at this length before storing, so one long monologue
#: does not become one giant, unsearchable row.
_MAX_TEXT = 4000


class ConversationLog:
    """Collects the running exchange and stores each one when it is complete."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.dir = Path(data_dir) if data_dir else get_user_data_dir()
        self._lock = threading.Lock()
        self._user: list[str] = []
        self._assistant: list[str] = []
        self._speaker: str | None = None
        self._started: float | None = None
        self._store = None

    # ------------------------------------------------------------ storage

    def store(self):
        """The searchable store (a MemoryStore on its own file), opened lazily."""
        if self._store is None:
            from src.memory.store import MemoryStore

            self._store = MemoryStore(self.dir / "conversations.db")
        return self._store

    def _jsonl_path(self) -> Path:
        folder = self.dir / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{datetime.now():%Y-%m-%d}.jsonl"

    # ------------------------------------------------------------ input

    def on_message(self, message: Any) -> tuple[str, str] | None:
        """Feed one server message. Returns a finished exchange to store, if any."""
        if not isinstance(message, dict):
            return None
        kind = message.get("type")
        text = str(message.get("text") or "").strip()
        if not text:
            return None
        with self._lock:
            if kind == "stt":
                from src.protocols import cues

                if cues.is_echo(text):
                    # the app's own cue, reported back as if the user said it
                    self._line("cue", text)
                    return None
                done = self._take() if self._assistant else None
                if self._started is None:
                    self._started = time.time()
                self._user.append(text)
                self._speaker = self._current_speaker() or self._speaker
                self._line("user", text)
                return done
            if kind == "tts" and message.get("state") in (None, "sentence_start"):
                if self._started is None:
                    self._started = time.time()
                # the same sentence can arrive twice (start and end markers)
                if not self._assistant or self._assistant[-1] != text:
                    self._assistant.append(text)
                    self._line("assistant", text)
        return None

    def flush(self) -> tuple[str, str] | None:
        """The session ended: whatever is pending is an exchange."""
        with self._lock:
            return self._take() if (self._user or self._assistant) else None

    def _take(self) -> tuple[str, str]:
        user, assistant = " ".join(self._user), " ".join(self._assistant)
        self._user, self._assistant, self._started = [], [], None
        return user, assistant

    @staticmethod
    def _current_speaker() -> str | None:
        try:
            from src.memory import speaker

            return speaker.get_current()
        except Exception:
            return None

    def _line(self, role: str, text: str) -> None:
        try:
            with self._jsonl_path().open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "at": datetime.now().isoformat(timespec="seconds"),
                            "role": role,
                            "text": text,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as e:
            logger.debug(f"conversation log: could not write the transcript line: {e}")

    def save(self, exchange: tuple[str, str]) -> int | None:
        """Store one exchange with its embedding. Blocking: call off the loop."""
        user, assistant = exchange
        parts = []
        who = self._speaker or "User"
        if user:
            parts.append(f"{who}: {user}")
        if assistant:
            parts.append(f"Assistant: {assistant}")
        text = "\n".join(parts)[:_MAX_TEXT]
        if not text:
            return None
        try:
            return self.store().add(text, kind="event", source="conversation")
        except Exception as e:
            logger.warning(f"conversation log: could not store an exchange: {e}")
            return None

    # ------------------------------------------------------------ output

    def recent(self, hours: float = 3.0, max_chars: int = 2500) -> str:
        """The last few hours, oldest first, cut from the old end to fit."""
        try:
            rows = self.store().recent(limit=40)
        except Exception:
            return ""
        cutoff = time.time() - hours * 3600
        picked, used = [], 0
        for r in rows:  # newest first
            at = _parse(r.get("created_at"))
            if at is None or at.timestamp() < cutoff:
                break
            line = f"[{at.astimezone():%H:%M}] {r['text']}"
            if used + len(line) > max_chars:
                break
            picked.append(line)
            used += len(line)
        return "\n".join(reversed(picked))

    def last_line(self) -> str:
        """One short line: when they last talked and what about."""
        try:
            rows = self.store().recent(limit=1)
        except Exception:
            return ""
        if not rows:
            return ""
        at = _parse(rows[0].get("created_at"))
        first = rows[0]["text"].splitlines()[0][:160]
        if at is None:
            return f"Last exchange: {first}"
        return f"Last exchange ({at.astimezone():%a %H:%M}): {first}"

    def search(self, query: str, k: int = 3) -> list[dict]:
        try:
            rows = self.store().search(query, k=k)
        except Exception as e:
            logger.debug(f"conversation log: search failed: {e}")
            return []
        out = []
        for r in rows:
            at = _parse(r.get("created_at"))
            out.append(
                {
                    "when": at.astimezone().strftime("%Y-%m-%d %H:%M") if at else "",
                    "text": r["text"][:500],
                }
            )
        return out


def _parse(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


_log: ConversationLog | None = None
_log_lock = threading.Lock()


def get_conversation_log() -> ConversationLog:
    global _log
    with _log_lock:
        if _log is None:
            _log = ConversationLog()
        return _log


def set_conversation_log(log: ConversationLog | None) -> None:
    """For tests."""
    global _log
    _log = log
