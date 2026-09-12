"""System telemetry and serial-port access.

Two of the wishlist items that are genuinely useful in a garage: "what is this
machine doing right now", and talking to a microcontroller over USB serial,
which is what the ESP32 work needs.

Serial is read/write on purpose - flashing aside, talking to a board means
sending it commands. It is limited to real serial devices (/dev/tty*, COM*) so
it cannot be pointed at an arbitrary file.
"""

from __future__ import annotations

import asyncio
import glob
import os
import time
from typing import Any

from src.logging import get_logger

logger = get_logger()

MAX_SERIAL_BYTES = 20_000


# ---------------------------------------------------------------- telemetry

def snapshot() -> dict[str, Any]:
    """A broad view of machine state in one call."""
    import psutil

    out: dict[str, Any] = {}
    try:
        out["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        out["cpu_count"] = psutil.cpu_count(logical=True)
        load = os.getloadavg()
        out["load_avg"] = {"1m": round(load[0], 2), "5m": round(load[1], 2),
                           "15m": round(load[2], 2)}
    except Exception:
        pass
    try:
        m = psutil.virtual_memory()
        out["memory"] = {"total_gb": round(m.total / 1e9, 1),
                         "used_gb": round(m.used / 1e9, 1),
                         "percent": m.percent}
        s = psutil.swap_memory()
        out["swap"] = {"total_gb": round(s.total / 1e9, 1), "percent": s.percent}
    except Exception:
        pass
    try:
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                disks.append({"mount": part.mountpoint,
                              "total_gb": round(u.total / 1e9, 1),
                              "free_gb": round(u.free / 1e9, 1),
                              "percent": u.percent})
            except OSError:
                continue
        out["disks"] = disks
    except Exception:
        pass
    try:
        temps = psutil.sensors_temperatures() or {}
        hot = []
        for name, entries in temps.items():
            for e in entries:
                if e.current:
                    hot.append({"sensor": f"{name}:{e.label or 'n/a'}",
                                "celsius": round(e.current, 1)})
        if hot:
            out["temperatures"] = sorted(hot, key=lambda h: -h["celsius"])[:8]
    except Exception:
        pass
    try:
        fans = psutil.sensors_fans() or {}
        rpm = [{"fan": f"{n}:{e.label or i}", "rpm": e.current}
               for n, es in fans.items() for i, e in enumerate(es)]
        if rpm:
            out["fans"] = rpm[:6]
    except Exception:
        pass
    try:
        bat = psutil.sensors_battery()
        if bat:
            out["battery"] = {"percent": round(bat.percent, 1),
                              "plugged_in": bat.power_plugged}
    except Exception:
        pass
    try:
        out["boot_time"] = time.strftime("%Y-%m-%d %H:%M",
                                         time.localtime(psutil.boot_time()))
    except Exception:
        pass
    return out


def top_processes(limit: int = 8, by: str = "cpu") -> list[dict]:
    import psutil

    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append({"pid": info["pid"], "name": info["name"],
                          "cpu": round(info.get("cpu_percent") or 0, 1),
                          "memory": round(info.get("memory_percent") or 0, 1)})
        except Exception:
            continue
    key = "memory" if str(by).lower().startswith("mem") else "cpu"
    return sorted(procs, key=lambda d: -d[key])[: max(1, min(int(limit), 25))]


# ------------------------------------------------------------------- serial

def _is_serial_device(port: str) -> bool:
    p = (port or "").strip()
    if not p:
        return False
    return (
        p.startswith("/dev/tty")
        or p.startswith("/dev/serial/")
        or p.upper().startswith("COM")
    )


def list_ports() -> list[dict]:
    try:
        from serial.tools import list_ports as lp

        found = [{"port": p.device, "description": p.description,
                  "hwid": p.hwid} for p in lp.comports()]
    except Exception as e:
        logger.warning(f"[Serial] enumeration failed: {e}")
        found = []
    if not found:  # fall back to globbing, some boards do not report properly
        for pat in ("/dev/ttyUSB*", "/dev/ttyACM*"):
            for dev in sorted(glob.glob(pat)):
                found.append({"port": dev, "description": "(detected by path)",
                              "hwid": ""})

    # A PC exposes dozens of legacy /dev/ttyS* UARTs with nothing attached. They
    # drown the one port that matters, so only surface them if nothing real is
    # present. USB-attached boards always win.
    def is_real(entry: dict) -> bool:
        port = entry.get("port", "")
        if "ttyUSB" in port or "ttyACM" in port or "/dev/serial/" in port:
            return True
        desc = (entry.get("description") or "").lower()
        return bool(desc) and desc not in ("n/a", "(detected by path)")

    real = [e for e in found if is_real(e)]
    return real if real else found


def _read_sync(port: str, baud: int, seconds: float, send: str | None) -> dict:
    import serial

    with serial.Serial(port, baud, timeout=0.3) as ser:
        if send is not None:
            payload = (send + "\n").encode("utf-8", "replace")
            ser.write(payload)
            ser.flush()
        chunks: list[bytes] = []
        total = 0
        deadline = time.time() + seconds
        while time.time() < deadline and total < MAX_SERIAL_BYTES:
            data = ser.read(1024)
            if data:
                chunks.append(data)
                total += len(data)
        raw = b"".join(chunks)
    return {"ok": True, "port": port, "baud": baud, "bytes": len(raw),
            "text": raw.decode("utf-8", "replace")[:MAX_SERIAL_BYTES]}


async def serial_io(port: str, baud: int = 115200, seconds: float = 3.0,
                    send: str | None = None) -> dict:
    if not _is_serial_device(port):
        return {"ok": False, "error": (
            f"{port!r} is not a serial device. Use list_serial_ports first; "
            "expected something like /dev/ttyUSB0 or /dev/ttyACM0."
        )}
    if not os.path.exists(port) and not port.upper().startswith("COM"):
        return {"ok": False, "error": f"{port} does not exist. Is the board plugged in?"}
    seconds = max(0.2, min(float(seconds or 3.0), 20.0))
    try:
        baud = int(baud or 115200)
    except (TypeError, ValueError):
        baud = 115200
    logger.info(f"[Serial] {port} @ {baud} for {seconds:.1f}s"
                f"{' (sending)' if send else ''}")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_read_sync, port, baud, seconds, send),
            timeout=seconds + 10,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Serial read timed out."}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
