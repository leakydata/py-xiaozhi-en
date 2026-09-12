"""Device activation in CLI mode."""

from datetime import datetime

from src.constants.system import SystemConstants
from src.logging import get_logger
from src.ui.shared.activation import BaseActivation

logger = get_logger()


class CliActivation(BaseActivation):
    """Handles device activation in CLI mode.

    Subclasses BaseActivation, overriding only the methods that print to the terminal.
    """

    def __init__(self, activation_service, init_result: dict):
        super().__init__(activation_service, init_result)

    async def run(self) -> bool:
        self._print_header()

        if not self.needs_activation():
            self._log("The device is already activated, nothing more to do")
            self._print_success()
            return True

        self._print_device_info()
        try:
            return await self._core_activate()
        except KeyboardInterrupt:
            self._log("\nActivation cancelled")
            return False

    # ---- the BaseActivation display methods ----

    def _show_code(self, data: dict) -> None:
        self._print_activation_info(data)

    def _show_result(self, success: bool) -> None:
        if success:
            self._print_success()
        else:
            self._print_failure()

    def _show_error(self, msg: str) -> None:
        self._log(msg)

    # ---- terminal output helpers ----

    def _print_header(self):
        print("\n" + "=" * 60)
        print(f"{SystemConstants.APP_DISPLAY_NAME} - device activation")
        print("=" * 60)

    def _print_device_info(self):
        """Print the device details."""
        serial = self._service.get_serial_number() or "--"
        mac = self._service.get_mac_address() or "--"
        status = self._service.get_activation_status()

        print("\nDevice:")
        print(f"  Serial number: {serial}")
        print(f"  MAC address: {mac}")

        local = status.get("local_activated", False)
        server = status.get("server_activated", False)
        consistent = status.get("status_consistent", True)

        if not consistent:
            status_text = (
                "needs reactivating"
                if local and not server
                else "repaired automatically"
            )
        else:
            status_text = "activated" if local else "not activated"

        print(f"  Status: {status_text}")

    def _print_activation_info(self, data: dict):
        """Print the activation details."""
        code = data.get("code", "------")
        message = data.get(
            "message", "Go to xiaozhi.me and enter the verification code"
        )

        print("\n" + "-" * 60)
        print("Activation")
        print("-" * 60)
        print(f"Verification code: {' '.join(code)}")
        print(f"Details: {message}")
        print("-" * 60)
        print("\nWhat to do:")
        print("  1. Open xiaozhi.me in a browser")
        print("  2. Sign in to your account")
        print("  3. Choose to add a device")
        print(f"  4. Enter the verification code: {code}")
        print("  5. Confirm adding the device")

    def _print_success(self):
        print("\n" + "=" * 60)
        print("Device activated.")
        print("=" * 60)
        print("The device has been added to your account")
        print(f"Starting {SystemConstants.APP_DISPLAY_NAME}...")
        print("=" * 60 + "\n")

    def _print_failure(self):
        print("\n" + "=" * 60)
        print("Device activation failed")
        print("=" * 60)
        print("Possible reasons:")
        print("  - an unstable network connection")
        print("  - the verification code was wrong or has expired")
        print("  - the server is temporarily unavailable")
        print("\nWhat to try:")
        print("  - check your network connection")
        print("  - run the program again for a new code")
        print("  - make sure the code is entered correctly")
        print("=" * 60 + "\n")

    def _log(self, message: str):
        """Print a log line with a timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        logger.info(message)
