"""Gizmo 3D: setas X/Y, plano XY e anel de rotação em torno de Z.

Geometria gerada em coordenadas do mundo a cada quadro (tamanho constante na
tela); a detecção é feita em pixels, projetando os pontos de referência.
"""
from __future__ import annotations

import math

import numpy as np

COLORS = {"x": (0.90, 0.30, 0.30), "y": (0.35, 0.80, 0.35), "xy": (0.30, 0.64, 1.0), "rot": (0.35, 0.55, 1.0)}
HOT = (1.0, 0.82, 0.25)
HIT_PX = 9
RING_R = 0.85  # raio do anel, em fração do tamanho do gizmo


def _box(a, b, w, color):
    """Prisma de seção quadrada entre a e b (triângulos com cor)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(d, up)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    corners = [u * w + v * w, -u * w + v * w, -u * w - v * w, u * w - v * w]
    tris = []
    for i in range(4):
        c0, c1 = corners[i], corners[(i + 1) % 4]
        tris += [a + c0, a + c1, b + c1, a + c0, b + c1, b + c0]
    return [(*p, *color, 1.0) for p in tris]


def _cone(base, tip, r, color, n=12):
    base, tip = np.asarray(base, float), np.asarray(tip, float)
    d = tip - base
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(d, up)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    out = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0 = base + (u * math.cos(a0) + v * math.sin(a0)) * r
        p1 = base + (u * math.cos(a1) + v * math.sin(a1)) * r
        out += [p0, p1, tip, p0, base, p1]
    return [(*p, *color, 1.0) for p in out]


def gizmo_triangles(center, size: float, hot: str | None = None) -> np.ndarray:
    c = np.asarray(center, float)
    tris = []
    for axis, d in (("x", (1, 0, 0)), ("y", (0, 1, 0))):
        col = HOT if hot == axis else COLORS[axis]
        tip = c + np.array(d) * size
        tris += _box(c, c + np.array(d) * size * 0.78, size * 0.022, col)
        tris += _cone(c + np.array(d) * size * 0.78, tip, size * 0.07, col)
    # plano XY
    col = HOT if hot == "xy" else COLORS["xy"]
    q = [c + np.array(p) * size for p in ((0.22, 0.22, 0), (0.45, 0.22, 0), (0.45, 0.45, 0), (0.22, 0.45, 0))]
    for p in (q[0], q[1], q[2], q[0], q[2], q[3]):
        tris.append((*p, *col, 0.55))
    # anel de rotação (faixa plana)
    col = HOT if hot == "rot" else COLORS["rot"]
    r0, r1 = size * (RING_R - 0.03), size * (RING_R + 0.03)
    n = 64
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p = [c + np.array([math.cos(a) * r, math.sin(a) * r, 0]) for a, r in ((a0, r0), (a0, r1), (a1, r1), (a1, r0))]
        for k in (0, 1, 2, 0, 2, 3):
            tris.append((*p[k], *col, 0.9))
    return np.array(tris, dtype="f4")


def _seg_dist(p, a, b) -> float:
    ab = b - a
    L2 = float(ab @ ab)
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, float((p - a) @ ab) / L2))
    return float(np.linalg.norm(p - (a + ab * t)))


def hit_test(project, center, size: float, mouse) -> str | None:
    """``project``: (n, 3) mundo → (n, 2) pixels. Retorna o manipulador sob o mouse."""
    c = np.asarray(center, float)
    m = np.asarray(mouse, float)
    pts = project(np.array([c, c + (size, 0, 0), c + (0, size, 0)]))
    if pts is None:
        return None
    pc, px, py = pts
    quad = project(np.array([c + np.array(p) * size for p in ((0.22, 0.22, 0), (0.45, 0.22, 0),
                                                                (0.45, 0.45, 0), (0.22, 0.45, 0))]))
    if quad is not None and point_in_polygon(m, quad):
        return "xy"
    best, best_d = None, HIT_PX
    for name, tip in (("x", px), ("y", py)):
        d = _seg_dist(m, pc, tip)
        if d < best_d:
            best, best_d = name, d
    ring = project(np.array([c + np.array([math.cos(a) * size * RING_R, math.sin(a) * size * RING_R, 0])
                             for a in np.linspace(0, 2 * math.pi, 65)]))
    if ring is not None:
        d = min(_seg_dist(m, ring[i], ring[i + 1]) for i in range(len(ring) - 1))
        if d < best_d:
            best = "rot"
    return best


def point_in_polygon(p, poly) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside
