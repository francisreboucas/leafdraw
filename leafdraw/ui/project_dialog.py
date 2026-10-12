"""Dados do projeto exibidos no carimbo das folhas."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit

from leafdraw.core.sheets import PROJECT_FIELDS


class ProjectDialog(QDialog):
    def __init__(self, info: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dados do projeto")
        self.setMinimumWidth(460)
        self.edits: dict[str, QLineEdit] = {}
        form = QFormLayout(self)
        for key, label in PROJECT_FIELDS:
            e = QLineEdit(info.get(key, ""))
            if key == "data":
                e.setPlaceholderText("vazio = data de hoje")
            if key == "revisao":
                e.setPlaceholderText("00")
            self.edits[key] = e
            form.addRow(label, e)
        form.addRow(QLabel("Esses dados aparecem no carimbo de todas as folhas."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict[str, str]:
        return {k: e.text().strip() for k, e in self.edits.items() if e.text().strip()}
