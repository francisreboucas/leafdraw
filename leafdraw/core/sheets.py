"""Folhas de impressão (pranchas) e seus elementos.

Coordenadas da folha em milímetros, origem no canto superior esquerdo e Y
para baixo (como no papel). Janelas de vista mostram o modelo (metros, Y para
cima) numa escala ``1:scale``.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, fields, replace
from typing import ClassVar

PAPER_SIZES = {"A0": (1189.0, 841.0), "A1": (841.0, 594.0), "A2": (594.0, 420.0), "A3": (420.0, 297.0),
               "A4": (297.0, 210.0)}
STANDARD_SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000, 1250,
                   1500, 2000, 2500, 5000, 10000]
TITLE_BLOCK_W = 180.0
TITLE_BLOCK_H = 56.0


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def paper_size(paper: str, orientation: str) -> tuple[float, float]:
    w, h = PAPER_SIZES[paper]
    return (w, h) if orientation == "landscape" else (h, w)


def margins(paper: str) -> tuple[float, float, float, float]:
    """(esquerda, topo, direita, base) em mm, como na ABNT NBR 16752."""
    m = 10.0 if paper in ("A0", "A1") else 7.0
    return (25.0, m, m, m)


def fit_scale(model_w: float, model_h: float, rect_w_mm: float, rect_h_mm: float) -> int:
    """Menor escala padrão em que o modelo (m) cabe no retângulo (mm)."""
    for s in STANDARD_SCALES:
        if model_w * 1000 / s <= rect_w_mm and model_h * 1000 / s <= rect_h_mm:
            return s
    return STANDARD_SCALES[-1]


def _from_json(v):
    if isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return tuple(float(x) for x in v)
    return v


@dataclass(kw_only=True)
class SheetElement:
    kind: ClassVar[str] = ""
    label: ClassVar[str] = ""

    id: str = field(default_factory=new_id)
    x: float = 0.0
    y: float = 0.0
    w: float = 50.0
    h: float = 30.0

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)

    def to_dict(self) -> dict:
        d = {"kind": self.kind}
        for f in fields(self):
            d[f.name] = copy.deepcopy(getattr(self, f.name))
        return d

    @staticmethod
    def from_dict(d: dict) -> SheetElement:
        d = dict(d)
        cls = ELEMENT_TYPES[d.pop("kind")]
        names = {f.name for f in fields(cls)}
        return cls(**{k: _from_json(v) for k, v in d.items() if k in names})


@dataclass(kw_only=True)
class ViewportElement(SheetElement):
    kind: ClassVar[str] = "viewport"
    label: ClassVar[str] = "Janela de vista"

    center: tuple[float, float] = (0.0, 0.0)  # ponto do modelo no centro da janela (m)
    scale: int = 100  # 1:scale
    mode: str = "2d"  # "2d" | "3d"
    camera: dict | None = None  # câmera 3D (yaw, pitch, distance, target, ortho)
    frame: bool = True
    hidden_layers: list[str] = field(default_factory=list)

    @property
    def mm_per_m(self) -> float:
        return 1000.0 / self.scale

    def model_rect(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) do modelo visível, em metros."""
        hw = self.w / 2 / self.mm_per_m
        hh = self.h / 2 / self.mm_per_m
        cx, cy = self.center
        return (cx - hw, cy - hh, cx + hw, cy + hh)

    def paper_to_model(self, px: float, py: float) -> tuple[float, float]:
        k = self.mm_per_m
        cx, cy = self.center
        return (cx + (px - self.x - self.w / 2) / k, cy - (py - self.y - self.h / 2) / k)


@dataclass(kw_only=True)
class TitleBlockElement(SheetElement):
    kind: ClassVar[str] = "titleblock"
    label: ClassVar[str] = "Carimbo"


@dataclass(kw_only=True)
class PlantTableElement(SheetElement):
    kind: ClassVar[str] = "planttable"
    label: ClassVar[str] = "Quadro de vegetação"

    title: str = "QUADRO DE VEGETAÇÃO"
    text_height: float = 2.0  # mm
    show_areas: bool = True


@dataclass(kw_only=True)
class TextElement(SheetElement):
    kind: ClassVar[str] = "text"
    label: ClassVar[str] = "Texto"

    text: str = "Texto"
    text_height: float = 3.5  # mm
    bold: bool = False


@dataclass(kw_only=True)
class NorthElement(SheetElement):
    kind: ClassVar[str] = "north"
    label: ClassVar[str] = "Norte"

    rotation: float = 0.0  # graus, anti-horário


@dataclass(kw_only=True)
class ScaleBarElement(SheetElement):
    kind: ClassVar[str] = "scalebar"
    label: ClassVar[str] = "Escala gráfica"

    length_m: float = 10.0
    divisions: int = 5
    viewport_id: str = ""  # vazio = primeira janela de vista da folha


ELEMENT_TYPES: dict[str, type[SheetElement]] = {
    c.kind: c for c in (ViewportElement, TitleBlockElement, PlantTableElement, TextElement, NorthElement,
                        ScaleBarElement)
}


@dataclass(kw_only=True)
class Sheet:
    id: str = field(default_factory=new_id)
    name: str = "Planta de paisagismo"
    paper: str = "A1"
    orientation: str = "landscape"
    elements: list[SheetElement] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float]:
        return paper_size(self.paper, self.orientation)

    def frame_rect(self) -> tuple[float, float, float, float]:
        """Retângulo útil dentro das margens: (x, y, w, h)."""
        W, H = self.size
        l, t, r, b = margins(self.paper)
        return (l, t, W - l - r, H - t - b)

    def element(self, eid: str) -> SheetElement | None:
        return next((e for e in self.elements if e.id == eid), None)

    def viewports(self) -> list[ViewportElement]:
        return [e for e in self.elements if isinstance(e, ViewportElement)]

    def main_scale(self) -> int | None:
        vps = self.viewports()
        return vps[0].scale if vps else None

    def with_element(self, el: SheetElement) -> Sheet:
        """Cópia com ``el`` substituído (mesmo id) ou acrescentado."""
        els = [el if e.id == el.id else e for e in self.elements]
        if not any(e.id == el.id for e in self.elements):
            els.append(el)
        return replace(self, elements=els)

    def without_element(self, eid: str) -> Sheet:
        return replace(self, elements=[e for e in self.elements if e.id != eid])

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "paper": self.paper, "orientation": self.orientation,
                "elements": [e.to_dict() for e in self.elements]}

    @staticmethod
    def from_dict(d: dict) -> Sheet:
        return Sheet(id=d["id"], name=d.get("name", ""), paper=d.get("paper", "A1"),
                     orientation=d.get("orientation", "landscape"),
                     elements=[SheetElement.from_dict(e) for e in d.get("elements", [])])


def default_sheet(bounds, name: str = "Planta de paisagismo", paper: str = "A1",
                  orientation: str = "landscape") -> Sheet:
    """Folha com carimbo, quadro de vegetação, norte, escala gráfica e uma janela
    de vista enquadrando ``bounds`` (xmin, ymin, xmax, ymax do modelo)."""
    sheet = Sheet(name=name, paper=paper, orientation=orientation)
    fx, fy, fw, fh = sheet.frame_rect()
    gap = 5.0
    tb_w = min(TITLE_BLOCK_W, fw)
    side_column = fw >= 2.2 * TITLE_BLOCK_W  # A0-A2 paisagem: coluna lateral para quadro e carimbo
    tb = TitleBlockElement(x=fx + fw - tb_w, y=fy + fh - TITLE_BLOCK_H, w=tb_w, h=TITLE_BLOCK_H)
    els: list[SheetElement] = [tb]
    if side_column:
        vp_rect = (fx + gap, fy + gap, fw - tb_w - 3 * gap, fh - 2 * gap)
        els.append(PlantTableElement(x=tb.x, y=fy + gap, w=tb_w, h=fh - TITLE_BLOCK_H - 2 * gap - 40))
        north_y = tb.y - 40
        els.append(NorthElement(x=tb.x + 5, y=north_y, w=25, h=30))
        els.append(ScaleBarElement(x=tb.x + 40, y=north_y + 12, w=tb_w - 45, h=12))
    else:
        vp_rect = (fx + gap, fy + gap, fw - 2 * gap, fh - TITLE_BLOCK_H - 3 * gap)
        els.append(NorthElement(x=fx + gap, y=tb.y + 5, w=20, h=25))
        els.append(ScaleBarElement(x=fx + gap + 25, y=tb.y + 15, w=min(80.0, tb.x - fx - 35), h=12))
    x, y, w, h = vp_rect
    vp = ViewportElement(x=x, y=y, w=w, h=h)
    if bounds is not None:
        bw, bh = bounds[2] - bounds[0], bounds[3] - bounds[1]
        vp.scale = fit_scale(bw * 1.05, bh * 1.05, w, h)
        vp.center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    els.insert(0, vp)
    sheet.elements = els
    for e in els:
        if isinstance(e, ScaleBarElement):
            e.length_m = nice_bar_length(vp.scale, e.w)
    return sheet


def nice_bar_length(scale: int, max_mm: float) -> float:
    """Maior comprimento "redondo" (m) que cabe em ``max_mm`` na escala dada."""
    best = 1.0
    for m in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if m * 1000 / scale <= max_mm * 0.9:
            best = float(m)
    return best


PROJECT_FIELDS = [
    ("projeto", "Projeto"),
    ("cliente", "Cliente"),
    ("endereco", "Endereço"),
    ("autor", "Responsável técnico"),
    ("registro", "Registro (CAU/CREA)"),
    ("data", "Data"),
    ("revisao", "Revisão"),
]
