# -*- coding: utf-8 -*-
"""The emotion service - manages the emotion assets."""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QUrl

from src.logging import get_logger
from src.utils.resource_finder import get_assets_dir

logger = get_logger()


class EmotionService(QObject):
    """The emotion service - finds the emotion files and turns them into URLs."""

    EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[str, str] = {}
        self._emotion_dir = get_assets_dir() / "emojis"

        if not self._emotion_dir.exists():
            logger.warning(f"no emotion directory at: {self._emotion_dir}")

    def get_emotion_url(self, emotion_name: str) -> str:
        """Get a URL for an emotion that QML can use.

        Args:
            emotion_name: the emotion name

        Returns:
            a file:// URL, or an emoji character
        """
        # check the cache
        if emotion_name in self._cache:
            return self._cache[emotion_name]

        # find the file
        path = self._find_emotion_file(emotion_name)
        if not path:
            # fall back to neutral
            path = self._find_emotion_file("neutral")

        # turn it into a URL
        if path:
            url = QUrl.fromLocalFile(str(path)).toString()
        else:
            url = "😊"  # the last resort
            logger.warning(f"no file for the emotion {emotion_name}, using an emoji")

        self._cache[emotion_name] = url
        return url

    def _find_emotion_file(self, name: str) -> Optional[Path]:
        """Find the file for an emotion."""
        for ext in self.EXTENSIONS:
            file_path = self._emotion_dir / f"{name}{ext}"
            if file_path.exists():
                return file_path
        return None

    def clear_cache(self):
        """Clear the cache."""
        self._cache.clear()

    def preload(self, names: list[str]):
        """Preload the emotions."""
        for name in names:
            self.get_emotion_url(name)
        logger.debug(f"preloaded {len(names)} emotions")
