"""The UI package: the gui, cli and gpio front ends.

Import only what you need, so one mode does not drag in another:
    from src.ui.gui import GuiViewManager
    from src.ui.cli import CliViewManager
    from src.ui.gpio import GpioViewManager  # Linux only
    from src.ui.shared import ViewPort, create_viewport
"""

__all__ = []
