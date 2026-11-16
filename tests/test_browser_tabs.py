"""browser_tabs merges per-letter tab searches into one list."""

import asyncio
import json

from src.mcp.tools.browser import register as reg


def test_tabs_are_merged_by_id_and_filtered(monkeypatch):
    def match(ch):
        rows = {
            "a": [
                ["1", "Inbox - Gmail", "google-chrome"],
                ["2", "YouTube", "google-chrome"],
            ],
            "b": [["1", "Inbox - Gmail", "google-chrome"]],
        }
        return rows.get(ch, [])

    monkeypatch.setattr(reg, "_match", match)
    monkeypatch.setattr(reg.shutil, "which", lambda _: "/usr/bin/busctl")
    out = json.loads(asyncio.run(reg.browser_tabs_payload({})))
    assert out["count"] == 2
    out = json.loads(asyncio.run(reg.browser_tabs_payload({"contains": "gmail"})))
    assert [t["title"] for t in out["tabs"]] == ["Inbox - Gmail"]


def test_no_extension_says_so(monkeypatch):
    monkeypatch.setattr(reg, "_match", lambda ch: [])
    monkeypatch.setattr(reg.shutil, "which", lambda _: "/usr/bin/busctl")
    out = json.loads(asyncio.run(reg.browser_tabs_payload({})))
    assert out["tabs"] == [] and "extension" in out["note"]


def test_only_web_addresses_are_opened(monkeypatch):
    opened = []
    monkeypatch.setattr(reg.subprocess, "Popen", lambda cmd, **k: opened.append(cmd))
    assert reg.open_address("https://example.com/a")["opened"]
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "example.com", ""):
        assert not reg.open_address(bad)["opened"]
    assert opened == [["xdg-open", "https://example.com/a"]]


def test_switching_needs_exactly_one_match(monkeypatch):
    rows = [
        ["1", "Inbox - Gmail", "chrome"],
        ["2", "Gmail settings", "chrome"],
        ["3", "Suno", "chrome"],
    ]
    monkeypatch.setattr(reg, "_match", lambda ch: rows if ch == "a" else [])
    ran = []

    def fake_run(cmd, **k):
        ran.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(reg.subprocess, "run", fake_run)
    many = reg.switch_to_tab("gmail")
    assert not many["switched"] and len(many["matches"]) == 2 and not ran
    one = reg.switch_to_tab("suno")
    assert (
        one["switched"]
        and ran[0][-3:] == ["Run", "ss", "3"]
        or ran[0][-2:] == ["3", ""]
    )
    assert not reg.switch_to_tab("zzz")["switched"]
