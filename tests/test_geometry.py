import math

import pytest

from leafdraw.core.coords import direct_distance, parse_input
from leafdraw.core.editing import explode_entity, find_boundary, offset_entity
from leafdraw.core.entities import Arc, Circle, Dimension, Hatch, Line, Polyline, Text
from leafdraw.core.geom import (Affine, ArcP, Seg, arc_from_3_points, intersections, nearest_on,
                                perpendicular_feet)


def approx_pt(p, q, tol=1e-9):
    return math.dist(p, q) < tol


# --- transformações ------------------------------------------------------

def test_rotation_about_point():
    t = Affine.rotation(90, (1, 1))
    assert approx_pt(t.apply((2, 1)), (1, 2))


def test_mirror_and_compose():
    m = Affine.mirror((0, 0), (0, 1))  # eixo Y
    assert approx_pt(m.apply((3, 2)), (-3, 2))
    assert m.mirrored
    t = Affine.translation(1, 0) @ Affine.scaling(2)
    assert approx_pt(t.apply((1, 1)), (3, 2))
    assert t.scale == pytest.approx(2)


def test_arc_mirror_keeps_geometry():
    a = Arc(center=(0, 0), radius=1, start=0, end=90)
    m = a.transformed(Affine.mirror((0, 0), (0, 1)))
    assert approx_pt(m.start_point, (0, 1), 1e-9) or approx_pt(m.end_point, (0, 1), 1e-9)
    assert m.sweep == pytest.approx(90)
    assert {round(m.start), round(m.end)} == {90, 180}


def test_text_mirror_stays_readable():
    t = Text(position=(1, 0), text="Ipê", rotation=0)
    m = t.transformed(Affine.mirror((0, 0), (0, 1)))
    assert m.rotation == pytest.approx(0)
    assert approx_pt(m.position, (-1, 0))


# --- primitivas ------------------------------------------------------------

def test_intersections():
    assert approx_pt(intersections(Seg((0, 0), (2, 2)), Seg((0, 2), (2, 0)))[0], (1, 1))
    pts = intersections(Seg((-2, 0), (2, 0)), ArcP((0, 0), 1))
    assert sorted(round(p[0], 9) for p in pts) == [-1, 1]
    pts = intersections(Seg((-2, 0), (2, 0)), ArcP((0, 0), 1, 0, 90))
    assert len(pts) == 1 and approx_pt(pts[0], (1, 0))
    pts = intersections(ArcP((0, 0), 1), ArcP((1, 0), 1))
    assert len(pts) == 2


def test_nearest_and_perpendicular():
    assert approx_pt(nearest_on(Seg((0, 0), (10, 0)), (3, 5)), (3, 0))
    assert approx_pt(nearest_on(ArcP((0, 0), 2), (0, 5)), (0, 2))
    assert perpendicular_feet(Seg((0, 0), (10, 0)), (12, 3)) == []
    assert approx_pt(perpendicular_feet(Seg((0, 0), (10, 0)), (4, 3))[0], (4, 0))


def test_arc_from_3_points():
    c, r, a0, a1 = arc_from_3_points((1, 0), (0, 1), (-1, 0))
    assert approx_pt(c, (0, 0)) and r == pytest.approx(1)
    assert (round(a0), round(a1)) == (0, 180)
    c, r, a0, a1 = arc_from_3_points((1, 0), (0, -1), (-1, 0))
    assert (round(a0), round(a1)) == (180, 360 % 360) or (round(a0), round(a1)) == (180, 0)


# --- entrada de coordenadas -------------------------------------------------

@pytest.mark.parametrize("text,base,expected", [
    ("10,5", None, (10, 5)),
    ("@3,4", (1, 1), (4, 5)),
    ("@2<90", (1, 1), (1, 3)),
    ("2,5;3", None, (2.5, 3)),
    ("@1,5;-2", (0, 0), (1.5, -2)),
])
def test_parse_points(text, base, expected):
    r = parse_input(text, base)
    assert r.kind == "point" and approx_pt(r.point, expected, 1e-9)


def test_parse_values_and_text():
    assert parse_input("7.5").value == 7.5
    assert parse_input("2,5", prefer_value=True).value == 2.5
    assert parse_input("2,5").kind == "point"
    assert parse_input("pl").kind == "text"
    with pytest.raises(ValueError):
        parse_input("@abc")
    assert approx_pt(direct_distance((0, 0), (10, 0), 3), (3, 0))


# --- edição ----------------------------------------------------------------

def test_offset_line_and_circle():
    o = offset_entity(Line(p1=(0, 0), p2=(10, 0)), 2, (5, -1))
    assert approx_pt(o.p1, (0, -2)) and approx_pt(o.p2, (10, -2))
    assert offset_entity(Circle(radius=5), 1, (0, 0)).radius == pytest.approx(4)
    assert offset_entity(Circle(radius=5), 1, (10, 0)).radius == pytest.approx(6)


def test_offset_closed_polyline():
    sq = Polyline(vertices=[(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    inner = offset_entity(sq, 1, (5, 5))
    assert inner.area == pytest.approx(64)
    outer = offset_entity(sq, 1, (20, 5))
    assert outer.area == pytest.approx(144)
    assert inner.id != sq.id


def test_explode():
    pl = Polyline(vertices=[(0, 0), (1, 0), (1, 1)], closed=True, layer="x")
    lines = explode_entity(pl)
    assert len(lines) == 3 and all(l.layer == "x" for l in lines)
    parts = explode_entity(Dimension(p1=(0, 0), p2=(4, 0), offset=1))
    assert any(isinstance(p, Text) and p.text == "4,00" for p in parts)


def test_find_boundary_with_island():
    outer = Polyline(vertices=[(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    island = Circle(center=(5, 5), radius=2)
    loops = find_boundary([outer, island], (1, 1))
    h = Hatch(loops=loops)
    assert h.area == pytest.approx(100 - math.pi * 4, rel=1e-2)
    # contorno formado por linhas soltas
    lines = [Line(p1=a, p2=b) for a, b in [((0, 0), (4, 0)), ((4, 0), (4, 3)), ((4, 3), (0, 3)), ((0, 3), (0, 0))]]
    loops = find_boundary(lines, (1, 1))
    assert Hatch(loops=loops).area == pytest.approx(12)
    assert find_boundary(lines, (10, 10)) is None


def test_dimension_value_and_transform():
    d = Dimension(p1=(0, 0), p2=(3, 4), offset=1)
    assert d.label() == "5,00"
    m = d.transformed(Affine.mirror((0, 0), (0, 1)))
    assert m.offset == pytest.approx(-1)
    assert d.layout()["d1"] == pytest.approx((-0.8, 0.6))
