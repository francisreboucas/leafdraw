"""Gerenciador de Objetos: catálogo de plantas com busca e arrastar-e-soltar."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from leafdraw.ui.symbols import elevation_pixmap, plan_pixmap, sp_icon
from leafdraw.ui.viewport2d import SPECIES_MIME

ROLE_ID = Qt.ItemDataRole.UserRole
PREVIEW = 72  # px das prévias Planta/Vista


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
    # (id da espécie, modo: "plant" | "planting" | "plantrow")
    speciesActivated = Signal(str, str)
    editRequested = Signal()

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
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._activate("plant"))

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setMinimumHeight(70)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # as duas versões da espécie: Planta (vista de cima) e Vista (de frente, usada nas elevações)
        self.versions = QWidget()
        vrow = QHBoxLayout(self.versions)
        vrow.setContentsMargins(0, 0, 0, 0)
        self.plan_preview, self.elev_preview = QLabel(), QLabel()
        for title, lab in (("Planta", self.plan_preview), ("Vista", self.elev_preview)):
            box = QVBoxLayout()
            lab.setFixedSize(PREVIEW, PREVIEW)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet("background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);")
            cap = QLabel(title)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet("color: #9aa5b1;")
            box.addWidget(lab, 0, Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(cap)
            vrow.addLayout(box)
        vrow.addStretch()
        self.versions.hide()

        self.mode_buttons = []
        row = QHBoxLayout()
        for mode, text, tip in (("plant", "Isolada", "Inserir plantas isoladas (duplo clique ou arrastar)"),
                                ("planting", "Maciço", "Plantar uma área fechada em malha [MAC]"),
                                ("plantrow", "Em linha", "Distribuir ao longo de uma linha [LIN]")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setEnabled(False)
            b.clicked.connect(lambda _c=False, m=mode: self._activate(m))
            row.addWidget(b)
            self.mode_buttons.append(b)
        edit = QPushButton("Editar catálogo…")
        edit.clicked.connect(self.editRequested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.versions)
        layout.addWidget(self.details)
        layout.addLayout(row)
        layout.addWidget(edit)
        self.populate()

    def populate(self, select: str | None = None):
        current = select or self.current_species()
        self.tree.clear()
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
                it.setIcon(0, sp_icon(sp))
                it.setToolTip(0, sp.nome_cientifico)
                for col in (1, 2):
                    it.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                group.addChild(it)
                if sp.id == current:
                    self.tree.setCurrentItem(it)
        self.tree.expandAll()
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
        self._filter(self.search.text())

    def current_species(self) -> str | None:
        it = self.tree.currentItem()
        return it.data(0, ROLE_ID) if it else None

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
        sp = self.catalog.get(it.data(0, ROLE_ID)) if it and it.data(0, ROLE_ID) else None
        for b in self.mode_buttons:
            b.setEnabled(sp is not None)
        if sp is None:
            self.details.clear()
            self.versions.hide()
            return
        self.plan_preview.setPixmap(plan_pixmap(sp.simbolo, sp.cor, PREVIEW - 8, sp.desenho_planta))
        self.elev_preview.setPixmap(elevation_pixmap(sp, PREVIEW - 8, PREVIEW - 8))
        self.versions.show()
        origin = self.catalog.origin(sp.id)
        tag = f" <span style='color:#e0b050'>[{origin}]</span>" if origin != "embutida" else ""
        self.details.setText(
            f"<b>{sp.nome_popular}</b> — <i>{sp.nome_cientifico}</i>{tag}<br>"
            f"Altura {fmt_m(sp.altura)} · Copa {fmt_m(sp.copa)} · {sp.insolacao}<br>"
            f"<span style='color:#9aa5b1'>{sp.notas}</span>"
        )

    def _activate(self, mode: str):
        sid = self.current_species()
        if sid:
            self.speciesActivated.emit(sid, mode)
