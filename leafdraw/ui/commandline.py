"""Linha de comando no estilo AutoCAD: histórico, prompt e campo de entrada."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout, QWidget

COLORS = {"info": "#c8d0d8", "cmd": "#8fb8ff", "error": "#ff7b7b", "result": "#9fe09f"}


class CommandLine(QWidget):
    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        mono = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setFont(mono)
        self.history.setFixedHeight(64)
        self.history.document().setMaximumBlockCount(500)
        self.prompt = QLabel()
        self.prompt.setFont(mono)
        self.prompt.setStyleSheet("color: #ffd23f;")
        self.edit = QLineEdit()
        self.edit.setFont(mono)
        self.edit.setFrame(False)
        self.edit.setPlaceholderText("digite um comando ou coordenada (ex.: L, @3,4, 5<45)")
        self.edit.installEventFilter(self)
        self.edit.returnPressed.connect(self._submit)
        self._recent: list[str] = []
        self._recent_pos = 0

        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 2)
        row.addWidget(self.prompt)
        row.addWidget(self.edit, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.history)
        layout.addLayout(row)

    def set_prompt(self, text: str):
        self.prompt.setText(text + (":" if text and not text.endswith(":") else ""))

    def log(self, text: str, kind: str = "info"):
        color = COLORS.get(kind, COLORS["info"])
        self.history.append(f"<span style='color:{color}'>{html.escape(text)}</span>")
        sb = self.history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def inject(self, text: str):
        """Recebe teclas digitadas no viewport."""
        if text == "\n":
            self._submit()
            return
        self.edit.setFocus()
        self.edit.insert(text)

    def _submit(self):
        text = self.edit.text()
        self.edit.clear()
        if text.strip():
            self._recent.append(text)
            self._recent_pos = len(self._recent)
        self.submitted.emit(text)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            key = ev.key()
            if key == Qt.Key.Key_Escape:
                self.edit.clear()
                self.cancelled.emit()
                return True
            if key == Qt.Key.Key_Space:  # como no AutoCAD, espaço confirma
                self._submit()
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._recent:
                step = -1 if key == Qt.Key.Key_Up else 1
                self._recent_pos = max(0, min(len(self._recent), self._recent_pos + step))
                self.edit.setText(self._recent[self._recent_pos] if self._recent_pos < len(self._recent) else "")
                return True
        return super().eventFilter(obj, ev)
