"""Vistas (elevações) geradas a partir da planta.

Cada espécie tem duas versões: **planta** (símbolo visto de cima) e **vista**
(silhueta de frente). A vista vem de um bloco importado pelo usuário ou, sem
ele, é gerada pelo tipo de símbolo, pela altura e pela copa.

Uma ``ElevationView`` guarda só a linha de corte e onde o desenho fica; o
conteúdo é recalculado a partir das plantas e do terreno sempre que mudam.
Coordenadas do desenho: X ao longo da linha (da esquerda para a direita de
quem olha), Y = cota − ``datum``, ambos somados a ``origin``.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field

from leafdraw.core.entities import ElevationView, Plant, PlantingArea, Point

TRUNK_COLOR = "#7a5a3c"
MAX_MASSED = 3000  # mudas de maciço desenhadas por vista


@dataclass(frozen=True)
class Shape:
    """Polilinha de um símbolo. ``fill``: "folha" (cor da espécie), "tronco" ou "" (só traço)."""

    pts: tuple[Point, ...]
    closed: bool
    fill: str = ""

    def mapped(self, f) -> Shape:
        return Shape(tuple(f(p) for p in self.pts), self.closed, self.fill)


def rng_for(key: str) -> random.Random:
    return random.Random(zlib.crc32(key.encode()))


def _quad(p0, c, p1, n: int = 6) -> list[Point]:
    """Bezier quadrática achatada (sem o 1º ponto)."""
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, d = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        out.append((a * p0[0] + b * c[0] + d * p1[0], a * p0[1] + b * c[1] + d * p1[1]))
    return out


def _lobed_arc(cx, cy, rx, ry, a0, a1, lobes, bulge, rnd) -> list[Point]:
    """Contorno de nuvem (lobos) sobre uma elipse, de ``a0`` a ``a1`` (rad)."""
    pts = [(cx + rx * math.cos(a0), cy + ry * math.sin(a0))]
    step = (a1 - a0) / lobes
    for i in range(lobes):
        am = a0 + (i + 0.5) * step
        b = bulge * (1 + rnd.uniform(-0.05, 0.05))
        ae = a0 + (i + 1) * step
        k = 1 if i == lobes - 1 else 1 + rnd.uniform(-0.04, 0.04)
        end = (cx + rx * k * math.cos(ae), cy + ry * k * math.sin(ae))
        pts += _quad(pts[-1], (cx + rx * b * math.cos(am), cy + ry * b * math.sin(am)), end)
    return pts


def _trunk(w_base: float, w_top: float, top: float) -> Shape:
    return Shape(((-w_base / 2, 0.0), (w_base / 2, 0.0), (w_top / 2, top), (-w_top / 2, top)), True, "tronco")


def procedural_shapes(simbolo: str, w: float, h: float, seed: str = "") -> list[Shape]:
    """Silhueta de frente com base no ponto (0, 0), largura ``w`` e altura ``h`` (m)."""
    w, h = max(w, 0.05), max(h, 0.05)
    shapes = _procedural(simbolo, w, h, rng_for(seed or simbolo))
    # os lobos e as folhas passam um pouco do contorno de referência: ajusta à copa × altura
    pts = [p for sh in shapes for p in sh.pts]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y1 = max(p[1] for p in pts)
    kx, ky = w / max(x1 - x0, 1e-9), h / max(y1, 1e-9)
    cx = (x0 + x1) / 2
    return [sh.mapped(lambda p: ((p[0] - cx) * kx, p[1] * ky)) for sh in shapes]


def _procedural(simbolo: str, w: float, h: float, rnd: random.Random) -> list[Shape]:
    r = w / 2
    if simbolo == "palmeira":
        top = h * 0.82
        tw = max(0.12, min(w * 0.06, h * 0.03))
        out = [_trunk(tw * 1.25, tw * 0.9, top)]
        for k in range(1, max(3, int(top / 0.5))):  # anéis do estipe
            y = top * k / max(3, int(top / 0.5))
            out.append(Shape(((-tw * 0.5, y), (tw * 0.5, y + tw * 0.15)), False))
        crown_h = h - top
        for k in range(9):
            side = -1 if k % 2 else 1
            reach = r * (0.4 + 0.6 * (k // 2) / 3) if k < 8 else r * 0.15
            rise = crown_h * (1.0 - 0.55 * (k // 2) / 3) if k < 8 else crown_h
            droop = crown_h * 0.9 * (k // 2) / 3
            tip = (side * reach * rnd.uniform(0.92, 1.0), top + rise - droop)
            ctrl = (side * reach * 0.45, top + rise * 1.1)
            spine = [(0.0, top)] + _quad((0.0, top), ctrl, tip, 8)
            thick = max(r * 0.09, 0.04)
            upper, lower = [], []
            for i, (x, y) in enumerate(spine):
                f = math.sin(math.pi * i / (len(spine) - 1)) * thick
                upper.append((x, y + f))
                lower.append((x, y - f))
            out.append(Shape(tuple(upper + lower[::-1]), True, "folha"))
        return out
    if simbolo == "arbusto":
        cy = h * 0.05
        pts = _lobed_arc(0.0, cy, r, h - cy, 0.0, math.pi, max(5, min(14, int(w / 0.25))), 1.12, rnd)
        pts = [(x, max(y, 0.0)) for x, y in pts] + [(-r * 0.75, 0.0), (r * 0.75, 0.0)]
        return [Shape(tuple(pts), True, "folha")]
    if simbolo == "forracao":
        pts = _lobed_arc(0.0, 0.0, r, h, 0.0, math.pi, max(6, min(30, int(w / 0.12))), 1.18, rnd)
        out = [Shape(tuple([(x, max(y, 0.0)) for x, y in pts]), True, "folha")]
        for i in range(max(2, min(8, int(w / 0.2)))):  # tufos
            x = -r * 0.7 + 1.4 * r * (i + 0.5) / max(2, min(8, int(w / 0.2)))
            out.append(Shape(((x - h * 0.25, h * 0.35), (x, h * 0.75), (x + h * 0.25, h * 0.35)), False))
        return out
    # arvore
    crown_h = min(h * 0.68, max(w * 1.1, h * 0.4))
    y0 = h - crown_h
    tw = max(0.1, min(w * 0.07, h * 0.05))
    out = [_trunk(tw * 1.4, tw * 0.75, y0 + crown_h * 0.35)]
    for side in (-1, 1):  # galhos visíveis sob a copa
        out.append(Shape(((0.0, y0 + crown_h * 0.12), (side * r * 0.35, y0 + crown_h * 0.3)), False))
    crown = _lobed_arc(0.0, y0 + crown_h / 2, r, crown_h / 2, -math.pi / 2, 1.5 * math.pi,
                       max(9, min(16, int(w / 0.5))), 1.13, rnd)
    out.append(Shape(tuple(crown), True, "folha"))
    return out


def custom_elevation_shapes(drawing, w: float, h: float) -> list[Shape]:
    return [Shape(tuple((x * w, y * h) for x, y in pts), closed, "folha" if closed else "")
            for closed, pts in drawing]


def custom_plan_shapes(drawing, radius: float) -> list[Shape]:
    return [Shape(tuple((x * radius, y * radius) for x, y in pts), closed, "folha" if closed else "")
            for closed, pts in drawing]


def species_elevation(sp, w: float, h: float, seed: str = "") -> list[Shape]:
    if sp is not None and sp.desenho_vista:
        return custom_elevation_shapes(sp.desenho_vista, w, h)
    return procedural_shapes(sp.simbolo if sp else "arvore", w, h, seed)


# --- cálculo da vista ---------------------------------------------------------------

@dataclass
class ElevationPlant:
    eid: str
    species: str
    x: float  # centro da base, coordenadas do desenho
    y: float
    width: float
    height: float
    dist: float  # distância da linha de corte (m)
    color: str
    shapes: list[Shape] = field(default_factory=list)  # já em coordenadas do desenho


@dataclass
class ElevationData:
    profile: list[Point]
    plants: list[ElevationPlant]  # do fundo para a frente
    depth_range: float = 1.0

    def bounds(self):
        pts = list(self.profile) + [p for pl in self.plants for s in pl.shapes for p in s.pts]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


def frame(ev: ElevationView):
    """(u, n, L): direção da linha, normal para onde a vista olha e comprimento."""
    (x1, y1), (x2, y2) = ev.p1, ev.p2
    L = math.hypot(x2 - x1, y2 - y1) or 1e-9
    u = ((x2 - x1) / L, (y2 - y1) / L)
    n = (-u[1] * ev.side, u[0] * ev.side)
    return u, n, L


def to_view(ev: ElevationView, p: Point) -> tuple[float, float]:
    """(t, d): posição ao longo da linha (da esquerda de quem olha) e distância à frente."""
    u, n, L = frame(ev)
    vx, vy = p[0] - ev.p1[0], p[1] - ev.p1[1]
    t = vx * u[0] + vy * u[1]
    return (t if ev.side > 0 else L - t), vx * n[0] + vy * n[1]


def compute_elevation(ev: ElevationView, entities, is_visible, catalog, terrain=None) -> ElevationData:
    """Monta a vista. ``is_visible(e)`` diz se a entidade está numa camada visível."""
    u, n, L = frame(ev)
    ox, oy = ev.origin
    ground = terrain if terrain is not None and terrain.valid else None

    def z_at(x, y):
        return float(ground.elevation(x, y)) if ground else 0.0

    if ground:
        pts3 = ground.drape_polyline([ev.p1, ev.p2])
        prof = sorted((to_view(ev, (float(x), float(y)))[0], float(z)) for x, y, z in pts3)
    else:
        prof = [(0.0, 0.0), (L, 0.0)]
    profile = [(ox + t, oy + z - ev.datum) for t, z in prof]

    def inside(t, d, r):
        return -1e-9 <= t <= L + 1e-9 and d >= -r and (ev.depth <= 0 or d <= ev.depth)

    plants: list[ElevationPlant] = []
    budget = MAX_MASSED
    for e in entities:
        if isinstance(e, Plant):
            t, d = to_view(ev, e.position)
            if not inside(t, d, e.canopy / 2) or not is_visible(e):
                continue
            sp = catalog.get(e.species)
            plants.append(_placed(e.id, e.species, sp, e.color, ox + t, oy + z_at(*e.position) - ev.datum,
                                  e.canopy, e.height, d))
        elif isinstance(e, PlantingArea) and budget > 0 and is_visible(e):
            sp = catalog.get(e.species)
            size = min(e.spacing * 1.05, sp.copa if sp else e.spacing)
            height = sp.altura if sp else 0.3
            for i, p in enumerate(e.points()):
                t, d = to_view(ev, p)
                if not inside(t, d, size / 2):
                    continue
                plants.append(_placed(f"{e.id}:{i}", e.species, sp, e.color, ox + t, oy + z_at(*p) - ev.datum,
                                      size, height, d, massed=True))
                budget -= 1
                if budget <= 0:
                    break
    plants.sort(key=lambda pl: -pl.dist)
    far = max((pl.dist for pl in plants), default=1.0)
    return ElevationData(profile, plants, max(far, 1e-6))


def _placed(eid, sid, sp, color, x, y, w, h, d, massed=False) -> ElevationPlant:
    if massed and not (sp and sp.desenho_vista):
        simbolo = sp.simbolo if sp and sp.simbolo in ("arbusto", "forracao") else "arbusto"
        shapes = procedural_shapes(simbolo, w, h, eid)
    else:
        shapes = species_elevation(sp, w, h, eid)
    shapes = [s.mapped(lambda p: (p[0] + x, p[1] + y)) for s in shapes]
    return ElevationPlant(eid, sid, x, y, w, h, d, color or (sp.cor if sp else "#6cc070"), shapes)


def marker_geometry(ev: ElevationView) -> dict:
    """Marca da linha de corte na planta: linha, setas (para onde a vista olha) e rótulos."""
    u, n, L = frame(ev)
    h = ev.text_height
    arrows, labels = [], []
    for p in (ev.p1, ev.p2):
        tip = (p[0] + n[0] * h * 2.2, p[1] + n[1] * h * 2.2)
        wing = h * 0.55
        arrows.append(((p[0] + u[0] * wing, p[1] + u[1] * wing), tip, (p[0] - u[0] * wing, p[1] - u[1] * wing)))
        labels.append((p[0] - n[0] * h * 0.6 - h * 0.35, p[1] - n[1] * h * 0.6 - h * 0.5))
    return {"line": (ev.p1, ev.p2), "arrows": arrows, "labels": labels}


def title_position(ev: ElevationView, data: ElevationData | None) -> Point:
    """Início da linha de base do título, centrado sob o desenho."""
    _u, _n, L = frame(ev)
    low = min((p[1] for p in data.profile), default=ev.origin[1]) if data else ev.origin[1]
    return (ev.origin[0] + L / 2, low - ev.text_height * 2.2)
