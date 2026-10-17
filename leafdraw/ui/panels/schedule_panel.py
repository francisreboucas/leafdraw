"""Quantitativos: tabela de espécies e áreas, atualizada com o desenho."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from leafdraw.core.schedule import area_schedule, plant_schedule

ROLE_ID = Qt.ItemDataRole.UserRole
COLUMNS = ["Espécie", "Nome científico", "Origem", "Isoladas", "Maciço", "Área (m²)", "Total"]


def _n(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class SchedulePanel(QWidget):
    exportRequested = Signal()
    speciesSelected = Signal(str)  # duplo clique: selecionar no desenho

    def __init__(self, doc, catalog, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.catalog = catalog
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._on_double)

        self.summary = QLabel()
        export = QPushButton("Exportar CSV…")
        export.clicked.connect(self.exportRequested)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(export)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.tree)
        layout.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        for sig in (doc.entityAdded, doc.entityRemoved, doc.entityChanged, doc.documentReset):
            sig.connect(self._schedule)
        self.refresh()

    def _schedule(self, *_):
        if self.isVisible():
            self._timer.start()
        else:
            self._stale = True

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_stale", False):
            self._stale = False
            self.refresh()

    def refresh(self):
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        plants = plant_schedule(self.doc, self.catalog)
        cat = None
        for r in plants:
            if r.categoria != cat:
                cat = r.categoria
                head = QTreeWidgetItem([cat or "Sem categoria"])
                head.setFont(0, bold)
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(head)
            it = QTreeWidgetItem([r.nome_popular, r.nome_cientifico, r.origem, str(r.individual or ""),
                                  str(r.massed or ""), _n(r.massed_area) if r.massed_area else "", str(r.total)])
            it.setData(0, ROLE_ID, r.species)
            f = QFont(self.tree.font())
            f.setItalic(True)
            it.setFont(1, f)
            for c in range(3, len(COLUMNS)):
                it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(it)
        areas = area_schedule(self.doc)
        if areas:
            head = QTreeWidgetItem(["Revestimentos (hachuras)"])
            head.setFont(0, bold)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for a in areas:
                it = QTreeWidgetItem([a.label, f"{a.count} hachura(s)", "", "", "", _n(a.area), ""])
                it.setTextAlignment(5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tree.addTopLevelItem(it)
        total = sum(r.total for r in plants)
        self.summary.setText(f"{len(plants)} espécie(s) · {total} muda(s)")

    def _on_double(self, it, _col):
        sid = it.data(0, ROLE_ID)
        if sid:
            self.speciesSelected.emit(sid)
