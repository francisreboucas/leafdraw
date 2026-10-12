"""Entidades do desenho. Unidades em metros, eixo Y para cima, ângulos em graus.

As entidades são tratadas como imutáveis: uma edição gera uma nova versão
com o mesmo ``id`` (via ``dataclasses.replace``), o que simplifica o undo.
"""
from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field, fields, replace
from typing import ClassVar

from leafdraw.core.geom import Affine, ArcP, Seg, angle_of, norm_angle, polar, sweep

Point = tuple[float, float]
SnapPoint = tuple[Point, str]  # (ponto, tipo: "end" | "mid" | "center" | "quad")
Bounds = tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _bounds(pts) -> Bounds:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def polyline_length(pts, closed: bool = False) -> float:
    if len(pts) < 2:
        return 0.0
    seq = list(pts) + ([pts[0]] if closed else [])
    return sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))


def signed_area(pts) -> float:
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2


def polygon_area(pts) -> float:
    return abs(signed_area(pts)) if len(pts) >= 3 else 0.0


def union_bounds(bounds_list) -> Bounds | None:
    bounds_list = list(bounds_list)
    if not bounds_list:
        return None
    return (
        min(b[0] for b in bounds_list),
        min(b[1] for b in bounds_list),
        max(b[2] for b in bounds_list),
        max(b[3] for b in bounds_list),
    )


def readable_angle(deg: float) -> float:
    """Normaliza um ângulo de texto para (-90, 90], mantendo-o legível."""
    a = norm_angle(deg)
    if 90 < a <= 270:
        a -= 180
    elif a > 270:
        a -= 360
    return a


def _segs(pts, closed=False) -> list[Seg]:
    seq = list(pts) + ([pts[0]] if closed and pts else [])
    return [Seg(a, b) for a, b in zip(seq, seq[1:])]


def _from_json(v):
    """Converte listas numéricas do JSON de volta para tuplas (pontos)."""
    if isinstance(v, list):
        if v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return tuple(float(x) for x in v)
        return [_from_json(x) for x in v]
    return v


@dataclass(kw_only=True)
class Entity:
    kind: ClassVar[str] = ""

    id: str = field(default_factory=new_id)
    layer: str = "0"
    color: str = ""  # vazio = cor da camada

    def primitives(self) -> list:
        """Segmentos e arcos exatos (snaps, offset, tesselação)."""
        return []

    def snap_points(self) -> list[SnapPoint]:
        raise NotImplementedError

    def bounds(self) -> Bounds:
        raise NotImplementedError

    def transformed(self, t: Affine) -> Entity:
        raise NotImplementedError

    def translated(self, dx: float, dy: float) -> Entity:
        return self.transformed(Affine.translation(dx, dy))

    def copy_new_id(self) -> Entity:
        return replace(self, id=new_id())

    def to_dict(self) -> dict:
        d = {"kind": self.kind}
        for f in fields(self):
            d[f.name] = copy.deepcopy(getattr(self, f.name))
        return d

    @staticmethod
    def from_dict(d: dict) -> Entity:
        d = dict(d)
        cls = ENTITY_TYPES[d.pop("kind")]
        names = {f.name for f in fields(cls)}
        return cls(**{k: _from_json(v) for k, v in d.items() if k in names})


@dataclass(kw_only=True)
class Line(Entity):
    kind: ClassVar[str] = "line"

    p1: Point = (0.0, 0.0)
    p2: Point = (0.0, 0.0)

    @property
    def length(self) -> float:
        return math.dist(self.p1, self.p2)

    @property
    def angle(self) -> float:
        return angle_of(self.p1, self.p2)

    def primitives(self):
        return [Seg(self.p1, self.p2)]

    def snap_points(self):
        return [(self.p1, "end"), (self.p2, "end"), (_mid(self.p1, self.p2), "mid")]

    def bounds(self):
        return _bounds([self.p1, self.p2])

    def transformed(self, t):
        return replace(self, p1=t.apply(self.p1), p2=t.apply(self.p2))


@dataclass(kw_only=True)
class Polyline(Entity):
    kind: ClassVar[str] = "polyline"

    vertices: list[Point] = field(default_factory=list)
    closed: bool = False

    @property
    def length(self) -> float:
        return polyline_length(self.vertices, self.closed)

    @property
    def area(self) -> float:
        return polygon_area(self.vertices) if self.closed else 0.0

    def segments(self):
        seq = self.vertices + ([self.vertices[0]] if self.closed and self.vertices else [])
        return list(zip(seq, seq[1:]))

    def primitives(self):
        return _segs(self.vertices, self.closed)

    def snap_points(self):
        pts = [(v, "end") for v in self.vertices]
        pts += [(_mid(a, b), "mid") for a, b in self.segments()]
        return pts

    def bounds(self):
        return _bounds(self.vertices)

    def transformed(self, t):
        return replace(self, vertices=[t.apply(v) for v in self.vertices])


@dataclass(kw_only=True)
class Circle(Entity):
    kind: ClassVar[str] = "circle"

    center: Point = (0.0, 0.0)
    radius: float = 1.0

    @property
    def area(self) -> float:
        return math.pi * self.radius**2

    @property
    def length(self) -> float:
        return 2 * math.pi * self.radius

    def primitives(self):
        return [ArcP(self.center, self.radius)]

    def snap_points(self):
        quads = [(polar(self.center, self.radius, a), "quad") for a in (0, 90, 180, 270)]
        return [(self.center, "center"), *quads]

    def bounds(self):
        x, y = self.center
        r = self.radius
        return (x - r, y - r, x + r, y + r)

    def transformed(self, t):
        return replace(self, center=t.apply(self.center), radius=self.radius * t.scale)


@dataclass(kw_only=True)
class Arc(Entity):
    """Arco anti-horário de ``start`` até ``end`` (graus)."""

    kind: ClassVar[str] = "arc"

    center: Point = (0.0, 0.0)
    radius: float = 1.0
    start: float = 0.0
    end: float = 90.0

    @property
    def sweep(self) -> float:
        return sweep(self.start, self.end)

    @property
    def length(self) -> float:
        return math.radians(self.sweep) * self.radius

    @property
    def start_point(self) -> Point:
        return polar(self.center, self.radius, self.start)

    @property
    def end_point(self) -> Point:
        return polar(self.center, self.radius, self.end)

    def primitives(self):
        return [ArcP(self.center, self.radius, self.start, self.end)]

    def snap_points(self):
        prim = self.primitives()[0]
        pts = [(self.start_point, "end"), (self.end_point, "end"),
               (polar(self.center, self.radius, self.start + self.sweep / 2), "mid"), (self.center, "center")]
        pts += [(polar(self.center, self.radius, a), "quad") for a in (0, 90, 180, 270) if prim.contains_angle(a)]
        return pts

    def bounds(self):
        pts = [p for p, kind in self.snap_points() if kind != "center"]
        return _bounds(pts)

    def transformed(self, t):
        a0, a1 = t.map_angle(self.start), t.map_angle(self.end)
        if t.mirrored:
            a0, a1 = a1, a0
        return replace(self, center=t.apply(self.center), radius=self.radius * t.scale, start=a0, end=a1)


@dataclass(kw_only=True)
class Text(Entity):
    """Texto alinhado à esquerda; ``position`` é o início da linha de base da 1ª linha.

    ``height`` é a altura das maiúsculas, como no AutoCAD.
    """

    kind: ClassVar[str] = "text"

    position: Point = (0.0, 0.0)
    text: str = ""
    height: float = 0.25
    rotation: float = 0.0

    LINE_SPACING: ClassVar[float] = 1.6
    CHAR_WIDTH: ClassVar[float] = 0.62  # estimativa para limites; o desenho usa a fonte real

    def lines(self) -> list[str]:
        return self.text.split("\n") or [""]

    def snap_points(self):
        return [(self.position, "end")]

    def corners(self) -> list[Point]:
        lines = self.lines()
        w = max(len(s) for s in lines) * self.height * self.CHAR_WIDTH
        bottom = -self.height * (0.25 + self.LINE_SPACING * (len(lines) - 1))
        t = Affine.rotation(self.rotation, self.position) @ Affine.translation(*self.position)
        return [t.apply(p) for p in ((0, bottom), (w, bottom), (w, self.height), (0, self.height))]

    def bounds(self):
        return _bounds(self.corners())

    def transformed(self, t):
        rot = t.map_angle(self.rotation)
        if t.mirrored:
            rot = readable_angle(rot)
        return replace(self, position=t.apply(self.position), height=self.height * t.scale, rotation=rot)


@dataclass(kw_only=True)
class Dimension(Entity):
    """Cota alinhada entre ``p1`` e ``p2``.

    ``offset`` é a distância (com sinal) da linha de cota até a reta p1→p2;
    positivo fica à esquerda de p1→p2.
    """

    kind: ClassVar[str] = "dimension"

    p1: Point = (0.0, 0.0)
    p2: Point = (1.0, 0.0)
    offset: float = 0.5
    text_height: float = 0.2
    decimals: int = 2
    text_override: str = ""

    @property
    def value(self) -> float:
        return math.dist(self.p1, self.p2)

    def label(self) -> str:
        if self.text_override:
            return self.text_override.replace("<>", self._fmt())
        return self._fmt()

    def _fmt(self) -> str:
        return f"{self.value:.{self.decimals}f}".replace(".", ",")

    def layout(self) -> dict:
        """Geometria da cota: linhas de chamada, linha de cota, ticks e texto."""
        (x1, y1), (x2, y2) = self.p1, self.p2
        L = math.dist(self.p1, self.p2) or 1e-9
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        nx, ny = -uy, ux
        o = self.offset
        d1 = (x1 + nx * o, y1 + ny * o)
        d2 = (x2 + nx * o, y2 + ny * o)
        h = self.text_height
        gap, ext = 0.3 * h, 0.6 * h
        sgn = 1 if o >= 0 else -1
        ext_lines = []
        for p, d in ((self.p1, d1), (self.p2, d2)):
            if abs(o) > gap:
                ext_lines.append(((p[0] + nx * gap * sgn, p[1] + ny * gap * sgn),
                                  (d[0] + nx * ext * sgn, d[1] + ny * ext * sgn)))
        over = 0.6 * h
        dim_line = ((d1[0] - ux * over, d1[1] - uy * over), (d2[0] + ux * over, d2[1] + uy * over))
        t = 0.5 * h  # ticks a 45°
        tx, ty = (ux + nx) * t / math.sqrt(2), (uy + ny) * t / math.sqrt(2)
        ticks = [((d[0] - tx, d[1] - ty), (d[0] + tx, d[1] + ty)) for d in (d1, d2)]
        angle = readable_angle(math.degrees(math.atan2(uy, ux)))
        flip = 1 if abs(norm_angle(angle) - norm_angle(math.degrees(math.atan2(uy, ux)))) < 1e-6 else -1
        mid = _mid(d1, d2)
        # o texto fica do lado de "cima" da leitura
        tnx, tny = nx * flip, ny * flip
        text_pos = (mid[0] + tnx * 0.4 * h, mid[1] + tny * 0.4 * h)
        return {"d1": d1, "d2": d2, "ext": ext_lines, "dim": dim_line, "ticks": ticks,
                "text_center": text_pos, "angle": angle}

    def line_segments(self) -> list[tuple[Point, Point]]:
        lay = self.layout()
        return [*lay["ext"], lay["dim"], *lay["ticks"]]

    def primitives(self):
        return [Seg(a, b) for a, b in self.line_segments()]

    def snap_points(self):
        lay = self.layout()
        return [(self.p1, "end"), (self.p2, "end"), (lay["d1"], "end"), (lay["d2"], "end"),
                (_mid(lay["d1"], lay["d2"]), "mid")]

    def bounds(self):
        pts = [p for seg in self.line_segments() for p in seg] + [self.p1, self.p2]
        return _bounds(pts)

    def transformed(self, t):
        s = t.scale
        return replace(self, p1=t.apply(self.p1), p2=t.apply(self.p2),
                       offset=self.offset * s * (-1 if t.mirrored else 1), text_height=self.text_height * s)


HATCH_PATTERNS = {
    "solid": "Sólido",
    "diagonal": "Diagonal",
    "cross": "Cruzado",
    "horizontal": "Linhas",
    "grass": "Grama",
    "dots": "Pontilhado",
    "gravel": "Pedriscos",
}


@dataclass(kw_only=True)
class Hatch(Entity):
    """Hachura. ``loops[0]`` é o contorno externo; os demais, furos (regra par-ímpar)."""

    kind: ClassVar[str] = "hatch"

    loops: list[list[Point]] = field(default_factory=list)
    pattern: str = "diagonal"
    scale: float = 1.0  # tamanho do módulo do padrão (m)
    angle: float = 0.0

    @property
    def area(self) -> float:
        if not self.loops:
            return 0.0
        return max(0.0, polygon_area(self.loops[0]) - sum(polygon_area(l) for l in self.loops[1:]))

    def primitives(self):
        return [s for loop in self.loops for s in _segs(loop, True)]

    def snap_points(self):
        return [(v, "end") for loop in self.loops for v in loop]

    def bounds(self):
        return _bounds([v for loop in self.loops for v in loop])

    def transformed(self, t):
        return replace(self, loops=[[t.apply(v) for v in loop] for loop in self.loops],
                       scale=self.scale * t.scale, angle=norm_angle(t.map_angle(self.angle)))


@dataclass(kw_only=True)
class Plant(Entity):
    """Instância de uma espécie do catálogo posicionada no desenho."""

    kind: ClassVar[str] = "plant"

    position: Point = (0.0, 0.0)
    species: str = ""
    canopy: float = 1.0  # diâmetro da copa (m)
    height: float = 1.0  # altura (m)

    def primitives(self):
        return [ArcP(self.position, self.canopy / 2)]

    def snap_points(self):
        return [(self.position, "center")]

    def bounds(self):
        x, y = self.position
        r = self.canopy / 2
        return (x - r, y - r, x + r, y + r)

    def transformed(self, t):
        # o porte da planta é biológico: transformações só reposicionam
        return replace(self, position=t.apply(self.position))


ENTITY_TYPES: dict[str, type[Entity]] = {
    c.kind: c for c in (Line, Polyline, Circle, Arc, Text, Dimension, Hatch, Plant)
}

KIND_NAMES = {
    "line": "Linha",
    "polyline": "Polilinha",
    "circle": "Círculo",
    "arc": "Arco",
    "text": "Texto",
    "dimension": "Cota",
    "hatch": "Hachura",
    "plant": "Planta",
}
