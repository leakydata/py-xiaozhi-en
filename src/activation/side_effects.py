"""What happens alongside an activation code: the clipboard and the spoken announcement."""

from __future__ import annotations

from typing import Optional

from src.logging import get_logger

logger = get_logger()


def apply_code_side_effects(code: str, message: Optional[str] = None) -> None:
    """Log it, copy it, announce it. The CLI/GUI wording is not this function's job."""
    if not code:
        return
    msg = message or "Enter the verification code in the control panel"
    logger.info(f"Activation: {msg}")
    logger.info(f"Verification code: {code}")

    # The code is already in hand, so copy it straight across. This used to
    # format it into a Chinese sentence and regex it back out again, which only
    # worked while both halves stayed Chinese.
    try:
        from src.utils.common_utils import copy_to_clipboard

        copy_to_clipboard(code)
    except Exception as e:
        logger.debug(f"Failed to copy the verification code: {e}")

    try:
        from src.utils.activation_announcer import announce_activation_code

        announce_activation_code(code)
    except Exception as e:
        logger.debug(f"Failed to announce the verification code: {e}")


def announce_code(code: str) -> None:
    """Announce only (used while polling for a retry)."""
    if not code:
        return
    from src.utils.activation_announcer import announce_activation_code

    announce_activation_code(code)
