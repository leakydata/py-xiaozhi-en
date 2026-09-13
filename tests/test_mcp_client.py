"""The outbound MCP client: schema fidelity, result flattening, filtering.

Everything here runs against a fake server rather than a real one, so the
suite stays offline and does not depend on Boswell being up.
"""

import json

import pytest

from src.mcp.client.bridge import (
    _filtered,
    make_proxy_tool,
    properties_from_input_schema,
)
from src.mcp.client.session import _content_to_text

# -- schema conversion ------------------------------------------------------


def test_array_argument_survives_the_round_trip():
    """A list argument must reach the backend as an array, not a string.

    This is the case the old Property model could not express at all, and
    Boswell's tag_conversation(clips, topics) depends on it.
    """
    schema = {
        "type": "object",
        "properties": {
            "clips": {"type": "array", "items": {"type": "string"}},
            "topics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["clips", "topics"],
    }
    props = properties_from_input_schema(schema)
    out = props.to_json()
    assert out["clips"]["type"] == "array"
    assert out["clips"]["items"] == {"type": "string"}
    assert set(props.get_required()) == {"clips", "topics"}


def test_optional_without_default_is_not_required_and_not_sent():
    """An optional argument left out must be omitted, not sent as null."""
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "person": {"type": "string"}},
        "required": ["query"],
    }
    props = properties_from_input_schema(schema)
    assert props.get_required() == ["query"]
    parsed = props.parse_arguments({"query": "hello"})
    assert parsed == {"query": "hello"}
    assert "person" not in parsed


def test_missing_required_argument_is_rejected():
    props = properties_from_input_schema(
        {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    )
    with pytest.raises(ValueError):
        props.parse_arguments({})


def test_nullable_union_type_is_accepted():
    """["string", "null"] is common and must not blow up the conversion."""
    props = properties_from_input_schema(
        {"type": "object", "properties": {"due": {"type": ["string", "null"]}}}
    )
    assert props.to_json()["due"]["type"] == ["string", "null"]


# -- result flattening ------------------------------------------------------


def test_text_blocks_are_joined():
    assert (
        _content_to_text(
            {
                "content": [
                    {"type": "text", "text": "one"},
                    {"type": "text", "text": "two"},
                ]
            }
        )
        == "one\ntwo"
    )


def test_binary_blocks_are_described_not_inlined():
    """A base64 image must never reach a text-to-speech pipeline."""
    out = _content_to_text(
        {"content": [{"type": "image", "data": "AAAA", "mimeType": "image/png"}]}
    )
    assert "AAAA" not in out
    assert "image" in out


def test_error_results_are_marked():
    out = _content_to_text(
        {"content": [{"type": "text", "text": "nope"}], "isError": True}
    )
    assert out.startswith("error:")


def test_structured_content_without_blocks():
    out = _content_to_text({"structuredContent": {"clips": 3}})
    assert json.loads(out) == {"clips": 3}


# -- filtering --------------------------------------------------------------

_TOOLS = [{"name": n} for n in ("search", "stats", "delete_clips", "rebuild_index")]


def test_include_keeps_only_what_is_named():
    got = _filtered(_TOOLS, {"include": ["search", "stats"]}, "srv")
    assert [t["name"] for t in got] == ["search", "stats"]


def test_exclude_drops_what_is_named():
    got = _filtered(_TOOLS, {"exclude": ["delete_clips", "rebuild_index"]}, "srv")
    assert [t["name"] for t in got] == ["search", "stats"]


def test_no_filter_offers_everything():
    assert len(_filtered(_TOOLS, {}, "srv")) == len(_TOOLS)


def test_include_naming_an_absent_tool_is_survivable():
    """A typo in the config must not lose the tools that do exist."""
    got = _filtered(_TOOLS, {"include": ["search", "nonexistent"]}, "srv")
    assert [t["name"] for t in got] == ["search"]


# -- the proxy tool ---------------------------------------------------------


class _FakeSession:
    name = "fake"

    def __init__(self, reply="done"):
        self.reply = reply
        self.calls = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return self.reply


@pytest.mark.asyncio
async def test_proxy_forwards_under_the_remote_name():
    """The prefix is local. The server must be called by its own name."""
    session = _FakeSession()
    tool = make_proxy_tool(
        session,
        {
            "name": "search",
            "description": "find things",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        "fake.",
    )
    assert tool.name == "fake.search"
    assert tool.description.startswith("[fake]")

    out = json.loads(await tool.call({"query": "kettle"}))
    assert out["content"][0]["text"] == "done"
    assert session.calls == [("search", {"query": "kettle"})]


# -- child environment ------------------------------------------------------


def test_child_environment_drops_our_virtualenv(monkeypatch):
    """A child server must not inherit the host's Python environment.

    py-xiaozhi runs under `uv run`, so VIRTUAL_ENV is set. A server launched as
    `uv run ...` that inherited it resolved against py-xiaozhi's venv and died
    on an import present in its own - which is exactly how Boswell failed while
    passing every standalone test.
    """
    from src.mcp.client.transport import _child_environment

    monkeypatch.setenv("VIRTUAL_ENV", "/home/u/app/.venv")
    monkeypatch.setenv("PYTHONPATH", "/home/u/app")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/home/u/app/.venv")
    monkeypatch.setenv("PATH", "/home/u/app/.venv/bin:/usr/bin:/bin")

    env = _child_environment(None)

    assert "VIRTUAL_ENV" not in env
    assert "PYTHONPATH" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env
    # and the venv's bin is off PATH, so `python` is not shadowed either
    assert "/home/u/app/.venv/bin" not in env["PATH"].split(":")
    assert "/usr/bin" in env["PATH"].split(":")


def test_explicit_env_in_config_still_wins(monkeypatch):
    """Scrubbing must not override something the server's config asked for."""
    from src.mcp.client.transport import _child_environment

    monkeypatch.setenv("VIRTUAL_ENV", "/home/u/app/.venv")
    env = _child_environment({"VIRTUAL_ENV": "/deliberate", "TOKEN": "abc"})
    assert env["VIRTUAL_ENV"] == "/deliberate"
    assert env["TOKEN"] == "abc"
