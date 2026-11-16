"""Screenshots on Linux: monitor discovery and cropping to one monitor."""

import io
import subprocess
from types import SimpleNamespace

from PIL import Image

from src.mcp.tools.screenshot.screenshot_camera import ScreenshotCamera

KSCREEN = """\x1b[01;32mOutput: \x1b[0;0m1 DP-2 uuid-a
\t\x1b[01;32menabled\x1b[0;0m
\t\x1b[01;32mpriority 1\x1b[0;0m
\t\x1b[01;33mGeometry: \x1b[0;0m1920,0 1920x1080
Output: 2 DP-3 uuid-b
\tenabled
\tpriority 2
\tGeometry: 0,0 1920x1080
Output: 3 VGA-1 uuid-c
\tdisabled
\tpriority 3
\tGeometry: 3840,0 1024x768
"""


def camera():
    return ScreenshotCamera.__new__(ScreenshotCamera)


def test_monitors_come_back_main_first_and_disabled_ones_are_left_out(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/kscreen-doctor")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=KSCREEN)
    )
    mons = ScreenshotCamera._linux_monitors()
    assert [m["name"] for m in mons] == ["DP-2", "DP-3"]
    assert (mons[0]["x"], mons[0]["w"]) == (1920, 1920)


def test_a_single_monitor_is_cropped_out_of_the_desktop(monkeypatch):
    desktop = Image.new("RGB", (3840, 1080), "black")
    desktop.paste(Image.new("RGB", (1920, 1080), "red"), (1920, 0))  # DP-2, main
    buf = io.BytesIO()
    desktop.save(buf, "PNG")

    def fake_run(cmd, **k):
        if cmd[0] == "spectacle":
            open(cmd[-1], "wb").write(buf.getvalue())
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout=KSCREEN)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/x")
    monkeypatch.setattr(subprocess, "run", fake_run)
    jpeg = camera()._capture_linux("main")
    img = Image.open(io.BytesIO(jpeg))
    assert img.size == (1920, 1080)
    r, g, b = img.getpixel((960, 540))
    assert r > 200 and g < 60 and b < 60  # the red main monitor
    whole = Image.open(io.BytesIO(camera()._capture_linux(None)))
    assert whole.size[0] == 2600  # downscaled to the size limit
