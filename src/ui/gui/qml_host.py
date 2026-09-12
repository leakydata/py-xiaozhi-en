"""The QML engine host: loading, injecting context, and driving the root window."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine

from src.logging import get_logger

logger = get_logger()


def _show_window(window, *, activate: bool) -> None:
    """Show a window; with activate=False it avoids taking focus, which keeps macOS fullscreen Spaces happy."""
    if window is None:
        return

    if activate:
        window.show()
        window.raise_()
        window.requestActivate()
        return

    # the QWidget path: ShowWithoutActivating
    set_attr = getattr(window, "setAttribute", None)
    if callable(set_attr):
        set_attr(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        try:
            window.show()
        finally:
            set_attr(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        return

    # QQuickWindow / QWindow: drop focusability briefly so it does not become the key window
    # (on macOS the key window shoves another fullscreen app off its Space)
    flags = window.flags()
    try:
        window.setFlags(flags | Qt.WindowType.WindowDoesNotAcceptFocus)
        window.show()
    finally:
        window.setFlags(flags)


class QmlAppHost:
    """Owns the QML engine's lifecycle and access to the root object, and nothing else."""

    def __init__(self) -> None:
        self._engine: QQmlApplicationEngine | None = None

    @property
    def engine(self) -> QQmlApplicationEngine | None:
        return self._engine

    def create_engine(self) -> QQmlApplicationEngine:
        self._engine = QQmlApplicationEngine()
        return self._engine

    def inject_context(self, properties: dict) -> None:
        if not self._engine:
            raise RuntimeError("QML engine not created")
        ctx = self._engine.rootContext()
        for name, obj in properties.items():
            ctx.setContextProperty(name, obj)
        logger.debug("QmlAppHost: injected the QML context %s", list(properties))

    def load_main(self) -> None:
        if not self._engine:
            raise RuntimeError("QML engine not created")
        qml_dir = Path(__file__).parent / "qml"
        self._engine.addImportPath(str(qml_dir))
        main_qml = qml_dir / "main.qml"
        self._engine.load(QUrl.fromLocalFile(str(main_qml)))
        if not self._engine.rootObjects():
            logger.error("QmlAppHost: the QML failed to load")
            raise RuntimeError("Failed to load QML")
        logger.debug("QmlAppHost: loaded %s", main_qml)

    def root_window(self):
        if not self._engine:
            return None
        roots = self._engine.rootObjects()
        return roots[0] if roots else None

    def show_root(self, *, activate: bool = True) -> None:
        """Show the main window.

        Args:
            activate: True brings it to the front (the tray's "Show Window", or a shortcut);
                      False just shows it without requestActivate (used on a cold start, so a macOS fullscreen app keeps its Space)
        """
        _show_window(self.root_window(), activate=activate)

    def toggle_root_visible(self) -> None:
        window = self.root_window()
        if window is None:
            return
        if window.isVisible():
            window.hide()
        else:
            # the user asked for it, so bring it to the front
            self.show_root(activate=True)

    def shutdown(self) -> None:
        if self._engine:
            self._engine.deleteLater()
            self._engine = None
