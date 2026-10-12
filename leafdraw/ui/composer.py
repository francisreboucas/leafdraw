"""Compositor de folhas: pranchas com janelas de vista, carimbo, quadro e PDF."""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Callable

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QPicture
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGraphicsItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QSplitter, QToolBar, QVBoxLayout, QWidget)

from leafdraw.core.commands import ReplaceSheets
from leafdraw.core.sheets import (PAPER_SIZES, STANDARD_SCALES, NorthElement, PlantTableElement, ScaleBarElement,
                                  Sheet, SheetElement, TextElement, TitleBlockElement, ViewportElement,
                                  default_sheet, fit_scale, new_id, nice_bar_length)
from leafdraw.ui.render import RenderContext, draw_element, draw_sheet, plant_table_height

ORIENTATIONS = {"landscape": "Paisagem", "portrait": "Retrato"}
HANDLE_PX = 9
SNAP_MM = 0.5


def _snap(v: float) -> float:
    return round(v / SNAP_MM) * SNAP_MM


def _mm_spin(value: float, minimum: float = 0.0, maximum: float = 2000.0, suffix: str = " mm",
             decimals: int = 1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


class PaperItem(QGraphicsItem):
    """O papel: sombra, folha branca e moldura das margens."""

    def __init__(self, sheet: Sheet):
        super().__init__()
        self.sheet = sheet
        self.setZValue(-10)

    def boundingRect(self):
        W, H = self.sheet.size
        return QRectF(-2, -2, W + 8, H + 8)

    def paint(self, painter, option, widget=None):
        W, H = self.sheet.size
        painter.fillRect(QRectF(3, 3, W, H), QColor(0, 0, 0, 90))
        bare = replace(self.sheet, elements=[])
        draw_sheet(painter, bare, None)


class ElementItem(QGraphicsItem):
    def __init__(self, composer: SheetComposer, sheet: Sheet, el: SheetElement):
        super().__init__()
        self.c = composer
        self.sheet = sheet
        self.el = el
        self.temp: SheetElement | None = None  # estado durante arrasto (pan/redimensionar)
        self._picture: QPicture | None = None
        self._mode: str | None = None
        self._start = QPointF()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setPos(el.x, el.y)
        self.setZValue(0 if isinstance(el, ViewportElement) else 1)
        self.setAcceptHoverEvents(True)
        self.setToolTip(el.label)

    @property
    def current(self) -> SheetElement:
        return self.temp or self.el

    def size(self) -> tuple[float, float]:
        e = self.current
        if isinstance(e, PlantTableElement):
            return e.w, max(5.0, plant_table_height(e, self.c.context(self.sheet)))
        return e.w, e.h

    def boundingRect(self):
        w, h = self.size()
        return QRectF(-1, -1, w + 2, h + 2)

    def invalidate(self):
        self.prepareGeometryChange()
        self._picture = None
        self.update()

    def paint(self, painter, option, widget=None):
        if self._picture is None:
            pic = QPicture()
            p = QPainter(pic)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            e = self.current
            if isinstance(e, PlantTableElement):
                e = replace(e, h=self.size()[1])
            draw_element(p, e, self.sheet, self.c.context(self.sheet))
            p.end()
            self._picture = pic
        painter.drawPicture(0, 0, self._picture)
        if self.isSelected():
            w, h = self.size()
            pen = QPen(QColor("#2f7bff"), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, w, h))
            s = HANDLE_PX / max(painter.worldTransform().m11(), 1e-6)
            painter.setBrush(QBrush(QColor("#2f7bff")))
            painter.drawRect(QRectF(w - s, h - s, s, s))

    def _on_handle(self, pos: QPointF) -> bool:
        w, h = self.size()
        tol = HANDLE_PX * 1.5 / max(self.c.view.transform().m11(), 1e-6)
        return abs(pos.x() - w) <= tol and abs(pos.y() - h) <= tol

    def hoverMoveEvent(self, e):
        if self.isSelected() and self._on_handle(e.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif isinstance(self.el, ViewportElement) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.isSelected() and self._on_handle(e.pos()):
                self._mode = "resize"
            elif isinstance(self.el, ViewportElement) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._mode = "pan"
            if self._mode:
                self._start = e.scenePos()
                self.temp = self.el
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._mode is None:
            super().mouseMoveEvent(e)
            return
        d = e.scenePos() - self._start
        if self._mode == "resize":
            self.temp = replace(self.el, w=max(10.0, _snap(self.el.w + d.x())), h=max(5.0, _snap(self.el.h + d.y())))
        else:
            k = self.el.mm_per_m
            cx, cy = self.el.center
            self.temp = replace(self.el, center=(cx - d.x() / k, cy + d.y() / k))
        self.invalidate()

    def mouseReleaseEvent(self, e):
        if self._mode is not None:
            new, self.temp, mode = self.temp, None, self._mode
            self._mode = None
            if new is not None and new != self.el:
                self.c.commit_element(new, "Redimensionar elemento" if mode == "resize" else "Mover vista")
            else:
                self.invalidate()
            return
        super().mouseReleaseEvent(e)
        self.c.commit_positions()

    def mouseDoubleClickEvent(self, e):
        if isinstance(self.el, ViewportElement) and self.el.mode == "2d":
            self.c.openInModel.emit(*self.el.model_rect())
            return
        super().mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        if not (isinstance(self.el, ViewportElement) and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            e.ignore()
            return
        scales = STANDARD_SCALES
        i = min(range(len(scales)), key=lambda j: abs(scales[j] - self.el.scale))
        i = max(0, min(len(scales) - 1, i + (1 if e.delta() < 0 else -1)))
        if scales[i] != self.el.scale:
            self.c.commit_element(replace(self.el, scale=scales[i]), f"Escala 1:{scales[i]}")
        e.accept()


class PaperView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(72, 76, 82))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan = None

    def fit(self, rect: QRectF):
        self.fitInView(rect.adjusted(-10, -10, 10, 10), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(e)  # Ctrl+roda numa janela de vista muda a escala
            if e.isAccepted():
                return
        f = 1.2 ** (e.angleDelta().y() / 120)
        s = self.transform().m11() * f
        if 0.05 <= s <= 80:
            self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.viewport().unsetCursor()
            return
        super().mouseReleaseEvent(e)


class NewSheetDialog(QDialog):
    def __init__(self, parent=None, name="Planta de paisagismo"):
        super().__init__(parent)
        self.setWindowTitle("Nova folha")
        self.name = QLineEdit(name)
        self.paper = QComboBox()
        for p, (w, h) in PAPER_SIZES.items():
            self.paper.addItem(f"{p} ({w:.0f} × {h:.0f} mm)", p)
        self.paper.setCurrentIndex(1)
        self.orient = QComboBox()
        for k, v in ORIENTATIONS.items():
            self.orient.addItem(v, k)
        form = QFormLayout(self)
        form.addRow("Título da prancha", self.name)
        form.addRow("Papel", self.paper)
        form.addRow("Orientação", self.orient)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class SheetComposer(QWidget):
    openInModel = Signal(float, float, float, float)
    editProjectRequested = Signal()

    def __init__(self, doc, catalog, render3d: Callable | None = None, current_camera: Callable | None = None,
                 parent=None):
        super().__init__(parent)
        self.doc = doc
        self.catalog = catalog
        self.render3d = render3d
        self.current_camera = current_camera
        self.current_id: str | None = None
        self.items: dict[str, ElementItem] = {}
        self._rebuilding = False

        # lista de folhas
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_sheet_selected)
        self.list.itemDoubleClicked.connect(lambda _it: self._focus_name())
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Folhas"))
        lv.addWidget(self.list)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        for row, text, slot in ((row1, "Nova…", self.new_sheet), (row1, "Duplicar", self.duplicate_sheet),
                                (row2, "Excluir", self.delete_sheet), (row2, "▲", lambda: self.move_sheet(-1)),
                                (row2, "▼", lambda: self.move_sheet(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lv.addLayout(row1)
        lv.addLayout(row2)

        # folha
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._on_selection)
        self.view = PaperView()
        self.view.setScene(self.scene)
        self.toolbar = QToolBar()
        for text, slot in (("Janela 2D", self.add_viewport), ("Janela 3D", lambda: self.add_viewport(mode="3d")),
                           ("Carimbo", lambda: self.add_element(TitleBlockElement, w=180, h=56)),
                           ("Quadro de vegetação", lambda: self.add_element(PlantTableElement, w=180, h=60)),
                           ("Texto", lambda: self.add_element(TextElement, w=60, h=8)),
                           ("Norte", lambda: self.add_element(NorthElement, w=20, h=25)),
                           ("Escala gráfica", self.add_scalebar)):
            self.toolbar.addAction(text, slot)
        self.toolbar.addSeparator()
        self.toolbar.addAction("Excluir elemento", self.delete_selected)
        self.toolbar.addAction("Ajustar zoom", self.fit_view)
        self.toolbar.addSeparator()
        self.toolbar.addAction("PDF desta folha…", lambda: self.export_pdf(all_sheets=False))
        self.toolbar.addAction("PDF de todas…", lambda: self.export_pdf(all_sheets=True))
        self.toolbar.addAction("Imprimir…", self.print_sheets)
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.toolbar)
        cv.addWidget(self.view)
        self.hint = QLabel("Arraste para mover · alça azul redimensiona · Ctrl+arrastar/Ctrl+roda numa janela "
                           "de vista: pan/escala · duplo clique abre a região no Modelo · Del exclui")
        self.hint.setStyleSheet("color: #9aa5b1; padding: 2px 6px;")
        cv.addWidget(self.hint)

        # propriedades
        self.props = QWidget()
        self.form = QFormLayout(self.props)
        self.props_title = QLabel()
        self.props_title.setStyleSheet("font-weight: bold;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        wrap = QWidget()
        wv = QVBoxLayout(wrap)
        wv.addWidget(self.props_title)
        wv.addWidget(self.props)
        wv.addStretch()
        scroll.setWidget(wrap)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(scroll)
        split.setSizes([200, 900, 300])
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self._dirty_timer = QTimer(self)
        self._dirty_timer.setSingleShot(True)
        self._dirty_timer.setInterval(120)
        self._dirty_timer.timeout.connect(self.invalidate_all)
        doc.sheetsChanged.connect(self.refresh)
        for sig in (doc.entityAdded, doc.entityRemoved, doc.entityChanged, doc.layersChanged, doc.projectChanged):
            sig.connect(lambda *_: self._dirty_timer.start())
        self.refresh()

    # --- contexto de desenho ------------------------------------------------

    def context(self, sheet: Sheet) -> RenderContext:
        ids = [s.id for s in self.doc.sheets]
        n = ids.index(sheet.id) + 1 if sheet.id in ids else 1
        r3d = (lambda vp, w, h: self.render3d(vp.camera, w, h)) if self.render3d else None
        return RenderContext(self.doc, self.catalog, r3d, (n, max(1, len(ids))))

    def sheet(self) -> Sheet | None:
        return self.doc.sheet(self.current_id) if self.current_id else None

    # --- sincronização ------------------------------------------------------

    def refresh(self):
        self._rebuilding = True
        self.list.blockSignals(True)
        self.list.clear()
        for i, sh in enumerate(self.doc.sheets, 1):
            it = QListWidgetItem(f"{i:02d} · {sh.name}  [{sh.paper}]")
            it.setData(Qt.ItemDataRole.UserRole, sh.id)
            self.list.addItem(it)
            if sh.id == self.current_id:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        cur = self.list.currentItem()
        new_id = cur.data(Qt.ItemDataRole.UserRole) if cur else None
        first = new_id != self.current_id
        self.current_id = new_id
        self._rebuild_scene()
        self._rebuilding = False
        if first:
            self.fit_view()
        self._on_selection()

    def _rebuild_scene(self):
        selected = {it.el.id for it in self.items.values() if it.isSelected()}
        self.scene.clear()
        self.items.clear()
        sh = self.sheet()
        if sh is None:
            self.scene.addText("Nenhuma folha. Clique em \"Nova…\" para criar uma prancha.")
            return
        W, H = sh.size
        self.scene.setSceneRect(QRectF(-W * 0.2, -H * 0.2, W * 1.4, H * 1.4))
        self.scene.addItem(PaperItem(sh))
        for el in sh.elements:
            it = ElementItem(self, sh, el)
            self.scene.addItem(it)
            self.items[el.id] = it
            if el.id in selected:
                it.setSelected(True)

    def invalidate_all(self):
        for it in self.items.values():
            it.invalidate()

    def fit_view(self):
        sh = self.sheet()
        if sh is not None:
            W, H = sh.size
            self.view.fit(QRectF(0, 0, W, H))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.fit_view)

    def _on_sheet_selected(self, it, _prev=None):
        if self._rebuilding:
            return
        self.current_id = it.data(Qt.ItemDataRole.UserRole) if it else None
        self._rebuild_scene()
        self.fit_view()
        self._on_selection()

    # --- comandos -------------------------------------------------------------

    def _replace_sheet(self, new: Sheet, text: str):
        sheets = [new if s.id == new.id else s for s in self.doc.sheets]
        self.doc.undo_stack.push(ReplaceSheets(self.doc, sheets, text))

    def commit_element(self, el: SheetElement, text: str):
        sh = self.sheet()
        if sh is not None:
            self._replace_sheet(sh.with_element(el), text)

    def commit_positions(self):
        sh = self.sheet()
        if sh is None:
            return
        moved = []
        for it in self.items.values():
            x, y = _snap(it.pos().x()), _snap(it.pos().y())
            if (x, y) != (it.el.x, it.el.y):
                moved.append(replace(it.el, x=x, y=y))
        if moved:
            for el in moved:
                sh = sh.with_element(el)
            self._replace_sheet(sh, f"Mover {len(moved)} elemento(s)")

    def new_sheet(self):
        dlg = NewSheetDialog(self, f"Planta de paisagismo {len(self.doc.sheets) + 1:02d}" if self.doc.sheets
                             else "Planta de paisagismo")
        if not dlg.exec():
            return
        sh = default_sheet(self.doc.bounds(), dlg.name.text().strip() or "Folha", dlg.paper.currentData(),
                           dlg.orient.currentData())
        self.current_id = sh.id
        self.doc.undo_stack.push(ReplaceSheets(self.doc, [*self.doc.sheets, sh], "Nova folha"))
        self.fit_view()

    def duplicate_sheet(self):
        sh = self.sheet()
        if sh is None:
            return
        dup = replace(sh, id=new_id(), name=f"{sh.name} (cópia)",
                      elements=[replace(e, id=new_id()) for e in sh.elements])
        i = self.doc.sheets.index(sh)
        sheets = [*self.doc.sheets[: i + 1], dup, *self.doc.sheets[i + 1:]]
        self.current_id = dup.id
        self.doc.undo_stack.push(ReplaceSheets(self.doc, sheets, "Duplicar folha"))

    def delete_sheet(self):
        sh = self.sheet()
        if sh is None:
            return
        if QMessageBox.question(self, "Folhas", f"Excluir a folha \"{sh.name}\"?") != QMessageBox.StandardButton.Yes:
            return
        self.current_id = None
        self.doc.undo_stack.push(ReplaceSheets(self.doc, [s for s in self.doc.sheets if s.id != sh.id],
                                               "Excluir folha"))

    def move_sheet(self, step: int):
        sh = self.sheet()
        if sh is None:
            return
        sheets = list(self.doc.sheets)
        i = sheets.index(sh)
        j = i + step
        if 0 <= j < len(sheets):
            sheets[i], sheets[j] = sheets[j], sheets[i]
            self.doc.undo_stack.push(ReplaceSheets(self.doc, sheets, "Reordenar folhas"))

    def _free_spot(self) -> tuple[float, float]:
        fx, fy, _fw, _fh = self.sheet().frame_rect()
        return fx + 10, fy + 10

    def add_element(self, cls, **kw):
        sh = self.sheet()
        if sh is None:
            self.new_sheet()
            sh = self.sheet()
            if sh is None:
                return
        x, y = self._free_spot()
        el = cls(x=x, y=y, **kw)
        self._replace_sheet(sh.with_element(el), f"Adicionar {cls.label.lower()}")
        self._select(el.id)

    def add_viewport(self, mode: str = "2d"):
        sh = self.sheet()
        if sh is None:
            self.add_element(ViewportElement)
            return
        fx, fy, fw, fh = sh.frame_rect()
        w, h = fw * 0.4, fh * 0.4
        b = self.doc.bounds()
        vp = ViewportElement(x=fx + 10, y=fy + 10, w=w, h=h, mode=mode)
        if b is not None:
            vp.scale = fit_scale((b[2] - b[0]) * 1.05, (b[3] - b[1]) * 1.05, w, h)
            vp.center = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        if mode == "3d" and self.current_camera:
            vp.camera = self.current_camera()
            vp.frame = True
        self._replace_sheet(sh.with_element(vp), "Adicionar janela de vista")
        self._select(vp.id)

    def add_scalebar(self):
        sh = self.sheet()
        scale = (sh.main_scale() if sh else None) or 100
        self.add_element(ScaleBarElement, w=80, h=12, length_m=nice_bar_length(scale, 80))

    def delete_selected(self):
        sh = self.sheet()
        ids = [it.el.id for it in self.items.values() if it.isSelected()]
        if sh is None or not ids:
            return
        for eid in ids:
            sh = sh.without_element(eid)
        self._replace_sheet(sh, f"Excluir {len(ids)} elemento(s)")

    def _select(self, eid: str):
        self.scene.clearSelection()
        it = self.items.get(eid)
        if it is not None:
            it.setSelected(True)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.view.hasFocus():
            self.delete_selected()
            return
        super().keyPressEvent(e)

    def _focus_name(self):
        self.scene.clearSelection()
        self._on_selection()

    # --- propriedades -----------------------------------------------------------

    def _on_selection(self):
        if self._rebuilding:
            return
        while self.form.rowCount():
            self.form.removeRow(0)
        sh = self.sheet()
        if sh is None:
            self.props_title.setText("")
            return
        sel = [it for it in self.items.values() if it.isSelected()]
        if len(sel) == 1:
            self._element_form(sh, sel[0].el)
        elif sel:
            self.props_title.setText(f"{len(sel)} elementos selecionados")
        else:
            self._sheet_form(sh)

    def _sheet_form(self, sh: Sheet):
        self.props_title.setText("Folha")
        name = QLineEdit(sh.name)
        name.editingFinished.connect(lambda: name.text().strip() != sh.name and self._replace_sheet(
            replace(sh, name=name.text().strip() or sh.name), "Renomear folha"))
        self.form.addRow("Título", name)
        paper = QComboBox()
        for p in PAPER_SIZES:
            paper.addItem(p, p)
        paper.setCurrentText(sh.paper)
        paper.activated.connect(lambda i: self._replace_sheet(replace(sh, paper=paper.itemData(i)), "Papel"))
        self.form.addRow("Papel", paper)
        orient = QComboBox()
        for k, v in ORIENTATIONS.items():
            orient.addItem(v, k)
        orient.setCurrentIndex(list(ORIENTATIONS).index(sh.orientation))
        orient.activated.connect(lambda i: self._replace_sheet(replace(sh, orientation=orient.itemData(i)),
                                                               "Orientação"))
        self.form.addRow("Orientação", orient)
        W, H = sh.size
        self.form.addRow("Tamanho", QLabel(f"{W:.0f} × {H:.0f} mm"))
        btn = QPushButton("Dados do projeto (carimbo)…")
        btn.clicked.connect(self.editProjectRequested)
        self.form.addRow(btn)

    def _element_form(self, sh: Sheet, el: SheetElement):
        self.props_title.setText(el.label)
        commit = self.commit_element
        for attr, label in (("x", "X"), ("y", "Y"), ("w", "Largura"), ("h", "Altura")):
            if attr == "h" and isinstance(el, PlantTableElement):
                continue
            s = _mm_spin(getattr(el, attr), 0 if attr in "xy" else 5)
            s.valueChanged.connect(lambda v, a=attr: commit(replace(el, **{a: v}), "Posição/tamanho"))
            self.form.addRow(label, s)

        if isinstance(el, ViewportElement):
            scale = QComboBox()
            scale.setEditable(True)
            for s in STANDARD_SCALES:
                scale.addItem(f"1:{s}", s)
            scale.setCurrentText(f"1:{el.scale}")

            def set_scale():
                txt = scale.currentText().replace(" ", "").split(":")[-1]
                try:
                    v = int(float(txt.replace(",", ".")))
                except ValueError:
                    return
                if v > 0 and v != el.scale:
                    commit(replace(el, scale=v), f"Escala 1:{v}")

            scale.activated.connect(lambda _i: set_scale())
            scale.lineEdit().editingFinished.connect(set_scale)
            self.form.addRow("Escala", scale)
            if el.mode == "2d":
                cx = _mm_spin(el.center[0], -1e7, 1e7, " m", 2)
                cy = _mm_spin(el.center[1], -1e7, 1e7, " m", 2)
                cx.valueChanged.connect(lambda v: commit(replace(el, center=(v, el.center[1])), "Centro da vista"))
                cy.valueChanged.connect(lambda v: commit(replace(el, center=(el.center[0], v)), "Centro da vista"))
                self.form.addRow("Centro X", cx)
                self.form.addRow("Centro Y", cy)
                fit = QPushButton("Enquadrar todo o desenho")
                fit.clicked.connect(lambda: self._fit_viewport(el))
                self.form.addRow(fit)
            else:
                cam = QPushButton("Usar a câmera atual do 3D")
                cam.clicked.connect(lambda: self.current_camera and commit(
                    replace(el, camera=self.current_camera()), "Câmera da vista 3D"))
                self.form.addRow(cam)
            frame = QCheckBox("Moldura")
            frame.setChecked(el.frame)
            frame.toggled.connect(lambda v: commit(replace(el, frame=v), "Moldura"))
            self.form.addRow(frame)
            if el.mode == "2d":
                self.form.addRow(QLabel("Camadas visíveis nesta vista:"))
                for lid, layer in self.doc.layers.items():
                    cb = QCheckBox(layer.name)
                    cb.setChecked(lid not in el.hidden_layers)
                    cb.toggled.connect(lambda on, l=lid: commit(replace(el, hidden_layers=sorted(
                        (set(el.hidden_layers) - {l}) if on else (set(el.hidden_layers) | {l}))), "Camadas da vista"))
                    self.form.addRow(cb)
        elif isinstance(el, TitleBlockElement):
            btn = QPushButton("Editar dados do projeto…")
            btn.clicked.connect(self.editProjectRequested)
            self.form.addRow(btn)
            self.form.addRow(QLabel("Conteúdo = título da folha; escala = 1ª janela de vista."))
        elif isinstance(el, PlantTableElement):
            title = QLineEdit(el.title)
            title.editingFinished.connect(lambda: commit(replace(el, title=title.text()), "Título do quadro"))
            self.form.addRow("Título", title)
            th = _mm_spin(el.text_height, 1, 20)
            th.valueChanged.connect(lambda v: commit(replace(el, text_height=v), "Altura do texto"))
            self.form.addRow("Altura do texto", th)
            areas = QCheckBox("Incluir revestimentos (hachuras)")
            areas.setChecked(el.show_areas)
            areas.toggled.connect(lambda v: commit(replace(el, show_areas=v), "Revestimentos"))
            self.form.addRow(areas)
        elif isinstance(el, TextElement):
            text = QLineEdit(el.text.replace("\n", "\\n"))
            text.setToolTip("Use \\n para quebrar linha")
            text.editingFinished.connect(lambda: commit(replace(el, text=text.text().replace("\\n", "\n")), "Texto"))
            self.form.addRow("Texto", text)
            th = _mm_spin(el.text_height, 1, 100)
            th.valueChanged.connect(lambda v: commit(replace(el, text_height=v), "Altura do texto"))
            self.form.addRow("Altura", th)
            bold = QCheckBox("Negrito")
            bold.setChecked(el.bold)
            bold.toggled.connect(lambda v: commit(replace(el, bold=v), "Negrito"))
            self.form.addRow(bold)
        elif isinstance(el, NorthElement):
            rot = _mm_spin(el.rotation, -360, 360, "°", 1)
            rot.valueChanged.connect(lambda v: commit(replace(el, rotation=v), "Rotação do norte"))
            self.form.addRow("Rotação", rot)
        elif isinstance(el, ScaleBarElement):
            ln = _mm_spin(el.length_m, 0.1, 100000, " m", 1)
            ln.valueChanged.connect(lambda v: commit(replace(el, length_m=v), "Comprimento da escala"))
            self.form.addRow("Comprimento", ln)
            div = QSpinBox()
            div.setRange(1, 20)
            div.setValue(el.divisions)
            div.valueChanged.connect(lambda v: commit(replace(el, divisions=v), "Divisões"))
            self.form.addRow("Divisões", div)
            link = QComboBox()
            link.addItem("1ª janela de vista", "")
            for i, vp in enumerate(sh.viewports(), 1):
                link.addItem(f"Janela {i} (1:{vp.scale})", vp.id)
            link.setCurrentIndex(max(0, link.findData(el.viewport_id)))
            link.activated.connect(lambda i: commit(replace(el, viewport_id=link.itemData(i)), "Vista da escala"))
            self.form.addRow("Vinculada a", link)

    def _fit_viewport(self, vp: ViewportElement):
        b = self.doc.bounds()
        if b is None:
            return
        scale = fit_scale((b[2] - b[0]) * 1.05, (b[3] - b[1]) * 1.05, vp.w, vp.h)
        self.commit_element(replace(vp, scale=scale, center=((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)),
                            "Enquadrar vista")

    # --- saída ----------------------------------------------------------------

    def export_pdf(self, all_sheets: bool, path: str | None = None) -> bool:
        sheets = list(self.doc.sheets) if all_sheets else [s for s in (self.sheet(),) if s]
        if not sheets:
            QMessageBox.information(self, "PDF", "Crie uma folha primeiro.")
            return False
        if path is None:
            base = os.path.splitext(self.doc.file_path)[0] if self.doc.file_path else "pranchas"
            path, _ = QFileDialog.getSaveFileName(self, "Exportar PDF", base + ".pdf", "PDF (*.pdf)")
            if not path:
                return False
        try:
            write_pdf(path, sheets, self.context, self.doc.project.get("projeto", ""))
        except OSError as exc:
            QMessageBox.critical(self, "PDF", f"Não foi possível gravar {path}:\n{exc}")
            return False
        return True

    def print_sheets(self):
        sheets = list(self.doc.sheets)
        if not sheets:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        for i, sh in enumerate(sheets):
            if i:
                printer.newPage()
            page = printer.pageRect(QPrinter.Unit.DevicePixel)
            W, H = sh.size
            k = min(page.width() / W, page.height() / H)
            painter.save()
            painter.scale(k, k)
            draw_sheet(painter, sh, self.context(sh))
            painter.restore()
        painter.end()


def write_pdf(path: str, sheets: list[Sheet], context: Callable[[Sheet], RenderContext], title: str = ""):
    """PDF vetorial, uma página por folha, no tamanho real do papel."""
    writer = QPdfWriter(path)
    writer.setResolution(600)
    writer.setCreator("LeafDraw")
    writer.setTitle(title or "Pranchas")
    painter = None
    for i, sh in enumerate(sheets):
        W, H = sh.size
        size = QPageSize(QSizeF(W, H), QPageSize.Unit.Millimeter, sh.paper, QPageSize.SizeMatchPolicy.ExactMatch)
        writer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
        if painter is None:
            painter = QPainter(writer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        else:
            writer.newPage()
        k = writer.resolution() / 25.4
        painter.save()
        painter.scale(k, k)
        draw_sheet(painter, sh, context(sh))
        painter.restore()
    if painter is not None:
        painter.end()
