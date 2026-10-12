import ezdxf
import pytest

from leafdraw.core.commands import AddEntities
from leafdraw.core.document import Document
from leafdraw.core.dxf_io import export_dxf, import_drawing, read_drawing
from leafdraw.core.entities import Arc, Circle, Dimension, Hatch, Line, Plant, Polyline, Text


def _kinds(entities):
    out = {}
    for e in entities:
        out[e.kind] = out.get(e.kind, 0) + 1
    return out


def test_export_import_roundtrip(tmp_path):
    doc = Document()
    ents = [
        Line(p1=(0, 0), p2=(10, 0), layer="construcao"),
        Polyline(vertices=[(0, 0), (5, 0), (5, 5)], closed=True, layer="canteiros", color="#ff0000"),
        Circle(center=(2, 2), radius=1),
        Arc(center=(0, 0), radius=3, start=10, end=100),
        Text(position=(1, 1), text="Jardim", height=0.3, rotation=15),
        Text(position=(1, 4), text="duas\nlinhas", height=0.2),
        Dimension(p1=(0, 0), p2=(10, 0), offset=-1),
        Hatch(loops=[[(0, 0), (5, 0), (5, 5)]], pattern="grass", scale=2),
        Plant(position=(3, 3), species="eugenia-uniflora", canopy=4, height=5, layer="vegetacao"),
    ]
    doc.undo_stack.push(AddEntities(doc, ents))
    path = str(tmp_path / "out.dxf")
    export_dxf(doc, path)

    drawing = read_drawing(path)
    assert drawing.header["$INSUNITS"] == 6
    imp = import_drawing(drawing, species_ids={"eugenia-uniflora"}, existing_layers=doc.layers)
    got = imp.finalize(imp.guess_factor(), to_origin=False)
    kinds = _kinds(got)
    assert kinds == {"line": 1, "polyline": 1, "circle": 1, "arc": 1, "text": 2, "dimension": 1,
                     "hatch": 1, "plant": 1}
    by_kind = {e.kind: e for e in got}
    assert by_kind["polyline"].color == "#ff0000"
    assert by_kind["polyline"].layer == "canteiros"  # camada existente reaproveitada
    assert by_kind["plant"].canopy == pytest.approx(4)
    assert by_kind["plant"].height == pytest.approx(5)
    assert by_kind["hatch"].pattern == "grass"
    assert by_kind["hatch"].scale == pytest.approx(2)
    assert by_kind["dimension"].offset == pytest.approx(-1)
    assert by_kind["arc"].start == pytest.approx(10)
    two = [e for e in got if e.kind == "text" and "\n" in e.text][0]
    assert two.position == pytest.approx((1, 4))


def test_import_units_and_blocks(tmp_path):
    dwg = ezdxf.new("R2010")
    dwg.header["$INSUNITS"] = 5  # cm
    dwg.layers.add("ARQ-PAREDE", color=1)
    blk = dwg.blocks.new("PORTA")
    blk.add_line((0, 0), (90, 0))  # camada 0: herda a camada do INSERT
    blk.add_arc((0, 0), 90, 0, 90)
    msp = dwg.modelspace()
    msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 500)], dxfattribs={"layer": "ARQ-PAREDE"})
    msp.add_blockref("PORTA", (100, 0), dxfattribs={"layer": "ARQ-PAREDE", "rotation": 90})
    msp.add_lwpolyline([(0, 0, 0, 0, 1), (100, 0)], format="xyseb")  # com bulge
    msp.add_point((5, 5))
    path = str(tmp_path / "arq.dxf")
    dwg.saveas(path)

    imp = import_drawing(read_drawing(path))
    assert imp.guess_factor() == 0.01
    assert imp.skipped["POINT"] == 1
    got = imp.finalize(0.01, to_origin=False)
    names = {l.id: l.name for l in imp.layers}
    door = [e for e in got if isinstance(e, Line)][0]
    assert names[door.layer] == "ARQ-PAREDE"
    assert door.p2 == pytest.approx((1.0, 0.9))  # 100 cm + rotação de 90°
    bulged = [e for e in got if isinstance(e, Polyline) and len(e.vertices) > 3]
    assert bulged, "polilinha com bulge deve ser discretizada"
    wall = [e for e in got if isinstance(e, Polyline) and len(e.vertices) == 3][0]
    assert wall.vertices[2] == pytest.approx((10, 5))
