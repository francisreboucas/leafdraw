"""Desenho de folhas de impressão — o mesmo código serve a tela e o PDF.

Unidades do painter: milímetros do papel, Y para baixo. Dentro das janelas de
vista o painter passa para metros do modelo, Y para cima.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF

from leafdraw.core.entities import Dimension, ElevationView, Hatch, Plant, PlantingArea, Text
from leafdraw.core.schedule import area_schedule, plant_schedule
from leafdraw.core.sheets import (NorthElement, PlantTableElement, ScaleBarElement, Sheet, SheetElement,
                                  TextElement, TitleBlockElement, ViewportElement, nice_bar_length)
from leafdraw.ui.items2d import (TEXT_FONT, elevation_data, entity_fill, entity_path, hatch_brush, loops_path,
                                 paint_elevation, planting_dots)
from leafdraw.ui.symbols import paint_symbol, plan_args

BLACK = QColor(0, 0, 0)
GREY = QColor(110, 110, 110)
MIN_LW = 0.09  # mm
PRINT_DPI_3D = 200


@dataclass
class RenderContext:
    doc: object
    catalog: object
    render3d: Callable[[ViewportElement, int, int], QImage | None] | None = None
    sheet_number: tuple[int, int] = (1, 1)  # (n, total)


def print_color(color: str | QColor) -> QColor:
    """Cores muito claras (feitas para o fundo escuro da tela) saem pretas no papel."""
    c = QColor(color)
    return BLACK if c.lightnessF() > 0.80 else c


def pen_mm(color, width_mm: float, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(QColor(color), width_mm, style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    return pen


# --- texto no papel ----------------------------------------------------------

@lru_cache(maxsize=2048)
def _paper_text(text: str, bold: bool) -> tuple[QPainterPath, float]:
    font = QFont(TEXT_FONT)
    font.setPixelSize(100)
    font.setBold(bold)
    cap = QFontMetricsF(font).capHeight() or 70.0
    path = QPainterPath()
    for i, line in enumerate(text.split("\n")):
        path.addText(0, i * 1.6 * cap, font, line)
    return path, cap


def text_width(text: str, h: float, bold: bool = False) -> float:
    path, cap = _paper_text(text, bold)
    return path.boundingRect().width() * h / cap


def draw_text(painter: QPainter, x: float, y: float, text: str, h: float, align: str = "left",
              bold: bool = False, color: QColor = BLACK, max_w: float | None = None):
    """Texto com altura de maiúscula ``h`` (mm); ``y`` é a linha de base da 1ª linha."""
    if not text:
        return
    path, cap = _paper_text(text, bold)
    k = h / cap
    w = path.boundingRect().width() * k
    if max_w is not None and w > max_w > 0:  # comprime na horizontal para caber
        kx = k * max_w / w
        w = max_w
    else:
        kx = k
    dx = {"left": 0.0, "center": -w / 2, "right": -w}[align]
    painter.save()
    painter.translate(x + dx, y)
    painter.scale(kx, k)
    painter.fillPath(path, QBrush(color))
    painter.restore()


# --- folha ---------------------------------------------------------------------

def draw_sheet(painter: QPainter, sheet: Sheet, ctx: RenderContext, paper: bool = True):
    W, H = sheet.size
    if paper:
        painter.fillRect(QRectF(0, 0, W, H), Qt.GlobalColor.white)
    fx, fy, fw, fh = sheet.frame_rect()
    painter.setPen(pen_mm(BLACK, 0.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(fx, fy, fw, fh))
    for el in sheet.elements:
        painter.save()
        painter.translate(el.x, el.y)
        draw_element(painter, el, sheet, ctx)
        painter.restore()


def draw_element(painter: QPainter, el: SheetElement, sheet: Sheet, ctx: RenderContext):
    """Desenha um elemento com origem no seu canto superior esquerdo."""
    if isinstance(el, ViewportElement):
        draw_viewport(painter, el, ctx)
    elif isinstance(el, TitleBlockElement):
        draw_titleblock(painter, el, sheet, ctx)
    elif isinstance(el, PlantTableElement):
        draw_plant_table(painter, el, ctx)
    elif isinstance(el, TextElement):
        draw_text(painter, 0, el.text_height, el.text, el.text_height, bold=el.bold)
    elif isinstance(el, NorthElement):
        draw_north(painter, el)
    elif isinstance(el, ScaleBarElement):
        draw_scalebar(painter, el, sheet)


# --- janela de vista ---------------------------------------------------------------

def draw_viewport(painter: QPainter, vp: ViewportElement, ctx: RenderContext):
    rect = QRectF(0, 0, vp.w, vp.h)
    painter.save()
    painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    if vp.mode == "3d":
        img = None
        if ctx.render3d is not None:
            px_w = max(1, int(vp.w / 25.4 * PRINT_DPI_3D))
            px_h = max(1, int(vp.h / 25.4 * PRINT_DPI_3D))
            img = ctx.render3d(vp, px_w, px_h)
        if img is not None and not img.isNull():
            painter.drawImage(rect, img)
        else:
            painter.fillRect(rect, QColor(225, 230, 235))
            draw_text(painter, vp.w / 2, vp.h / 2, "Vista 3D (abra a aba Modelo uma vez para gerar)", 3,
                      align="center", color=GREY)
    else:
        k = vp.mm_per_m
        cx, cy = vp.center
        painter.translate(vp.w / 2, vp.h / 2)
        painter.scale(k, -k)
        painter.translate(-cx, -cy)
        x0, y0, x1, y1 = vp.model_rect()
        hidden = set(vp.hidden_layers)
        doc = ctx.doc
        ordered = sorted(doc.entities.values(), key=_z_order)
        for e in ordered:
            layer = doc.layer_for(e)
            if not layer.visible or layer.id in hidden:
                continue
            if isinstance(e, ElevationView):  # o tamanho do desenho só se sabe depois de montá-lo
                paint_elevation(painter, e, elevation_data(doc, ctx.catalog, e),
                                print_color(e.color or layer.color), lw=max(layer.lineweight, MIN_LW) / k,
                                print_mode=True)
                continue
            b = e.bounds()
            if b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
                continue
            draw_model_entity(painter, e, layer, ctx.catalog, k)
    painter.restore()
    if vp.frame:
        painter.setPen(pen_mm(BLACK, 0.25))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)


def _z_order(e) -> float:
    if isinstance(e, Hatch):
        return 0.0
    if isinstance(e, PlantingArea):
        return 1.0
    if isinstance(e, Plant):
        return 3.0 + 1 / (1 + e.height)
    return 2.0


def draw_model_entity(painter: QPainter, e, layer, catalog, k: float):
    """Desenha uma entidade em coordenadas do modelo; ``k`` = mm de papel por metro."""
    lw = max(layer.lineweight, MIN_LW) / k
    color = print_color(e.color or layer.color)
    if isinstance(e, Plant):
        sp = catalog.get(e.species)
        painter.save()
        painter.translate(*e.position)
        simbolo, drawing = plan_args(sp)
        paint_symbol(painter, simbolo, e.canopy / 2, QColor(e.color or (sp.cor if sp else "#6cc070")),
                     pen_width=0.13 / k, drawing=drawing)
        painter.restore()
    elif isinstance(e, PlantingArea):
        sp = catalog.get(e.species)
        c = QColor(e.color or (sp.cor if sp else "#6cc070"))
        fill = loops_path(e.loops)
        c.setAlpha(45)
        painter.fillPath(fill, QBrush(c))
        c.setAlpha(200)
        r = min(e.spacing * 0.38, sp.copa / 2 if sp else e.spacing * 0.38)
        painter.fillPath(planting_dots(e, r), QBrush(c))
        painter.setPen(pen_mm(c.darker(140), lw, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(fill)
    elif isinstance(e, Hatch):
        painter.fillPath(entity_fill(e), hatch_brush(e.pattern, color, e.scale, e.angle))
    elif isinstance(e, Text):
        painter.fillPath(entity_fill(e), QBrush(color))
    else:
        path = entity_path(e)
        painter.setPen(pen_mm(color, 0.13 / k if isinstance(e, Dimension) else lw))  # cotas sempre finas
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        fill = entity_fill(e)
        if fill is not None:
            painter.fillPath(fill, QBrush(color))


# --- carimbo ---------------------------------------------------------------------

def draw_titleblock(painter: QPainter, el: TitleBlockElement, sheet: Sheet, ctx: RenderContext):
    info = ctx.doc.project
    w, h = el.w, el.h
    rows = [0.27, 0.17, 0.22, 0.17, 0.17]
    ys = [0.0]
    for f in rows:
        ys.append(ys[-1] + f * h)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen_mm(BLACK, 0.18))
    for y in ys[1:-1]:
        painter.drawLine(QPointF(0, y), QPointF(w, y))
    scale = sheet.main_scale()
    n, total = ctx.sheet_number
    cells = [
        [("PROJETO", info.get("projeto", ""), 4.0, 1.0)],
        [("CLIENTE", info.get("cliente", ""), 2.2, 0.5), ("ENDEREÇO", info.get("endereco", ""), 2.2, 0.5)],
        [("CONTEÚDO", sheet.name, 3.2, 1.0)],
        [("RESPONSÁVEL TÉCNICO", info.get("autor", ""), 2.2, 0.62), ("REGISTRO", info.get("registro", ""), 2.2, 0.38)],
        [("ESCALA", f"1:{scale}" if scale else "INDICADA", 2.5, 0.25),
         ("DATA", info.get("data") or date.today().strftime("%d/%m/%Y"), 2.5, 0.25),
         ("REVISÃO", info.get("revisao", "") or "00", 2.5, 0.2),
         ("PRANCHA", f"{n:02d}/{total:02d}", 3.0, 0.3)],
    ]
    for r, row in enumerate(cells):
        y0, y1 = ys[r], ys[r + 1]
        x = 0.0
        for label, value, vh, frac in row:
            cw = w * frac
            if x > 0:
                painter.setPen(pen_mm(BLACK, 0.18))
                painter.drawLine(QPointF(x, y0), QPointF(x, y1))
            draw_text(painter, x + 1.5, y0 + 2.6, label, 1.4, color=GREY)
            draw_text(painter, x + 1.5, y1 - (y1 - y0 - vh) / 2 + 0.6, value, vh, bold=(label in ("PROJETO", "CONTEÚDO")),
                      max_w=cw - 3)
            x += cw
    painter.setPen(pen_mm(BLACK, 0.35))
    painter.drawRect(QRectF(0, 0, w, h))


# --- quadro de vegetação ---------------------------------------------------------

def plant_table_height(el: PlantTableElement, ctx: RenderContext) -> float:
    return draw_plant_table(None, el, ctx)


def draw_plant_table(painter: QPainter | None, el: PlantTableElement, ctx: RenderContext) -> float:
    """Desenha o quadro e devolve a altura usada (mm). Com ``painter=None`` só mede."""
    th = el.text_height
    rh = th * 2.6
    w = el.w
    rows = plant_schedule(ctx.doc, ctx.catalog)
    areas = area_schedule(ctx.doc) if el.show_areas else []
    widths = [0.08, 0.25, 0.29, 0.10, 0.09, 0.09, 0.10]
    xs = [0.0]
    for f in widths:
        xs.append(xs[-1] + f * w)
    height = rh * 1.3 + rh * (2 + len(rows))
    if areas:
        height += rh * (1 + len(areas))
    if painter is None:
        return height

    painter.save()
    painter.setClipRect(QRectF(0, 0, w, max(el.h, 1)), Qt.ClipOperation.IntersectClip)
    y = 0.0
    thin, thick = pen_mm(BLACK, 0.13), pen_mm(BLACK, 0.35)

    def hline(yy, pen=thin):
        painter.setPen(pen)
        painter.drawLine(QPointF(0, yy), QPointF(w, yy))

    def vlines(y0, y1):
        painter.setPen(thin)
        for x in xs[1:-1]:
            painter.drawLine(QPointF(x, y0), QPointF(x, y1))

    draw_text(painter, w / 2, y + rh * 1.3 * 0.68, el.title, th * 1.25, align="center", bold=True)
    y += rh * 1.3
    hline(y, thick)
    heads = ["", "NOME POPULAR", "NOME CIENTÍFICO", "ORIGEM", "ALT. (m)", "COPA (m)", "QTD."]
    top_rows = y
    for i, t in enumerate(heads):
        draw_text(painter, (xs[i] + xs[i + 1]) / 2, y + rh * 0.68, t, th * 0.8, align="center", bold=True,
                  max_w=xs[i + 1] - xs[i] - 1)
    y += rh
    hline(y)
    for r in rows:
        sp = ctx.catalog.get(r.species)
        if sp is not None:
            painter.save()
            painter.translate((xs[0] + xs[1]) / 2, y + rh / 2)
            painter.scale(1, -1)  # símbolos estão com Y para cima
            paint_symbol(painter, sp.simbolo, rh * 0.38, QColor(sp.cor), pen_width=0.1, drawing=sp.desenho_planta)
            painter.restore()
        base = y + rh * 0.68
        draw_text(painter, xs[1] + 1.2, base, r.nome_popular, th, max_w=xs[2] - xs[1] - 2)
        f = th * 0.95
        draw_text(painter, xs[2] + 1.2, base, r.nome_cientifico, f, max_w=xs[3] - xs[2] - 2, color=QColor(40, 40, 40))
        draw_text(painter, (xs[3] + xs[4]) / 2, base, r.origem, f, align="center", max_w=xs[4] - xs[3] - 1)
        draw_text(painter, (xs[4] + xs[5]) / 2, base, _n(r.altura), th, align="center")
        draw_text(painter, (xs[5] + xs[6]) / 2, base, _n(r.copa), th, align="center")
        draw_text(painter, xs[-1] - 1.5, base, str(r.total), th, align="right")
        y += rh
        hline(y)
    draw_text(painter, xs[-2] - 1.5, y + rh * 0.68, "TOTAL DE MUDAS", th, align="right", bold=True)
    draw_text(painter, xs[-1] - 1.5, y + rh * 0.68, str(sum(r.total for r in rows)), th, align="right", bold=True)
    vlines(top_rows, y)
    y += rh
    hline(y, thick)
    if areas:
        draw_text(painter, xs[1] + 1.2, y + rh * 0.68, "REVESTIMENTOS", th, bold=True)
        draw_text(painter, xs[-1] - 1.5, y + rh * 0.68, "ÁREA (m²)", th * 0.8, align="right", bold=True)
        y += rh
        hline(y)
        for a in areas:
            draw_text(painter, xs[1] + 1.2, y + rh * 0.68, a.label, th)
            draw_text(painter, xs[-1] - 1.5, y + rh * 0.68, _n(a.area), th, align="right")
            y += rh
            hline(y)
    painter.setPen(thick)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(0, 0, w, y))
    painter.restore()
    return y


def _n(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --- norte e escala gráfica --------------------------------------------------------

def draw_north(painter: QPainter, el: NorthElement):
    r = min(el.w, el.h * 0.8) / 2
    c = QPointF(el.w / 2, el.h - r - 0.5)
    painter.save()
    painter.translate(c)
    painter.setPen(pen_mm(BLACK, 0.25))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(0, 0), r, r)
    painter.rotate(-el.rotation)
    a = r * 0.92
    painter.setBrush(QBrush(BLACK))
    painter.drawPolygon(QPolygonF([QPointF(0, -a), QPointF(r * 0.28, a * 0.55), QPointF(0, a * 0.3)]))
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawPolygon(QPolygonF([QPointF(0, -a), QPointF(-r * 0.28, a * 0.55), QPointF(0, a * 0.3)]))
    draw_text(painter, 0, -r - 1.2, "N", max(2.0, r * 0.45), align="center", bold=True)
    painter.restore()


def draw_scalebar(painter: QPainter, el: ScaleBarElement, sheet: Sheet):
    vps = sheet.viewports()
    vp = next((v for v in vps if v.id == el.viewport_id), vps[0] if vps else None)
    if vp is None:
        draw_text(painter, 0, 4, "Escala gráfica: sem janela de vista", 2, color=GREY)
        return
    length = el.length_m
    if length * vp.mm_per_m > el.w:  # a escala da vista mudou: encurta para caber no elemento
        length = nice_bar_length(vp.scale, el.w)
    el = replace(el, length_m=length)
    total = length * vp.mm_per_m
    n = max(1, el.divisions)
    seg = total / n
    bar_y, bar_h = el.h * 0.42, min(2.0, el.h * 0.18)
    draw_text(painter, 0, bar_y - 1.2, f"ESCALA 1:{vp.scale}", 2.0, bold=True)
    painter.setPen(pen_mm(BLACK, 0.18))
    for i in range(n):
        painter.setBrush(QBrush(BLACK) if i % 2 == 0 else Qt.GlobalColor.white)
        painter.drawRect(QRectF(i * seg, bar_y, seg, bar_h))
    labels = {0: "0", n: f"{_trim(el.length_m)} m"}
    if n % 2 == 0:
        labels[n // 2] = _trim(el.length_m / 2)
    for i, t in labels.items():
        draw_text(painter, i * seg, bar_y + bar_h + 2.6, t, 1.8, align="center" if 0 < i < n else ("left" if i == 0 else "right"))


def _trim(v: float) -> str:
    return (f"{v:.2f}".rstrip("0").rstrip(".")).replace(".", ",")
