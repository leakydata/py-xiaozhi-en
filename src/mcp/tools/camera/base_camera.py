"""
Base camera implementation.
"""

from abc import ABC, abstractmethod
from typing import Any

from src.logging import get_logger
from src.utils.config_manager import get_config

from .capture_backend import capture_jpeg, load_capture_config

logger = get_logger()


class BaseCamera(ABC):
    """
    The camera base class, defining the interface.
    """

    def __init__(self):
        """
        Initialise the base camera.
        """
        self.jpeg_data = {
            "buf": b"",
            "len": 0,
        }  # the image as JPEG bytes, and its length

        # read the camera settings from the config (capture_backend reads the capture details itself)
        config = get_config()
        self.camera_index = config.get_config("CAMERA.camera_index", 0)
        self.frame_width = config.get_config("CAMERA.frame_width", 640)
        self.frame_height = config.get_config("CAMERA.frame_height", 480)

    def capture_frame(self) -> bool:
        """Capture a JPEG frame through whichever backend applies (OpenCV/V4L2 or picamera2).

        A desktop or Pi USB camera goes through OpenCV; a Pi CSI camera falls back to picamera2 when OpenCV fails in auto mode.
        There is a timeout, so a wedged driver cannot take the thread down with it.
        """
        cfg = load_capture_config()
        # keep in step with the instance fields (the config wins even if something changed the index)
        self.camera_index = cfg.camera_index
        self.frame_width = cfg.frame_width
        self.frame_height = cfg.frame_height

        jpeg = capture_jpeg(cfg)
        if not jpeg:
            logger.error(
                "camera capture failed "
                f"(backend={cfg.backend}, device={cfg.device!r}, index={cfg.camera_index})"
            )
            return False

        self.set_jpeg_data(jpeg)
        logger.info(
            f"Image captured successfully (size: {self.jpeg_data['len']} bytes)"
        )
        return True

    # the legacy name
    def capture_with_cv2(self) -> bool:
        return self.capture_frame()

    def set_explain_url(self, url: str):  # noqa: B027
        """Set the vision service URL (subclasses override as needed)."""

    def set_explain_token(self, token: str):  # noqa: B027
        """Set the vision service token (subclasses override as needed)."""

    @abstractmethod
    def capture(self) -> bool:
        """
        Capture an image.
        """

    @abstractmethod
    def analyze(self, question: str, image_data: bytes | None = None) -> str:
        """Analyse an image.

        Args:
            question: what the user asked
            image_data: image data from elsewhere; None uses self.jpeg_data
        """

    def get_jpeg_data(self) -> dict[str, Any]:
        """
        Get the JPEG data.
        """
        return self.jpeg_data

    def set_jpeg_data(self, data_bytes: bytes):
        """
        Set the JPEG data.
        """
        self.jpeg_data["buf"] = data_bytes
        self.jpeg_data["len"] = len(data_bytes)
