"""Ícones desenhados em código (sem arquivos de recurso)."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from leafdraw.ui import theme
from leafdraw.ui.symbols import paint_symbol

SIZE = 64


def _dot(p: QPainter, x, y, r=5):
    p.save()
    p.setBrush(QBrush(theme.ICON))
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _cube(p: QPainter, face: str | None):
    front = QPolygonF([QPointF(12, 24), QPointF(40, 24), QPointF(40, 52), QPointF(12, 52)])
    top = QPolygonF([QPointF(12, 24), QPointF(24, 12), QPointF(52, 12), QPointF(40, 24)])
    right = QPolygonF([QPointF(40, 24), QPointF(52, 12), QPointF(52, 40), QPointF(40, 52)])
    faces = {"front": front, "top": top, "right": right}
    for name, poly in faces.items():
        p.setBrush(QBrush(QColor(77, 163, 255, 200)) if name == face or face == "all" else Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(theme.ICON, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    if name == "select":
        p.setBrush(QBrush(theme.ICON))
        p.drawPolygon(QPolygonF([QPointF(16, 8), QPointF(16, 50), QPointF(27, 40), QPointF(35, 56),
                                 QPointF(42, 52), QPointF(34, 37), QPointF(48, 36)]))
    elif name == "line":
        p.drawLine(12, 52, 52, 12)
        _dot(p, 12, 52)
        _dot(p, 52, 12)
    elif name == "polyline":
        pts = [QPointF(8, 50), QPointF(22, 18), QPointF(40, 40), QPointF(56, 12)]
        p.drawPolyline(QPolygonF(pts))
        for q in pts:
            _dot(p, q.x(), q.y(), 4)
    elif name == "rect":
        p.drawRect(QRectF(10, 16, 44, 32))
    elif name == "circle":
        p.drawEllipse(QPointF(32, 32), 22, 22)
        _dot(p, 32, 32, 4)
    elif name == "plant":
        p.translate(32, 32)
        paint_symbol(p, "arvore", 26, QColor("#6cc070"))
    elif name == "zoom_extents":
        p.drawRect(QRectF(14, 14, 36, 36))
        for (x1, y1, x2, y2) in ((4, 4, 14, 14), (60, 4, 50, 14), (4, 60, 14, 50), (60, 60, 50, 50)):
            p.drawLine(x1, y1, x2, y2)
    elif name == "layout_2d":
        p.drawRect(QRectF(8, 8, 48, 48))
        p.setPen(QPen(theme.ICON, 2))
        for i in (20, 32, 44):
            p.drawLine(8, i, 56, i)
            p.drawLine(i, 8, i, 56)
    elif name == "layout_3d":
        _cube(p, None)
    elif name == "layout_split":
        p.drawRect(QRectF(6, 12, 24, 40))
        p.drawRect(QRectF(34, 12, 24, 40))
    elif name in ("cam_top", "cam_front", "cam_right"):
        p.setPen(QPen(theme.ICON, 3))
        _cube(p, name[4:])
    elif name == "cam_persp":
        p.setPen(QPen(theme.ICON, 3))
        _cube(p, "all")
    elif name == "layer_add":
        p.drawPolygon(QPolygonF([QPointF(6, 30), QPointF(32, 18), QPointF(58, 30), QPointF(32, 42)]))
        p.drawLine(46, 46, 46, 62)
        p.drawLine(38, 54, 54, 54)
    elif name == "layer_remove":
        p.drawPolygon(QPolygonF([QPointF(6, 30), QPointF(32, 18), QPointF(58, 30), QPointF(32, 42)]))
        p.drawLine(38, 54, 54, 54)
    elif name == "layer_current":
        p.drawPolyline(QPolygonF([QPointF(12, 34), QPointF(26, 48), QPointF(52, 18)]))
    elif name == "arc":
        p.drawArc(QRectF(10, 18, 44, 44), 0, 180 * 16)
        _dot(p, 10, 40, 4)
        _dot(p, 54, 40, 4)
        _dot(p, 32, 18, 4)
    elif name == "text":
        f = p.font()
        f.setPixelSize(44)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "A")
    elif name == "dimension":
        p.setPen(QPen(theme.ICON, 3))
        p.drawLine(10, 50, 10, 22)
        p.drawLine(54, 50, 54, 22)
        p.drawLine(6, 30, 58, 30)
        p.drawLine(5, 35, 15, 25)
        p.drawLine(49, 35, 59, 25)
        f = p.font()
        f.setPixelSize(16)
        p.setFont(f)
        p.drawText(QRectF(10, 4, 44, 22), Qt.AlignmentFlag.AlignCenter, "2,5")
    elif name == "hatch":
        p.drawRect(QRectF(10, 10, 44, 44))
        p.setPen(QPen(theme.ICON, 2))
        p.setClipRect(QRectF(10, 10, 44, 44))
        for k in range(-40, 60, 10):
            p.drawLine(10 + k, 54, 54 + k, 10)
        p.setClipping(False)
    elif name in ("move", "copy"):
        if name == "copy":
            p.setPen(QPen(theme.ICON, 3, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(6, 6, 26, 26))
            p.setPen(pen)
        p.drawRect(QRectF(30, 30, 26, 26) if name == "copy" else QRectF(20, 20, 24, 24))
        if name == "move":
            for (x1, y1, x2, y2) in ((32, 4, 32, 16), (32, 48, 32, 60), (4, 32, 16, 32), (48, 32, 60, 32)):
                p.drawLine(x1, y1, x2, y2)
    elif name == "rotate":
        p.drawArc(QRectF(10, 10, 44, 44), 30 * 16, 280 * 16)
        p.setBrush(QBrush(theme.ICON))
        p.drawPolygon(QPolygonF([QPointF(50, 10), QPointF(56, 24), QPointF(42, 22)]))
    elif name == "scale":
        p.drawRect(QRectF(8, 30, 26, 26))
        p.setPen(QPen(theme.ICON, 3, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(8, 8, 48, 48))
        p.setPen(pen)
        p.drawLine(34, 30, 50, 14)
    elif name == "mirror":
        p.setPen(QPen(theme.ICON, 2, Qt.PenStyle.DashLine))
        p.drawLine(32, 4, 32, 60)
        p.setPen(pen)
        p.drawPolygon(QPolygonF([QPointF(26, 14), QPointF(26, 50), QPointF(8, 50)]))
        p.drawPolygon(QPolygonF([QPointF(38, 14), QPointF(38, 50), QPointF(56, 50)]))
    elif name == "offset":
        p.drawPolyline(QPolygonF([QPointF(8, 50), QPointF(8, 14), QPointF(50, 14)]))
        p.setPen(QPen(theme.ICON, 3, Qt.PenStyle.DashLine))
        p.drawPolyline(QPolygonF([QPointF(20, 56), QPointF(20, 26), QPointF(56, 26)]))
    elif name == "explode":
        for (x1, y1, x2, y2) in ((32, 6, 32, 22), (32, 42, 32, 58), (6, 32, 22, 32), (42, 32, 58, 32),
                                 (14, 14, 22, 22), (50, 50, 42, 42), (14, 50, 22, 42), (50, 14, 42, 22)):
            p.drawLine(x1, y1, x2, y2)
    elif name == "erase":
        p.drawLine(14, 14, 50, 50)
        p.drawLine(50, 14, 14, 50)
    elif name == "distance":
        p.drawRect(QRectF(6, 22, 52, 20))
        p.setPen(QPen(theme.ICON, 2))
        for x in range(12, 56, 8):
            p.drawLine(x, 22, x, 32 if (x // 8) % 2 else 28)
    elif name == "planting":
        p.drawRect(QRectF(6, 6, 52, 52))
        p.setBrush(QBrush(QColor("#6cc070")))
        p.setPen(Qt.PenStyle.NoPen)
        for j, y in enumerate((16, 30, 44)):
            for x in ((16, 30, 44) if j % 2 == 0 else (23, 37, 51))[: 3 if j % 2 == 0 else 2]:
                p.drawEllipse(QPointF(x, y), 5, 5)
    elif name == "plantrow":
        p.drawLine(4, 50, 60, 50)
        p.setBrush(QBrush(QColor("#6cc070")))
        p.setPen(Qt.PenStyle.NoPen)
        for x in (12, 32, 52):
            p.drawEllipse(QPointF(x, 34), 9, 9)
    elif name == "trim":
        p.drawLine(32, 4, 32, 60)
        p.drawLine(4, 32, 26, 32)
        p.setPen(QPen(theme.ICON, 3, Qt.PenStyle.DotLine))
        p.drawLine(38, 32, 60, 32)
    elif name == "extend":
        p.drawLine(54, 4, 54, 60)
        p.drawLine(6, 32, 26, 32)
        p.setPen(QPen(theme.ICON, 3, Qt.PenStyle.DashLine))
        p.drawLine(28, 32, 50, 32)
    elif name == "label":
        p.translate(18, 40)
        paint_symbol(p, "arvore", 14, QColor("#6cc070"))
        p.resetTransform()
        p.setPen(pen)
        p.drawLine(28, 32, 44, 16)
        p.drawLine(44, 16, 60, 16)
    elif name == "schedule":
        p.drawRect(QRectF(8, 8, 48, 48))
        for y in (20, 32, 44):
            p.drawLine(8, y, 56, y)
        p.drawLine(24, 8, 24, 56)
    elif name in ("import", "export"):
        p.drawRect(QRectF(8, 36, 48, 20))
        y0, y1 = (6, 30) if name == "import" else (30, 6)
        p.drawLine(32, y0, 32, y1)
        tip = y1
        d = 8 if name == "import" else -8
        p.drawLine(32, tip, 24, tip - d)
        p.drawLine(32, tip, 40, tip - d)
    p.end()
    return QIcon(pm)


def color_icon(color: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.setPen(QColor(0, 0, 0, 160))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)
