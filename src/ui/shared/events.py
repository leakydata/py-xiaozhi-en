"""The dataclasses for the UI events."""

from dataclasses import dataclass


@dataclass
class UISendTextRequest:
    """Send text."""

    text: str
