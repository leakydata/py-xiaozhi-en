"""The volume backend protocol, and the factory for it."""

from __future__ import annotations

from typing import Protocol


class VolumeBackend(Protocol):
    """A platform's volume implementation."""

    def get_volume(self) -> int:
        """The current volume, 0-100."""
        ...

    def set_volume(self, volume: int) -> None:
        """Set the volume, 0-100 (the caller has already clamped it)."""
        ...
