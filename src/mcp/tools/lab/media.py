"""Image and audio/video operations, workspace-scoped.

Pillow and ffmpeg are already present, so these cost no new dependencies.
Every path goes through the workspace resolver, so inputs and outputs stay
inside the assistant's folder - ffmpeg will not be pointed at ~/.ssh.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from src.logging import get_logger
from src.mcp.tools.files import store

logger = get_logger()

FFMPEG_TIMEOUT = 180.0


# -------------------------------------------------------------------- images

def image_info(path: str) -> dict[str, Any]:
    from PIL import Image

    p = store.resolve(path)
    with Image.open(p) as im:
        return {"path": store.rel_to_root(p), "format": im.format,
                "mode": im.mode, "width": im.width, "height": im.height,
                "bytes": p.stat().st_size}


def image_edit(path: str, out: str, *, width: int = 0, height: int = 0,
               rotate: int = 0, grayscale: bool = False,
               crop: str = "", quality: int = 88) -> dict[str, Any]:
    """Resize / rotate / crop / greyscale in one pass."""
    from PIL import Image

    src = store.resolve(path)
    dst = store.resolve(out)
    with Image.open(src) as im:
        if crop:
            try:
                l, t, r, b = (int(v) for v in crop.replace(" ", "").split(","))
            except ValueError:
                raise ValueError("crop must be 'left,top,right,bottom' in pixels")
            im = im.crop((l, t, r, b))
        if width or height:
            w = int(width) or int(im.width * (int(height) / im.height))
            h = int(height) or int(im.height * (int(width) / im.width))
            im = im.resize((max(1, w), max(1, h)), Image.LANCZOS)
        if rotate:
            im = im.rotate(-int(rotate), expand=True)
        if grayscale:
            im = im.convert("L")
        if dst.suffix.lower() in (".jpg", ".jpeg") and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        params = {"quality": int(quality)} if dst.suffix.lower() in (".jpg", ".jpeg") else {}
        im.save(dst, **params)
        result = {"path": store.rel_to_root(dst), "width": im.width,
                  "height": im.height, "bytes": dst.stat().st_size}
    logger.info(f"[Image] {store.rel_to_root(src)} -> {result['path']}")
    return result


# --------------------------------------------------------------------- media

def _ff(name: str) -> str | None:
    return shutil.which(name)


async def _run_ff(args: list[str]) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(store.root()),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"ffmpeg timed out after {FFMPEG_TIMEOUT:.0f}s"}
    except Exception as e:
        return {"ok": False, "error": f"Could not run ffmpeg: {e}"}
    text = (out or b"").decode("utf-8", "replace")
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
            "log": text[-2000:]}


async def media_info(path: str) -> dict:
    probe = _ff("ffprobe")
    if not probe:
        return {"ok": False, "error": "ffprobe is not installed."}
    p = store.resolve(path)
    if not p.exists():
        return {"ok": False, "error": f"{store.rel_to_root(p)} does not exist"}
    args = [probe, "-v", "error", "-show_entries",
            "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,sample_rate,channels",
            "-of", "default=noprint_wrappers=1", str(p)]
    res = await _run_ff(args)
    if not res.get("ok"):
        return res
    info: dict[str, Any] = {}
    for line in res["log"].splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info.setdefault(k.strip(), v.strip())
    return {"ok": True, "path": store.rel_to_root(p), "info": info}


async def media_convert(path: str, out: str, *, start: str = "", duration: str = "",
                        audio_only: bool = False, scale_width: int = 0) -> dict:
    """Transcode, trim, extract audio or downscale - whatever the extensions imply."""
    ff = _ff("ffmpeg")
    if not ff:
        return {"ok": False, "error": "ffmpeg is not installed."}
    src = store.resolve(path)
    dst = store.resolve(out)
    if not src.exists():
        return {"ok": False, "error": f"{store.rel_to_root(src)} does not exist"}
    dst.parent.mkdir(parents=True, exist_ok=True)

    args = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    if start:
        args += ["-ss", str(start)]
    args += ["-i", str(src)]
    if duration:
        args += ["-t", str(duration)]
    if audio_only:
        args += ["-vn"]
    elif scale_width:
        args += ["-vf", f"scale={int(scale_width)}:-2"]
    args += [str(dst)]

    logger.info(f"[Media] {store.rel_to_root(src)} -> {store.rel_to_root(dst)}")
    res = await _run_ff(args)
    if res.get("ok") and dst.exists():
        res["path"] = store.rel_to_root(dst)
        res["bytes"] = dst.stat().st_size
    return res
