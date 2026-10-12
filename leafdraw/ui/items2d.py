"""Itens gráficos do viewport 2D."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QGraphicsItem

from leafdraw.core.entities import Arc, Circle, Dimension, Entity, Hatch, Line, Plant, Polyline, Text
from leafdraw.ui import theme
from leafdraw.ui.symbols import paint_symbol, symbol_bounds, symbol_paths

PICK_TOLERANCE_PX = 6
TEXT_FONT = "Arial"
TILE = 64  # px do ladrilho de hachura


def cosmetic_pen(color, width=0.0, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)
    return pen


# --- texto -----------------------------------------------------------------

@lru_cache(maxsize=4096)
def _unit_text_path(text: str) -> QPainterPath:
    """Texto com altura de maiúscula = 1, Y para cima, linha de base em y=0."""
    font = QFont(TEXT_FONT)
    font.setPixelSize(100)
    cap = QFontMetricsF(font).capHeight() or 70.0
    path = QPainterPath()
    for i, line in enumerate(text.split("\n")):
        path.addText(0, i * Text.LINE_SPACING * cap, font, line)
    return QTransform(1 / cap, 0, 0, -1 / cap, 0, 0).map(path)


def text_path(text: str, height: float, position=(0.0, 0.0), rotation: float = 0.0,
              center: bool = False) -> QPainterPath:
    unit = _unit_text_path(text)
    t = QTransform()
    t.translate(*position)
    t.rotate(rotation)
    t.scale(height, height)
    if center:
        t.translate(-unit.boundingRect().width() / 2, 0)
    return t.map(unit)


# --- hachuras --------------------------------------------------------------

@lru_cache(maxsize=256)
def _hatch_tile(pattern: str, rgba: int) -> QPixmap:
    color = QColor.fromRgba(rgba)
    pm = QPixmap(TILE, TILE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, 2.5))
    T = TILE
    if pattern in ("diagonal", "cross"):
        for k in (-T, 0, T):
            p.drawLine(QPointF(k, T), QPointF(k + T, 0))
        if pattern == "cross":
            for k in (-T, 0, T):
                p.drawLine(QPointF(k, 0), QPointF(k + T, T))
    elif pattern == "horizontal":
        p.drawLine(QPointF(0, T / 2), QPointF(T, T / 2))
    elif pattern == "dots":
        p.setBrush(QBrush(color))
        for x, y in ((16, 16), (48, 48)):
            p.drawEllipse(QPointF(x, y), 2.5, 2.5)
    elif pattern == "grass":
        for x, y in ((14, 20), (44, 12), (30, 46), (56, 52)):
            p.drawLine(QPointF(x, y), QPointF(x - 4, y - 8))
            p.drawLine(QPointF(x, y), QPointF(x, y - 10))
            p.drawLine(QPointF(x, y), QPointF(x + 4, y - 8))
    elif pattern == "gravel":
        for x, y, r in ((12, 14, 5), (40, 10, 4), (52, 38, 6), (24, 44, 4.5), (8, 56, 3)):
            p.drawEllipse(QPointF(x, y), r, r * 0.75)
    p.end()
    return pm


def hatch_brush(pattern: str, color: QColor, scale: float, angle: float) -> QBrush:
    if pattern == "solid":
        c = QColor(color)
        c.setAlpha(150)
        return QBrush(c)
    brush = QBrush(_hatch_tile(pattern, color.rgba()))
    t = QTransform()
    t.rotate(angle)
    t.scale(scale / TILE, scale / TILE)
    brush.setTransform(t)
    return brush


# --- geometria ---------------------------------------------------------------

def entity_path(e: Entity) -> QPainterPath:
    """Traço (linhas) em coordenadas de cena."""
    path = QPainterPath()
    if isinstance(e, Line):
        path.moveTo(*e.p1)
        path.lineTo(*e.p2)
    elif isinstance(e, Polyline) and e.vertices:
        path.moveTo(*e.vertices[0])
        for v in e.vertices[1:]:
            path.lineTo(*v)
        if e.closed:
            path.closeSubpath()
    elif isinstance(e, Circle):
        path.addEllipse(QPointF(*e.center), e.radius, e.radius)
    elif isinstance(e, Arc):
        add_arc(path, e.center, e.radius, e.start, e.sweep)
    elif isinstance(e, Dimension):
        for a, b in e.line_segments():
            path.moveTo(*a)
            path.lineTo(*b)
    return path


def add_arc(path: QPainterPath, center, radius: float, start: float, sweep: float):
    # o Qt mede ângulos com Y para baixo; a cena tem Y para cima, daí os sinais
    rect = QRectF(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)
    path.arcMoveTo(rect, -start)
    path.arcTo(rect, -start, -sweep)


def entity_fill(e: Entity) -> QPainterPath | None:
    if isinstance(e, Text):
        return text_path(e.text, e.height, e.position, e.rotation)
    if isinstance(e, Dimension):
        lay = e.layout()
        return text_path(e.label(), e.text_height, lay["text_center"], lay["angle"], center=True)
    if isinstance(e, Hatch):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for loop in e.loops:
            path.addPolygon(QPolygonF([QPointF(*v) for v in loop]))
            path.closeSubpath()
        return path
    return None


class EntityItem(QGraphicsItem):
    def __init__(self, view, entity: Entity):
        super().__init__()
        self.view = view
        self.entity = entity
        self._stroke = QPainterPath()
        self._fill: QPainterPath | None = None
        self._brush = QBrush()
        self._rect = QRectF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.refresh()

    def set_entity(self, entity: Entity):
        self.entity = entity
        self.refresh()

    def species(self):
        return self.view.catalog.get(self.entity.species) if isinstance(self.entity, Plant) else None

    def refresh(self):
        """Recalcula geometria e estado a partir da entidade e da camada."""
        self.prepareGeometryChange()
        e = self.entity
        layer = self.view.doc.layer_for(e)
        self.color = QColor(e.color) if e.color else QColor(layer.color)
        self._fill = None
        if isinstance(e, Plant):
            sp = self.species()
            self.symbol = sp.simbolo if sp else "arvore"
            self.plant_color = QColor(e.color or (sp.cor if sp else "#6cc070"))
            r = e.canopy / 2
            self._stroke = symbol_paths(self.symbol, r)[0]
            self._rect = symbol_bounds(r)
            self.setPos(*e.position)
            self.setZValue(2 + 1 / (1 + e.height))  # plantas menores por cima
        else:
            self._stroke = entity_path(e)
            self._fill = entity_fill(e)
            if isinstance(e, Hatch):
                self._brush = hatch_brush(e.pattern, self.color, e.scale, e.angle)
            br = self._stroke.boundingRect()
            if self._fill is not None:
                br = br.united(self._fill.boundingRect()) if not self._stroke.isEmpty() else self._fill.boundingRect()
            pad = max(br.width(), br.height(), 1.0) * 0.01
            self._rect = br.adjusted(-pad, -pad, pad, pad)
            self.setPos(0, 0)
            self.setZValue({"hatch": 0.5, "text": 1.5, "dimension": 1.5}.get(e.kind, 1.0))
        self.setVisible(layer.visible)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not layer.locked)
        if layer.locked and self.isSelected():
            self.setSelected(False)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def shape(self) -> QPainterPath:
        if isinstance(self.entity, (Plant, Hatch)):
            return self._fill if self._fill is not None else self._stroke
        path = QPainterPath()
        if not self._stroke.isEmpty():
            stroker = QPainterPathStroker()
            stroker.setWidth(2 * PICK_TOLERANCE_PX * self.view.pixel_size())
            path = stroker.createStroke(self._stroke)
        if self._fill is not None:
            box = QPainterPath()
            box.addRect(self._fill.boundingRect())
            path = path.united(box) if not path.isEmpty() else box
        return path

    def ghost_path(self) -> QPainterPath:
        """Contorno em coordenadas de cena, para prévias de edição."""
        path = QPainterPath(self._stroke)
        if self._fill is not None:
            path.addPath(self._fill)
        return self.sceneTransform().map(path)

    def paint(self, painter, option, widget=None):
        selected = self.isSelected()
        e = self.entity
        if isinstance(e, Plant):
            outline = theme.SELECTION if selected else None
            paint_symbol(painter, self.symbol, e.canopy / 2, self.plant_color, outline)
            if selected:
                painter.setPen(cosmetic_pen(theme.SELECTION, 0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self._stroke.boundingRect())
            return
        color = theme.SELECTION if selected else self.color
        if isinstance(e, Hatch):
            painter.fillPath(self._fill, self._brush)
            if selected:
                painter.setPen(cosmetic_pen(theme.SELECTION, 1.5, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(self._fill)
            return
        if not self._stroke.isEmpty():
            painter.setPen(cosmetic_pen(color, 2 if selected else 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._stroke)
        if self._fill is not None:
            painter.fillPath(self._fill, QBrush(color))


class MoveGizmo(QGraphicsItem):
    """Gizmo de translação. Desenhado em pixels (ignora a escala da vista).

    Coordenadas locais têm Y para baixo (tela), por isso o eixo Y aponta para -y.
    """

    AXIS_LEN = 62
    HEAD = 14

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(1000)
        self.hover: str | None = None

    def boundingRect(self):
        n = self.AXIS_LEN + self.HEAD + 4
        return QRectF(-12, -n, n + 12, n + 12)

    def set_hover(self, handle: str | None):
        if handle != self.hover:
            self.hover = handle
            self.update()

    def handle_at(self, view, view_pos: QPointF) -> str | None:
        if not self.isVisible():
            return None
        c = QPointF(view.mapFromScene(self.pos()))
        dx = view_pos.x() - c.x()
        dy = view_pos.y() - c.y()
        end = self.AXIS_LEN + self.HEAD
        if abs(dx) <= 8 and abs(dy) <= 8:
            return "xy"
        if 14 <= dx <= 32 and -32 <= dy <= -14:
            return "xy"
        if 8 < dx <= end and abs(dy) <= 7:
            return "x"
        if abs(dx) <= 7 and -end <= dy < -8:
            return "y"
        return None

    def _color(self, handle, base):
        return QColor("#ffd23f") if self.hover == handle else QColor(base)

    def paint(self, painter, option, widget=None):
        L, H = self.AXIS_LEN, self.HEAD
        painter.setPen(Qt.PenStyle.NoPen)
        plane = self._color("xy", "#4da3ff")
        plane.setAlpha(110)
        painter.setBrush(QBrush(plane))
        painter.drawRect(QRectF(14, -32, 18, 18))
        for handle, color, tip in (("x", "#e05555", QPointF(L, 0)), ("y", "#55c055", QPointF(0, -L))):
            c = self._color(handle, color)
            painter.setPen(QPen(c, 3))
            painter.drawLine(QPointF(0, 0), tip)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(c))
            if handle == "x":
                head = [QPointF(L + H, 0), QPointF(L, -6), QPointF(L, 6)]
            else:
                head = [QPointF(0, -L - H), QPointF(-6, -L), QPointF(6, -L)]
            painter.drawPolygon(QPolygonF(head))
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QBrush(self._color("xy", "#f0f0f0")))
        painter.drawRect(QRectF(-5, -5, 10, 10))


SNAP_LABELS = {"end": "Extremidade", "mid": "Ponto médio", "center": "Centro", "quad": "Quadrante",
               "int": "Interseção", "perp": "Perpendicular", "near": "Próximo"}


class SnapMarker(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(2000)
        self.kind = "end"

    def set_kind(self, kind: str):
        if kind != self.kind:
            self.kind = kind
            self.setToolTip(SNAP_LABELS.get(kind, ""))
            self.update()

    def boundingRect(self):
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(theme.SNAP, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        k = self.kind
        if k == "mid":
            h = 7
            painter.drawPolygon(QPolygonF([QPointF(0, -h), QPointF(h * math.sqrt(3) / 2, h / 2),
                                           QPointF(-h * math.sqrt(3) / 2, h / 2)]))
        elif k == "center":
            painter.drawEllipse(QPointF(0, 0), 6, 6)
        elif k == "quad":
            painter.drawPolygon(QPolygonF([QPointF(0, -7), QPointF(7, 0), QPointF(0, 7), QPointF(-7, 0)]))
        elif k == "int":
            painter.drawLine(QPointF(-6, -6), QPointF(6, 6))
            painter.drawLine(QPointF(-6, 6), QPointF(6, -6))
        elif k == "perp":
            painter.drawLine(QPointF(-7, 6), QPointF(7, 6))
            painter.drawLine(QPointF(0, 6), QPointF(0, -7))
        elif k == "near":
            painter.drawPolygon(QPolygonF([QPointF(-6, -6), QPointF(6, -6), QPointF(-6, 6), QPointF(6, 6)]))
        else:
            painter.drawRect(QRectF(-6, -6, 12, 12))
