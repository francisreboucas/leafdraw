"""Operações de edição que geram novas entidades: offset, explodir e contorno de hachura."""
from __future__ import annotations

import math
from dataclasses import replace

from shapely.geometry import LineString, MultiLineString, Point as SPoint, Polygon
from shapely.ops import polygonize, unary_union

from leafdraw.core.entities import (Arc, Circle, Dimension, Entity, Hatch, Line, Polyline, Text,
                                    signed_area)
from leafdraw.core.geom import nearest_on, point_side, tessellate

OFFSET_KINDS = ("line", "polyline", "circle", "arc")


def offset_entity(e: Entity, distance: float, side_point) -> Entity | None:
    """Cópia paralela de ``e`` a ``distance`` metros, do lado de ``side_point``."""
    if distance <= 0:
        return None
    if isinstance(e, Line):
        L = e.length
        if L == 0:
            return None
        nx, ny = -(e.p2[1] - e.p1[1]) / L, (e.p2[0] - e.p1[0]) / L
        s = 1 if point_side(e.p1, e.p2, side_point) > 0 else -1
        dx, dy = nx * distance * s, ny * distance * s
        return replace(e, p1=(e.p1[0] + dx, e.p1[1] + dy), p2=(e.p2[0] + dx, e.p2[1] + dy)).copy_new_id()
    if isinstance(e, (Circle, Arc)):
        outside = math.dist(e.center, side_point) > e.radius
        r = e.radius + distance if outside else e.radius - distance
        return replace(e, radius=r).copy_new_id() if r > 1e-9 else None
    if isinstance(e, Polyline) and len(e.vertices) >= 2:
        return _offset_polyline(e, distance, side_point)
    return None


def _offset_polyline(e: Polyline, distance: float, side_point) -> Polyline | None:
    if e.closed and len(e.vertices) >= 3:
        poly = Polygon(e.vertices)
        if not poly.is_valid:
            poly = poly.buffer(0)
        inside = poly.contains(SPoint(side_point))
        res = poly.buffer(-distance if inside else distance, join_style="mitre", mitre_limit=5.0)
        if res.is_empty:
            return None
        if res.geom_type == "MultiPolygon":
            res = max(res.geoms, key=lambda g: g.area)
        verts = [tuple(map(float, c)) for c in res.exterior.coords[:-1]]
        if signed_area(verts) * signed_area(e.vertices) < 0:
            verts.reverse()
        return replace(e, vertices=verts).copy_new_id()
    # lado: pelo segmento mais próximo do ponto de referência
    segs = e.primitives()
    nearest = min(segs, key=lambda s: math.dist(nearest_on(s, side_point), side_point))
    left = point_side(nearest.a, nearest.b, side_point) > 0
    res = LineString(e.vertices).offset_curve(distance if left else -distance, join_style="mitre", mitre_limit=5.0)
    if res.is_empty:
        return None
    if isinstance(res, MultiLineString):
        res = max(res.geoms, key=lambda g: g.length)
    return replace(e, vertices=[tuple(map(float, c)) for c in res.coords]).copy_new_id()


def explode_entity(e: Entity) -> list[Entity]:
    """Decompõe em entidades mais simples. Lista vazia se não for decomponível."""
    base = {"layer": e.layer, "color": e.color}
    if isinstance(e, Polyline):
        return [Line(p1=a, p2=b, **base) for a, b in e.segments()]
    if isinstance(e, Dimension):
        lay = e.layout()
        out: list[Entity] = [Line(p1=a, p2=b, **base) for a, b in e.line_segments()]
        out.append(Text(position=_text_start(e, lay), text=e.label(), height=e.text_height,
                        rotation=lay["angle"], **base))
        return out
    if isinstance(e, Hatch):
        return [Polyline(vertices=list(loop), closed=True, **base) for loop in e.loops]
    return []


def _text_start(e: Dimension, lay) -> tuple[float, float]:
    """Início aproximado da linha de base para um texto centrado em ``text_center``."""
    w = len(e.label()) * e.text_height * Text.CHAR_WIDTH
    a = math.radians(lay["angle"])
    cx, cy = lay["text_center"]
    return (cx - math.cos(a) * w / 2, cy - math.sin(a) * w / 2)


# --- contorno de hachura -------------------------------------------------

def entity_polygon(e: Entity) -> Polygon | None:
    """Polígono de uma entidade fechada (polilinha fechada, círculo)."""
    if isinstance(e, Polyline) and e.closed and len(e.vertices) >= 3:
        poly = Polygon(e.vertices)
    elif isinstance(e, Circle):
        poly = SPoint(e.center).buffer(e.radius, quad_segs=32)
    else:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.geom_type != "Polygon":
            return None
    return poly if poly.area > 0 else None


def _linework(e: Entity):
    for pr in e.primitives():
        pts = tessellate(pr, 3.0)
        if len(pts) >= 2:
            yield LineString(pts)


def find_boundary(entities: list[Entity], point) -> list[list[tuple[float, float]]] | None:
    """Contorno (externo + furos) que envolve ``point``.

    Tenta primeiro entidades fechadas; se nenhuma envolver o ponto, monta
    regiões a partir das linhas soltas (polygonize).
    """
    p = SPoint(point)
    closed = [(e, poly) for e in entities if (poly := entity_polygon(e)) is not None]
    containing = [poly for _e, poly in closed if poly.contains(p)]
    if containing:
        outer = min(containing, key=lambda g: g.area)
        inner = [poly for _e, poly in closed
                 if poly is not outer and not poly.contains(p) and outer.contains(poly)]
        # só furos de primeiro nível
        holes = [h for h in inner if not any(o is not h and o.contains(h) for o in inner)]
        return [_coords(outer.exterior)] + [_coords(h.exterior) for h in holes]

    lines = [ls for e in entities if not isinstance(e, (Text, Hatch)) for ls in _linework(e)]
    if not lines:
        return None
    regions = [g for g in polygonize(unary_union(lines)) if g.contains(p)]
    if not regions:
        return None
    region = min(regions, key=lambda g: g.area)
    return [_coords(region.exterior)] + [_coords(r) for r in region.interiors]


def _coords(ring) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in ring.coords[:-1]]
