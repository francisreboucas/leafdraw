"""Editor do catálogo de espécies (cria, edita, duplica e remove espécies do usuário)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from leafdraw.core.catalog import ORIGENS, SYMBOLS, Species
from leafdraw.core.dxf_io import dwg_supported, read_drawing
from leafdraw.core.gltf import cached_model
from leafdraw.core.symbol_blocks import MODEL_SPACE, block_drawing, list_blocks
from leafdraw.ui.icons import color_icon
from leafdraw.ui.symbols import elevation_pixmap, plan_pixmap, sp_icon

ROLE_ID = Qt.ItemDataRole.UserRole
PREVIEW = 84
WHOLE_DRAWING = "(desenho inteiro)"
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
        self._drawings: dict[str, object] = {"planta": None, "vista": None}  # blocos próprios do formulário

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
        self.f_origem = QComboBox()
        for key, name in ORIGENS.items():
            self.f_origem.addItem(name, key)
        self.f_insol = QComboBox()
        self.f_insol.setEditable(True)
        self.f_insol.addItems(INSOLACAO)
        self.f_notas = QPlainTextEdit()
        self.f_notas.setFixedHeight(70)
        self.version_rows = {kind: self._version_row(kind) for kind in ("planta", "vista")}
        self.f_modelo = QLineEdit()
        self.f_modelo.setPlaceholderText("Automático (forma do símbolo)")
        self.f_modelo.setClearButtonEnabled(True)
        self.f_modelo.setToolTip("Modelo glTF 2.0 (.glb) usado na vista 3D. É ajustado à copa e à altura "
                                 "da espécie; a base do modelo fica no chão.")
        self.f_modelo.textChanged.connect(self._update_model_status)
        self.model_status = QLabel()
        self.model_status.setStyleSheet("color: #9aa5b1;")
        pick_model = QPushButton("Escolher…")
        pick_model.clicked.connect(self._pick_model)
        model_row = QWidget()
        mr = QHBoxLayout(model_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.addWidget(self.f_modelo, 1)
        mr.addWidget(pick_model)
        for w in (self.f_altura, self.f_copa):
            w.valueChanged.connect(self._update_previews)
        self.f_simbolo.currentIndexChanged.connect(self._update_previews)
        self.save_btn = QPushButton("Salvar espécie")
        self.save_btn.clicked.connect(self._save)

        form = QFormLayout()
        form.addRow("", self.origin)
        form.addRow("Nome popular", self.f_popular)
        form.addRow("Nome científico", self.f_cientifico)
        form.addRow("Categoria", self.f_categoria)
        form.addRow("Origem", self.f_origem)
        form.addRow("Altura adulta", self.f_altura)
        form.addRow("Diâmetro da copa", self.f_copa)
        form.addRow("Cor do símbolo", self.f_cor)
        form.addRow("Símbolo", self.f_simbolo)
        form.addRow("Versão Planta", self.version_rows["planta"][0])
        form.addRow("Versão Vista", self.version_rows["vista"][0])
        form.addRow("Modelo 3D", model_row)
        form.addRow("", self.model_status)
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
            it = QListWidgetItem(sp_icon(sp), f"{sp.nome_popular}  —  {sp.categoria}")
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
        self.origin.setText(f"Fonte: {origin} · id {sp.id}")
        self.f_popular.setText(sp.nome_popular)
        self.f_cientifico.setText(sp.nome_cientifico)
        self.f_categoria.setCurrentText(sp.categoria)
        self.f_origem.setCurrentIndex(list(ORIGENS).index(sp.origem))
        self.f_altura.setValue(sp.altura)
        self.f_copa.setValue(sp.copa)
        self._set_color(sp.cor)
        self.f_simbolo.setCurrentIndex(list(SYMBOLS).index(sp.simbolo))
        self._drawings = {"planta": sp.desenho_planta, "vista": sp.desenho_vista}
        self._update_previews()
        self.f_modelo.setText(sp.modelo_3d)
        self.f_insol.setCurrentText(sp.insolacao)
        self.f_notas.setPlainText(sp.notas)
        removable = self.catalog.can_remove(sp.id)  # embutidas e de projeto não são excluídas
        self.remove_btn.setEnabled(removable)
        self.remove_btn.setText("Restaurar original" if origin == "editada" else "Excluir")

    def _set_color(self, color: str):
        self._color = color
        self.f_cor.setIcon(color_icon(color, 16))
        self.f_cor.setText(color)
        self._update_previews()

    # --- versões Planta e Vista ---------------------------------------------

    def _version_row(self, kind: str):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        preview = QLabel()
        preview.setFixedSize(PREVIEW, PREVIEW)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet("background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);")
        status = QLabel()
        status.setStyleSheet("color: #9aa5b1;")
        imp = QPushButton("Importar bloco…")
        imp.setToolTip("Usa um bloco de um arquivo DXF/DWG como desenho desta versão. "
                       + ("A Planta é ajustada ao diâmetro da copa." if kind == "planta"
                          else "A Vista é ajustada à copa (largura) e à altura; a base do bloco fica no chão."))
        imp.clicked.connect(lambda: self._import_block(kind))
        auto = QPushButton("Automático")
        auto.setToolTip("Volta ao desenho gerado pelo tipo de símbolo, altura e copa")
        auto.clicked.connect(lambda: self._set_drawing(kind, None))
        buttons = QVBoxLayout()
        buttons.addWidget(status)
        buttons.addWidget(imp)
        buttons.addWidget(auto)
        buttons.addStretch()
        row.addWidget(preview)
        row.addLayout(buttons)
        row.addStretch()
        return w, preview, status, auto

    def _preview_species(self) -> Species:
        return Species(id=self._current or "preview", nome_popular="", nome_cientifico="", categoria="",
                       altura=self.f_altura.value(), copa=self.f_copa.value(), cor=self._color,
                       simbolo=self.f_simbolo.currentData() or "arvore",
                       desenho_planta=self._drawings["planta"], desenho_vista=self._drawings["vista"])

    def _update_previews(self, *_):
        if not hasattr(self, "version_rows"):
            return
        sp = self._preview_species()
        size = PREVIEW - 8
        pixmaps = {"planta": plan_pixmap(sp.simbolo, sp.cor, size, sp.desenho_planta),
                   "vista": elevation_pixmap(sp, size, size)}
        for kind, (_w, preview, status, auto) in self.version_rows.items():
            preview.setPixmap(pixmaps[kind])
            custom = self._drawings[kind] is not None
            status.setText("Bloco importado" if custom else "Automático")
            auto.setEnabled(custom)

    def _set_drawing(self, kind: str, drawing):
        self._drawings[kind] = drawing
        self._update_previews()

    def _import_block(self, kind: str):
        filt = "Desenhos CAD (*.dxf *.dwg)" if dwg_supported() else "DXF (*.dxf)"
        path, _ = QFileDialog.getOpenFileName(self, f"Bloco da versão {kind.capitalize()}", "", filt)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            drawing = read_drawing(path)
            blocks = list_blocks(drawing)
        except Exception as exc:
            QMessageBox.warning(self, "Importar bloco", f"Não foi possível ler o arquivo:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        choice, ok = QInputDialog.getItem(self, "Importar bloco",
                                          f"Bloco para a versão {kind.capitalize()}:",
                                          blocks + [WHOLE_DRAWING], 0, False)
        if not ok:
            return
        try:
            result = block_drawing(drawing, MODEL_SPACE if choice == WHOLE_DRAWING else choice, kind)
        except ValueError as exc:
            QMessageBox.warning(self, "Importar bloco", str(exc))
            return
        self._set_drawing(kind, result)

    # --- modelo 3D ----------------------------------------------------------

    def _pick_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Modelo 3D da espécie", "", "glTF 2.0 (*.glb *.gltf)")
        if path:
            self.f_modelo.setText(path)

    def _update_model_status(self, *_):
        text = self.f_modelo.text().strip()
        if not text:
            self.model_status.setText("")
            return
        probe = Species(id="probe", nome_popular="", nome_cientifico="", categoria="", altura=1, copa=1,
                        cor="#000000", modelo_3d=text)
        path = self.catalog.model_file(probe)
        if path is None:
            self.model_status.setText("Arquivo não encontrado")
            return
        model, err = cached_model(path)
        if model is None:
            self.model_status.setText(err)
            return
        w, d, h = model.size
        textured = any(p.material.image for p in model.primitives)
        self.model_status.setText(f"{model.triangles:,} triângulos · {w:.2f} × {d:.2f} × {h:.2f} (original)"
                                  .replace(",", ".") + (" · com textura" if textured else ""))

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
                       origem=self.f_origem.currentData(),
                       notas=self.f_notas.toPlainText().strip(), desenho_planta=self._drawings["planta"],
                       desenho_vista=self._drawings["vista"], modelo_3d=self.f_modelo.text().strip())

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
