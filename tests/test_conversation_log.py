"""Every exchange is kept, searchable, and handed to the next session."""

import asyncio
import json

import pytest

from src.memory import conversation_log as mod
from src.memory.conversation_log import ConversationLog


@pytest.fixture
def log(tmp_path):
    lg = ConversationLog(tmp_path)
    mod.set_conversation_log(lg)
    yield lg
    mod.set_conversation_log(None)


def say(lg, user, reply):
    out = lg.on_message({"type": "stt", "text": user})
    if out:
        lg.save(out)
    for sentence in reply:
        lg.on_message({"type": "tts", "state": "sentence_start", "text": sentence})


def test_an_exchange_is_stored_when_the_next_one_starts(log):
    say(log, "What's the weather like?", ["It's sunny.", "About 20 degrees."])
    assert log.store().count() == 0
    say(log, "And tomorrow?", ["Rain."])
    rows = log.store().recent(limit=5)
    assert len(rows) == 1
    assert rows[0]["text"] == (
        "User: What's the weather like?\nAssistant: It's sunny. About 20 degrees."
    )


def test_a_closed_session_flushes_what_is_pending(log):
    say(log, "Remind me what we fixed", ["The idle timeout."])
    log.save(log.flush())
    assert "idle timeout" in log.store().recent(limit=1)[0]["text"]
    assert log.flush() is None


def test_a_repeated_sentence_marker_is_kept_once(log):
    log.on_message({"type": "stt", "text": "hi"})
    log.on_message({"type": "tts", "state": "sentence_start", "text": "Hello."})
    log.on_message({"type": "tts", "state": "sentence_start", "text": "Hello."})
    assert log.flush() == ("hi", "Hello.")


def test_tts_start_and_stop_without_text_are_ignored(log):
    log.on_message({"type": "tts", "state": "start"})
    log.on_message({"type": "tts", "state": "stop"})
    assert log.flush() is None


def test_a_plain_transcript_is_written_per_day(log, tmp_path):
    say(log, "hello there", ["Hi."])
    files = list((tmp_path / "transcripts").glob("*.jsonl"))
    lines = [json.loads(x) for x in files[0].read_text().splitlines()]
    assert [(x["role"], x["text"]) for x in lines] == [
        ("user", "hello there"),
        ("assistant", "Hi."),
    ]


def test_recent_reads_oldest_first_and_fits_the_budget(log):
    for i in range(6):
        say(log, f"question {i}", [f"answer {i}"])
    log.save(log.flush())
    text = log.recent(hours=3)
    assert text.index("question 0") < text.index("question 5")
    short = log.recent(hours=3, max_chars=120)
    assert "question 5" in short and "question 0" not in short


def test_past_conversations_come_back_from_recall(log, monkeypatch, tmp_path):
    from src.mcp.tools.memory import tools
    from src.memory.store import MemoryStore

    monkeypatch.setattr(tools, "get_memory", lambda: MemoryStore(tmp_path / "m.db"))
    say(
        log,
        "The compressor in the garage keeps tripping the breaker",
        ["Try a soft starter."],
    )
    log.save(log.flush())
    out = json.loads(asyncio.run(tools.recall_payload({"query": "compressor breaker"})))
    assert out["past_conversations"]
    assert "soft starter" in out["past_conversations"][0]["text"]


def test_the_next_session_is_told_where_it_left_off(log, monkeypatch, tmp_path):
    from src.mcp import briefing

    say(log, "Let's plan the chicken coop", ["Sure, how big?"])
    log.save(log.flush())

    class T:
        def __init__(self, name):
            self.name = name

    text = briefing.build([T("remember"), T("recall")])
    assert "Where you left off" in text and "chicken coop" in text


def test_recall_description_carries_the_recent_talk(log, monkeypatch, tmp_path):
    from src.mcp.tools.memory import register as reg
    from src.mcp.tools.memory import tools
    from src.memory.store import MemoryStore

    monkeypatch.setattr(tools, "get_memory", lambda: MemoryStore(tmp_path / "m.db"))
    say(log, "Let's plan the chicken coop", ["Sure, how big?"])
    log.save(log.flush())
    registered = []
    reg.register_memory_tools(registered.append)
    recall = next(t for t in registered if t.name == "recall").to_json()
    assert "WHAT YOU WERE TALKING ABOUT" in recall["description"]
    assert "chicken coop" in recall["description"]
