import json
from dataclasses import replace

import ezdxf
import pytest

from leafdraw.core.catalog import PlantCatalog, Species
from leafdraw.core.commands import AddEntities
from leafdraw.core.document import Document
from leafdraw.core.dxf_io import export_dxf
from leafdraw.core.elevation import compute_elevation, procedural_shapes, species_elevation, to_view
from leafdraw.core.entities import Contour, ElevationView, Entity, Plant, PlantingArea
from leafdraw.core.geom import Affine
from leafdraw.core.symbol_blocks import MODEL_SPACE, block_drawing, list_blocks
from leafdraw.core.terrain import Terrain, document_terrain

IPE = "handroanthus-albus"  # altura 10, copa 6


@pytest.fixture(scope="module")
def catalog():
    return PlantCatalog.load()


def _compute(ev, ents, catalog, terrain=None):
    return compute_elevation(ev, ents, lambda e: True, catalog, terrain)


@pytest.mark.parametrize("simbolo", ["arvore", "palmeira", "arbusto", "forracao"])
def test_procedural_shapes_fit_the_plant(simbolo):
    shapes = procedural_shapes(simbolo, 6.0, 10.0, "x")
    pts = [p for s in shapes for p in s.pts]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert min(ys) == pytest.approx(0.0, abs=1e-6)  # apoiada no chão
    assert max(ys) == pytest.approx(10.0, rel=0.08)
    assert max(xs) - min(xs) == pytest.approx(6.0, rel=0.15)
    assert any(s.closed and s.fill == "folha" for s in shapes)
    assert procedural_shapes(simbolo, 6.0, 10.0, "x") == shapes  # determinístico


def test_selects_plants_in_front_within_depth(catalog):
    ev = ElevationView(p1=(0, 0), p2=(10, 0), side=1, depth=20, origin=(100, 50))
    front = Plant(position=(3, 5), species=IPE, canopy=6, height=10)
    behind = Plant(position=(3, -5), species=IPE, canopy=6, height=10)
    far = Plant(position=(3, 25), species=IPE, canopy=6, height=10)
    outside = Plant(position=(15, 5), species=IPE, canopy=6, height=10)
    data = _compute(ev, [front, behind, far, outside], catalog)
    assert [p.eid for p in data.plants] == [front.id]
    pl = data.plants[0]
    assert (pl.x, pl.y) == pytest.approx((103, 50))
    assert data.profile == [(100, 50), (110, 50)]
    # sem limite de profundidade entra a mais distante; ordem do fundo para a frente
    data = _compute(replace(ev, depth=0), [front, far], catalog)
    assert [p.eid for p in data.plants] == [far.id, front.id]
    # olhando para o outro lado: a de trás entra e o eixo X se inverte
    data = _compute(replace(ev, side=-1), [front, behind], catalog)
    assert [p.eid for p in data.plants] == [behind.id]
    assert data.plants[0].x == pytest.approx(107)


def test_to_view_mirrors_with_side():
    ev = ElevationView(p1=(0, 0), p2=(10, 0), side=1)
    assert to_view(ev, (2, 3)) == pytest.approx((2, 3))
    assert to_view(replace(ev, side=-1), (2, -3)) == pytest.approx((8, 3))


def test_plants_sit_on_terrain(catalog):
    ents = [Contour(vertices=[(-10, 0), (20, 0)], elevation=0.0), Contour(vertices=[(-10, 20), (20, 20)], elevation=4.0)]
    terrain = Terrain.from_entities(ents)
    p = Plant(position=(5, 10), species=IPE, canopy=6, height=10)
    ev = ElevationView(p1=(0, 1), p2=(10, 1), origin=(0, 0), datum=0.0)
    data = _compute(ev, [p], catalog, terrain)
    assert data.plants[0].y == pytest.approx(2.0, abs=0.05)
    assert all(y == pytest.approx(0.2, abs=0.05) for _x, y in data.profile)


def test_massed_plants_included(catalog):
    area = PlantingArea(loops=[[(0, 1), (10, 1), (10, 3), (0, 3)]], species="ixora-coccinea", spacing=0.5)
    ev = ElevationView(p1=(0, 0), p2=(10, 0))
    data = _compute(ev, [area], catalog)
    assert len(data.plants) == area.count


def test_entity_roundtrip_and_transform():
    ev = ElevationView(p1=(0, 0), p2=(10, 0), side=-1, depth=5, origin=(1, 2), datum=3, name="B")
    assert Entity.from_dict(json.loads(json.dumps(ev.to_dict()))) == ev
    moved = ev.transformed(Affine.translation(5, 5))
    assert moved.origin == (6, 7) and moved.p1 == ev.p1  # só o desenho se move
    assert ev.moved_grip(2, (5, 3)).p1 == pytest.approx((0, 3))
    assert ev.moved_grip(3, (9, 9)).origin == (9, 9)


def test_document_terrain_is_cached():
    doc = Document()
    c = Contour(vertices=[(0, 0), (10, 0)], elevation=0)
    doc.undo_stack.push(AddEntities(doc, [c, Contour(vertices=[(0, 10), (10, 10)], elevation=2)]))
    t1 = document_terrain(doc)
    assert document_terrain(doc) is t1
    doc.undo_stack.push(AddEntities(doc, [Contour(vertices=[(0, 20), (10, 20)], elevation=4)]))
    assert document_terrain(doc) is not t1


def test_block_import_and_species_roundtrip(tmp_path, catalog):
    dwg = ezdxf.new()
    blk = dwg.blocks.new("ARVORE_VISTA")
    blk.add_line((0, 0), (0, 200))  # tronco
    blk.add_circle((0, 500), 300)  # copa
    blk.add_text("ignorado", height=50)
    dwg.modelspace().add_circle((10, 10), 5)
    path = tmp_path / "blocos.dxf"
    dwg.saveas(path)
    dwg = ezdxf.readfile(path)
    assert list_blocks(dwg) == ["ARVORE_VISTA"]

    vista = block_drawing(dwg, "ARVORE_VISTA", "vista")
    pts = [p for _c, ps in vista for p in ps]
    assert min(p[1] for p in pts) == pytest.approx(0) and max(p[1] for p in pts) == pytest.approx(1)
    assert min(p[0] for p in pts) == pytest.approx(-0.5) and max(p[0] for p in pts) == pytest.approx(0.5)
    assert sorted(c for c, _ in vista) == [False, True]

    planta = block_drawing(dwg, MODEL_SPACE, "planta")
    assert max(abs(c) for _c, ps in planta for p in ps for c in p) == pytest.approx(1, abs=1e-3)

    sp = replace(catalog.get(IPE), desenho_vista=vista, desenho_planta=planta)
    back = Species.from_dict(json.loads(json.dumps(sp.to_dict())))
    assert back == sp
    shapes = species_elevation(back, 6.0, 10.0)
    assert max(p[1] for s in shapes for p in s.pts) == pytest.approx(10)


def test_block_without_geometry_fails():
    dwg = ezdxf.new()
    dwg.blocks.new("VAZIO").add_text("x")
    with pytest.raises(ValueError):
        block_drawing(dwg, "VAZIO", "vista")


def test_dxf_export_includes_elevation(tmp_path, catalog):
    doc = Document()
    doc.undo_stack.push(AddEntities(doc, [Plant(position=(3, 5), species=IPE, canopy=6, height=10),
                                          ElevationView(p1=(0, 0), p2=(10, 0), origin=(0, -30), name="A")]))
    path = tmp_path / "vista.dxf"
    export_dxf(doc, str(path), catalog)
    msp = ezdxf.readfile(path).modelspace()
    texts = {e.dxf.text for e in msp.query("TEXT")}
    assert "VISTA A" in texts
    assert len(msp.query("LWPOLYLINE")) >= 4  # perfil + silhueta
