"""Ferramentas interativas do viewport 2D.

Cada ferramenta recebe eventos já convertidos para coordenadas de cena e com
snap aplicado. Os métodos retornam True quando consumiram o evento. A entrada
digitada na linha de comando chega por ``input_point``/``input_value``/``input_text``.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsView, QInputDialog

from leafdraw.core.commands import AddEntities, RemoveEntities, ReplaceEntities
from leafdraw.core.editing import OFFSET_KINDS, explode_entity, find_boundary, offset_entity
from leafdraw.core.entities import (HATCH_PATTERNS, PLANTING_LAYOUTS, Arc, Circle, Dimension, Hatch, Line, Plant,
                                    PlantingArea, Polyline, Text)
from leafdraw.core.modify import EXTEND_KINDS, PATH_KINDS, TRIM_KINDS, distribute_along, extend_entity, trim_entity
from leafdraw.core.geom import Affine, angle_of, arc_from_3_points, nearest_on, point_side
from leafdraw.ui import theme
from leafdraw.ui.items2d import EntityItem, add_arc, cosmetic_pen, entity_fill, entity_path
from leafdraw.ui.symbols import symbol_paths

MIN_SIZE = 1e-6
NO_DRAG = QGraphicsView.DragMode.NoDrag
RUBBER_BAND = QGraphicsView.DragMode.RubberBandDrag


def _pt(p: QPointF):
    return (p.x(), p.y())


def fmt(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}".replace(".", ",")


def qtransform(t: Affine) -> QTransform:
    return QTransform(t.a, t.c, t.b, t.d, t.e, t.f)


class Tool:
    name = ""
    is_select = False
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, view):
        self.view = view

    @property
    def doc(self):
        return self.view.doc

    def activate(self):
        pass

    def deactivate(self):
        pass

    def hint(self) -> str:
        return ""

    def drag_mode(self):
        return NO_DRAG

    def expects(self) -> str:
        """O que a linha de comando deve fornecer: none | point | value | point_value."""
        return "none"

    def ref_point(self) -> QPointF | None:
        """Ponto de referência para coordenadas relativas (@)."""
        return None

    def base_point(self) -> QPointF | None:
        """Ponto de referência para o modo orto e a perpendicular."""
        return self.ref_point()

    def wants_snap(self) -> bool:
        return True

    def shows_gizmo(self) -> bool:
        return False

    def press(self, e, p: QPointF) -> bool:
        return False

    def double_click(self, e, p: QPointF) -> bool:
        return self.press(e, p)

    def move(self, e, p: QPointF) -> bool:
        return False

    def release(self, e, p: QPointF) -> bool:
        return False

    def input_point(self, p: QPointF) -> bool:
        return False

    def input_value(self, v: float) -> bool:
        return False

    def input_text(self, s: str) -> bool:
        return False

    def finish(self):
        pass

    def cancel(self) -> bool:
        """Cancela a operação em andamento. False se não havia nada a cancelar."""
        return False

    def _hint_changed(self):
        self.view.hintChanged.emit(self.hint())

    def message(self, text: str):
        self.view.message.emit(text)


class SelectTool(Tool):
    name = "select"
    is_select = True
    cursor = Qt.CursorShape.ArrowCursor

    def __init__(self, view):
        super().__init__(view)
        self.drag = None
        self.grip = None
        self.preview: QGraphicsPathItem | None = None

    def hint(self):
        return "Comando: digite um comando ou selecione objetos. Arraste o gizmo ou os grips para editar."

    def deactivate(self):
        self._clear_preview()
        self.view.set_hover_grip(None)

    def base_point(self):
        return QPointF(*self.grip["origin"]) if self.grip else None

    def _clear_preview(self):
        if self.preview is not None:
            self.view.scene().removeItem(self.preview)
            self.preview = None

    def drag_mode(self):
        return RUBBER_BAND

    def wants_snap(self):
        return self.drag is not None or self.grip is not None

    def shows_gizmo(self):
        return self.grip is None

    def press(self, e, p):
        if e.button() != Qt.MouseButton.LeftButton:
            return False
        v = self.view
        hit = v.grip_at(e.position())
        if hit is not None:
            item, index = hit
            self.grip = {"item": item, "index": index, "origin": item.entity.grips()[index]}
            self.preview = QGraphicsPathItem()
            self.preview.setPen(cosmetic_pen(theme.PREVIEW, 1, Qt.PenStyle.DashLine))
            self.preview.setZValue(1500)
            v.scene().addItem(self.preview)
            v.gizmo.hide()
            return True
        handle = v.gizmo.handle_at(v, e.position())
        if handle:
            items = v.selected_items()
            self.drag = {"handle": handle, "start": QPointF(p), "items": items,
                         "base": {it: it.pos() for it in items}, "gizmo": v.gizmo.pos()}
            v.exclude_from_snap(items)
            return True
        return v.click_select(e)

    def _delta(self, p: QPointF) -> QPointF:
        d = p - self.drag["start"]
        if self.drag["handle"] == "x":
            d.setY(0)
        elif self.drag["handle"] == "y":
            d.setX(0)
        return d

    def move(self, e, p):
        v = self.view
        if self.grip is not None:
            new = self.grip["item"].entity.moved_grip(self.grip["index"], _pt(p))
            self.preview.setPath(preview_shape(new, v.catalog) if new is not None else QPainterPath())
            return True
        if self.drag is None:
            if e is not None:
                v.set_hover_grip(v.grip_at(e.position()))
                handle = v.gizmo.handle_at(v, e.position())
                v.gizmo.set_hover(handle)
                v.viewport().setCursor(Qt.CursorShape.SizeAllCursor if handle else self.cursor)
            return False
        d = self._delta(p)
        for it in self.drag["items"]:
            it.setPos(self.drag["base"][it] + d)
        v.gizmo.setPos(self.drag["gizmo"] + d)
        return True

    def release(self, e, p):
        if self.grip is not None and e.button() == Qt.MouseButton.LeftButton:
            g, self.grip = self.grip, None
            self._clear_preview()
            ent = g["item"].entity
            new = ent.moved_grip(g["index"], _pt(p))
            if new is not None and new != ent:
                self.doc.undo_stack.push(ReplaceEntities(self.doc, [new], "Editar por grip"))
            self.view.update_gizmo()
            return True
        if self.drag is None or e.button() != Qt.MouseButton.LeftButton:
            return False
        d = self._delta(p)
        self._restore()
        if math.hypot(d.x(), d.y()) > MIN_SIZE:
            moved = [it.entity.translated(d.x(), d.y()) for it in self.drag["items"]]
            self.doc.undo_stack.push(ReplaceEntities(self.doc, moved, f"Mover {len(moved)} objeto(s)"))
        self.drag = None
        self.view.update_gizmo()
        return True

    def _restore(self):
        for it in self.drag["items"]:
            it.setPos(self.drag["base"][it])
        self.view.gizmo.setPos(self.drag["gizmo"])
        self.view.exclude_from_snap([])

    def cancel(self):
        if self.grip is not None:
            self.grip = None
            self._clear_preview()
            self.view.update_gizmo()
            return True
        if self.drag is None:
            return False
        self._restore()
        self.drag = None
        return True


def preview_shape(e, catalog) -> QPainterPath:
    """Contorno de uma entidade (ainda não desenhada) para prévias."""
    if isinstance(e, Plant):
        sp = catalog.get(e.species)
        outline, _ = symbol_paths(sp.simbolo if sp else "arvore", e.canopy / 2)
        return outline.translated(*e.position)
    path = entity_path(e)
    fill = entity_fill(e)
    if fill is not None:
        path.addPath(fill)
    return path


def boundary_at(view, p: QPointF):
    """Contorno fechado (com furos) em volta de ``p``, a partir do que está visível."""
    view_rect = view.mapToScene(view.viewport().rect()).boundingRect()
    cands = [it.entity for it in view.items_by_id.values()
             if it.isVisible() and not isinstance(it.entity, (Plant, Text, Hatch, PlantingArea))
             and it.sceneBoundingRect().intersects(view_rect)]
    return find_boundary(cands, _pt(p))


def _cutting_entities(view, rect: QRectF, exclude) -> list:
    """Primitivas de corte/limite: geometria visível em ``rect`` (sem plantas, textos e preenchimentos)."""
    prims = []
    for it in view.scene().items(rect):
        if (isinstance(it, EntityItem) and it is not exclude and it.isVisible()
                and not isinstance(it.entity, (Plant, Text, Hatch, PlantingArea, Dimension))):
            prims += it.entity.primitives()
    return prims


class DrawTool(Tool):
    """Base para ferramentas que coletam pontos e mostram uma prévia."""

    def __init__(self, view):
        super().__init__(view)
        self.points: list[QPointF] = []
        self.preview: QGraphicsPathItem | None = None
        self.cursor_pos: QPointF | None = None

    def activate(self):
        self.preview = QGraphicsPathItem()
        self.preview.setPen(cosmetic_pen(theme.PREVIEW, 1, Qt.PenStyle.DashLine))
        self.preview.setZValue(1500)
        self.view.scene().addItem(self.preview)

    def deactivate(self):
        if self.preview is not None:
            self.view.scene().removeItem(self.preview)
            self.preview = None
        self.points.clear()

    def expects(self):
        return "point"

    def ref_point(self):
        return self.points[-1] if self.points else None

    def preview_path(self, cursor: QPointF) -> QPainterPath:
        return QPainterPath()

    def move(self, e, p):
        self.cursor_pos = QPointF(p)
        self.refresh_preview()
        return True

    def refresh_preview(self):
        if self.preview is not None and self.cursor_pos is not None:
            self.preview.setPath(self.preview_path(self.cursor_pos))

    def reset(self):
        self.points.clear()
        if self.preview is not None:
            self.preview.setPath(QPainterPath())
        self._hint_changed()

    def cancel(self):
        if not self.points:
            return False
        self.reset()
        return True

    def commit(self, entities, text):
        layer = self.doc.current_layer
        for ent in entities:
            ent.layer = layer
        self.doc.undo_stack.push(AddEntities(self.doc, entities, text))

    def press(self, e, p):
        if e.button() == Qt.MouseButton.RightButton:
            self.finish()
            return True
        if e.button() != Qt.MouseButton.LeftButton:
            return False
        return self.input_point(p)

    def input_point(self, p):
        self.add_point(QPointF(p))
        self._hint_changed()
        self.refresh_preview()
        return True

    def add_point(self, p: QPointF):
        raise NotImplementedError

    def finish(self):
        self.reset()


# --- desenho -------------------------------------------------------------

class LineTool(DrawTool):
    name = "line"

    def hint(self):
        if not self.points:
            return "Linha: primeiro ponto"
        return "Linha: próximo ponto (Enter, Esc ou botão direito encerram)"

    def add_point(self, p):
        if self.points and QLineF(self.points[-1], p).length() > MIN_SIZE:
            self.commit([Line(p1=_pt(self.points[-1]), p2=_pt(p))], "Linha")
        self.points = [p]

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.points:
            path.moveTo(self.points[-1])
            path.lineTo(cursor)
        return path


class PolylineTool(DrawTool):
    name = "polyline"
    CLOSE_PX = 10

    def hint(self):
        if not self.points:
            return "Polilinha: primeiro vértice"
        return "Polilinha: próximo vértice [F = fechar] (Enter, duplo clique ou botão direito terminam)"

    def add_point(self, p):
        if len(self.points) >= 3:
            px = QLineF(self.points[0], p).length() / self.view.pixel_size()
            if px <= self.CLOSE_PX:
                self._commit(closed=True)
                return
        if not self.points or QLineF(self.points[-1], p).length() > MIN_SIZE:
            self.points.append(p)

    def input_text(self, s):
        if s.upper() in ("F", "FECHAR") and len(self.points) >= 3:
            self._commit(closed=True)
            return True
        return False

    def double_click(self, e, p):
        if e.button() == Qt.MouseButton.LeftButton:
            self.finish()
            return True
        return super().double_click(e, p)

    def finish(self):
        self._commit(closed=False)

    def _commit(self, closed: bool):
        pts = [_pt(q) for q in self.points]
        if len(pts) >= (3 if closed else 2):
            self.commit([Polyline(vertices=pts, closed=closed)], "Polilinha")
        self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.points:
            path.moveTo(self.points[0])
            for q in self.points[1:]:
                path.lineTo(q)
            path.lineTo(cursor)
        return path


class RectTool(DrawTool):
    name = "rect"

    def hint(self):
        return "Retângulo: primeiro canto" if not self.points else "Retângulo: canto oposto (ex.: @4,3)"

    def base_point(self):
        return None

    def add_point(self, p):
        if not self.points:
            self.points = [p]
            return
        a = self.points[0]
        if abs(p.x() - a.x()) > MIN_SIZE and abs(p.y() - a.y()) > MIN_SIZE:
            verts = [(a.x(), a.y()), (p.x(), a.y()), (p.x(), p.y()), (a.x(), p.y())]
            self.commit([Polyline(vertices=verts, closed=True)], "Retângulo")
        self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.points:
            path.addRect(QRectF(self.points[0], cursor).normalized())
        return path


class CircleTool(DrawTool):
    name = "circle"

    def hint(self):
        return "Círculo: centro" if not self.points else "Círculo: raio (digite o valor ou clique um ponto)"

    def expects(self):
        return "point_value" if self.points else "point"

    def base_point(self):
        return None

    def add_point(self, p):
        if not self.points:
            self.points = [p]
            return
        self._commit(QLineF(self.points[0], p).length())

    def input_value(self, v):
        if not self.points:
            return False
        self._commit(v)
        return True

    def _commit(self, r):
        if r > MIN_SIZE:
            self.commit([Circle(center=_pt(self.points[0]), radius=r)], "Círculo")
        self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.points:
            c = self.points[0]
            r = QLineF(c, cursor).length()
            path.addEllipse(c, r, r)
            path.moveTo(c)
            path.lineTo(cursor)
        return path


class ArcTool(DrawTool):
    name = "arc"

    def hint(self):
        return ("Arco: ponto inicial", "Arco: segundo ponto", "Arco: ponto final")[len(self.points)]

    def add_point(self, p):
        self.points.append(p)
        if len(self.points) == 3:
            res = arc_from_3_points(*(_pt(q) for q in self.points))
            if res is not None:
                c, r, a0, a1 = res
                self.commit([Arc(center=c, radius=r, start=a0, end=a1)], "Arco")
            self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if len(self.points) == 1:
            path.moveTo(self.points[0])
            path.lineTo(cursor)
        elif len(self.points) == 2:
            res = arc_from_3_points(_pt(self.points[0]), _pt(self.points[1]), _pt(cursor))
            if res is not None:
                c, r, a0, a1 = res
                add_arc(path, c, r, a0, (a1 - a0) % 360 or 360)
        return path


class TextTool(DrawTool):
    name = "text"
    height = 0.25

    def hint(self):
        return f"Texto: ponto de inserção (digite um número para mudar a altura; atual {fmt(TextTool.height)} m)"

    def expects(self):
        return "point_value"

    def base_point(self):
        return None

    def input_value(self, v):
        if v <= 0:
            return False
        TextTool.height = v
        self._hint_changed()
        return True

    def add_point(self, p):
        text, ok = QInputDialog.getMultiLineText(self.view, "Texto", "Conteúdo:")
        if ok and text.strip():
            self.commit([Text(position=_pt(p), text=text.rstrip("\n"), height=TextTool.height)], "Texto")
        self.view.setFocus()

    def preview_path(self, cursor):
        h = TextTool.height
        path = QPainterPath()
        path.addRect(QRectF(cursor.x(), cursor.y(), h * 4, h))
        return path


class DimensionTool(DrawTool):
    name = "dimension"
    text_height = 0.2

    def hint(self):
        return ("Cota: primeiro ponto", "Cota: segundo ponto",
                "Cota: posição da linha de cota (clique ou digite o afastamento)")[len(self.points)]

    def expects(self):
        return "point_value" if len(self.points) == 2 else "point"

    def base_point(self):
        return self.points[0] if len(self.points) == 1 else None

    def _dim(self, offset) -> Dimension:
        return Dimension(p1=_pt(self.points[0]), p2=_pt(self.points[1]), offset=offset,
                         text_height=DimensionTool.text_height)

    def _offset_for(self, p: QPointF) -> float:
        a, b = _pt(self.points[0]), _pt(self.points[1])
        L = math.dist(a, b) or 1.0
        return point_side(a, b, _pt(p)) / L

    def add_point(self, p):
        if len(self.points) < 2:
            if not self.points or QLineF(self.points[0], p).length() > MIN_SIZE:
                self.points.append(p)
            return
        self._commit(self._offset_for(p))

    def input_value(self, v):
        if len(self.points) != 2:
            return False
        side = 1 if self.cursor_pos is None or self._offset_for(self.cursor_pos) >= 0 else -1
        self._commit(abs(v) * side)
        return True

    def _commit(self, offset):
        self.commit([self._dim(offset)], "Cota")
        self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if len(self.points) == 1:
            path.moveTo(self.points[0])
            path.lineTo(cursor)
        elif len(self.points) == 2:
            d = self._dim(self._offset_for(cursor))
            path = entity_path(d)
            path.addPath(entity_fill(d))
        return path


HATCH_KEYS = {"S": "solid", "D": "diagonal", "X": "cross", "L": "horizontal", "G": "grass", "P": "dots",
              "PE": "gravel"}


class HatchTool(DrawTool):
    name = "hatch"
    pattern = "grass"
    scale = 1.0
    angle = 0.0

    def hint(self):
        opts = " ".join(f"{k}={HATCH_PATTERNS[v]}" for k, v in HATCH_KEYS.items())
        return (f"Hachura ({HATCH_PATTERNS[HatchTool.pattern]}, módulo {fmt(HatchTool.scale)} m): "
                f"clique dentro de uma área fechada [{opts}; número = módulo]")

    def expects(self):
        return "point_value"

    def wants_snap(self):
        return False

    def input_text(self, s):
        pat = HATCH_KEYS.get(s.upper())
        if pat is None:
            return False
        HatchTool.pattern = pat
        self._hint_changed()
        return True

    def input_value(self, v):
        if v <= 0:
            return False
        HatchTool.scale = v
        self._hint_changed()
        return True

    def add_point(self, p):
        loops = boundary_at(self.view, p)
        if not loops:
            self.message("Hachura: nenhuma área fechada encontrada nesse ponto.")
            return
        h = Hatch(loops=loops, pattern=HatchTool.pattern, scale=HatchTool.scale, angle=HatchTool.angle)
        self.commit([h], "Hachura")
        self.message(f"Hachura criada: área {fmt(h.area)} m².")


class PlantTool(DrawTool):
    name = "plant"

    def __init__(self, view, species_id: str):
        super().__init__(view)
        self.species = view.catalog.get(species_id)

    def hint(self):
        return f"Planta: {self.species.nome_popular}. Clique para posicionar; Esc encerra."

    def base_point(self):
        return None

    def add_point(self, p):
        self.view.place_plant(self.species.id, p)

    def preview_path(self, cursor):
        outline, details = symbol_paths(self.species.simbolo, self.species.copa / 2)
        path = QPainterPath(outline)
        path.addPath(details)
        return path.translated(cursor)

    def finish(self):
        pass

    def press(self, e, p):
        if e.button() == Qt.MouseButton.RightButton:
            self.view.escape()
            return True
        return super().press(e, p)

    def double_click(self, e, p):
        return True  # evita inserir duas plantas no mesmo ponto


class DistanceTool(DrawTool):
    name = "distance"

    def hint(self):
        return "Medir: primeiro ponto" if not self.points else "Medir: segundo ponto"

    def add_point(self, p):
        if not self.points:
            self.points = [p]
            return
        a, b = self.points[0], p
        dx, dy = b.x() - a.x(), b.y() - a.y()
        self.message(f"Distância {fmt(math.hypot(dx, dy), 3)} m · ΔX {fmt(dx, 3)} · ΔY {fmt(dy, 3)} · "
                     f"ângulo {fmt(angle_of(_pt(a), _pt(b)), 1)}°")
        self.reset()

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.points:
            path.moveTo(self.points[0])
            path.lineTo(cursor)
        return path


# --- edição --------------------------------------------------------------

class EditTool(DrawTool):
    """Ferramenta que opera sobre uma seleção (pré-selecionada ou escolhida agora)."""

    label = ""

    def activate(self):
        super().activate()
        self.targets = self.view.selected_items()
        self.selecting = not self.targets
        if not self.selecting:
            self.on_targets()

    def drag_mode(self):
        return RUBBER_BAND if self.selecting else NO_DRAG

    def hint(self):
        if self.selecting:
            return f"{self.label}: selecione objetos e pressione Enter"
        return self.step_hint()

    def step_hint(self) -> str:
        return ""

    def expects(self):
        return "none" if self.selecting else self.step_expects()

    def step_expects(self) -> str:
        return "point"

    def wants_snap(self):
        return not self.selecting

    def press(self, e, p):
        if self.selecting:
            if e.button() == Qt.MouseButton.RightButton:
                self._end_selection()
                return True
            return self.view.click_select(e)
        return super().press(e, p)

    def double_click(self, e, p):
        if self.selecting:
            return self.press(e, p)
        return super().double_click(e, p)

    def move(self, e, p):
        if self.selecting:
            return False
        return super().move(e, p)

    def input_point(self, p):
        if self.selecting:
            return False
        return super().input_point(p)

    def finish(self):
        if self.selecting:
            self._end_selection()
        else:
            self.view.request_select()

    def _end_selection(self):
        items = self.view.selected_items()
        if not items:
            return
        self.targets = items
        self.selecting = False
        self.view.setDragMode(self.drag_mode())
        self.on_targets()
        self._hint_changed()

    def on_targets(self):
        pass

    def entities(self):
        return [it.entity for it in self.targets if it.entity.id in self.doc.entities]


class TransformTool(EditTool):
    """Base para mover/copiar/rotacionar/escalar/espelhar com prévia fantasma."""

    copies = False
    repeat = False

    def on_targets(self):
        self.ghost = QPainterPath()
        for it in self.targets:
            self.ghost.addPath(it.ghost_path())

    def transform_for(self, p: QPointF) -> Affine | None:
        raise NotImplementedError

    def preview_path(self, cursor):
        if self.selecting or not self.points:
            return QPainterPath()
        t = self.transform_for(cursor)
        path = qtransform(t).map(self.ghost) if t is not None else QPainterPath()
        path.moveTo(self.points[0])
        path.lineTo(cursor)
        return path

    def add_point(self, p):
        if not self.points:
            self.points = [p]
            return
        t = self.transform_for(p)
        if t is not None:
            self.apply(t)

    def apply(self, t: Affine):
        ents = self.entities()
        if not ents:
            self.view.request_select()
            return
        if self.copies:
            self.doc.undo_stack.push(AddEntities(self.doc, [e.transformed(t).copy_new_id() for e in ents],
                                                 f"{self.label} {len(ents)} objeto(s)"))
        else:
            self.doc.undo_stack.push(ReplaceEntities(self.doc, [e.transformed(t) for e in ents],
                                                     f"{self.label} {len(ents)} objeto(s)"))
        if self.repeat:
            self.refresh_preview()
        else:
            self.view.request_select()


class MoveTool(TransformTool):
    name = "move"
    label = "Mover"

    def step_hint(self):
        return "Mover: ponto base" if not self.points else "Mover: ponto de destino (ex.: @2,0)"

    def transform_for(self, p):
        b = self.points[0]
        return Affine.translation(p.x() - b.x(), p.y() - b.y())


class CopyTool(MoveTool):
    name = "copy"
    label = "Copiar"
    copies = True
    repeat = True

    def step_hint(self):
        return "Copiar: ponto base" if not self.points else "Copiar: destino (repete; Enter encerra)"


class RotateTool(TransformTool):
    name = "rotate"
    label = "Rotacionar"

    def step_hint(self):
        return "Rotacionar: ponto base" if not self.points else "Rotacionar: ângulo (digite em graus ou clique)"

    def step_expects(self):
        return "point_value" if self.points else "point"

    def transform_for(self, p):
        b = self.points[0]
        if QLineF(b, p).length() < MIN_SIZE:
            return None
        return Affine.rotation(angle_of(_pt(b), _pt(p)), _pt(b))

    def input_value(self, v):
        if not self.points:
            return False
        self.apply(Affine.rotation(v, _pt(self.points[0])))
        return True


class ScaleTool(TransformTool):
    name = "scale"
    label = "Escalar"

    def step_hint(self):
        return "Escalar: ponto base" if not self.points else "Escalar: fator (digite ou clique; distância = fator)"

    def step_expects(self):
        return "point_value" if self.points else "point"

    def transform_for(self, p):
        s = QLineF(self.points[0], p).length()
        return Affine.scaling(s, _pt(self.points[0])) if s > MIN_SIZE else None

    def input_value(self, v):
        if not self.points or v <= 0:
            return False
        self.apply(Affine.scaling(v, _pt(self.points[0])))
        return True


class MirrorTool(TransformTool):
    name = "mirror"
    label = "Espelhar"
    copies = True

    def step_hint(self):
        return ("Espelhar: primeiro ponto do eixo" if not self.points
                else "Espelhar: segundo ponto do eixo (os originais são mantidos)")

    def transform_for(self, p):
        if QLineF(self.points[0], p).length() < MIN_SIZE:
            return None
        return Affine.mirror(_pt(self.points[0]), _pt(p))


class ExplodeTool(EditTool):
    name = "explode"
    label = "Explodir"

    def on_targets(self):
        ents = self.entities()
        removed, added = [], []
        for e in ents:
            parts = explode_entity(e)
            if parts:
                removed.append(e.id)
                added += parts
        if removed:
            stack = self.doc.undo_stack
            stack.beginMacro(f"Explodir {len(removed)} objeto(s)")
            stack.push(RemoveEntities(self.doc, removed))
            stack.push(AddEntities(self.doc, added))
            stack.endMacro()
            self.message(f"Explodir: {len(removed)} objeto(s) em {len(added)}.")
        else:
            self.message("Explodir: nada a decompor (polilinhas, cotas e hachuras podem ser explodidas).")
        self.view.request_select()


class EraseTool(EditTool):
    name = "erase"
    label = "Apagar"

    def on_targets(self):
        ids = [e.id for e in self.entities()]
        if ids:
            self.doc.undo_stack.push(RemoveEntities(self.doc, ids, f"Excluir {len(ids)} objeto(s)"))
        self.view.request_select()


class OffsetTool(DrawTool):
    name = "offset"
    distance = 1.0

    def __init__(self, view):
        super().__init__(view)
        self.state = "dist"
        self.source = None

    def hint(self):
        d = fmt(OffsetTool.distance)
        if self.state == "dist":
            return f"Offset: distância (digite ou clique dois pontos; Enter usa {d} m)"
        if self.state == "pick":
            return f"Offset ({d} m): selecione linha, polilinha, círculo ou arco (Enter encerra)"
        return "Offset: clique do lado desejado"

    def expects(self):
        return "point_value" if self.state == "dist" else "point"

    def wants_snap(self):
        return self.state == "dist"

    def input_value(self, v):
        if self.state != "dist" or v <= 0:
            return False
        OffsetTool.distance = v
        self.state = "pick"
        self._hint_changed()
        return True

    def add_point(self, p):
        if self.state == "dist":
            if not self.points:
                self.points = [p]
                return
            d = QLineF(self.points[0], p).length()
            self.points.clear()
            if d > MIN_SIZE:
                OffsetTool.distance = d
                self.state = "pick"
            return
        if self.state == "pick":
            it = self.view.pick(p, OFFSET_KINDS)
            if it is not None:
                self.source = it.entity
                self.state = "side"
            return
        res = offset_entity(self.source, OffsetTool.distance, _pt(p))
        if res is not None:
            self.doc.undo_stack.push(AddEntities(self.doc, [res], "Offset"))
        self.state = "pick"
        self.source = None

    def preview_path(self, cursor):
        if self.state == "dist" and self.points:
            path = QPainterPath()
            path.moveTo(self.points[0])
            path.lineTo(cursor)
            return path
        if self.state == "side" and self.source is not None:
            res = offset_entity(self.source, OffsetTool.distance, _pt(cursor))
            if res is not None:
                return entity_path(res)
        return QPainterPath()

    def finish(self):
        if self.state == "dist":
            self.state = "pick"
            self._hint_changed()
        else:
            self.view.request_select()

    def cancel(self):
        if self.state == "side":
            self.state = "pick"
            self.source = None
            self._hint_changed()
            self.refresh_preview()
            return True
        return super().cancel()


# --- paisagismo -----------------------------------------------------------

class PlantingTool(DrawTool):
    """Maciço: clique dentro de uma área fechada para plantá-la em malha."""

    name = "planting"
    layout = "triangular"

    def __init__(self, view, species_id: str):
        super().__init__(view)
        self.species = view.catalog.get(species_id)
        self.spacing = self.species.copa

    def hint(self):
        lay = PLANTING_LAYOUTS[PlantingTool.layout].split(" ")[0].lower()
        return (f"Maciço de {self.species.nome_popular} (espaçamento {fmt(self.spacing)} m, {lay}): "
                f"clique dentro de uma área fechada [número = espaçamento; T = triangular, Q = quadrado]")

    def expects(self):
        return "point_value"

    def wants_snap(self):
        return False

    def input_value(self, v):
        if v <= 0:
            return False
        self.spacing = v
        self._hint_changed()
        return True

    def input_text(self, s):
        lay = {"T": "triangular", "Q": "square"}.get(s.upper())
        if lay is None:
            return False
        PlantingTool.layout = lay
        self._hint_changed()
        return True

    def add_point(self, p):
        loops = boundary_at(self.view, p)
        if not loops:
            self.message("Maciço: nenhuma área fechada encontrada nesse ponto.")
            return
        pa = PlantingArea(loops=loops, species=self.species.id, spacing=self.spacing, layout=PlantingTool.layout)
        if pa.count == 0:
            self.message("Maciço: a área é pequena demais para esse espaçamento.")
            return
        self.commit([pa], f"Maciço de {self.species.nome_popular}")
        self.message(f"Maciço: {pa.count} mudas de {self.species.nome_popular} em {fmt(pa.area)} m² "
                     f"({fmt(pa.density, 1)} mudas/m²).")

    def finish(self):
        self.view.request_select()


class PlantRowTool(DrawTool):
    """Plantas em linha ao longo de um caminho existente (cerca viva, alameda)."""

    name = "plantrow"
    from_ends = False

    def __init__(self, view, species_id: str):
        super().__init__(view)
        self.species = view.catalog.get(species_id)
        self.spacing = self.species.copa
        self.path_item = None

    def hint(self):
        if self.path_item is None:
            return f"Plantas em linha ({self.species.nome_popular}): clique numa linha, polilinha, arco ou círculo"
        mode = "das pontas" if PlantRowTool.from_ends else "centralizado"
        n = len(self._positions())
        return (f"Plantas em linha: {n} × {self.species.nome_popular} a cada {fmt(self.spacing)} m ({mode}). "
                f"Enter confirma [número = espaçamento; P = pontas/centralizado]")

    def expects(self):
        return "point" if self.path_item is None else "value"

    def wants_snap(self):
        return False

    def _positions(self):
        if self.path_item is None:
            return []
        return distribute_along(self.path_item.entity, self.spacing, PlantRowTool.from_ends)

    def add_point(self, p):
        if self.path_item is None:
            self.path_item = self.view.pick(p, PATH_KINDS)
        self.refresh_preview()

    def input_value(self, v):
        if self.path_item is None or v <= 0:
            return False
        self.spacing = v
        self._hint_changed()
        self.refresh_preview()
        return True

    def input_text(self, s):
        if s.upper() != "P" or self.path_item is None:
            return False
        PlantRowTool.from_ends = not PlantRowTool.from_ends
        self._hint_changed()
        self.refresh_preview()
        return True

    def refresh_preview(self):
        if self.preview is None:
            return
        path = QPainterPath()
        outline, _ = symbol_paths(self.species.simbolo, self.species.copa / 2)
        for x, y in self._positions():
            path.addPath(outline.translated(x, y))
        self.preview.setPath(path)

    def finish(self):
        if self.path_item is None:
            self.view.request_select()
            return
        sp = self.species
        plants = [Plant(position=pos, species=sp.id, canopy=sp.copa, height=sp.altura) for pos in self._positions()]
        if plants:
            self.commit(plants, f"{len(plants)} × {sp.nome_popular} em linha")
            self.message(f"Plantas em linha: {len(plants)} × {sp.nome_popular}.")
        self.path_item = None
        self.reset()

    def cancel(self):
        if self.path_item is None:
            return False
        self.path_item = None
        self.reset()
        return True


class TrimTool(DrawTool):
    name = "trim"

    def hint(self):
        return "Aparar: clique no trecho a remover (repete; Enter encerra)"

    def wants_snap(self):
        return False

    def add_point(self, p):
        it = self.view.pick(p, TRIM_KINDS)
        if it is None:
            return
        cutters = _cutting_entities(self.view, it.sceneBoundingRect(), it)
        parts = trim_entity(it.entity, _pt(p), cutters)
        if parts is None:
            self.message("Aparar: nenhuma interseção com outros objetos.")
            return
        replace_with(self.doc, it.entity, parts, "Aparar")

    def finish(self):
        self.view.request_select()


class ExtendTool(DrawTool):
    name = "extend"

    def hint(self):
        return "Estender: clique perto da ponta a estender (repete; Enter encerra)"

    def wants_snap(self):
        return False

    def add_point(self, p):
        it = self.view.pick(p, EXTEND_KINDS)
        if it is None:
            return
        view_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        new = extend_entity(it.entity, _pt(p), _cutting_entities(self.view, view_rect, it))
        if new is None:
            self.message("Estender: nenhum limite visível nessa direção.")
            return
        self.doc.undo_stack.push(ReplaceEntities(self.doc, [new], "Estender"))

    def finish(self):
        self.view.request_select()


def replace_with(doc, old, parts, text):
    stack = doc.undo_stack
    stack.beginMacro(text)
    stack.push(RemoveEntities(doc, [old.id]))
    if parts:
        stack.push(AddEntities(doc, parts))
    stack.endMacro()


class LabelTool(EditTool):
    """Rótulo de plantas: texto com a quantidade e linhas de chamada."""

    name = "label"
    label = "Rótulo"

    def entities(self):
        return [e for e in super().entities() if isinstance(e, (Plant, PlantingArea))]

    def on_targets(self):
        if not self.entities():
            self.message("Rótulo: selecione plantas ou maciços.")
            self.view.request_select()

    def step_hint(self):
        return "Rótulo: clique a posição do texto"

    def _lines(self) -> list[str]:
        counts: dict[str, int] = {}
        for e in self.entities():
            counts[e.species] = counts.get(e.species, 0) + (e.count if isinstance(e, PlantingArea) else 1)
        out = []
        for sid, n in counts.items():
            sp = self.view.catalog.get(sid)
            out.append(f"{n} {sp.nome_popular if sp else sid}")
        return out

    def _leaders(self, p: QPointF) -> list[tuple]:
        P = _pt(p)
        segs = []
        for e in self.entities():
            if isinstance(e, Plant):
                c, r = e.position, e.canopy / 2
                d = math.dist(c, P)
                if d <= r:
                    continue
                end = (c[0] + (P[0] - c[0]) * r / d, c[1] + (P[1] - c[1]) * r / d)
            else:
                end = min((nearest_on(pr, P) for pr in e.primitives()), key=lambda q: math.dist(q, P))
            segs.append((P, end))
        return segs

    def preview_path(self, cursor):
        path = QPainterPath()
        if self.selecting:
            return path
        for a, b in self._leaders(cursor):
            path.moveTo(*a)
            path.lineTo(*b)
        h = TextTool.height
        path.addPath(entity_fill(Text(position=(cursor.x() + h * 0.4, cursor.y() + h * 0.4),
                                      text="\n".join(self._lines()), height=h)))
        return path

    def add_point(self, p):
        h = TextTool.height
        ents = [Line(p1=a, p2=b) for a, b in self._leaders(p)]
        ents.append(Text(position=(p.x() + h * 0.4, p.y() + h * 0.4), text="\n".join(self._lines()), height=h))
        self.commit(ents, "Rótulo de plantas")
        self.view.request_select()
