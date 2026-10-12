"""Símbolos 2D de vegetação, desenhados em escala real (raio em metros)."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform

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


def symbol_paths(simbolo: str, radius: float) -> tuple[QPainterPath, QPainterPath]:
    outline, details = _unit_symbol(simbolo)
    t = QTransform.fromScale(radius, radius)
    return t.map(outline), t.map(details)


def paint_symbol(painter: QPainter, simbolo: str, radius: float, color: QColor, outline_color: QColor | None = None):
    outline, details = symbol_paths(simbolo, radius)
    fill = QColor(color)
    fill.setAlpha(FILL_ALPHA.get(simbolo, 80))
    pen = QPen(outline_color or color.lighter(130), 0)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(QBrush(fill))
    painter.drawPath(outline)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(details)


def species_icon(simbolo: str, color: str, size: int = 32) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    paint_symbol(p, simbolo, size * 0.42, QColor(color))
    p.end()
    return QIcon(pm)


def symbol_bounds(radius: float) -> QRectF:
    r = radius * 1.05
    return QRectF(-r, -r, 2 * r, 2 * r)
