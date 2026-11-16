"""Find out which short texts xiaozhi.me accepts as `listen`/`detect`.

The app makes the assistant speak unprompted (reminders, check-in, speak-up) by
sending a short cue the way a wake word is sent. The server refuses long text
there ("Detect is only for wake words, do not send long texts") and the real
limit is not documented. This connects once with the app's own credentials,
sends each cue, and reports which were refused and which got a reply.

It uses the same device identity as the app, so a running app's session is
dropped while it runs (the app reconnects on its own). By default it refuses
to run if anyone has spoken to the app in the last 20 minutes.

    uv run python scripts/cue_probe.py [--force] [texts...]
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_TEXTS = ["reminder due", "still there?", "room sound", "hi"]
LOG = Path.home() / ".local/share/py-xiaozhi/logs/app.log"
OUT = Path.home() / ".local/share/py-xiaozhi/cue_probe.json"


def recently_used(minutes: float = 20) -> bool:
    try:
        tail = LOG.read_text(errors="replace").splitlines()[-4000:]
    except Exception:
        return False
    cutoff = datetime.now() - timedelta(minutes=minutes)
    for line in reversed(tail):
        if "type=stt" in line:
            m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
            if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") > cutoff:
                return True
            return False
    return False


async def probe(texts: list[str]) -> list[dict]:
    import websockets

    from src.utils.config_manager import initialize_config

    cfg = initialize_config()
    url = cfg.get_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL")
    headers = {
        "Authorization": "Bearer "
        + str(cfg.get_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN")),
        "Protocol-Version": "1",
        "Device-Id": cfg.get_config("SYSTEM_OPTIONS.DEVICE_ID"),
        "Client-Id": cfg.get_config("SYSTEM_OPTIONS.CLIENT_ID"),
    }
    results = []
    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": 1,
                    "features": {"mcp": False},
                    "transport": "websocket",
                    "audio_params": {
                        "format": "opus",
                        "sample_rate": 16000,
                        "channels": 1,
                        "frame_duration": 20,
                    },
                }
            )
        )
        session = ""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.recv(), 10)
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "hello":
                    session = data.get("session_id", "")
                    break
        for text in texts:
            await ws.send(
                json.dumps(
                    {
                        "session_id": session,
                        "type": "listen",
                        "state": "start",
                        "mode": "manual",
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "session_id": session,
                        "type": "listen",
                        "state": "detect",
                        "text": text,
                    }
                )
            )
            verdict, heard, said = "no reply", None, []
            end = time.monotonic() + 12
            while time.monotonic() < end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), end - time.monotonic())
                except (asyncio.TimeoutError, TimeoutError):
                    break
                if not isinstance(msg, str):
                    continue
                data = json.loads(msg)
                kind = data.get("type")
                if kind == "alert" and "Detect is only" in str(data.get("message")):
                    verdict = "refused"
                    break
                if kind == "stt":
                    heard = data.get("text")
                    verdict = "accepted"
                if kind == "tts" and data.get("text"):
                    said.append(data["text"])
                    verdict = "accepted"
                if kind == "tts" and data.get("state") == "stop":
                    break
            results.append(
                {
                    "text": text,
                    "chars": len(text),
                    "verdict": verdict,
                    "heard_as": heard,
                    "reply": " ".join(said)[:300],
                }
            )
            await ws.send(json.dumps({"session_id": session, "type": "abort"}))
            await asyncio.sleep(1)
    return results


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    if "--force" not in sys.argv and recently_used():
        print("someone used the app in the last 20 minutes; not probing (use --force)")
        return 2
    results = asyncio.run(probe(args or DEFAULT_TEXTS))
    OUT.write_text(
        json.dumps(
            {"at": datetime.now().isoformat(timespec="seconds"), "results": results},
            indent=2,
        )
    )
    for r in results:
        print(f"{r['verdict']:>9}  {r['text']!r} ({r['chars']})  -> {r['reply'][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
