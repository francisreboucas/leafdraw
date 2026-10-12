from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QHBoxLayout, QHeaderView, QMessageBox,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from leafdraw.ui.icons import color_icon, icon

COL_CUR, COL_NAME, COL_VIS, COL_LOCK, COL_COLOR = range(5)
ROLE_ID = Qt.ItemDataRole.UserRole


class LayersPanel(QWidget):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._updating = False

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Nome", "Vis.", "Bloq.", "Cor"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (COL_CUR, COL_VIS, COL_LOCK, COL_COLOR):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for name, tip, slot in (("layer_add", "Nova camada", self._add),
                                ("layer_remove", "Excluir camada", self._remove),
                                ("layer_current", "Tornar atual", self._make_current)):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addWidget(self.tree)

        for sig in (doc.layersChanged, doc.currentLayerChanged, doc.documentReset):
            sig.connect(self._schedule_rebuild)
        self.rebuild()

    def _schedule_rebuild(self, *_):
        # adiado: o sinal pode vir de dentro de um slot da própria árvore
        QTimer.singleShot(0, self.rebuild)

    def rebuild(self):
        self._updating = True
        selected = self._selected_id()
        self.tree.clear()
        for layer in self.doc.layers.values():
            it = QTreeWidgetItem()
            it.setData(COL_CUR, ROLE_ID, layer.id)
            current = layer.id == self.doc.current_layer
            it.setText(COL_CUR, "●" if current else "")
            it.setText(COL_NAME, layer.name)
            it.setToolTip(COL_CUR, "Camada atual" if current else "Duplo clique para tornar atual")
            it.setCheckState(COL_VIS, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            it.setCheckState(COL_LOCK, Qt.CheckState.Checked if layer.locked else Qt.CheckState.Unchecked)
            it.setIcon(COL_COLOR, color_icon(layer.color))
            it.setToolTip(COL_COLOR, "Duplo clique para mudar a cor")
            if layer.id != "0":
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            if current:
                font = QFont(it.font(COL_NAME))
                font.setBold(True)
                it.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(it)
            if layer.id == selected:
                it.setSelected(True)
        self._updating = False

    def _selected_id(self) -> str | None:
        it = self.tree.currentItem()
        return it.data(COL_CUR, ROLE_ID) if it else None

    def _on_item_changed(self, it, col):
        if self._updating:
            return
        lid = it.data(COL_CUR, ROLE_ID)
        if col == COL_NAME:
            try:
                self.doc.rename_layer(lid, it.text(COL_NAME))
            except ValueError as exc:
                QMessageBox.warning(self, "Camadas", str(exc))
                self._schedule_rebuild()
        elif col == COL_VIS:
            self.doc.update_layer(lid, visible=it.checkState(COL_VIS) == Qt.CheckState.Checked)
        elif col == COL_LOCK:
            self.doc.update_layer(lid, locked=it.checkState(COL_LOCK) == Qt.CheckState.Checked)

    def _on_double_click(self, it, col):
        lid = it.data(COL_CUR, ROLE_ID)
        if col == COL_COLOR:
            color = QColorDialog.getColor(QColor(self.doc.layers[lid].color), self, "Cor da camada")
            if color.isValid():
                self.doc.update_layer(lid, color=color.name())
        elif col == COL_NAME and lid != "0":
            self.tree.editItem(it, COL_NAME)
        elif col in (COL_CUR, COL_NAME):
            self.doc.set_current_layer(lid)

    def _add(self):
        layer = self.doc.add_layer()
        self.doc.set_current_layer(layer.id)

    def _remove(self):
        lid = self._selected_id()
        if lid is None:
            return
        ok, reason = self.doc.can_remove_layer(lid)
        if not ok:
            QMessageBox.information(self, "Camadas", reason)
            return
        self.doc.remove_layer(lid)

    def _make_current(self):
        lid = self._selected_id()
        if lid:
            self.doc.set_current_layer(lid)
