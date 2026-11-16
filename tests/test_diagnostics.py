"""The assistant reading its own log: filtered, shortened, redacted, summarised."""

import asyncio
import json
from datetime import datetime, timedelta

from src.mcp.tools.diagnostics import logs
from src.mcp.tools.diagnostics import register as reg

NOW = datetime(2026, 11, 15, 20, 0, 0)


def row(minutes_ago, level, logger, message):
    t = NOW - timedelta(minutes=minutes_ago)
    return (
        f"{t:%Y-%m-%d %H:%M:%S} | {level:<8} | [-] | {logger} | {message} | MainThread"
    )


def parsed(*rows):
    return [logs.parse_line(r) for r in rows]


def test_a_log_line_is_parsed_without_its_thread_name():
    ln = logs.parse_line(row(1, "WARNING", "src.bootstrap.session", "server alert: x"))
    assert ln.level == "WARNING" and ln.logger == "src.bootstrap.session"
    assert ln.message == "server alert: x"


def test_a_message_containing_the_separator_is_kept_whole():
    ln = logs.parse_line(row(1, "INFO", "src.a", "left | right"))
    assert ln.message == "left | right"


def test_continuation_lines_are_not_lines():
    assert logs.parse_line('  "jsonrpc": "2.0",') is None
    assert logs.parse_line("") is None


def test_secrets_are_hidden():
    assert "abc123def456ghi789" not in logs.redact("access_token=abc123def456ghi789")
    assert "hunter2hunter2" not in logs.redact('{"password": "hunter2hunter2"}')
    assert "Bearer" in logs.redact("Authorization: Bearer abcdefgh12345678")
    assert "abcdefgh12345678" not in logs.redact(
        "Authorization: Bearer abcdefgh12345678"
    )
    assert "A" * 50 not in logs.redact("key " + "A" * 50)


def test_ordinary_text_is_left_alone():
    assert logs.redact("turn-taking: user finished") == "turn-taking: user finished"


def test_the_time_window_and_level_are_honoured():
    lines = parsed(
        row(90, "ERROR", "src.a", "old"),
        row(5, "DEBUG", "src.a", "chatter"),
        row(3, "WARNING", "src.a", "recent warning"),
    )
    got = logs.select(logs.window(lines, 15, NOW), level="warning")
    assert [x.split(": ", 1)[1] for x in got["lines"]] == ["recent warning"]


def test_contains_and_logger_filters():
    lines = parsed(
        row(2, "INFO", "src.plugins.turn_taking", "interrupted by 'hi'"),
        row(2, "INFO", "src.plugins.audio", "TTS started"),
    )
    got = logs.select(lines, level="info", contains="INTERRUPTED")
    assert len(got["lines"]) == 1
    got = logs.select(lines, level="info", logger="audio")
    assert "TTS started" in got["lines"][0]


def test_repeats_collapse_into_one_line_with_a_count():
    lines = parsed(*[row(i, "WARNING", "src.a", "same thing") for i in range(5, 0, -1)])
    got = logs.select(lines, level="warning")
    assert len(got["lines"]) == 1 and "x5" in got["lines"][0]
    assert got["matched"] == 5


def test_too_many_lines_keeps_the_newest_and_says_so():
    lines = parsed(*[row(100 - i, "WARNING", "src.a", f"event {i}") for i in range(90)])
    got = logs.select(lines, level="warning", max_lines=10)
    assert len(got["lines"]) == 10 and "event 89" in got["lines"][-1]
    assert "note" in got


def test_long_lines_are_cut():
    ln = parsed(row(1, "ERROR", "src.a", "x" * 2000))[0]
    assert len(ln.short()) <= 260


def test_the_summary_reports_what_explains_a_complaint():
    lines = parsed(
        row(50, "INFO", "src.plugins.manager", "plugins sorted topologically: [...]"),
        row(
            10,
            "WARNING",
            "src.bootstrap.session",
            "server alert: {'message': 'Duplicate tool names: a, b'}",
        ),
        row(
            9,
            "WARNING",
            "src.bootstrap.session",
            "server alert: {'message': 'Duplicate tool names: a, b'}",
        ),
        row(
            8,
            "INFO",
            "src.protocols.protocol",
            "Connection closed cleanly by the server: x",
        ),
        row(8, "INFO", "src.core.protocol_manager", "protocol channel closed"),
        row(
            6,
            "INFO",
            "src.plugins.turn_taking",
            "turn-taking: interrupted by 'are you there' (over the echo for 0.04s)",
        ),
        row(
            5,
            "WARNING",
            "src.audio_codecs.audio_codec",
            "output stream status: output underflow",
        ),
        row(4, "ERROR", "src.mcp.x", "tool blew up"),
        row(
            3,
            "INFO",
            "src.audio_processing.wake_word_detect",
            "wake word detected: HEY",
        ),
    )
    s = logs.summarise(lines, 60, NOW)
    assert s["errors"] == 1
    assert s["connection_drops"] == 1 and s["drops_started_by_the_server"] == 1
    assert s["interruptions_of_the_assistant"] == 1
    assert s["audio_underflows"] == 1
    assert s["wake_word_detections"] == 1
    assert s["server_messages"][0]["times"] == 2
    assert "Duplicate tool names" in s["server_messages"][0]["what"]
    assert "0.04s" in s["last_interruptions"][0]
    assert s["app_last_started"].endswith("19:10:00")


def test_an_empty_window_says_so_instead_of_reporting_zeros():
    assert "No log lines" in logs.summarise([], 60, NOW)["note"]
    old = parsed(row(500, "INFO", "src.a", "x"))
    assert "No log lines" in logs.summarise(old, 60, NOW)["note"]


def test_the_tools_return_json_and_survive_a_missing_log(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "log_path", lambda: tmp_path / "nope.log")
    out = json.loads(asyncio.run(reg.app_health_payload({})))
    assert "note" in out
    out = json.loads(asyncio.run(reg.read_logs_payload({"level": "info"})))
    assert out["lines"] == [] and "note" in out


def test_bad_arguments_do_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "log_path", lambda: tmp_path / "nope.log")
    out = asyncio.run(reg.read_logs_payload({"minutes": "soon", "max_lines": "lots"}))
    assert json.loads(out)["window_minutes"] == 15.0


def test_the_briefing_tells_her_to_start_with_app_health():
    from src.mcp import briefing

    class T:
        def __init__(self, name):
            self.name = name

    text = briefing.build([T("recall"), T("app_health"), T("read_logs")])
    assert "call app_health first" in text
    assert "app_health, read_logs" in text


def test_the_same_server_message_from_different_sessions_is_one_kind():
    lines = parsed(
        row(
            3,
            "WARNING",
            "src.bootstrap.session",
            "server alert: {'message': 'Duplicate', 'session_id': '84a3ee87'}",
        ),
        row(
            2,
            "WARNING",
            "src.bootstrap.session",
            "server alert: {'message': 'Duplicate', 'session_id': 'c0ffee12'}",
        ),
    )
    kinds = logs.summarise(lines, 60, NOW)["server_messages"]
    assert len(kinds) == 1 and kinds[0]["times"] == 2
