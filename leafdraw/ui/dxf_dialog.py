"""Diálogo de opções da importação DXF/DWG."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QVBoxLayout)

from leafdraw.core.dxf_io import UNIT_NAMES
from leafdraw.core.entities import KIND_NAMES

UNIT_CHOICES = [("milímetros", 0.001), ("centímetros", 0.01), ("metros", 1.0), ("polegadas", 0.0254),
                ("pés", 0.3048)]
FAR_FROM_ORIGIN_M = 10_000.0


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class DxfImportDialog(QDialog):
    def __init__(self, path: str, imp, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar desenho")
        self.imp = imp
        self.bounds = imp.bounds()

        counts: dict[str, int] = {}
        for e in imp.entities:
            counts[e.kind] = counts.get(e.kind, 0) + 1
        summary = ", ".join(f"{n} {KIND_NAMES.get(k, k).lower()}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        detected = UNIT_NAMES.get(imp.insunits, "não definida")

        form = QFormLayout()
        form.addRow("Arquivo:", QLabel(os.path.basename(path)))
        info = QLabel(f"{len(imp.entities)} objetos ({summary or 'nenhum'})")
        info.setWordWrap(True)
        form.addRow("Conteúdo:", info)
        form.addRow("Camadas novas:", QLabel(str(len(imp.layers))))
        if imp.skipped:
            sk = QLabel(", ".join(f"{n}× {t}" for t, n in imp.skipped.most_common()))
            sk.setWordWrap(True)
            sk.setStyleSheet("color: #e0b050;")
            form.addRow("Ignorados:", sk)
        form.addRow("Unidade no arquivo:", QLabel(detected))

        self.unit = QComboBox()
        guess = imp.guess_factor()
        for i, (name, f) in enumerate(UNIT_CHOICES):
            self.unit.addItem(name, f)
            if abs(f - guess) < 1e-12:
                self.unit.setCurrentIndex(i)
        self.unit.currentIndexChanged.connect(self._update_size)
        form.addRow("Interpretar como:", self.unit)
        self.size = QLabel()
        form.addRow("Tamanho resultante:", self.size)

        self.to_origin = QCheckBox("Trazer o desenho para perto da origem")
        self.lock = QCheckBox("Bloquear as camadas importadas (usar como referência)")
        form.addRow(self.to_origin)
        form.addRow(self.lock)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Importar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._update_size()

    def factor(self) -> float:
        return self.unit.currentData()

    def _update_size(self, *_):
        if self.bounds is None:
            self.size.setText("—")
            return
        f = self.factor()
        b = self.bounds
        self.size.setText(f"{_fmt((b[2] - b[0]) * f)} × {_fmt((b[3] - b[1]) * f)} m")
        far = max(abs(b[0]), abs(b[1]), abs(b[2]), abs(b[3])) * f > FAR_FROM_ORIGIN_M
        self.to_origin.setChecked(bool(far))
