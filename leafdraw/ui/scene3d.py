"""Monta a cena 3D em arrays (numpy), sem OpenGL — o viewport só os envia à GPU."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PySide6.QtGui import QColor
from shapely.geometry import Polygon

from leafdraw.core.entities import Contour, Hatch, Plant, PlantingArea, SpotHeight, Text
from leafdraw.core.geom import tessellate
from leafdraw.core.terrain import flat_triangles
from leafdraw.ui.plants3d import HIGHLIGHT, MESHES, plant_instances, shadow_disc

LINE_LIFT = 0.04
FILL_LIFT = 0.015
SHADOW_LIFT = 0.025
MAX_MASSED_3D = 30_000
HATCH_COLORS = {"grass": "#5f9e4a", "gravel": "#b8a58a", "dots": "#c8b88a", "solid": None}


def rgb(color: str):
    c = QColor(color)
    return (c.redF(), c.greenF(), c.blueF())


@dataclass
class PickShape:
    kind: str  # "point" (centro + raio) | "lines" | "area"
    data: list = field(default_factory=list)  # arrays (n, 3)
    radius: float = 0.0


@dataclass
class SceneArrays:
    lines: list = field(default_factory=list)  # (x, y, z, r, g, b, a) em pares
    surfaces: list = field(default_factory=list)  # (x, y, z, nx, ny, nz, r, g, b, a) em trios
    shadows: list = field(default_factory=list)  # (x, y, z, r, g, b, a) em trios
    instances: dict = field(default_factory=lambda: {m: [] for m in MESHES})
    pick: dict = field(default_factory=dict)  # eid -> PickShape

    def merge_instances(self, inst: dict):
        for k, v in inst.items():
            self.instances[k] += v


class ZMap:
    """Cota do terreno com exagero vertical aplicado."""

    def __init__(self, terrain, exaggeration: float = 1.0):
        self.terrain = terrain
        self.k = exaggeration
        self.base = terrain.base if terrain is not None and terrain.valid else 0.0

    @property
    def active(self) -> bool:
        return self.terrain is not None and self.terrain.valid

    def scale(self, z: float) -> float:
        return self.base + (z - self.base) * self.k

    def at(self, x: float, y: float) -> float:
        return self.scale(self.terrain.elevation(x, y)) if self.active else 0.0

    def drape(self, pts) -> np.ndarray:
        if not self.active:
            return np.array([(x, y, 0.0) for x, y in pts], dtype=float)
        arr = self.terrain.drape_polyline(pts)
        arr[:, 2] = self.base + (arr[:, 2] - self.base) * self.k
        return arr

    def drape_polygon(self, poly: Polygon) -> np.ndarray:
        if not self.active:
            return flat_triangles(poly, 0.0)
        tris = self.terrain.drape_polygon(poly)
        if len(tris):
            tris[..., 2] = self.base + (tris[..., 2] - self.base) * self.k
        return tris


def build_scene(entities, doc, catalog, zmap: ZMap, selected: set[str] = frozenset()) -> SceneArrays:
    out = SceneArrays()
    massed_budget = MAX_MASSED_3D
    for e in entities:
        layer = doc.layer_for(e)
        if not layer.visible:
            continue
        sel = e.id in selected
        if isinstance(e, Plant):
            _plant(out, e, catalog, zmap, sel)
        elif isinstance(e, PlantingArea):
            massed_budget = _planting(out, e, catalog, zmap, sel, massed_budget)
        elif isinstance(e, Hatch):
            _hatch(out, e, layer, zmap, sel)
        elif isinstance(e, SpotHeight):
            _spot(out, e, layer, zmap, sel)
        elif isinstance(e, Text):
            continue
        else:
            _lines(out, e, layer, zmap, sel)
    return out


def _color(e, layer, sel: bool, alpha: float = 1.0):
    c = HIGHLIGHT if sel else rgb(e.color or layer.color)
    return (*c, alpha)


def _lines(out: SceneArrays, e, layer, zmap: ZMap, sel: bool):
    col = _color(e, layer, sel)
    pieces = []
    for pr in e.primitives():
        pts = tessellate(pr, 6.0)
        if isinstance(e, Contour):
            z = zmap.scale(e.elevation) + LINE_LIFT
            arr = np.array([(x, y, z) for x, y in pts], dtype=float)
        else:
            arr = zmap.drape(pts)
            arr[:, 2] += LINE_LIFT
        pieces.append(arr)
        for a, b in zip(arr[:-1], arr[1:]):
            out.lines += [(*a, *col), (*b, *col)]
    out.pick[e.id] = PickShape("lines", pieces)


def _spot(out: SceneArrays, e: SpotHeight, layer, zmap: ZMap, sel: bool):
    col = _color(e, layer, sel)
    x, y = e.position
    z = zmap.scale(e.elevation) + LINE_LIFT
    s = max(e.text_height, 0.2)
    segs = [((x - s, y, z), (x + s, y, z)), ((x, y - s, z), (x, y + s, z)), ((x, y, z), (x, y, z + s * 2))]
    for a, b in segs:
        out.lines += [(*a, *col), (*b, *col)]
    out.pick[e.id] = PickShape("point", [np.array([x, y, z])], radius=s)


def _polygon(loops) -> Polygon | None:
    if not loops or len(loops[0]) < 3:
        return None
    poly = Polygon(loops[0], [l for l in loops[1:] if len(l) >= 3])
    return poly if poly.is_valid else poly.buffer(0)


def _surface(out: SceneArrays, tris: np.ndarray, color, lift: float):
    if not len(tris):
        return
    v = tris.copy()
    v[..., 2] += lift
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n[n[:, 2] < 0] *= -1
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    for tri, nn in zip(v, n):
        for p in tri:
            out.surfaces.append((*p, *nn, *color))


def _outline_pick(out: SceneArrays, e, loops, zmap: ZMap):
    out.pick[e.id] = PickShape("area", [zmap.drape(list(loop) + [loop[0]]) for loop in loops if len(loop) >= 3])


def _hatch(out: SceneArrays, e: Hatch, layer, zmap: ZMap, sel: bool):
    poly = _polygon(e.loops)
    if poly is None:
        return
    base = e.color or HATCH_COLORS.get(e.pattern) or layer.color
    col = (*(HIGHLIGHT if sel else rgb(base)), 1.0)
    _surface(out, zmap.drape_polygon(poly), col, FILL_LIFT)
    _outline_pick(out, e, e.loops, zmap)


def _plant(out: SceneArrays, e: Plant, catalog, zmap: ZMap, sel: bool):
    sp = catalog.get(e.species)
    simbolo = sp.simbolo if sp else "arvore"
    color = rgb(e.color or (sp.cor if sp else "#6cc070"))
    x, y = e.position
    z0 = zmap.at(x, y)
    out.merge_instances(plant_instances(simbolo, x, y, z0, e.canopy, e.height, color, e.id, sel))
    crown = e.height * (0.65 if simbolo == "arvore" else 0.9 if simbolo == "palmeira" else 0.4)
    out.shadows += shadow_disc(x, y, zmap.at, e.canopy / 2 * 1.05, crown, SHADOW_LIFT + 0.02)
    out.pick[e.id] = PickShape("point", [np.array([x, y, z0 + e.height * 0.6])], radius=e.canopy / 2)


def _planting(out: SceneArrays, e: PlantingArea, catalog, zmap: ZMap, sel: bool, budget: int) -> int:
    sp = catalog.get(e.species)
    color = rgb(e.color or (sp.cor if sp else "#6cc070"))
    poly = _polygon(e.loops)
    if poly is not None:
        soil = (0.36, 0.28, 0.20) if not sel else HIGHLIGHT
        _surface(out, zmap.drape_polygon(poly), (*soil, 1.0), FILL_LIFT)
        _outline_pick(out, e, e.loops, zmap)
    if budget <= 0:
        return budget
    pts = e.points()[:budget]
    simbolo = sp.simbolo if sp else "forracao"
    size = min(e.spacing * 1.05, sp.copa if sp else e.spacing)
    height = sp.altura if sp else 0.3
    for i, (x, y) in enumerate(pts):
        out.merge_instances(plant_instances(simbolo if simbolo in ("arbusto", "forracao") else "arbusto",
                                            x, y, zmap.at(x, y), size, height, color, f"{e.id}:{i}", sel))
    return budget - len(pts)
