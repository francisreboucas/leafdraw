"""Símbolos 2D de vegetação, desenhados em escala real (raio em metros)."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform

from leafdraw.core.elevation import TRUNK_COLOR, custom_plan_shapes, species_elevation

# Opacidade do preenchimento por símbolo.
FILL_ALPHA = {"arvore": 70, "palmeira": 35, "arbusto": 140, "forracao": 90}


def _lobed(r: float, lobes: int, bulge: float) -> QPainterPath:
    path = QPainterPath()
    step = 2 * math.pi / lobes
    path.moveTo(r, 0)
    for i in range(lobes):
        am = (i + 0.5) * step
        a1 = (i + 1) * step
        path.quadTo(r * bulge * math.cos(am), r * bulge * math.sin(am), r * math.cos(a1), r * math.sin(a1))
    path.closeSubpath()
    return path


def _circle(r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(0, 0), r, r)
    return path


@lru_cache(maxsize=256)
def _unit_symbol(simbolo: str) -> tuple[QPainterPath, QPainterPath]:
    """(contorno, detalhes) para raio 1, centrados na origem."""
    details = QPainterPath()
    if simbolo == "palmeira":
        outline = _circle(1.0)
        fronds = 9
        for i in range(fronds):
            a = 2 * math.pi * i / fronds
            ca, sa = math.cos(a), math.sin(a)
            details.moveTo(0, 0)
            details.lineTo(0.95 * ca, 0.95 * sa)
            for t in (0.35, 0.55, 0.75):
                for side in (-1, 1):
                    b = a + side * math.radians(150)
                    details.moveTo(t * ca, t * sa)
                    details.lineTo(t * ca + 0.18 * math.cos(b), t * sa + 0.18 * math.sin(b))
    elif simbolo == "arbusto":
        outline = _lobed(0.92, 22, 1.09)
    elif simbolo == "forracao":
        outline = _circle(1.0)
        for i in range(5):
            a = 2 * math.pi * i / 5 + 0.3
            details.addEllipse(QPointF(0.5 * math.cos(a), 0.5 * math.sin(a)), 0.09, 0.09)
        details.addEllipse(QPointF(0, 0), 0.09, 0.09)
    else:  # arvore
        outline = _lobed(0.86, 14, 1.16)
        details.addEllipse(QPointF(0, 0), 0.06, 0.06)
        details.moveTo(-0.14, 0)
        details.lineTo(0.14, 0)
        details.moveTo(0, -0.14)
        details.lineTo(0, 0.14)
    return outline, details


def shape_path(shape) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in shape.pts]))
    if shape.closed:
        path.closeSubpath()
    return path


@lru_cache(maxsize=256)
def _unit_custom(drawing) -> tuple[QPainterPath, QPainterPath]:
    outline, details = QPainterPath(), QPainterPath()
    outline.setFillRule(Qt.FillRule.WindingFill)
    for sh in custom_plan_shapes(drawing, 1.0):
        (outline if sh.closed else details).addPath(shape_path(sh))
    return outline, details


def symbol_paths(simbolo: str, radius: float, drawing=None) -> tuple[QPainterPath, QPainterPath]:
    """(contorno, detalhes) do símbolo em planta; ``drawing`` = bloco próprio da espécie."""
    outline, details = _unit_custom(drawing) if drawing else _unit_symbol(simbolo)
    t = QTransform.fromScale(radius, radius)
    return t.map(outline), t.map(details)


def plan_args(sp) -> tuple[str, object]:
    """(símbolo, desenho próprio) da versão Planta de uma espécie (ou do padrão, sem espécie)."""
    return (sp.simbolo, sp.desenho_planta) if sp else ("arvore", None)


def paint_symbol(painter: QPainter, simbolo: str, radius: float, color: QColor, outline_color: QColor | None = None,
                 pen_width: float | None = None, drawing=None):
    """``pen_width`` em unidades do painter (impressão); None = traço fino de tela."""
    outline, details = symbol_paths(simbolo, radius, drawing)
    fill = QColor(color)
    fill.setAlpha(FILL_ALPHA.get(simbolo, 80))
    if pen_width is None:
        pen = QPen(outline_color or color.lighter(130), 0)
        pen.setCosmetic(True)
    else:
        pen = QPen(outline_color or color.darker(130), pen_width)
    painter.setPen(pen)
    painter.setBrush(QBrush(fill))
    painter.drawPath(outline)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(details)


def species_icon(simbolo: str, color: str, size: int = 32, drawing=None) -> QIcon:
    return QIcon(plan_pixmap(simbolo, color, size, drawing))


def plan_pixmap(simbolo: str, color: str, size: int = 32, drawing=None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    p.scale(1, -1)  # símbolos estão com Y para cima
    paint_symbol(p, simbolo, size * 0.42, QColor(color), drawing=drawing)
    p.end()
    return pm


def sp_icon(sp, size: int = 32) -> QIcon:
    """Ícone da versão Planta da espécie."""
    return species_icon(sp.simbolo, sp.cor, size, sp.desenho_planta)


# --- versão Vista (elevação) ----------------------------------------------------------

def paint_shapes(painter: QPainter, shapes, color: QColor, pen_width: float | None = None, fade: float = 0.0,
                 outline_color: QColor | None = None, print_mode: bool = False):
    """Desenha silhuetas de vista (Y para cima). ``fade`` 0..1 clareia o que está mais ao fundo."""
    leaf = QColor(color)
    trunk = QColor(TRUNK_COLOR)
    if print_mode:  # no papel, o fundo clareia misturando com branco (sem transparência)
        k = 0.25 + 0.5 * fade
        leaf = _mix(leaf, QColor("white"), k)
        trunk = _mix(trunk, QColor("white"), 0.2 + 0.5 * fade)
    else:
        leaf.setAlpha(int(225 - 120 * fade))
        trunk.setAlpha(int(235 - 120 * fade))
    line = QColor(outline_color) if outline_color is not None else (
        color.darker(150) if print_mode else color.lighter(135))
    if pen_width is None:
        pen = QPen(line, 0)
        pen.setCosmetic(True)
    else:
        pen = QPen(line, pen_width)
    for sh in shapes:
        path = shape_path(sh)
        painter.setPen(pen)
        if sh.closed and sh.fill:
            painter.setBrush(QBrush(trunk if sh.fill == "tronco" else leaf))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


def _mix(a: QColor, b: QColor, k: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
                           a.blueF() + (b.blueF() - a.blueF()) * k)


def elevation_pixmap(sp, w_px: int, h_px: int) -> QPixmap:
    """Prévia da versão Vista da espécie no tamanho dado (mantém a proporção altura/copa)."""
    pm = QPixmap(w_px, h_px)
    pm.fill(Qt.GlobalColor.transparent)
    if sp is None:
        return pm
    shapes = species_elevation(sp, sp.copa, sp.altura, sp.id)
    pts = [q for sh in shapes for q in sh.pts]
    x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
    y0, y1 = min(q[1] for q in pts), max(q[1] for q in pts)
    k = min((w_px - 4) / max(x1 - x0, 1e-6), (h_px - 4) / max(y1 - y0, 1e-6))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(w_px / 2 - (x0 + x1) / 2 * k, h_px - 2 + y0 * k)
    p.scale(k, -k)
    paint_shapes(p, shapes, QColor(sp.cor))
    p.end()
    return pm


def symbol_bounds(radius: float) -> QRectF:
    r = radius * 1.05
    return QRectF(-r, -r, 2 * r, 2 * r)
