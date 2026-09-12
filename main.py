import argparse
import asyncio
import locale
import os
import signal
import sys

# Windows: force the C/C++ runtime to UTF-8, or sherpa-onnx garbles the toned pinyin files
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        locale.setlocale(locale.LC_ALL, ".UTF-8")
    except locale.Error:
        pass

os.environ["QSG_RHI_BACKEND"] = "opengl"
# force qasync to use PySide6
os.environ["QT_API"] = "pyside6"
# Basic style, so custom controls are supported
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"


def parse_args():
    """Parse command-line arguments."""
    from src.constants.system import SystemConstants

    parser = argparse.ArgumentParser(description=SystemConstants.APP_DISPLAY_NAME)
    # run mode
    # - gui: graphical interface, PySide6 + QML
    # - cli: terminal interaction (light; good for headless/SSH)
    # - tui: full-screen TUI (Textual) with editable config; needs uv sync --extra tui
    # - gpio: physical buttons over GPIO; Linux only (Raspberry Pi)
    parser.add_argument(
        "--mode",
        choices=["gui", "cli", "tui", "gpio"],
        default="gui",
        help="run mode (default gui): gui / cli / tui (full-screen terminal) / gpio (Linux only)",
    )
    parser.add_argument(
        "--protocol",
        choices=["mqtt", "websocket"],
        default="websocket",
        metavar="PROTOCOL",
        help="transport: mqtt or websocket (default websocket; pass --protocol mqtt to switch)",
    )
    parser.add_argument(
        "--skip-activation",
        action="store_true",
        help="skip activation and start straight away (debugging only)",
    )
    return parser.parse_args()


# Parse arguments before initialising config and logging (no lazy ConfigManager singleton)
_args = parse_args()

from src.utils.config_manager import initialize_config  # noqa: E402

initialize_config()

from src.logging import load_logging_config, setup_logging  # noqa: E402

# CLI/TUI modes take over the terminal, so console logging is off there
setup_logging(
    enable_console=(_args.mode not in ("cli", "tui")),
    config=load_logging_config(),
)

from src.bootstrap.container import ServiceContainer  # noqa: E402
from src.constants.system import SystemConstants  # noqa: E402
from src.logging import get_logger  # noqa: E402

logger = get_logger()


async def handle_activation(mode: str) -> bool:
    """Run the device activation flow.

    Args:
        mode: run mode - "gui", "cli", "tui" or "gpio"

    Returns:
        bool: whether activation succeeded
    """
    try:
        from src.activation import ActivationService, create_activation_ui

        logger.info("Starting device activation check...")
        activation_service = await ActivationService.create()
        init_result = await activation_service.initialize()

        if not init_result.get("success", False):
            logger.error(f"Initialisation failed: {init_result.get('error', 'unknown error')}")
            return False

        if not init_result.get("need_activation_ui", False):
            logger.info("Device already activated; no activation needed")
            return True

        ui = create_activation_ui(mode, activation_service, init_result)
        return await ui.run()

    except Exception as e:
        logger.error(f"Activation flow error: {e}", exc_info=True)
        return False


async def start_app(mode: str, protocol: str, skip_activation: bool) -> int:
    """Single entry point for starting the app."""
    global _container  # used by the SIGINT handler
    logger.info(f"Starting {SystemConstants.APP_DISPLAY_NAME}")

    # activation
    if not skip_activation:
        activation_success = await handle_activation(mode)
        if not activation_success:
            logger.error("Device activation failed; exiting")
            return 1
    else:
        logger.warning("Skipping activation (debug mode)")

    # build and run the application
    _container = ServiceContainer()
    return await _container.run(mode=mode, protocol=protocol)


# global container reference, used by the SIGINT handler
_container = None


if __name__ == "__main__":
    exit_code = 1
    try:
        # use the already-parsed arguments
        args = _args

        # detect Wayland and set the Qt platform plugin accordingly
        import os

        is_wayland = (
            os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("XDG_SESSION_TYPE") == "wayland"
        )

        if args.mode == "gui" and is_wayland:
            if "QT_QPA_PLATFORM" not in os.environ:
                os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"
                logger.info("Wayland detected: setting QT_QPA_PLATFORM=wayland;xcb")
            os.environ.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
            logger.info("Wayland detection complete; compatibility settings applied")

        # signal handling
        try:
            if hasattr(signal, "SIGTRAP"):
                signal.signal(signal.SIGTRAP, signal.SIG_IGN)
        except Exception:
            pass

        if args.mode == "gui":
            # GUI mode: PySide6 + qasync
            try:
                import qasync
                from PySide6.QtWidgets import QApplication
            except ImportError as e:
                logger.error(
                    "GUI mode needs PySide6 + qasync, which are not installed.\n"
                    "Install the GUI extras into the project venv and try again:\n"
                    "  uv sync --extra gui\n"
                    "  # or: pip install '.[gui]'\n"
                    "then:\n"
                    "  uv run python main.py\n"
                    "  # or: .venv/bin/python main.py\n"
                    "Without a GUI you can use:\n"
                    "  python main.py --mode cli\n"
                    "  python main.py --mode tui   # needs uv sync --extra tui\n"
                    f"(original error: {e})"
                )
                sys.exit(1)

            qt_app = QApplication.instance() or QApplication(sys.argv)
            qt_app.setQuitOnLastWindowClosed(False)

            loop = qasync.QEventLoop(qt_app)
            asyncio.set_event_loop(loop)
            logger.info("Created the PySide6 + qasync event loop")

            # SIGINT: ask the TaskManager to shut down
            shutdown_state = {"requested": False}

            def handle_sigint(*_):
                if shutdown_state["requested"]:
                    return
                shutdown_state["requested"] = True
                logger.info("SIGINT received, exiting...")

                # request a graceful shutdown through the TaskManager
                try:
                    if _container and _container.tasks:
                        _container.tasks.request_shutdown()
                    else:
                        # container not ready yet - quit Qt directly
                        if loop.is_running():
                            loop.call_soon_threadsafe(qt_app.quit)
                except Exception:
                    qt_app.quit()

            signal.signal(signal.SIGINT, handle_sigint)

            try:
                with loop:
                    exit_code = loop.run_until_complete(
                        start_app(args.mode, args.protocol, args.skip_activation)
                    )
            except RuntimeError as e:
                # swallow qasync's "Event loop stopped before Future completed"
                if "Event loop stopped before Future completed" in str(e):
                    logger.debug("Event loop terminated normally")
                    exit_code = 0
                else:
                    raise
        else:
            # CLI / TUI / GPIO: plain asyncio
            if args.mode == "tui":
                try:
                    import textual  # noqa: F401
                except ImportError as e:
                    logger.error(
                        "TUI mode needs textual. Run:\n"
                        "  uv sync --extra tui\n"
                        "  pip install '.[tui]'\n"
                        "Headless or over SSH, use: python main.py --mode cli\n"
                        f"(original error: {e})"
                    )
                    sys.exit(1)

            # CLI / GPIO: plain asyncio; SIGINT asks the TaskManager to shut down
            shutdown_state = {"requested": False}

            def handle_sigint_cli(*_):
                if shutdown_state["requested"]:
                    # second Ctrl+C: hard exit
                    logger.warning("SIGINT again, forcing exit")
                    os._exit(130)
                shutdown_state["requested"] = True
                logger.info("SIGINT received, exiting...")
                try:
                    if _container and _container.tasks:
                        _container.tasks.request_shutdown()
                except Exception:
                    pass

            signal.signal(signal.SIGINT, handle_sigint_cli)
            exit_code = asyncio.run(
                start_app(args.mode, args.protocol, args.skip_activation)
            )

    except KeyboardInterrupt:
        logger.info("Interrupted by the user")
        exit_code = 0
    except Exception as e:
        logger.error(f"Exited with an error: {e}", exc_info=True)
        exit_code = 1
    finally:
        sys.exit(exit_code)
