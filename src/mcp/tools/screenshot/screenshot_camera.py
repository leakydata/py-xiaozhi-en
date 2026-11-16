"""
Screenshot camera implementation for capturing desktop screens.
"""

import io
import json
import sys

from src.logging import get_logger
from src.mcp.tools.camera.base_camera import BaseCamera

logger = get_logger()


class ScreenshotCamera(BaseCamera):
    """
    A camera implementation that takes desktop screenshots.
    """

    def __init__(self):
        """
        Initialise the screenshot camera.
        """
        super().__init__()
        logger.info("Initializing ScreenshotCamera")

        # import the dependencies
        self._import_dependencies()

    def _import_dependencies(self):
        """
        Import the dependencies this needs.
        """
        # check whether PIL is available (without tripping an unused-import warning)
        try:
            import importlib.util

            self._pil_available = importlib.util.find_spec("PIL.ImageGrab") is not None
            if self._pil_available:
                logger.info("PIL ImageGrab available for screenshot capture")
            else:
                logger.warning(
                    "PIL not available, will try alternative screenshot methods"
                )
        except Exception:
            self._pil_available = False
            logger.warning(
                "Failed to check PIL availability, fallback methods will be used"
            )

        # platform-specific imports
        if sys.platform == "darwin":  # macOS
            # use `which` to check whether the system screencapture command exists
            try:
                import shutil

                self._subprocess_available = shutil.which("screencapture") is not None
                if self._subprocess_available:
                    logger.info("screencapture command available for macOS screenshot")
                else:
                    logger.warning("screencapture command not found on macOS")
            except Exception:
                self._subprocess_available = False
        elif sys.platform == "win32":  # Windows
            try:
                import ctypes

                self._win32_available = hasattr(ctypes, "windll")
                logger.info("Win32 API available for Windows screenshot")
            except ImportError:
                self._win32_available = False

    def capture(self, display_id=None) -> bool:
        """Capture the desktop.

        Args:
            display_id: the display; None = every display, "main" = the primary screen, "secondary" = the secondary screen, 1,2,3... = a specific display

        Returns:
            True on success, False on failure
        """
        try:
            logger.info("Starting desktop screenshot capture...")

            # try the available capture methods in turn
            screenshot_data = None

            # prefer the platform-specific method (better multi-display support)
            if sys.platform == "darwin" and getattr(
                self, "_subprocess_available", False
            ):
                screenshot_data = self._capture_macos(display_id)
            elif sys.platform == "win32" and getattr(self, "_win32_available", False):
                screenshot_data = self._capture_windows(display_id)
            elif sys.platform.startswith("linux"):
                screenshot_data = self._capture_linux(display_id)

            # fallback: PIL ImageGrab
            if not screenshot_data and self._pil_available:
                screenshot_data = self._capture_with_pil()

            if screenshot_data:
                self.set_jpeg_data(screenshot_data)
                logger.info(
                    f"Screenshot captured successfully, size: {len(screenshot_data)} bytes"
                )
                return True
            else:
                logger.error("All screenshot capture methods failed")
                return False

        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}", exc_info=True)
            return False

    def _capture_with_pil(self) -> bytes:
        """Capture using PIL ImageGrab.

        Returns:
            the image as JPEG bytes
        """
        try:
            import PIL.ImageGrab

            logger.debug("Capturing screenshot with PIL ImageGrab...")

            # capture every screen (including multiple displays)
            screenshot = PIL.ImageGrab.grab(all_screens=True)

            # convert to RGB if the image has an alpha channel (RGBA)
            if screenshot.mode == "RGBA":
                # create a white background
                from PIL import Image

                background = Image.new("RGB", screenshot.size, (255, 255, 255))
                background.paste(
                    screenshot, mask=screenshot.split()[3]
                )  # use the alpha channel as the mask
                screenshot = background
            elif screenshot.mode not in ["RGB", "L"]:
                # make sure the format is JPEG-compatible
                screenshot = screenshot.convert("RGB")

            # encode as JPEG bytes
            byte_io = io.BytesIO()
            screenshot.save(byte_io, format="JPEG", quality=85)

            return byte_io.getvalue()

        except Exception as e:
            logger.error(f"PIL screenshot capture failed: {e}", exc_info=True)
            return None

    def _capture_macos(self, display_id=None) -> bytes:
        """Capture using the macOS system command (a display can be chosen).

        Args:
            display_id: the display; None = every display, "main" = the primary screen, "secondary" = the secondary screen, 1,2,3... = a specific display

        Returns:
            the image as JPEG bytes
        """
        try:
            from PIL import Image

            logger.debug(
                f"Capturing screenshot with macOS screencapture command, display_id: {display_id}"
            )

            # pick the capture strategy from display_id
            if display_id is None:
                # capture every display and stitch them together
                screenshot = self._capture_all_displays_macos()
            elif display_id == "main" or display_id == 1:
                # capture the primary display
                screenshot = self._capture_single_display_macos(1)
            elif display_id == "secondary" or display_id == 2:
                # capture the secondary display
                screenshot = self._capture_single_display_macos(2)
            elif isinstance(display_id, int) and display_id > 0:
                # capture the named display
                screenshot = self._capture_single_display_macos(display_id)
            else:
                logger.error(f"Invalid display_id: {display_id}")
                return None

            if not screenshot:
                logger.error("Failed to create composite screenshot")
                return None

            # convert to JPEG
            if screenshot.mode == "RGBA":
                # create a white background
                background = Image.new("RGB", screenshot.size, (255, 255, 255))
                background.paste(screenshot, mask=screenshot.split()[3])
                screenshot = background
            elif screenshot.mode not in ["RGB", "L"]:
                screenshot = screenshot.convert("RGB")

            # save as JPEG bytes
            byte_io = io.BytesIO()
            screenshot.save(byte_io, format="JPEG", quality=85)

            return byte_io.getvalue()

        except Exception as e:
            logger.error(f"macOS screenshot capture failed: {e}", exc_info=True)
            return None

    def _composite_displays(self, displays):
        """Stitch the screenshots of several displays into one image.

        Args:
            displays: the list of display records

        Returns:
            the stitched PIL Image
        """
        try:
            from PIL import Image

            # work out the size of the stitched image
            # assume the displays are arranged either vertically or horizontally
            total_width = max(display["size"][0] for display in displays)
            total_height = sum(display["size"][1] for display in displays)

            # also work out the size for a horizontal arrangement
            horizontal_width = sum(display["size"][0] for display in displays)
            horizontal_height = max(display["size"][1] for display in displays)

            # use whichever arrangement is more compact
            if total_width * total_height <= horizontal_width * horizontal_height:
                # vertical is more compact
                composite = Image.new("RGB", (total_width, total_height), (0, 0, 0))
                y_offset = 0
                for display in sorted(displays, key=lambda d: d["id"]):
                    x_offset = (total_width - display["size"][0]) // 2  # centred
                    composite.paste(display["image"], (x_offset, y_offset))
                    y_offset += display["size"][1]
                logger.debug(f"Created vertical composite: {composite.size}")
            else:
                # horizontal is more compact
                composite = Image.new(
                    "RGB", (horizontal_width, horizontal_height), (0, 0, 0)
                )
                x_offset = 0
                for display in sorted(displays, key=lambda d: d["id"]):
                    y_offset = (horizontal_height - display["size"][1]) // 2  # centred
                    composite.paste(display["image"], (x_offset, y_offset))
                    x_offset += display["size"][0]
                logger.debug(f"Created horizontal composite: {composite.size}")

            return composite

        except Exception as e:
            logger.error(f"Failed to composite displays: {e}", exc_info=True)
            return None

    def _capture_windows(self, display_id=None) -> bytes:
        """Capture using the Windows API.

        Args:
            display_id: the display (not implemented yet; the virtual screen is used)

        Returns:
            the image as JPEG bytes
        """
        try:
            import ctypes
            import ctypes.wintypes

            from PIL import Image

            logger.debug(
                f"Capturing screenshot with Windows API, display_id: {display_id}"
            )

            # get the virtual screen size (covering every display)
            user32 = ctypes.windll.user32
            # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
            virtual_left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            virtual_top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            virtual_width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            virtual_height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

            screensize = (virtual_width, virtual_height)
            screen_offset = (virtual_left, virtual_top)

            # create the device context
            hdc = user32.GetDC(None)
            hcdc = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
            hbmp = ctypes.windll.gdi32.CreateCompatibleBitmap(
                hdc, screensize[0], screensize[1]
            )
            ctypes.windll.gdi32.SelectObject(hcdc, hbmp)

            # blit the virtual screen into the bitmap (covering every display)
            ctypes.windll.gdi32.BitBlt(
                hcdc,
                0,
                0,
                screensize[0],
                screensize[1],
                hdc,
                screen_offset[0],
                screen_offset[1],
                0x00CC0020,
            )

            # read the bitmap data
            bmpinfo = ctypes.wintypes.BITMAPINFO()
            bmpinfo.bmiHeader.biSize = ctypes.sizeof(ctypes.wintypes.BITMAPINFOHEADER)
            bmpinfo.bmiHeader.biWidth = screensize[0]
            bmpinfo.bmiHeader.biHeight = -screensize[
                1
            ]  # a negative height means top-down
            bmpinfo.bmiHeader.biPlanes = 1
            bmpinfo.bmiHeader.biBitCount = 32
            bmpinfo.bmiHeader.biCompression = 0

            # allocate the buffer
            buffer_size = screensize[0] * screensize[1] * 4
            buffer = ctypes.create_string_buffer(buffer_size)

            # read the pixel data
            ctypes.windll.gdi32.GetDIBits(
                hcdc, hbmp, 0, screensize[1], buffer, ctypes.byref(bmpinfo), 0
            )

            # release the resources
            ctypes.windll.gdi32.DeleteObject(hbmp)
            ctypes.windll.gdi32.DeleteDC(hcdc)
            user32.ReleaseDC(None, hdc)

            # convert to a PIL Image
            image = Image.frombuffer("RGBA", screensize, buffer, "raw", "BGRA", 0, 1)
            image = image.convert("RGB")

            # encode as JPEG bytes
            byte_io = io.BytesIO()
            image.save(byte_io, format="JPEG", quality=85)

            return byte_io.getvalue()

        except Exception as e:
            logger.error(f"Windows screenshot capture failed: {e}", exc_info=True)
            return None

    #: Longest side of a screenshot sent for analysis, in pixels.
    _MAX_EDGE = 2600

    @staticmethod
    def _linux_monitors() -> list[dict]:
        """The connected monitors, main first, from KDE's kscreen-doctor.

        Each is {"name", "x", "y", "w", "h"}. Empty when kscreen-doctor is
        missing (not KDE) - then only whole-desktop capture is offered.
        """
        import re
        import shutil
        import subprocess

        if not shutil.which("kscreen-doctor"):
            return []
        try:
            out = subprocess.run(
                ["kscreen-doctor", "-o"], capture_output=True, text=True, timeout=5
            ).stdout
        except Exception:
            return []
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        monitors, cur = [], None
        for line in out.splitlines():
            m = re.match(r"Output:\s+\d+\s+(\S+)", line)
            if m:
                cur = {"name": m.group(1), "priority": 99, "on": True}
                monitors.append(cur)
            elif cur is not None:
                if line.strip() == "disabled":
                    cur["on"] = False
                m = re.search(r"priority\s+(\d+)", line)
                if m:
                    cur["priority"] = int(m.group(1))
                m = re.search(r"Geometry:\s+(-?\d+),(-?\d+)\s+(\d+)x(\d+)", line)
                if m:
                    cur.update(
                        x=int(m.group(1)),
                        y=int(m.group(2)),
                        w=int(m.group(3)),
                        h=int(m.group(4)),
                    )
        ok = [m for m in monitors if m["on"] and "w" in m]
        return sorted(ok, key=lambda m: m["priority"])

    def _capture_linux(self, display_id=None) -> bytes:
        """Capture on Linux, optionally just one monitor, as a JPEG.

        Wayland (KDE) only allows screenshots through the desktop's own tool,
        so spectacle is tried first; the older X11 tools follow. Monitors are
        numbered 1, 2, 3 in KDE's priority order, "main" is 1 and "secondary"
        is 2.
        """
        import io
        import os
        import subprocess
        import tempfile

        from PIL import Image

        commands = [
            ["spectacle", "-b", "-n", "-f", "-o"],  # KDE, works on Wayland
            ["gnome-screenshot", "-f"],
            ["scrot"],
            ["import", "-window", "root"],
        ]
        raw = None
        for base in commands:
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                os.unlink(path)  # some tools refuse to overwrite
                r = subprocess.run(
                    base + [path], capture_output=True, text=True, timeout=20
                )
                if r.returncode == 0 and os.path.exists(path):
                    with open(path, "rb") as f:
                        raw = f.read()
                    logger.debug(f"captured with: {base[0]}")
                    break
            except subprocess.TimeoutExpired:
                logger.warning(f"screenshot command timed out: {base[0]}")
            except FileNotFoundError:
                logger.debug(f"screenshot tool not found: {base[0]}")
            except Exception as e:
                logger.debug(f"screenshot command failed {base[0]}: {e}")
            finally:
                if os.path.exists(path):
                    os.unlink(path)
        if not raw:
            return None

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if display_id is not None:
            monitors = self._linux_monitors()
            index = {"main": 0, "secondary": 1}.get(display_id)
            if index is None and isinstance(display_id, int):
                index = display_id - 1
            if monitors and index is not None and 0 <= index < len(monitors):
                m = monitors[index]
                # the capture's origin is the top-left of the whole desktop
                left = min(mm["x"] for mm in monitors)
                top = min(mm["y"] for mm in monitors)
                box = (
                    m["x"] - left,
                    m["y"] - top,
                    m["x"] - left + m["w"],
                    m["y"] - top + m["h"],
                )
                img = img.crop(box)
                logger.info(f"screenshot cropped to {m['name']} {m['w']}x{m['h']}")
            else:
                logger.warning(
                    f"display {display_id!r} not found among {len(monitors)} "
                    "monitors; sending the whole desktop"
                )
        img.thumbnail((self._MAX_EDGE, self._MAX_EDGE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=82)
        return out.getvalue()

    def analyze(self, question: str, image_data: bytes | None = None) -> str:
        try:
            logger.info(f"Analyzing screenshot with question: {question}")

            # prefer the photo camera injected at registration time (it shares the vision URL and token)
            camera_instance = getattr(self, "_photo_camera_ref", None)
            buf = image_data if image_data is not None else self.jpeg_data["buf"]
            if camera_instance is not None:
                return camera_instance.analyze(question, image_data=buf)

            from src.mcp.tools.camera import create_camera

            return create_camera().analyze(question, image_data=buf)

        except Exception as e:
            logger.error(f"Error analyzing screenshot: {e}", exc_info=True)
            return json.dumps(
                {"success": False, "message": f"Failed to analyze screenshot: {e}"}
            )

    def _capture_single_display_macos(self, display_num):
        """Capture a single macOS display.

        Args:
            display_num: the display number (1, 2, 3, ...)

        Returns:
            the PIL Image
        """
        try:
            import os
            import subprocess
            import tempfile

            from PIL import Image

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_path = temp_file.name

            cmd = [
                "screencapture",
                "-D",
                str(display_num),
                "-x",
                "-t",
                "png",
                temp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0 and os.path.exists(temp_path):
                try:
                    img = Image.open(temp_path)
                    screenshot = img.copy()
                    os.unlink(temp_path)
                    logger.debug(f"Captured display {display_num}: {screenshot.size}")
                    return screenshot
                except Exception as e:
                    logger.error(
                        f"Failed to read display {display_num}: {e}", exc_info=True
                    )
                    os.unlink(temp_path)
                    return None
            else:
                logger.error(
                    f"screencapture failed for display {display_num}: {result.stderr}"
                )
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                return None

        except Exception as e:
            logger.error(f"Single display capture failed: {e}", exc_info=True)
            return None

    def _capture_all_displays_macos(self):
        """Capture every macOS display and stitch them together.

        Returns:
            the stitched PIL Image
        """
        try:
            import os
            import subprocess
            import tempfile

            from PIL import Image

            # find every available display
            displays = []
            for display_id in range(1, 5):  # probe up to 4 displays
                with tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                ) as temp_file:
                    temp_path = temp_file.name

                cmd = [
                    "screencapture",
                    "-D",
                    str(display_id),
                    "-x",
                    "-t",
                    "png",
                    temp_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0 and os.path.exists(temp_path):
                    try:
                        img = Image.open(temp_path)
                        displays.append(
                            {
                                "id": display_id,
                                "size": img.size,
                                "image": img.copy(),
                                "path": temp_path,
                            }
                        )
                        logger.debug(f"Found display {display_id}: {img.size}")
                    except Exception as e:
                        logger.debug(f"Failed to read display {display_id}: {e}")
                        os.unlink(temp_path)
                else:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)

            if not displays:
                logger.error("No displays found")
                return None

            # remove the temporary file
            for display in displays:
                try:
                    os.unlink(display["path"])
                except Exception as e:
                    logger.debug(f"failed to remove the screenshot temporary file: {e}")

            if len(displays) == 1:
                # a single display, return it as is
                return displays[0]["image"]
            else:
                # several displays, stitch them together
                logger.debug(f"Compositing {len(displays)} displays")
                return self._composite_displays(displays)

        except Exception as e:
            logger.error(f"All displays capture failed: {e}", exc_info=True)
            return None
