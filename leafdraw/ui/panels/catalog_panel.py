"""Gerenciador de Objetos: catálogo de plantas com busca e arrastar-e-soltar."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from leafdraw.ui.symbols import species_icon
from leafdraw.ui.viewport2d import SPECIES_MIME

ROLE_ID = Qt.ItemDataRole.UserRole


def fmt_m(v: float) -> str:
    return f"{v:.1f} m".replace(".", ",")


class SpeciesTree(QTreeWidget):
    def startDrag(self, actions):
        it = self.currentItem()
        sid = it.data(0, ROLE_ID) if it else None
        if not sid:
            return
        mime = QMimeData()
        mime.setData(SPECIES_MIME, QByteArray(sid.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(it.icon(0).pixmap(40, 40))
        drag.exec(Qt.DropAction.CopyAction)


class CatalogPanel(QWidget):
    speciesActivated = Signal(str)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar espécie…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)

        self.tree = SpeciesTree()
        self.tree.setHeaderLabels(["Espécie", "Altura", "Copa"])
        self.tree.setIconSize(QSize(24, 24))
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.currentItemChanged.connect(self._show_details)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._activate(it))

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setMinimumHeight(70)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.insert_btn = QPushButton("Inserir no desenho")
        self.insert_btn.setEnabled(False)
        self.insert_btn.clicked.connect(lambda: self._activate(self.tree.currentItem()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.details)
        layout.addWidget(self.insert_btn)
        self._populate()

    def _populate(self):
        bold = QFont(self.tree.font())
        bold.setBold(True)
        for cat in self.catalog.categories():
            group = QTreeWidgetItem([cat])
            group.setFont(0, bold)
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            for sp in sorted((s for s in self.catalog.all() if s.categoria == cat), key=lambda s: s.nome_popular):
                it = QTreeWidgetItem([sp.nome_popular, fmt_m(sp.altura), fmt_m(sp.copa)])
                it.setData(0, ROLE_ID, sp.id)
                it.setIcon(0, species_icon(sp.simbolo, sp.cor))
                it.setToolTip(0, sp.nome_cientifico)
                for col in (1, 2):
                    it.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                group.addChild(it)
        self.tree.expandAll()
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)

    def _filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            visible = 0
            for j in range(group.childCount()):
                it = group.child(j)
                sp = self.catalog.get(it.data(0, ROLE_ID))
                match = not text or text in sp.nome_popular.lower() or text in sp.nome_cientifico.lower()
                it.setHidden(not match)
                visible += match
            group.setHidden(visible == 0)

    def _show_details(self, it, _prev=None):
        sp = self.catalog.get(it.data(0, ROLE_ID)) if it else None
        self.insert_btn.setEnabled(sp is not None)
        if sp is None:
            self.details.clear()
            return
        self.details.setText(
            f"<b>{sp.nome_popular}</b> — <i>{sp.nome_cientifico}</i><br>"
            f"Altura {fmt_m(sp.altura)} · Copa {fmt_m(sp.copa)} · {sp.insolacao}<br>"
            f"<span style='color:#9aa5b1'>{sp.notas}</span>"
        )

    def _activate(self, it):
        sid = it.data(0, ROLE_ID) if it else None
        if sid:
            self.speciesActivated.emit(sid)
