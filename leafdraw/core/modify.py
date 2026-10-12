"""Aparar, estender e distribuir ao longo de caminhos."""
from __future__ import annotations

import math
from dataclasses import replace

from leafdraw.core.entities import Arc, Circle, Entity, Line, Polyline
from leafdraw.core.geom import (ArcP, Seg, angle_of, intersections, nearest_on, norm_angle, param_on,
                                point_along, point_on, prim_length)

TRIM_KINDS = ("line", "polyline", "circle", "arc")
EXTEND_KINDS = ("line", "polyline", "arc")
PATH_KINDS = ("line", "polyline", "arc", "circle")
_RAY = 1e6  # comprimento do "raio" usado para estender
_EPS = 1e-9


def _cut_params(prims, cutters) -> list[float]:
    """Distâncias (ao longo do caminho) onde ``prims`` cruza os ``cutters``."""
    out, acc = [], 0.0
    for pr in prims:
        for c in cutters:
            for pt in intersections(pr, c):
                out.append(acc + param_on(pr, pt))
        acc += prim_length(pr)
    return sorted(set(round(t, 9) for t in out))


def _param_along(prims, p) -> float:
    best, best_d, acc = 0.0, math.inf, 0.0
    for pr in prims:
        q = nearest_on(pr, p)
        d = math.dist(q, p)
        if d < best_d:
            best, best_d = acc + param_on(pr, q), d
        acc += prim_length(pr)
    return best


def _sub_path(prims, d0: float, d1: float) -> list[tuple[float, float]]:
    """Pontos do caminho entre as distâncias d0 e d1 (arcos discretizados)."""
    pts, acc = [], 0.0
    for pr in prims:
        L = prim_length(pr)
        a, b = max(d0, acc), min(d1, acc + L)
        if b > a + 1e-12:
            if isinstance(pr, Seg):
                seq = [point_on(pr, a - acc), point_on(pr, b - acc)]
            else:
                n = max(2, math.ceil(math.degrees((b - a) / pr.r) / 3))
                seq = [point_on(pr, a - acc + (b - a) * k / n) for k in range(n + 1)]
            for q in seq:
                if not pts or math.dist(pts[-1], q) > _EPS:
                    pts.append(q)
        acc += L
    return pts


def _piece(e: Entity, prims, a: float, b: float, base) -> Entity:
    if isinstance(e, Line):
        return Line(p1=point_along(prims, a), p2=point_along(prims, b), **base)
    if isinstance(e, Arc):
        return Arc(center=e.center, radius=e.radius, start=norm_angle(e.start + math.degrees(a / e.radius)),
                   end=norm_angle(e.start + math.degrees(b / e.radius)), **base)
    return Polyline(vertices=_sub_path(prims, a, b), **base)


def trim_entity(e: Entity, pick, cutters) -> list[Entity] | None:
    """Remove o trecho de ``e`` sob ``pick`` entre as interseções vizinhas.

    Retorna as partes que sobram ou None se não houver interseções para aparar.
    """
    base = {"layer": e.layer, "color": e.color}
    if isinstance(e, Circle):
        angles = sorted({round(angle_of(e.center, pt), 9) for c in cutters
                         for pt in intersections(ArcP(e.center, e.radius), c)})
        if len(angles) < 2:
            return None
        a = angle_of(e.center, pick)
        # remove o intervalo anti-horário [lo, hi] que contém o clique; sobra o arco hi→lo
        lo = max((x for x in angles if x <= a), default=angles[-1])
        hi = min((x for x in angles if x > a), default=angles[0])
        return [Arc(center=e.center, radius=e.radius, start=hi, end=lo, **base)]

    prims = e.primitives()
    if not prims:
        return None
    L = sum(prim_length(p) for p in prims)
    t = _param_along(prims, pick)

    if isinstance(e, Polyline) and e.closed:
        ts = _cut_params(prims, cutters)
        if len(ts) < 2:
            return None
        lo = max((x for x in ts if x <= t), default=ts[-1] - L)
        hi = min((x for x in ts if x > t), default=ts[0] + L)
        # sobra o trecho que começa em hi e dá a volta até lo
        start = hi % L
        pts = _sub_path(prims + prims, start, start + L - (hi - lo))
        return [Polyline(vertices=pts, **base)] if len(pts) >= 2 else []

    if isinstance(e, (Line, Polyline, Arc)):
        ts = [x for x in _cut_params(prims, cutters) if _EPS < x < L - _EPS]
        if not ts:
            return None
        lo = max((x for x in ts if x < t), default=0.0)
        hi = min((x for x in ts if x > t), default=L)
        return [_piece(e, prims, a, b, base) for a, b in ((0.0, lo), (hi, L)) if b - a > _EPS]
    return None


def extend_entity(e: Entity, pick, boundaries) -> Entity | None:
    """Estende a ponta de ``e`` mais próxima de ``pick`` até o limite mais próximo."""
    if isinstance(e, Line):
        at_end = math.dist(pick, e.p2) <= math.dist(pick, e.p1)
        a, b = (e.p1, e.p2) if at_end else (e.p2, e.p1)
        new = _extend_point(a, b, boundaries)
        if new is None:
            return None
        return replace(e, p2=new) if at_end else replace(e, p1=new)
    if isinstance(e, Polyline) and not e.closed and len(e.vertices) >= 2:
        v = e.vertices
        at_end = math.dist(pick, v[-1]) <= math.dist(pick, v[0])
        a, b = (v[-2], v[-1]) if at_end else (v[1], v[0])
        new = _extend_point(a, b, boundaries)
        if new is None:
            return None
        verts = list(v)
        verts[-1 if at_end else 0] = new
        return replace(e, vertices=verts)
    if isinstance(e, Arc):
        at_end = math.dist(pick, e.end_point) <= math.dist(pick, e.start_point)
        full = ArcP(e.center, e.radius)
        cands = [angle_of(e.center, pt) for c in boundaries for pt in intersections(full, c)]
        room = 360 - e.sweep - 1e-7
        if at_end:
            gaps = [g for x in cands if 1e-7 < (g := norm_angle(x - e.end)) < room]
            return replace(e, end=norm_angle(e.end + min(gaps))) if gaps else None
        gaps = [g for x in cands if 1e-7 < (g := norm_angle(e.start - x)) < room]
        return replace(e, start=norm_angle(e.start - min(gaps))) if gaps else None
    return None


def _extend_point(a, b, boundaries):
    """Interseção mais próxima do raio que sai de b na direção a→b."""
    L = math.dist(a, b)
    if L < 1e-12:
        return None
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    ray = Seg(b, (b[0] + ux * _RAY, b[1] + uy * _RAY))
    hits = [pt for c in boundaries for pt in intersections(ray, c) if math.dist(pt, b) > _EPS]
    return min(hits, key=lambda q: math.dist(q, b)) if hits else None


def path_length(e: Entity) -> float:
    return sum(prim_length(p) for p in e.primitives())


def distribute_along(e: Entity, spacing: float, from_ends: bool = False) -> list[tuple[float, float]]:
    """Posições a cada ``spacing`` metros ao longo de ``e``.

    Caminhos abertos: por padrão a sobra é dividida entre as duas pontas
    (cerca viva); com ``from_ends`` as pontas recebem plantas e o espaçamento
    é ajustado para fechar exatamente (alameda). Caminhos fechados recebem
    plantas igualmente espaçadas.
    """
    prims = e.primitives()
    L = sum(prim_length(p) for p in prims)
    if spacing <= 0 or L <= 0:
        return []
    closed = isinstance(e, Circle) or (isinstance(e, Polyline) and e.closed)
    if closed:
        n = max(1, round(L / spacing))
        return [point_along(prims, L * i / n) for i in range(n)]
    if from_ends:
        n = max(1, round(L / spacing))
        return [point_along(prims, L * i / n) for i in range(n + 1)]
    n = max(1, math.floor(L / spacing))
    start = (L - (n - 1) * spacing) / 2
    return [point_along(prims, start + i * spacing) for i in range(n)]
