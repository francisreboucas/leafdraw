"""Terreno: superfície triangulada (TIN) a partir de curvas e cotas de nível.

Fora da envoltória convexa dos pontos o terreno é plano, na cota mais baixa
(``base``), para que objetos fora da área levantada fiquem num chão coerente.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPoint, Point as SPoint, Polygon
from shapely.strtree import STRtree

from leafdraw.core.entities import Contour, SpotHeight

MAX_SAMPLES = 20_000


def terrain_points(entities) -> np.ndarray:
    """Pontos (x, y, z) das curvas (adensadas) e cotas de nível."""
    contours = [e for e in entities if isinstance(e, Contour) and len(e.vertices) >= 2]
    spots = [e for e in entities if isinstance(e, SpotHeight)]
    total = sum(e.length for e in contours)
    step = max(0.5, total / MAX_SAMPLES) if total else 1.0
    pts: dict[tuple[float, float], float] = {}
    for c in contours:
        for (x0, y0), (x1, y1) in c.segments():
            n = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / step))
            for i in range(n + (0 if c.closed else 1)):
                t = i / n
                pts[(round(x0 + (x1 - x0) * t, 6), round(y0 + (y1 - y0) * t, 6))] = c.elevation
        if not c.closed:
            x, y = c.vertices[-1]
            pts[(round(x, 6), round(y, 6))] = c.elevation
    for s in spots:
        pts[(round(s.position[0], 6), round(s.position[1], 6))] = s.elevation
    if not pts:
        return np.zeros((0, 3))
    return np.array([(x, y, z) for (x, y), z in pts.items()], dtype=float)


class Terrain:
    def __init__(self, points: np.ndarray):
        self.valid = False
        self.base = 0.0
        self.vertices = np.zeros((0, 3))
        self.triangles = np.zeros((0, 3), dtype=int)
        if len(points) < 3:
            return
        xy = points[:, :2]
        if MultiPoint([tuple(p) for p in xy]).convex_hull.area <= 1e-9:
            return  # colineares
        index = {(round(x, 6), round(y, 6)): i for i, (x, y) in enumerate(xy)}
        tris = shapely.delaunay_triangles(MultiPoint([tuple(p) for p in xy]))
        faces = []
        for g in tris.geoms:
            ids = [index.get((round(x, 6), round(y, 6))) for x, y in g.exterior.coords[:3]]
            if None not in ids:
                faces.append(ids)
        if not faces:
            return
        self.vertices = points.astype(float)
        self.triangles = np.array(faces, dtype=int)
        self.base = float(points[:, 2].min())
        self.top = float(points[:, 2].max())
        self.polys = [Polygon(self.vertices[f, :2]) for f in self.triangles]
        self.hull = shapely.union_all(self.polys).buffer(0)
        self.tree = STRtree(self.polys)
        self._planes = self._plane_coefficients()
        self.valid = True

    @staticmethod
    def from_entities(entities) -> Terrain:
        return Terrain(terrain_points(entities))

    def _plane_coefficients(self) -> np.ndarray:
        """z = a·x + b·y + c para cada triângulo."""
        v = self.vertices[self.triangles]  # (T, 3, 3)
        p0, p1, p2 = v[:, 0], v[:, 1], v[:, 2]
        n = np.cross(p1 - p0, p2 - p0)
        nz = np.where(np.abs(n[:, 2]) < 1e-12, 1e-12, n[:, 2])
        a = -n[:, 0] / nz
        b = -n[:, 1] / nz
        c = p0[:, 2] - a * p0[:, 0] - b * p0[:, 1]
        return np.stack([a, b, c], axis=1)

    def _tri_at(self, x: float, y: float) -> int | None:
        pt = SPoint(x, y)
        for i in self.tree.query(pt):
            if self.polys[i].covers(pt):
                return int(i)
        return None

    def elevation(self, x: float, y: float) -> float:
        if not self.valid:
            return 0.0
        i = self._tri_at(x, y)
        if i is None:
            return self.base
        a, b, c = self._planes[i]
        return float(a * x + b * y + c)

    # --- geometria assentada sobre o terreno --------------------------------

    def drape_polyline(self, pts) -> np.ndarray:
        """Polilinha (x, y) → pontos (x, y, z) quebrados nas arestas dos triângulos."""
        out: list[tuple[float, float, float]] = []
        for p, q in zip(pts, pts[1:]):
            for x, y in self._breakpoints(p, q)[(1 if out else 0):]:
                out.append((x, y, self.elevation(x, y)))
        if not out and pts:
            x, y = pts[0]
            out.append((x, y, self.elevation(x, y)))
        return np.array(out, dtype=float)

    def _breakpoints(self, p, q) -> list[tuple[float, float]]:
        if not self.valid:
            return [p, q]
        seg = LineString([p, q])
        L = seg.length
        if L < 1e-12:
            return [p]
        ts = {0.0, 1.0}
        for i in self.tree.query(seg):
            inter = seg.intersection(self.polys[i].exterior)
            for g in getattr(inter, "geoms", [inter]):
                for c in getattr(g, "coords", []):
                    ts.add(seg.project(SPoint(c)) / L)
        return [(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t) for t in sorted(ts)]

    def drape_polygon(self, poly: Polygon) -> np.ndarray:
        """Triângulos (n, 3, 3) que cobrem ``poly`` seguindo o terreno."""
        tris: list = []
        if poly.is_empty:
            return np.zeros((0, 3, 3))
        if not self.valid:
            return flat_triangles(poly, 0.0)
        for i in self.tree.query(poly):
            part = poly.intersection(self.polys[i])
            a, b, c = self._planes[i]
            for g in _polygons(part):
                for t in shapely.constrained_delaunay_triangles(g).geoms:
                    xy = np.array(t.exterior.coords[:3])
                    tris.append(np.column_stack([xy, a * xy[:, 0] + b * xy[:, 1] + c]))
        outside = poly.difference(self.hull)
        flat = flat_triangles(outside, self.base)
        out = np.array(tris) if tris else np.zeros((0, 3, 3))
        return np.concatenate([out, flat]) if len(flat) else out

    def mesh(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(vértices, normais suaves, índices) para desenho."""
        v = self.vertices
        f = self.triangles
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        fn[fn[:, 2] < 0] *= -1  # todas para cima
        vn = np.zeros_like(v)
        for k in range(3):
            np.add.at(vn, f[:, k], fn)
        vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
        return v, vn, f


def _polygons(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon" and x.area > 1e-12]


def flat_triangles(g, z: float) -> np.ndarray:
    tris = []
    for p in _polygons(g):
        for t in shapely.constrained_delaunay_triangles(p).geoms:
            xy = np.array(t.exterior.coords[:3])
            tris.append(np.column_stack([xy, np.full(3, z)]))
    return np.array(tris) if tris else np.zeros((0, 3, 3))
