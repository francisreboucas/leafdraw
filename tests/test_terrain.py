import numpy as np
import pytest
from shapely.geometry import Polygon

from leafdraw.core.entities import Contour, Entity, SpotHeight
from leafdraw.core.geom import Affine
from leafdraw.core.terrain import Terrain, terrain_points


def slope():
    """Rampa: z = x / 10 (curvas verticais a cada 10 m)."""
    return [Contour(vertices=[(x, 0), (x, 20)], elevation=x / 10) for x in (0, 10, 20, 30)]


def test_terrain_interpolates_plane():
    t = Terrain.from_entities(slope())
    assert t.valid and t.base == 0
    assert t.elevation(15, 10) == pytest.approx(1.5)
    assert t.elevation(25, 3) == pytest.approx(2.5)
    assert t.elevation(-50, 0) == pytest.approx(0)  # fora da área levantada: cota base


def test_spot_heights_and_empty():
    t = Terrain.from_entities([SpotHeight(position=(0, 0), elevation=1), SpotHeight(position=(10, 0), elevation=1),
                               SpotHeight(position=(0, 10), elevation=1), SpotHeight(position=(10, 10), elevation=5)])
    assert t.valid
    assert 1 <= t.elevation(5, 5) <= 5
    assert not Terrain.from_entities([]).valid
    assert Terrain.from_entities([]).elevation(3, 3) == 0
    assert not Terrain(np.array([(0, 0, 0), (1, 1, 1), (2, 2, 2)])).valid  # colineares


def test_drape_polyline_follows_surface():
    t = Terrain.from_entities(slope())
    pts = t.drape_polyline([(0, 5), (30, 5)])
    assert pts[0, 2] == pytest.approx(0) and pts[-1, 2] == pytest.approx(3)
    assert len(pts) > 2  # quebrada nas arestas dos triângulos
    assert np.allclose(pts[:, 2], pts[:, 0] / 10)


def test_drape_polygon_area_and_height():
    t = Terrain.from_entities(slope())
    sq = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
    tris = t.drape_polygon(sq)
    area = sum(Polygon(tr[:, :2]).area for tr in tris)
    assert area == pytest.approx(100)
    assert np.allclose(tris[..., 2], tris[..., 0] / 10)
    # parte fora do terreno fica plana na base
    out = t.drape_polygon(Polygon([(-10, 5), (-5, 5), (-5, 10), (-10, 10)]))
    assert np.allclose(out[..., 2], 0)


def test_mesh_normals_point_up():
    v, n, f = Terrain.from_entities(slope()).mesh()
    assert len(f) > 0 and np.all(n[:, 2] > 0)


def test_contour_entity_roundtrip_and_transform():
    c = Contour(vertices=[(0, 0), (5, 0)], elevation=812.5)
    assert Entity.from_dict(c.to_dict()) == c
    m = c.translated(1, 1)
    assert isinstance(m, Contour) and m.elevation == 812.5
    s = SpotHeight(position=(1, 2), elevation=-0.4)
    assert s.label() == "−0,40"
    assert Entity.from_dict(s.to_dict()) == s
    assert s.transformed(Affine.translation(1, 0)).position == (2, 2)


def test_points_dense_along_contours():
    pts = terrain_points([Contour(vertices=[(0, 0), (10, 0)], elevation=2)])
    assert len(pts) >= 11 and np.all(pts[:, 2] == 2)
