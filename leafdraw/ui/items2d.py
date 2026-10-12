"""Itens gráficos do viewport 2D."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QGraphicsItem

from leafdraw.core.elevation import compute_elevation, marker_geometry, title_position
from leafdraw.core.entities import (Arc, Circle, Dimension, ElevationView, Entity, Hatch, Line, Plant, PlantingArea,
                                    Polyline, SpotHeight, Text)
from leafdraw.core.terrain import document_terrain
from leafdraw.ui import theme
from leafdraw.ui.symbols import paint_shapes, paint_symbol, plan_args, symbol_bounds, symbol_paths

PICK_TOLERANCE_PX = 6
MAX_PLANTING_DOTS = 5000  # acima disso o maciço é desenhado só com preenchimento
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
    elif isinstance(e, SpotHeight):
        x, y = e.position
        s = e.text_height * 0.5
        path.moveTo(x - s, y)
        path.lineTo(x + s, y)
        path.moveTo(x, y - s)
        path.lineTo(x, y + s)
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
    if isinstance(e, (Hatch, PlantingArea)):
        return loops_path(e.loops)
    if isinstance(e, SpotHeight):
        h = e.text_height
        return text_path(e.label(), h, (e.position[0] + h * 0.6, e.position[1] + h * 0.3))
    return None


def loops_path(loops) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for loop in loops:
        path.addPolygon(QPolygonF([QPointF(*v) for v in loop]))
        path.closeSubpath()
    return path


def planting_dots(e: PlantingArea, radius: float) -> QPainterPath:
    path = QPainterPath()
    if e.area * e.density <= MAX_PLANTING_DOTS:
        for x, y in e.points():
            path.addEllipse(QPointF(x, y), radius, radius)
    return path


# --- vista (elevação) ---------------------------------------------------------

def elevation_data(doc, catalog, ev: ElevationView):
    return compute_elevation(ev, doc.entities.values(), lambda e: doc.layer_for(e).visible, catalog,
                             document_terrain(doc))


def elevation_box(ev: ElevationView, data) -> QPainterPath:
    """Retângulo que envolve o desenho da vista (com o título)."""
    path = QPainterPath()
    b = data.bounds() if data else None
    if b is not None:
        _tx, ty = title_position(ev, data)
        path.addRect(QRectF(QPointF(min(b[0], ev.origin[0]), min(b[1], ty - ev.text_height)),
                            QPointF(max(b[2], ev.origin[0] + ev.length), b[3])))
    return path


def paint_elevation(painter: QPainter, ev: ElevationView, data, color: QColor, lw: float | None = None,
                    print_mode: bool = False, selected: bool = False):
    """Desenha marca de corte, perfil do terreno, plantas (do fundo para a frente) e título.

    ``lw``: espessura base em unidades do modelo (impressão); None = traços de tela.
    """
    def pen(k: float, style=Qt.PenStyle.SolidLine) -> QPen:
        if lw is None:
            return cosmetic_pen(color, 1.2 * k, style)
        return QPen(color, lw * k, style, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin)

    mk = marker_geometry(ev)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen(1.0, Qt.PenStyle.DashDotLine))
    painter.drawLine(QPointF(*mk["line"][0]), QPointF(*mk["line"][1]))
    painter.setPen(pen(1.0))
    painter.setBrush(QBrush(color))
    for a, tip, b in mk["arrows"]:
        painter.drawPolygon(QPolygonF([QPointF(*a), QPointF(*tip), QPointF(*b)]))
    for pos in mk["labels"]:
        painter.fillPath(text_path(ev.name, ev.text_height, pos), QBrush(color))
    if data is None:
        return
    for pl in data.plants:
        paint_shapes(painter, pl.shapes, QColor(pl.color), None if lw is None else lw * 0.5,
                     fade=pl.dist / data.depth_range if data.depth_range else 0.0,
                     outline_color=theme.SELECTION if selected else None, print_mode=print_mode)
    if data.profile:
        prof = QPainterPath()
        prof.moveTo(*data.profile[0])
        for q in data.profile[1:]:
            prof.lineTo(*q)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen(2.2))
        painter.drawPath(prof)
    tx, ty = title_position(ev, data)
    title = text_path(f"VISTA {ev.name}", ev.text_height, (tx, ty), center=True)
    painter.fillPath(title, QBrush(color))
    w = title.boundingRect().width()
    painter.setPen(pen(1.5))
    painter.drawLine(QPointF(tx - w / 2, ty - ev.text_height * 0.45), QPointF(tx + w / 2, ty - ev.text_height * 0.45))


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
        sid = getattr(self.entity, "species", None)
        return self.view.catalog.get(sid) if sid else None

    def refresh(self):
        """Recalcula geometria e estado a partir da entidade e da camada."""
        self.prepareGeometryChange()
        e = self.entity
        layer = self.view.doc.layer_for(e)
        self.color = QColor(e.color) if e.color else QColor(layer.color)
        self._fill = None
        if isinstance(e, Plant):
            sp = self.species()
            self.symbol, self.drawing = plan_args(sp)
            self.plant_color = QColor(e.color or (sp.cor if sp else "#6cc070"))
            r = e.canopy / 2
            self._stroke = symbol_paths(self.symbol, r, self.drawing)[0]
            self._rect = symbol_bounds(r)
            self.setPos(*e.position)
            self.setZValue(2 + 1 / (1 + e.height))  # plantas menores por cima
        elif isinstance(e, ElevationView):
            self._data = elevation_data(self.view.doc, self.view.catalog, e)
            self._stroke = entity_path(Line(p1=e.p1, p2=e.p2))
            self._fill = elevation_box(e, self._data)
            br = self._stroke.boundingRect().united(self._fill.boundingRect())
            pad = max(e.text_height * 3, 0.5)
            self._rect = br.adjusted(-pad, -pad, pad, pad)
            self.setPos(0, 0)
            self.setZValue(1.0)
        elif isinstance(e, PlantingArea):
            sp = self.species()
            self.plant_color = QColor(e.color or (sp.cor if sp else "#6cc070"))
            self._fill = loops_path(e.loops)
            self._stroke = QPainterPath(self._fill)
            r = min(e.spacing * 0.38, (sp.copa / 2) if sp else e.spacing * 0.38)
            self._dots = planting_dots(e, r)
            br = self._fill.boundingRect()
            pad = max(br.width(), br.height(), 1.0) * 0.01
            self._rect = br.adjusted(-pad, -pad, pad, pad)
            self.setPos(0, 0)
            self.setZValue(0.7)
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
            self.setZValue({"hatch": 0.5, "text": 1.5, "dimension": 1.5, "spot": 1.5}.get(e.kind, 1.0))
        self.setVisible(layer.visible)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not layer.locked)
        if layer.locked and self.isSelected():
            self.setSelected(False)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def shape(self) -> QPainterPath:
        if isinstance(self.entity, (Plant, Hatch, PlantingArea)):
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
            paint_symbol(painter, self.symbol, e.canopy / 2, self.plant_color, outline, drawing=self.drawing)
            if selected:
                painter.setPen(cosmetic_pen(theme.SELECTION, 0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self._stroke.boundingRect())
            return
        color = theme.SELECTION if selected else self.color
        if isinstance(e, ElevationView):
            paint_elevation(painter, e, self._data, color, selected=selected)
            if selected:
                painter.setPen(cosmetic_pen(theme.SELECTION, 0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(self._fill)
            return
        if isinstance(e, PlantingArea):
            c = QColor(self.plant_color)
            c.setAlpha(40)
            painter.fillPath(self._fill, QBrush(c))
            c.setAlpha(170)
            painter.fillPath(self._dots, QBrush(c))
            painter.setPen(cosmetic_pen(theme.SELECTION if selected else self.plant_color,
                                        2 if selected else 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._stroke)
            return
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
