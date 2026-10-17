"""Janela "Sobre o LeafDraw": versão, links, informações do sistema e licenças."""
from __future__ import annotations

import platform
import sys
from importlib import metadata
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from leafdraw import __version__

REPO_URL = "https://github.com/francisreboucas/leafdraw"
ISSUES_URL = REPO_URL + "/issues"


def bundle_dir() -> Path:
    """Onde estão LICENSE e avisos de terceiros (instalado ou rodando do código-fonte)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _find(*names: str) -> Path | None:
    base = bundle_dir()
    for name in names:
        for p in (base / name, base / "packaging" / name):
            if p.exists():
                return p
    return None


def _pkg_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "?"


def system_info(gl_info: dict | None = None) -> str:
    gl = gl_info or {}
    lines = [
        f"LeafDraw {__version__}{' (instalado)' if getattr(sys, 'frozen', False) else ' (código-fonte)'}",
        f"Sistema: {platform.system()} {platform.release()} ({platform.version()}) {platform.machine()}",
        f"Python: {platform.python_version()}",
        f"Qt: {qVersion()} · PySide6: {PySide6.__version__}",
        f"moderngl: {_pkg_version('moderngl')} · numpy: {_pkg_version('numpy')} · "
        f"shapely: {_pkg_version('shapely')} · ezdxf: {_pkg_version('ezdxf')}",
        f"OpenGL: {gl.get('GL_VERSION', 'não iniciado (abra a vista 3D)')}",
        f"Placa de vídeo: {gl.get('GL_RENDERER', '?')} ({gl.get('GL_VENDOR', '?')})",
    ]
    return "\n".join(lines)


class AboutDialog(QDialog):
    def __init__(self, parent=None, gl_info: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o LeafDraw")
        self.setMinimumSize(560, 420)
        tabs = QTabWidget()
        tabs.addTab(self._about_tab(), "Sobre")
        tabs.addTab(self._system_tab(gl_info), "Sistema")
        tabs.addTab(self._licenses_tab(), "Licenças")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _about_tab(self) -> QWidget:
        w = QWidget()
        icon = QLabel()
        app_icon = QGuiApplication.windowIcon()
        if not app_icon.isNull():
            icon.setPixmap(app_icon.pixmap(112, 112))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("LeafDraw")
        f = QFont(title.font())
        f.setPointSize(f.pointSize() + 12)
        f.setBold(True)
        title.setFont(f)
        beta = " · <span style='color:#e0b050'>beta</span>" if any(c in __version__ for c in "ab") else ""
        version = QLabel(f"Versão {__version__}{beta}")
        version.setTextFormat(Qt.TextFormat.RichText)
        tagline = QLabel("CAD para paisagismo")
        tagline.setStyleSheet("color: #9aa5b1;")

        body = QLabel(
            "<p>Desenho técnico 2D, catálogo de plantas, maciços e quantitativos, terreno e vista 3D, "
            "pranchas com carimbo e exportação para PDF e DXF.</p>"
            f"<p><a href='{REPO_URL}' style='color:#6cb0ff'>Código-fonte e novidades</a> · "
            f"<a href='{ISSUES_URL}' style='color:#6cb0ff'>Relatar um problema ou sugerir melhorias</a></p>"
            "<p style='color:#9aa5b1'>Software livre sob a licença GNU GPL v3. Feito com Qt for Python "
            "(PySide6, LGPLv3), moderngl, NumPy, Shapely e ezdxf.</p>")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setOpenExternalLinks(True)

        text = QVBoxLayout()
        text.addWidget(title)
        text.addWidget(version)
        text.addWidget(tagline)
        text.addSpacing(10)
        text.addWidget(body)
        text.addStretch()
        row = QHBoxLayout(w)
        row.setContentsMargins(16, 16, 16, 16)
        row.setSpacing(18)
        row.addWidget(icon)
        row.addLayout(text, 1)
        return w

    def _system_tab(self, gl_info) -> QWidget:
        w = QWidget()
        info = system_info(gl_info)
        view = QPlainTextEdit(info)
        view.setReadOnly(True)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        copy = QPushButton("Copiar para a área de transferência")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(info))
        hint = QLabel("Inclua estas informações ao relatar um problema.")
        hint.setStyleSheet("color: #9aa5b1;")
        layout = QVBoxLayout(w)
        layout.addWidget(view)
        row = QHBoxLayout()
        row.addWidget(hint, 1)
        row.addWidget(copy)
        layout.addLayout(row)
        return w

    def _licenses_tab(self) -> QWidget:
        w = QWidget()
        notices = _find("THIRD_PARTY_NOTICES.txt")
        license_file = _find("LICENSE", "LICENSE.txt")
        text = notices.read_text(encoding="utf-8") if notices else "Avisos de terceiros não encontrados."
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        row = QHBoxLayout()
        if license_file:
            b = QPushButton("Ver licença do LeafDraw (GPL v3)")
            b.clicked.connect(lambda: view.setPlainText(license_file.read_text(encoding="utf-8")))
            row.addWidget(b)
        if notices:
            b = QPushButton("Avisos de terceiros")
            b.clicked.connect(lambda: view.setPlainText(text))
            row.addWidget(b)
        folder = _find("licenses")
        if folder:
            b = QPushButton("Abrir pasta de licenças")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
            row.addWidget(b)
        row.addStretch()
        layout = QVBoxLayout(w)
        layout.addWidget(view)
        layout.addLayout(row)
        return w
