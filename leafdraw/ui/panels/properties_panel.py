"""Propriedades da seleção atual. Edições geram comandos (desfazíveis)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from leafdraw.core.commands import ReplaceEntities
from leafdraw.core.entities import (HATCH_PATTERNS, KIND_NAMES, PLANTING_LAYOUTS, Arc, Circle, Contour, Dimension,
                                    ElevationView, Hatch, Line, Plant, PlantingArea, Polyline, SpotHeight, Text)
from leafdraw.ui.icons import color_icon
from leafdraw.ui.symbols import sp_icon


def fmt(v: float, unit: str = "m") -> str:
    return f"{v:,.2f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")


def _spin(value: float, minimum: float = 0.01, maximum: float = 10_000.0, suffix: str = " m",
          decimals: int = 2) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(0.1 if suffix == " m" else 1.0)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


def _angle_spin(value: float) -> QDoubleSpinBox:
    return _spin(value, -360.0, 360.0, "°", 1)


class PropertiesPanel(QWidget):
    def __init__(self, doc, catalog, view2d, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.catalog = catalog
        self.view = view2d
        self.header = QLabel()
        self.header.setStyleSheet("font-weight: bold; padding: 2px 0 6px 0;")
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.header)
        layout.addLayout(self.form)
        layout.addStretch()

        self._pending = False
        view2d.scene().selectionChanged.connect(self._schedule)
        doc.entityChanged.connect(self._on_entity_changed)
        doc.entityRemoved.connect(self._schedule)
        doc.layersChanged.connect(self._schedule)
        self.refresh()

    def _on_entity_changed(self, eid):
        if eid in self.view.selected_ids():
            self._schedule()

    def _schedule(self, *_):
        # agrupa várias notificações (ex.: seleção por janela) em uma atualização
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.refresh)

    def _push(self, new_entities, text):
        changed = [e for e in new_entities if e != self.doc.entities.get(e.id)]
        if changed:
            self.doc.undo_stack.push(ReplaceEntities(self.doc, changed, text))

    def refresh(self):
        self._pending = False
        while self.form.rowCount():
            self.form.removeRow(0)
        ids = [i for i in self.view.selected_ids() if i in self.doc.entities]
        if not ids:
            self.header.setText("Nenhum objeto selecionado")
            return
        ents = [self.doc.entities[i] for i in ids]
        self.header.setText(KIND_NAMES.get(ents[0].kind, ents[0].kind) if len(ents) == 1
                            else f"{len(ents)} objetos selecionados")
        self._layer_row(ents)
        self._color_row(ents)
        if all(isinstance(e, (Plant, PlantingArea)) for e in ents):
            self._species_row(ents)
        if len(ents) == 1:
            self._single(ents[0])
        else:
            plants = [e for e in ents if isinstance(e, Plant)]
            if plants:
                self.form.addRow("Plantas", QLabel(str(len(plants))))

    def _layer_row(self, ents):
        combo = QComboBox()
        layer_ids = list(self.doc.layers)
        for lid in layer_ids:
            combo.addItem(self.doc.layers[lid].name, lid)
        common = {e.layer for e in ents}
        if len(common) == 1 and next(iter(common)) in self.doc.layers:
            combo.setCurrentIndex(layer_ids.index(next(iter(common))))
        else:
            combo.setCurrentIndex(-1)
            combo.setPlaceholderText("(várias)")
        combo.activated.connect(lambda idx: self._push(
            [replace(e, layer=combo.itemData(idx)) for e in ents], "Mudar camada"))
        self.form.addRow("Camada", combo)

    def _color_row(self, ents):
        colors = {e.color for e in ents}
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if len(colors) > 1:
            btn.setText("(várias)")
        elif not next(iter(colors)):
            btn.setText("Por camada")
            btn.setIcon(color_icon(self.doc.layer_for(ents[0]).color))
        else:
            c = next(iter(colors))
            btn.setText(c)
            btn.setIcon(color_icon(c))
        menu = QMenu(btn)
        menu.addAction("Por camada", lambda: self._push([replace(e, color="") for e in ents], "Cor"))

        def choose():
            initial = QColor(ents[0].color or self.doc.layer_for(ents[0]).color)
            col = QColorDialog.getColor(initial, self, "Cor do objeto")
            if col.isValid():
                self._push([replace(e, color=col.name()) for e in ents], "Cor")

        menu.addAction("Escolher…", choose)
        btn.setMenu(menu)
        self.form.addRow("Cor", btn)

    def _species_row(self, ents):
        combo = QComboBox()
        species = sorted(self.catalog.all(), key=lambda s: s.nome_popular)
        for sp in species:
            combo.addItem(sp_icon(sp), sp.nome_popular, sp.id)
        common = {e.species for e in ents}
        ids = [sp.id for sp in species]
        if len(common) == 1 and next(iter(common)) in ids:
            combo.setCurrentIndex(ids.index(next(iter(common))))
        else:
            combo.setCurrentIndex(-1)
            combo.setPlaceholderText("(várias)")

        def change(idx):
            sp = self.catalog.get(combo.itemData(idx))
            new = [replace(e, species=sp.id, canopy=sp.copa, height=sp.altura) if isinstance(e, Plant)
                   else replace(e, species=sp.id) for e in ents]
            self._push(new, f"Trocar espécie para {sp.nome_popular}")

        combo.activated.connect(change)
        self.form.addRow("Espécie", combo)

    def _single(self, e):
        add = self.form.addRow
        if isinstance(e, Line):
            add("Comprimento", QLabel(fmt(e.length)))
            add("Ângulo", QLabel(f"{e.angle:.1f}°".replace(".", ",")))
        elif isinstance(e, ElevationView):
            name = QLineEdit(e.name)
            name.editingFinished.connect(
                lambda: name.text().strip() and self._push([replace(e, name=name.text().strip())], "Nome da vista"))
            add("Nome", name)
            flip = QPushButton("Olhar para o outro lado")
            flip.clicked.connect(lambda: self._push([replace(e, side=-e.side)], "Inverter vista"))
            add("Lado", flip)
            depth = _spin(e.depth, 0.0, 10_000)
            depth.setSpecialValueText("sem limite")
            depth.valueChanged.connect(lambda v: self._push([replace(e, depth=v)], "Profundidade da vista"))
            add("Profundidade", depth)
            datum = _spin(e.datum, -12000, 12000)
            datum.setToolTip("Cota que fica na base do desenho")
            datum.valueChanged.connect(lambda v: self._push([replace(e, datum=v)], "Cota de referência"))
            add("Cota da base", datum)
            th = _spin(e.text_height, maximum=50)
            th.valueChanged.connect(lambda v: self._push([replace(e, text_height=v)], "Altura do texto"))
            add("Altura do texto", th)
            add("Comprimento", QLabel(fmt(e.length)))
            item = self.view.items_by_id.get(e.id)
            data = getattr(item, "_data", None)
            if data is not None:
                add("Plantas na vista", QLabel(str(len(data.plants))))
        elif isinstance(e, SpotHeight):
            z = _spin(e.elevation, -12000, 12000)
            z.valueChanged.connect(lambda v: self._push([replace(e, elevation=v)], "Cota"))
            add("Cota", z)
            th = _spin(e.text_height, maximum=50)
            th.valueChanged.connect(lambda v: self._push([replace(e, text_height=v)], "Altura do texto"))
            add("Altura do texto", th)
        elif isinstance(e, Polyline):
            if isinstance(e, Contour):
                z = _spin(e.elevation, -12000, 12000)
                z.valueChanged.connect(lambda v: self._push([replace(e, elevation=v)], "Cota da curva"))
                add("Cota", z)
            add("Vértices", QLabel(str(len(e.vertices))))
            closed = QCheckBox()
            closed.setChecked(e.closed)
            closed.toggled.connect(lambda v: self._push([replace(e, closed=v)], "Fechar polilinha"))
            add("Fechada", closed)
            add("Perímetro" if e.closed else "Comprimento", QLabel(fmt(e.length)))
            if e.closed:
                add("Área", QLabel(fmt(e.area, "m²")))
        elif isinstance(e, Circle):
            r = _spin(e.radius)
            r.valueChanged.connect(lambda v: self._push([replace(e, radius=v)], "Raio"))
            add("Raio", r)
            add("Área", QLabel(fmt(e.area, "m²")))
        elif isinstance(e, Arc):
            r = _spin(e.radius)
            r.valueChanged.connect(lambda v: self._push([replace(e, radius=v)], "Raio"))
            add("Raio", r)
            a0 = _angle_spin(e.start)
            a0.valueChanged.connect(lambda v: self._push([replace(e, start=v % 360)], "Ângulo inicial"))
            add("Início", a0)
            a1 = _angle_spin(e.end)
            a1.valueChanged.connect(lambda v: self._push([replace(e, end=v % 360)], "Ângulo final"))
            add("Fim", a1)
            add("Comprimento", QLabel(fmt(e.length)))
        elif isinstance(e, Text):
            edit = QLineEdit(e.text.replace("\n", "\\n"))
            edit.setToolTip("Use \\n para quebrar linha")
            edit.editingFinished.connect(lambda: self._push(
                [replace(e, text=edit.text().replace("\\n", "\n"))], "Texto"))
            add("Texto", edit)
            h = _spin(e.height, maximum=100)
            h.valueChanged.connect(lambda v: self._push([replace(e, height=v)], "Altura do texto"))
            add("Altura", h)
            rot = _angle_spin(e.rotation)
            rot.valueChanged.connect(lambda v: self._push([replace(e, rotation=v)], "Rotação do texto"))
            add("Rotação", rot)
        elif isinstance(e, Dimension):
            add("Medida", QLabel(fmt(e.value)))
            h = _spin(e.text_height, maximum=100)
            h.valueChanged.connect(lambda v: self._push([replace(e, text_height=v)], "Altura do texto"))
            add("Altura do texto", h)
            dec = QSpinBox()
            dec.setRange(0, 4)
            dec.setValue(e.decimals)
            dec.valueChanged.connect(lambda v: self._push([replace(e, decimals=v)], "Casas decimais"))
            add("Casas decimais", dec)
            ov = QLineEdit(e.text_override)
            ov.setPlaceholderText("<> = medida")
            ov.editingFinished.connect(lambda: self._push([replace(e, text_override=ov.text())], "Texto da cota"))
            add("Texto", ov)
        elif isinstance(e, Hatch):
            combo = QComboBox()
            for key, name in HATCH_PATTERNS.items():
                combo.addItem(name, key)
            combo.setCurrentIndex(list(HATCH_PATTERNS).index(e.pattern) if e.pattern in HATCH_PATTERNS else 0)
            combo.activated.connect(lambda i: self._push([replace(e, pattern=combo.itemData(i))], "Padrão"))
            add("Padrão", combo)
            sc = _spin(e.scale, maximum=1000)
            sc.valueChanged.connect(lambda v: self._push([replace(e, scale=v)], "Escala da hachura"))
            add("Módulo", sc)
            ang = _angle_spin(e.angle)
            ang.valueChanged.connect(lambda v: self._push([replace(e, angle=v)], "Ângulo da hachura"))
            add("Ângulo", ang)
            add("Área", QLabel(fmt(e.area, "m²")))
        elif isinstance(e, PlantingArea):
            sp = self.catalog.get(e.species)
            if sp:
                add("", self._italic(sp.nome_cientifico))
            sc = _spin(e.spacing, maximum=20)
            sc.valueChanged.connect(lambda v: self._push([replace(e, spacing=v)], "Espaçamento do maciço"))
            add("Espaçamento", sc)
            lay = QComboBox()
            for key, name in PLANTING_LAYOUTS.items():
                lay.addItem(name, key)
            lay.setCurrentIndex(list(PLANTING_LAYOUTS).index(e.layout))
            lay.activated.connect(lambda i: self._push([replace(e, layout=lay.itemData(i))], "Malha do maciço"))
            add("Malha", lay)
            ang = _angle_spin(e.angle)
            ang.valueChanged.connect(lambda v: self._push([replace(e, angle=v)], "Ângulo da malha"))
            add("Ângulo", ang)
            add("Área", QLabel(fmt(e.area, "m²")))
            add("Densidade", QLabel(fmt(e.density, "mudas/m²")))
            add("Mudas", QLabel(f"<b>{e.count}</b>"))
        elif isinstance(e, Plant):
            sp = self.catalog.get(e.species)
            if sp:
                add("", self._italic(sp.nome_cientifico))
            canopy = _spin(e.canopy, maximum=60)
            canopy.valueChanged.connect(lambda v: self._push([replace(e, canopy=v)], "Diâmetro da copa"))
            add("Copa (Ø)", canopy)
            height = _spin(e.height, maximum=80)
            height.valueChanged.connect(lambda v: self._push([replace(e, height=v)], "Altura"))
            add("Altura", height)
            x, y = e.position
            add("Posição", QLabel(f"X {fmt(x)}   Y {fmt(y)}"))

    @staticmethod
    def _italic(text: str) -> QLabel:
        lab = QLabel(f"<i>{text}</i>")
        lab.setTextFormat(Qt.TextFormat.RichText)
        return lab
