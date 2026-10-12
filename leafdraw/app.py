from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from leafdraw.ui.theme import dark_palette


def configure_opengl():
    """Precisa rodar antes de criar a QApplication."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def create_app(argv=None) -> QApplication:
    configure_opengl()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("LeafDraw")
    app.setOrganizationName("LeafDraw")
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    return app


def main():
    app = create_app()
    from leafdraw.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.open_path(sys.argv[1])
    else:
        win.zoom_extents()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
