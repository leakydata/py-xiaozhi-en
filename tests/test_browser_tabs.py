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
