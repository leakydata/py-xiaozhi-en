"""Permanent basics: stored as core, shown to the assistant without a call."""

import asyncio
import json

import pytest

from src.mcp import briefing
from src.mcp.tools.memory import register as reg
from src.mcp.tools.memory import tools
from src.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = MemoryStore(tmp_path / "m.db")
    monkeypatch.setattr(tools, "get_memory", lambda: s)
    return s


def remember(**kw):
    return json.loads(asyncio.run(tools.remember_payload(kw)))


def test_core_is_a_kind_remember_accepts(store):
    out = remember(text="The user's name is Nathan.", kind="core")
    assert out["kind"] == "core"
    assert [r["text"] for r in store.core()] == ["The user's name is Nathan."]


def test_other_kinds_are_not_core(store):
    remember(text="Likes brief replies.", kind="fact")
    remember(text="Just a note.", kind="note")
    assert store.core() == []


def test_an_unknown_kind_falls_back_to_note(store):
    assert remember(text="x", kind="bogus")["kind"] == "note"


def test_the_snapshot_lists_the_basics_in_the_order_told(store):
    remember(text="Name is Nathan.", kind="core")
    remember(text="Dog is called Eli.", kind="core")
    assert tools.core_snapshot().splitlines() == [
        "- Name is Nathan.",
        "- Dog is called Eli.",
    ]


def test_the_snapshot_is_capped_in_size(store):
    for i in range(40):
        remember(text=f"Fact number {i} " + "x" * 80, kind="core")
    snap = tools.core_snapshot(max_chars=500)
    assert len(snap) <= 520 and snap.startswith("- Fact number 0")


def test_no_core_facts_is_an_empty_snapshot(store):
    assert tools.core_snapshot() == ""


def test_recall_with_kind_core_lists_them_all_without_a_query(store):
    remember(text="Name is Nathan.", kind="core")
    remember(text="Lives somewhere.", kind="fact")
    out = json.loads(asyncio.run(tools.recall_payload({"kind": "core"})))
    assert out["count"] == 1 and out["core"][0]["text"] == "Name is Nathan."


def test_the_basics_arrive_with_the_function_list(store):
    remember(text="Name is Nathan.", kind="core")
    registered = []
    reg.register_memory_tools(registered.append)
    recall = next(t for t in registered if t.name == "recall").to_json()
    assert "PERMANENT FACTS YOU ALREADY KNOW" in recall["description"]
    assert "Name is Nathan." in recall["description"]


def test_a_tool_list_is_still_built_when_the_snapshot_breaks(monkeypatch):
    def boom():
        raise RuntimeError("db gone")

    monkeypatch.setattr(reg, "core_snapshot", boom)
    registered = []
    reg.register_memory_tools(registered.append)
    recall = next(t for t in registered if t.name == "recall").to_json()
    assert (
        recall["name"] == "recall"
        and "Search long-term memory" in recall["description"]
    )


def test_remember_tells_her_never_to_use_the_servers_memory():
    registered = []
    reg.register_memory_tools(registered.append)
    text = next(t for t in registered if t.name == "remember").description
    assert "Use remember constantly" in text and "built-in" in text and "core" in text


def test_the_briefing_carries_the_rule_and_the_basics(store):
    remember(text="Name is Nathan.", kind="core")

    class T:
        def __init__(self, name):
            self.name = name

    text = briefing.build([T("remember"), T("recall")])
    assert "most important thing you do" in text and "built-in" in text
    assert "Name is Nathan." in text


def test_the_briefing_puts_remember_and_recall_first():
    class T:
        def __init__(self, name):
            self.name = name

    text = briefing.build([T("remember"), T("recall"), T("fetch_page")])
    assert text.index("most important tools are remember and recall") < text.index(
        "What you can do"
    )


def test_the_three_clashing_tool_names_are_gone():
    registered = []
    reg.register_memory_tools(registered.append)
    from src.mcp.tools.weather import register_weather_tools
    from src.mcp.tools.web import register_web_tools

    register_weather_tools(registered.append)
    register_web_tools(registered.append)
    names = {t.name for t in registered}
    assert not names & {"get_weather", "web_search", "get_current_time"}
    assert {"weather_lookup", "search_the_web", "current_date_time"} <= names


def test_other_tool_results_nudge_towards_memory_but_memory_tools_do_not():
    from src.mcp.mcp_server import McpServer

    out = McpServer._with_room(
        "weather_lookup", {"content": [{"type": "text", "text": "{}"}]}
    )
    assert any("[Memory:" in c["text"] for c in out["content"])
    for name in ("remember", "recall"):
        out = McpServer._with_room(name, {"content": []})
        assert not any("[Memory:" in c["text"] for c in out["content"])


def test_the_builtin_memory_is_allowed_only_for_constant_things_saved_here_too():
    registered = []
    reg.register_memory_tools(registered.append)
    text = next(t for t in registered if t.name == "remember").description
    assert "only for constant things" in text and "save those here too" in text
