"""Editor do catálogo de espécies (cria, edita, duplica e remove espécies do usuário)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)

from leafdraw.core.catalog import SYMBOLS, Species
from leafdraw.ui.icons import color_icon
from leafdraw.ui.symbols import species_icon

ROLE_ID = Qt.ItemDataRole.UserRole
INSOLACAO = ["Pleno sol", "Pleno sol a meia-sombra", "Meia-sombra", "Sombra"]


def _spin(maximum: float) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0.05, maximum)
    s.setDecimals(2)
    s.setSingleStep(0.1)
    s.setSuffix(" m")
    return s


class CatalogDialog(QDialog):
    def __init__(self, catalog, parent=None, select: str | None = None, in_use: set[str] = frozenset()):
        super().__init__(parent)
        self.in_use = set(in_use)
        self.setWindowTitle("Catálogo de espécies")
        self.resize(820, 520)
        self.catalog = catalog
        self.changed = False
        self._current: str | None = None
        self._color = "#6cc070"

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.search)
        lv.addWidget(self.list)
        lrow = QHBoxLayout()
        for text, slot in (("Nova", self._new), ("Duplicar", self._duplicate)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            lrow.addWidget(b)
        self.remove_btn = QPushButton("Excluir")
        self.remove_btn.clicked.connect(self._remove)
        lrow.addWidget(self.remove_btn)
        lv.addLayout(lrow)

        self.origin = QLabel()
        self.origin.setStyleSheet("color: #9aa5b1;")
        self.f_popular = QLineEdit()
        self.f_cientifico = QLineEdit()
        self.f_categoria = QComboBox()
        self.f_categoria.setEditable(True)
        self.f_categoria.addItems(catalog.categories())
        self.f_altura = _spin(120)
        self.f_copa = _spin(60)
        self.f_cor = QPushButton()
        self.f_cor.clicked.connect(self._pick_color)
        self.f_simbolo = QComboBox()
        for key, name in SYMBOLS.items():
            self.f_simbolo.addItem(name, key)
        self.f_insol = QComboBox()
        self.f_insol.setEditable(True)
        self.f_insol.addItems(INSOLACAO)
        self.f_notas = QPlainTextEdit()
        self.f_notas.setFixedHeight(70)
        self.save_btn = QPushButton("Salvar espécie")
        self.save_btn.clicked.connect(self._save)

        form = QFormLayout()
        form.addRow("", self.origin)
        form.addRow("Nome popular", self.f_popular)
        form.addRow("Nome científico", self.f_cientifico)
        form.addRow("Categoria", self.f_categoria)
        form.addRow("Altura adulta", self.f_altura)
        form.addRow("Diâmetro da copa", self.f_copa)
        form.addRow("Cor do símbolo", self.f_cor)
        form.addRow("Símbolo", self.f_simbolo)
        form.addRow("Insolação", self.f_insol)
        form.addRow("Notas", self.f_notas)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addLayout(form)
        rv.addStretch()
        rv.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([300, 520])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(split)
        layout.addWidget(QLabel("Espécies novas ou editadas ficam no seu catálogo e valem para todos os projetos. "
                                "O catálogo que acompanha o LeafDraw não é alterado."))
        layout.addWidget(buttons)
        self._populate(select)

    # --- lista ------------------------------------------------------------

    def _populate(self, select: str | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for sp in sorted(self.catalog.all(), key=lambda s: (s.categoria, s.nome_popular)):
            it = QListWidgetItem(species_icon(sp.simbolo, sp.cor), f"{sp.nome_popular}  —  {sp.categoria}")
            it.setData(ROLE_ID, sp.id)
            it.setToolTip(sp.nome_cientifico)
            self.list.addItem(it)
            if sp.id == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._on_select(self.list.currentItem())
        self._filter(self.search.text())

    def _filter(self, text: str):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            sp = self.catalog.get(it.data(ROLE_ID))
            it.setHidden(bool(t) and t not in sp.nome_popular.lower() and t not in sp.nome_cientifico.lower())

    def _on_select(self, it, _prev=None):
        sp = self.catalog.get(it.data(ROLE_ID)) if it else None
        self._current = sp.id if sp else None
        if sp is None:
            return
        self._load(sp)

    def _load(self, sp: Species):
        origin = self.catalog.origin(sp.id) or "nova"
        self.origin.setText(f"Origem: {origin} · id {sp.id}")
        self.f_popular.setText(sp.nome_popular)
        self.f_cientifico.setText(sp.nome_cientifico)
        self.f_categoria.setCurrentText(sp.categoria)
        self.f_altura.setValue(sp.altura)
        self.f_copa.setValue(sp.copa)
        self._set_color(sp.cor)
        self.f_simbolo.setCurrentIndex(list(SYMBOLS).index(sp.simbolo))
        self.f_insol.setCurrentText(sp.insolacao)
        self.f_notas.setPlainText(sp.notas)
        removable = self.catalog.can_remove(sp.id)  # embutidas e de projeto não são excluídas
        self.remove_btn.setEnabled(removable)
        self.remove_btn.setText("Restaurar original" if origin == "editada" else "Excluir")

    def _set_color(self, color: str):
        self._color = color
        self.f_cor.setIcon(color_icon(color, 16))
        self.f_cor.setText(color)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Cor do símbolo")
        if c.isValid():
            self._set_color(c.name())

    # --- ações ------------------------------------------------------------

    def _form_species(self, sid: str) -> Species | None:
        popular = self.f_popular.text().strip()
        cientifico = self.f_cientifico.text().strip()
        categoria = self.f_categoria.currentText().strip()
        if not popular or not cientifico or not categoria:
            QMessageBox.warning(self, "Catálogo", "Preencha nome popular, nome científico e categoria.")
            return None
        return Species(id=sid, nome_popular=popular, nome_cientifico=cientifico, categoria=categoria,
                       altura=self.f_altura.value(), copa=self.f_copa.value(), cor=self._color,
                       simbolo=self.f_simbolo.currentData(), insolacao=self.f_insol.currentText().strip(),
                       notas=self.f_notas.toPlainText().strip())

    def _save(self):
        if self._current is None:
            return
        sp = self._form_species(self._current)
        if sp is None or sp == self.catalog.get(self._current):
            return
        self.catalog.upsert(sp)
        self.changed = True
        self._populate(sp.id)

    def _new(self):
        sp = Species(id=self.catalog.new_id("nova especie"), nome_popular="Nova espécie",
                     nome_cientifico="Genus species", categoria=self.f_categoria.currentText() or "Árvores",
                     altura=3.0, copa=2.0, cor="#6cc070")
        self.catalog.upsert(sp)
        self.changed = True
        self._populate(sp.id)
        self.f_popular.setFocus()
        self.f_popular.selectAll()

    def _duplicate(self):
        if self._current is None:
            return
        src = self.catalog.get(self._current)
        sp = replace(src, id=self.catalog.new_id(src.nome_cientifico), nome_popular=f"{src.nome_popular} (cópia)")
        self.catalog.upsert(sp)
        self.changed = True
        self._populate(sp.id)

    def _remove(self):
        if self._current is None or not self.catalog.can_remove(self._current):
            return
        sp = self.catalog.get(self._current)
        edited = self.catalog.origin(sp.id) == "editada"
        q = (f"Restaurar {sp.nome_popular} para a versão original do catálogo?" if edited
             else f"Excluir {sp.nome_popular} do seu catálogo? Plantas já desenhadas continuam no projeto.")
        if QMessageBox.question(self, "Catálogo", q) != QMessageBox.StandardButton.Yes:
            return
        self.catalog.remove(sp.id, keep_for_project=sp.id in self.in_use)
        self.changed = True
        self._populate(sp.id if edited else None)
