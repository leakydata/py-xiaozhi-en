"""Create the activation UI for a run mode (the mirror of create_viewport)."""

from typing import Any


def create_activation_ui(mode: str, activation_service, init_result: dict) -> Any:
    """gui → GuiActivation; tui/cli/gpio → CliActivation.

    Args:
        mode: the run mode
        activation_service: the ActivationService
        init_result: the initialize() result, so it is not run twice
    """
    normalized = (mode or "cli").lower()
    if normalized == "gui":
        from src.ui.gui import GuiActivation

        return GuiActivation(activation_service, init_result)

    # tui, cli and gpio all use the plain terminal flow for activation
    from src.ui.cli import CliActivation

    return CliActivation(activation_service, init_result)
