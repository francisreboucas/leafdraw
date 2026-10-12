import math

import pytest

from leafdraw.core.catalog import PlantCatalog, Species
from leafdraw.core.commands import AddEntities
from leafdraw.core.document import Document
from leafdraw.core.entities import (Arc, Circle, Dimension, Entity, Hatch, Line, Plant, PlantingArea,
                                    Polyline)
from leafdraw.core.fileio import load_document, save_document
from leafdraw.core.geom import Affine
from leafdraw.core.modify import distribute_along, extend_entity, trim_entity
from leafdraw.core.schedule import area_schedule, plant_schedule, to_csv

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_planting_area_count_and_transform():
    pa = PlantingArea(loops=[SQUARE], species="x", spacing=1.0, layout="square")
    # recuo de meio espaçamento: pontos 0,5 … 9,5 → 10 × 10
    assert pa.count == 100
    tri = PlantingArea(loops=[SQUARE], spacing=1.0)
    assert 100 < tri.count < 120
    hole = PlantingArea(loops=[SQUARE, [(4, 4), (6, 4), (6, 6), (4, 6)]], spacing=1.0, layout="square")
    assert hole.count < 100
    moved = pa.translated(100, 0)
    assert moved.count == 100 and moved.spacing == 1.0
    assert Entity.from_dict(pa.to_dict()) == pa


def test_grips():
    ln = Line(p1=(0, 0), p2=(2, 0))
    assert ln.moved_grip(1, (2, 2)).p2 == (2, 2)
    assert ln.moved_grip(2, (1, 1)).p1 == pytest.approx((0, 1))
    c = Circle(center=(0, 0), radius=1)
    assert c.moved_grip(1, (3, 0)).radius == pytest.approx(3)
    a = Arc(center=(0, 0), radius=1, start=0, end=180)
    a2 = a.moved_grip(2, (-2, 0))
    assert a2.end_point == pytest.approx((-2, 0)) and a2.start_point == pytest.approx((1, 0))
    d = Dimension(p1=(0, 0), p2=(4, 0), offset=1)
    assert d.moved_grip(2, (2, -3)).offset == pytest.approx(-3)
    h = Hatch(loops=[SQUARE, [(4, 4), (6, 4), (6, 6)]])
    assert h.moved_grip(5, (5, 5)).loops[1][1] == (5, 5)


def test_trim_line_between_cutters():
    target = Line(p1=(0, 0), p2=(10, 0))
    cutters = [*Line(p1=(3, -1), p2=(3, 1)).primitives(), *Line(p1=(7, -1), p2=(7, 1)).primitives()]
    parts = trim_entity(target, (5, 0), cutters)
    assert [(p.p1, p.p2) for p in parts] == [((0, 0), (3, 0)), ((7, 0), (10, 0))]
    end = trim_entity(target, (9, 0), cutters)
    assert len(end) == 1 and end[0].p2 == pytest.approx((7, 0))
    assert trim_entity(target, (5, 0), []) is None


def test_trim_circle_and_closed_polyline():
    c = Circle(center=(0, 0), radius=1)
    cutter = Line(p1=(0, -2), p2=(0, 2)).primitives()
    arc = trim_entity(c, (1, 0), cutter)[0]
    assert isinstance(arc, Arc) and arc.sweep == pytest.approx(180)
    assert arc.start_point == pytest.approx((0, 1)) and arc.end_point == pytest.approx((0, -1))
    sq = Polyline(vertices=SQUARE, closed=True)
    cut = Line(p1=(5, -1), p2=(5, 11)).primitives()
    rest = trim_entity(sq, (10, 5), cut)[0]
    assert not rest.closed and rest.length == pytest.approx(20)


def test_extend():
    wall = Line(p1=(10, -5), p2=(10, 5)).primitives()
    ln = Line(p1=(0, 0), p2=(4, 0))
    assert extend_entity(ln, (3.9, 0), wall).p2 == pytest.approx((10, 0))
    pl = Polyline(vertices=[(0, 2), (2, 2), (4, 0)])
    assert extend_entity(pl, (3.9, 0.1), Line(p1=(-5, -3), p2=(10, -3)).primitives()).vertices[-1] == \
        pytest.approx((7, -3))
    arc = Arc(center=(0, 0), radius=5, start=0, end=45)
    ext = extend_entity(arc, arc.end_point, Line(p1=(0, 0), p2=(0, 10)).primitives())
    assert ext.end == pytest.approx(90)


def test_distribute_along():
    ln = Line(p1=(0, 0), p2=(10, 0))
    pts = distribute_along(ln, 3)
    assert [round(p[0], 6) for p in pts] == [2, 5, 8]
    pts = distribute_along(ln, 3, from_ends=True)
    assert len(pts) == 4 and pts[0] == pytest.approx((0, 0)) and pts[-1] == pytest.approx((10, 0))
    ring = distribute_along(Circle(radius=10), 2 * math.pi)
    assert len(ring) == 10


def test_schedule_and_csv():
    doc = Document()
    cat = PlantCatalog([Species("a", "Ipê", "Handroanthus", "Árvores", 10, 6, "#ffff00"),
                        Species("b", "Grama", "Zoysia", "Forrações", 0.1, 0.3, "#00ff00", "forracao")])
    ents = [Plant(species="a"), Plant(species="a", position=(5, 5)),
            PlantingArea(loops=[SQUARE], species="b", spacing=1.0, layout="square"),
            Hatch(loops=[SQUARE], pattern="grass"), Hatch(loops=[[(0, 0), (2, 0), (2, 2), (0, 2)]], pattern="grass")]
    doc.undo_stack.push(AddEntities(doc, ents))
    rows = plant_schedule(doc, cat)
    assert [(r.nome_popular, r.total) for r in rows] == [("Ipê", 2), ("Grama", 100)]
    assert rows[1].massed_area == pytest.approx(100)
    areas = area_schedule(doc)
    assert areas[0].label == "Grama" and areas[0].area == pytest.approx(104) and areas[0].count == 2
    csv = to_csv(rows, areas)
    assert "Ipê;Handroanthus;10,00;6,00;2;0;0,00;2" in csv and "Total de mudas;102" in csv


def test_user_catalog_and_project_species(tmp_path):
    user = tmp_path / "user.json"
    cat = PlantCatalog.load(user_path=user)
    sid = cat.new_id("Eugenia uniflora")
    assert sid != "eugenia-uniflora"  # já existe no embutido
    mine = Species(sid, "Pitanga anã", "Eugenia uniflora", "Frutíferas", 2, 1.5, "#aa3333", "arbusto")
    cat.upsert(mine)
    assert PlantCatalog.load(user_path=user).get(sid) == mine
    assert cat.origin(sid) == "usuário"

    doc = Document()
    doc.undo_stack.push(AddEntities(doc, [Plant(species=sid, layer="vegetacao")]))
    path = str(tmp_path / "p.leaf")
    save_document(doc, path, cat)

    other_cat = PlantCatalog.load()  # outra máquina, sem a espécie do usuário
    added = load_document(Document(), path, other_cat)
    assert [s.id for s in added] == [sid]
    assert other_cat.origin(sid) == "projeto"
    assert other_cat.get(sid).nome_popular == "Pitanga anã"


def test_planting_rotation_keeps_count():
    pa = PlantingArea(loops=[SQUARE], spacing=1.0, layout="square")
    rot = pa.transformed(Affine.rotation(30, (5, 5)))
    assert rot.count == pa.count
