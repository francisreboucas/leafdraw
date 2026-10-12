"""Viewport 2D (planta baixa) baseado em QGraphicsView.

A cena usa metros como unidade e a vista é espelhada em Y para que o eixo Y
aponte para cima, como em qualquer CAD.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from leafdraw.core.commands import AddEntities
from leafdraw.core.coords import direct_distance, parse_input
from leafdraw.core.entities import Contour, ElevationView, Plant, PlantingArea, SpotHeight, union_bounds
from leafdraw.core.geom import intersections, nearest_on, perpendicular_feet
from leafdraw.ui import theme
from leafdraw.ui.items2d import PICK_TOLERANCE_PX, EntityItem, MoveGizmo, SnapMarker, cosmetic_pen
from leafdraw.ui.tools import SelectTool, Tool

SPECIES_MIME = "application/x-leafdraw-species"
SCENE_HALF = 50_000.0  # m
GRID_STEPS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
GRID_MIN_PX = 14
SNAP_PX = 10
ZOOM_RANGE = (0.05, 20_000.0)  # px por metro; abaixo disso a cena (100 km) quase cabe na tela e o zoom não ancora
# entidades que alteram o conteúdo das vistas (elevações)
ELEVATION_SOURCES = (Plant, PlantingArea, Contour, SpotHeight)
SNAP_MODES = ("end", "mid", "center", "quad", "int", "perp", "near")
DEFAULT_SNAP_MODES = {"end", "mid", "center", "quad", "int", "perp"}
MAX_SNAP_PRIMITIVES = 60
MAX_GRIP_ENTITIES = 100
GRIP_PX = 4  # meia largura do quadrado do grip


def zoom_about(view: QGraphicsView, pos: QPointF, factor: float):
    """Escala a vista mantendo parado o ponto da cena sob ``pos`` (pixels do viewport).

    Não usa a âncora AnchorUnderMouse do Qt: ela depende da última posição registrada
    pelo mouseMoveEvent do QGraphicsView, que as ferramentas nem sempre repassam, e o
    zoom acabava puxado para outro ponto.
    """
    before = view.viewportTransform().inverted()[0].map(pos)
    view.scale(factor, factor)
    drift = view.viewportTransform().map(before) - pos
    h, v = view.horizontalScrollBar(), view.verticalScrollBar()
    h.setValue(h.value() + round(drift.x()))
    v.setValue(v.value() + round(drift.y()))


class Viewport2D(QGraphicsView):
    cursorMoved = Signal(float, float)
    hintChanged = Signal(str)
    toolChanged = Signal(str)
    message = Signal(str)
    typed = Signal(str)  # tecla digitada no viewport, encaminhada à linha de comando

    def __init__(self, doc, catalog, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.catalog = catalog
        self.items_by_id: dict[str, EntityItem] = {}
        self.snap_grid = False
        self.snap_objects = True
        self.snap_modes = set(DEFAULT_SNAP_MODES)
        self.ortho = False
        self.last_cursor = QPointF()
        self._pan_last: QPointF | None = None
        self._press_pos: QPointF | None = None
        self._hover_grip = None
        self._snap_excluded: set = set()

        scene = QGraphicsScene(-SCENE_HALF, -SCENE_HALF, 2 * SCENE_HALF, 2 * SCENE_HALF, self)
        self.setScene(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)  # o zoom ancora em zoom_about
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.scale(20, -20)

        self.gizmo = MoveGizmo()
        self.gizmo.hide()
        scene.addItem(self.gizmo)
        self.snap_marker = SnapMarker()
        self.snap_marker.hide()
        scene.addItem(self.snap_marker)

        self._elevations_pending = False
        self.tool: Tool | None = None
        self.set_tool(SelectTool(self))

        doc.entityAdded.connect(self._on_added)
        doc.entityRemoved.connect(self._on_removed)
        doc.entityChanged.connect(self._on_changed)
        doc.layersChanged.connect(self._on_layers)
        doc.documentReset.connect(self.rebuild)
        scene.selectionChanged.connect(self.update_gizmo)
        self.rebuild()

    # --- sincronização com o documento -----------------------------------

    def rebuild(self):
        for it in self.items_by_id.values():
            self.scene().removeItem(it)
        self.items_by_id.clear()
        for eid in self.doc.entities:
            self._on_added(eid)
        self.update_gizmo()

    def _on_added(self, eid):
        e = self.doc.entities[eid]
        it = EntityItem(self, e)
        self.scene().addItem(it)
        self.items_by_id[eid] = it
        self._elevation_source_changed(e)

    def _on_removed(self, eid):
        it = self.items_by_id.pop(eid, None)
        if it is not None:
            self._snap_excluded.discard(it)
            self.scene().removeItem(it)
            self._elevation_source_changed(it.entity)

    def _on_changed(self, eid):
        it = self.items_by_id.get(eid)
        if it is not None:
            old = it.entity
            it.set_entity(self.doc.entities[eid])
            if it.isSelected():
                self.update_gizmo()
            self._elevation_source_changed(old)

    def _elevation_source_changed(self, e):
        """Plantas e terreno mudaram: as vistas são refeitas uma vez, no fim do lote de alterações."""
        if isinstance(e, ELEVATION_SOURCES) and not self._elevations_pending:
            self._elevations_pending = True
            QTimer.singleShot(0, self.refresh_elevations)

    def refresh_elevations(self):
        self._elevations_pending = False
        for it in self.items_by_id.values():
            if isinstance(it.entity, ElevationView):
                it.refresh()

    def refresh_items(self):
        """Redesenha tudo (mudou camada, catálogo…)."""
        for it in self.items_by_id.values():
            it.refresh()
        self.update_gizmo()

    _on_layers = refresh_items

    # --- seleção ----------------------------------------------------------

    def selected_items(self) -> list[EntityItem]:
        return [it for it in self.scene().selectedItems() if isinstance(it, EntityItem)]

    def selected_ids(self) -> list[str]:
        return [it.entity.id for it in self.selected_items()]

    def select_all(self):
        for it in self.items_by_id.values():
            if it.isVisible() and it.flags() & it.GraphicsItemFlag.ItemIsSelectable:
                it.setSelected(True)

    def pick(self, scene_pt: QPointF, kinds=None) -> EntityItem | None:
        """Objeto mais acima sob o ponto; ``kinds`` restringe os tipos aceitos."""
        tol = PICK_TOLERANCE_PX * self.pixel_size()
        rect = QRectF(scene_pt.x() - tol, scene_pt.y() - tol, 2 * tol, 2 * tol)
        for it in self.scene().items(rect):  # ordem: do topo para baixo
            if (isinstance(it, EntityItem) and it.isVisible()
                    and it.flags() & it.GraphicsItemFlag.ItemIsSelectable
                    and (kinds is None or it.entity.kind in kinds)):
                return it
        return None

    def click_select(self, e) -> bool:
        """Seleção por clique (com Ctrl/Shift alterna). False se não acertou nada."""
        hit = self.pick(self.mapToScene(e.position().toPoint()))
        if hit is None:
            return False
        mods = e.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            hit.setSelected(not hit.isSelected())
        elif not hit.isSelected():
            self.scene().clearSelection()
            hit.setSelected(True)
        return True

    # --- grips ------------------------------------------------------------

    def _grip_items(self) -> list[EntityItem]:
        if not self.tool.is_select:
            return []
        items = self.selected_items()
        return items if len(items) <= MAX_GRIP_ENTITIES else []

    def grip_at(self, view_pos: QPointF):
        """(item, índice) do grip sob a posição de tela, ou None."""
        best, best_d = None, GRIP_PX + 2
        for it in self._grip_items():
            for i, (x, y) in enumerate(it.entity.grips()):
                q = self.mapFromScene(QPointF(x, y))
                d = max(abs(q.x() - view_pos.x()), abs(q.y() - view_pos.y()))
                if d <= best_d:
                    best, best_d = (it, i), d
        return best

    def set_hover_grip(self, hit):
        key = (hit[0].entity.id, hit[1]) if hit else None
        if key != self._hover_grip:
            self._hover_grip = key
            self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        items = self._grip_items()
        if not items:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        h = GRIP_PX
        for it in items:
            for i, (x, y) in enumerate(it.entity.grips()):
                q = self.mapFromScene(QPointF(x, y))
                hot = self._hover_grip == (it.entity.id, i)
                painter.setPen(QColor(10, 10, 10))
                painter.setBrush(theme.GRIP_HOT if hot else theme.GRIP)
                painter.drawRect(q.x() - h, q.y() - h, 2 * h, 2 * h)
        painter.restore()

    def update_gizmo(self):
        items = self.selected_items()
        if not items or not self.tool.shows_gizmo():
            self.gizmo.hide()
            return
        if isinstance(self.tool, SelectTool) and self.tool.drag is not None:
            return
        b = union_bounds(it.entity.bounds() for it in items)
        self.gizmo.setPos((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        self.gizmo.show()

    # --- ferramentas ------------------------------------------------------

    def set_tool(self, tool: Tool):
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = tool
        tool.activate()
        self.setDragMode(tool.drag_mode())
        self.viewport().setCursor(tool.cursor)
        self.snap_marker.hide()
        self.update_gizmo()
        self.hintChanged.emit(tool.hint())
        self.toolChanged.emit(tool.name)
        self.setFocus()

    def request_select(self):
        """Volta para a seleção depois que o evento atual terminar."""
        QTimer.singleShot(0, lambda: None if self.tool.is_select else self.set_tool(SelectTool(self)))

    def submit_input(self, text: str) -> bool:
        """Entrega a entrada digitada à ferramenta. False se não for para ela
        (o chamador tenta interpretar como comando). ValueError se inválida."""
        tool = self.tool
        want = tool.expects()
        ref = tool.ref_point()
        base = (ref.x(), ref.y()) if ref is not None else None
        # quando a ferramenta aceita número, "2,5" é 2.5 (para ponto use "2;5" ou "@")
        prefer_value = want in ("value", "point_value")
        parsed = parse_input(text, base, prefer_value=prefer_value)
        if parsed.kind == "text":
            return tool.input_text(parsed.text)
        if want == "none":
            return False
        if parsed.kind == "value":
            if want in ("value", "point_value"):
                if not tool.input_value(parsed.value):
                    raise ValueError("valor não aceito")
            elif base is not None:
                p = direct_distance(base, (self.last_cursor.x(), self.last_cursor.y()), parsed.value)
                if p is None:
                    raise ValueError("mova o cursor para indicar a direção")
                tool.input_point(QPointF(*p))
            else:
                raise ValueError("digite um ponto (x,y)")
        else:
            if want == "value":
                raise ValueError("digite um número")
            tool.input_point(QPointF(*parsed.point))
        tool.move(None, self.last_cursor)
        return True

    def escape(self):
        if self.tool.cancel():
            return
        if not self.tool.is_select:
            self.set_tool(SelectTool(self))
        else:
            self.scene().clearSelection()

    def place_plant(self, species_id: str, p: QPointF):
        sp = self.catalog.get(species_id)
        if sp is None:
            return
        plant = Plant(position=(p.x(), p.y()), species=sp.id, canopy=sp.copa, height=sp.altura,
                      layer=self.doc.current_layer)
        self.doc.undo_stack.push(AddEntities(self.doc, [plant], f"Inserir {sp.nome_popular}"))

    # --- escala e grade ---------------------------------------------------

    def pixel_size(self) -> float:
        """Tamanho de um pixel de tela em metros."""
        return 1.0 / abs(self.transform().m11())

    def grid_steps(self) -> tuple[float, float]:
        s = abs(self.transform().m11())
        minor = next((st for st in GRID_STEPS if st * s >= GRID_MIN_PX), GRID_STEPS[-1])
        major = next((st for st in GRID_STEPS if st * s >= GRID_MIN_PX * 5), GRID_STEPS[-1])
        return minor, major

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, theme.BG_2D)
        minor, major = self.grid_steps()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for step, color in ((minor, theme.GRID_MINOR), (major, theme.GRID_MAJOR)):
            painter.setPen(cosmetic_pen(color))
            x = math.floor(rect.left() / step) * step
            lines = []
            while x <= rect.right():
                lines.append(QLineF(x, rect.top(), x, rect.bottom()))
                x += step
            y = math.floor(rect.top() / step) * step
            while y <= rect.bottom():
                lines.append(QLineF(rect.left(), y, rect.right(), y))
                y += step
            painter.drawLines(lines)
        painter.setPen(cosmetic_pen(theme.AXIS_X, 1))
        painter.drawLine(QLineF(rect.left(), 0, rect.right(), 0))
        painter.setPen(cosmetic_pen(theme.AXIS_Y, 1))
        painter.drawLine(QLineF(0, rect.top(), 0, rect.bottom()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def zoom_extents(self):
        b = self.doc.bounds()
        if b is None:
            rect = QRectF(-10, -10, 20, 20)
        else:
            w = max(b[2] - b[0], 1.0)
            h = max(b[3] - b[1], 1.0)
            pad = max(w, h) * 0.08
            rect = QRectF(b[0] - pad, b[1] - pad, w + 2 * pad, h + 2 * pad)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.update_gizmo()

    # --- snap -------------------------------------------------------------

    def exclude_from_snap(self, items):
        self._snap_excluded = set(items)

    def snap(self, p: QPointF, base: QPointF | None = None) -> tuple[QPointF, str | None]:
        if self.snap_objects and self.snap_modes:
            hit = self._object_snap(p, base)
            if hit is not None:
                return hit
        if base is not None and self.ortho:
            if abs(p.x() - base.x()) >= abs(p.y() - base.y()):
                p = QPointF(p.x(), base.y())
            else:
                p = QPointF(base.x(), p.y())
        elif self.snap_grid:
            step = self.grid_steps()[0]
            p = QPointF(round(p.x() / step) * step, round(p.y() / step) * step)
        return p, None

    def _object_snap(self, p: QPointF, base: QPointF | None):
        modes = self.snap_modes
        tol = SNAP_PX * self.pixel_size()
        P = (p.x(), p.y())
        rect = QRectF(p.x() - tol, p.y() - tol, 2 * tol, 2 * tol)
        best, best_d = None, tol
        prims = []
        for it in self.scene().items(rect):
            if not isinstance(it, EntityItem) or not it.isVisible() or it in self._snap_excluded:
                continue
            for pt, kind in it.entity.snap_points():
                if kind in modes:
                    d = math.dist(pt, P)
                    if d < best_d:
                        best, best_d = (pt, kind), d
            for pr in it.entity.primitives():
                if math.dist(nearest_on(pr, P), P) <= tol:
                    prims.append(pr)
        prims = prims[:MAX_SNAP_PRIMITIVES]
        if "int" in modes:
            for i, a in enumerate(prims):
                for b in prims[i + 1:]:
                    for pt in intersections(a, b):
                        d = math.dist(pt, P)
                        if d < best_d:
                            best, best_d = (pt, "int"), d
        if "perp" in modes and base is not None:
            B = (base.x(), base.y())
            for pr in prims:
                for pt in perpendicular_feet(pr, B):
                    d = math.dist(pt, P)
                    if d < best_d:
                        best, best_d = (pt, "perp"), d
        if best is None and "near" in modes and prims:
            pt = min((nearest_on(pr, P) for pr in prims), key=lambda q: math.dist(q, P))
            best = (pt, "near")
        if best is None:
            return None
        return QPointF(*best[0]), best[1]

    def _snapped(self, pos: QPointF) -> tuple[QPointF, str | None]:
        raw = self.mapToScene(pos.toPoint())
        if not self.tool.wants_snap():
            return raw, None
        return self.snap(raw, self.tool.base_point())

    def _show_snap(self, p: QPointF, kind: str | None):
        if kind and self.tool.wants_snap():
            self.snap_marker.set_kind(kind)
            self.snap_marker.setPos(p)
            self.snap_marker.show()
        else:
            self.snap_marker.hide()

    # --- eventos ----------------------------------------------------------

    def wheelEvent(self, e):
        f = 1.2 ** (e.angleDelta().y() / 120)
        s = abs(self.transform().m11()) * f
        if ZOOM_RANGE[0] <= s <= ZOOM_RANGE[1]:
            zoom_about(self, e.position(), f)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        p, _ = self._snapped(e.position())
        if self.tool.press(e, p):
            e.accept()
            return
        self._press_pos = e.position() if e.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        p, _ = self._snapped(e.position())
        if self.tool.double_click(e, p):
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self._pan_last = e.position()
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - round(d.x()))
            v.setValue(v.value() - round(d.y()))
            return
        p, kind = self._snapped(e.position())
        self.last_cursor = p
        self._show_snap(p, kind)
        self.cursorMoved.emit(p.x(), p.y())
        if self.tool.move(e, p):
            return
        if self._press_pos is not None and self.dragMode() == QGraphicsView.DragMode.RubberBandDrag:
            # esquerda→direita: janela (só o que está inteiro); direita→esquerda: cruzamento
            window = e.position().x() >= self._press_pos.x()
            self.setRubberBandSelectionMode(Qt.ItemSelectionMode.ContainsItemShape if window
                                            else Qt.ItemSelectionMode.IntersectsItemShape)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self.viewport().setCursor(self.tool.cursor)
            return
        p, _ = self._snapped(e.position())
        if self.tool.release(e, p):
            return
        super().mouseReleaseEvent(e)
        self._press_pos = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.escape()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.typed.emit("\n")  # Enter/Espaço: a linha de comando decide (terminar ou repetir)
            return
        text = e.text()
        mods = e.modifiers() & ~(Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.KeypadModifier)
        if text and text.isprintable() and mods == Qt.KeyboardModifier.NoModifier:
            self.typed.emit(text)
            return
        super().keyPressEvent(e)

    def leaveEvent(self, e):
        self.snap_marker.hide()
        super().leaveEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(SPECIES_MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(SPECIES_MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(SPECIES_MIME):
            super().dropEvent(e)
            return
        sid = bytes(e.mimeData().data(SPECIES_MIME)).decode()
        p, _ = self.snap(self.mapToScene(e.position().toPoint()))
        self.place_plant(sid, p)
        e.acceptProposedAction()
        self.setFocus()
