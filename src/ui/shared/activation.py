"""The base class for the activation UI.

It owns the flow - fetch the code, show it, call service.activate, report the result - and subclasses only handle the display.
"""


class BaseActivation:
    """The base class for the activation UI (not an ABC, which would clash with PySide6's QObject metaclass).

    Args:
        activation_service: an ActivationService from create() - not a singleton
        init_result: the initialize() result handle_activation passes in, so it is not run twice
    """

    def __init__(self, activation_service=None, init_result=None):
        # the arguments are optional: with PySide6 multiple inheritance, QObject.__init__'s super chain may call this with none
        self._service = activation_service
        self._init_result = init_result

    def needs_activation(self) -> bool:
        """Whether the activation UI needs to run at all."""
        if self._init_result is None:
            return False
        return bool(self._init_result.get("need_activation_ui", False))

    async def _core_activate(self) -> bool:
        """The core flow: fetch the code, show it, then service.activate (which also copies it and reads it aloud)."""
        if self._service is None:
            self._show_error("The activation service is not initialised")
            return False

        data = self._service.get_activation_data()
        if not data:
            self._show_error("No activation data came back")
            return False

        self._show_code(data)
        success = await self._service.activate(data)
        self._show_result(success)
        return success

    async def run(self) -> bool:
        """Run the activation flow."""
        raise NotImplementedError

    def _show_code(self, data: dict) -> None:
        """Show the verification code (the CLI prints it; the GUI writes it to the model)."""
        raise NotImplementedError

    def _show_result(self, success: bool) -> None:
        """Show the result of activation."""
        raise NotImplementedError

    def _show_error(self, msg: str) -> None:
        """Show an error (subclasses may override)."""
        pass
