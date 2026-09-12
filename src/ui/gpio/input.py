"""GPIO input handling.

Wraps gpiozero's button watching, for GPIO buttons on a Raspberry Pi.
Linux only.

The button module:
- pressed pulls the line low (active low)
- released leaves it high

The default pin mapping (BCM numbering):
- KEY1: GPIO 17 - start/stop the conversation
- KEY2: GPIO 27 - interrupt what is being said
- KEY3: GPIO 22 - switch between auto and manual mode
- KEY4: GPIO 23 - quit

Change DEFAULT_PINS to use different pins.
"""

import sys
import threading
from typing import Callable, List, Optional

from src.logging import get_logger

logger = get_logger()

# the default GPIO pins (BCM numbering)
# change these to match how it is actually wired
DEFAULT_PINS: List[int] = [17, 27, 22, 23]


class GPIOInput:
    """Handles GPIO button input.

    Wraps gpiozero's Button class and calls back on a press.
    """

    def __init__(
        self,
        pins: Optional[List[int]] = None,
        bounce_time: float = 0.05,
    ):
        """Initialise the GPIO input.

        Args:
            pins: the GPIO pins (BCM numbering); DEFAULT_PINS by default
            bounce_time: the debounce time, in seconds
        """
        self._pins = pins or DEFAULT_PINS.copy()
        self._bounce_time = bounce_time
        self._buttons: List = []
        self._callbacks: dict[int, dict[str, Optional[Callable]]] = {}
        self._lock = threading.Lock()
        self._available = False

        # check the platform
        if sys.platform != "linux":
            logger.warning("GPIO mode only works on Linux")
            return

        # try to import gpiozero
        try:
            from gpiozero import Button  # type: ignore[import-not-found]

            self._Button = Button
            self._available = True
            logger.info(f"GPIO input initialised, pins: {self._pins}")
        except ImportError:
            logger.error(
                "gpiozero is not installed; run: sudo apt install python3-gpiozero python3-rpi.gpio"
            )
        except Exception as e:
            logger.error(f"GPIO initialisation failed: {e}", exc_info=True)

    @property
    def available(self) -> bool:
        """Whether GPIO is available."""
        return self._available

    @property
    def pins(self) -> List[int]:
        """The pins currently configured."""
        return self._pins.copy()

    def setup(
        self,
        on_key1_pressed: Optional[Callable] = None,
        on_key2_pressed: Optional[Callable] = None,
        on_key3_pressed: Optional[Callable] = None,
        on_key4_pressed: Optional[Callable] = None,
    ) -> bool:
        """Set the button callbacks.

        Args:
            on_key1_pressed: called when KEY1 is pressed
            on_key2_pressed: called when KEY2 is pressed
            on_key3_pressed: called when KEY3 is pressed
            on_key4_pressed: called when KEY4 is pressed

        Returns:
            whether they were set up
        """
        if not self._available:
            logger.warning("GPIO is unavailable, not setting up the buttons")
            return False

        callbacks = [on_key1_pressed, on_key2_pressed, on_key3_pressed, on_key4_pressed]

        try:
            for i, pin in enumerate(self._pins):
                # create the button (active low, with the internal pull-up)
                button = self._Button(pin, pull_up=True, bounce_time=self._bounce_time)
                self._buttons.append(button)

                # keep the callback
                with self._lock:
                    self._callbacks[i] = {
                        "pressed": callbacks[i] if i < len(callbacks) else None,
                    }

                # wire up the press callback
                if i < len(callbacks) and callbacks[i]:
                    # a closure captures the index
                    def make_handler(idx: int):
                        def handler():
                            with self._lock:
                                cb = self._callbacks.get(idx, {}).get("pressed")
                            if cb:
                                logger.debug(
                                    f"KEY{idx + 1} (GPIO{self._pins[idx]}) pressed"
                                )
                                cb()

                        return handler

                    button.when_pressed = make_handler(i)

                logger.debug(f"KEY{i + 1} -> GPIO{pin} configured")

            logger.info(f"GPIO buttons configured: {len(self._buttons)} of them")
            return True

        except Exception as e:
            logger.error(f"failed to configure the GPIO buttons: {e}", exc_info=True)
            return False

    def close(self) -> None:
        """Release the GPIO resources."""
        for button in self._buttons:
            try:
                button.close()
            except Exception as e:
                logger.warning(f"failed to close the GPIO button: {e}", exc_info=True)

        self._buttons.clear()
        with self._lock:
            self._callbacks.clear()
        logger.info("GPIO resources released")
