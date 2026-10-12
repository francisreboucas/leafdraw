import pytest

from leafdraw.core.catalog import default_catalog
from leafdraw.core.commands import AddEntities, RemoveEntities, ReplaceEntities
from leafdraw.core.document import Document
from leafdraw.core.entities import Circle, Entity, Line, Plant, Polyline
from leafdraw.core.fileio import load_document, save_document


@pytest.fixture
def doc():
    return Document()


def test_add_undo_redo(doc):
    line = Line(p1=(0, 0), p2=(3, 4))
    doc.undo_stack.push(AddEntities(doc, [line]))
    assert doc.entities[line.id].length == 5
    assert doc.is_modified()
    doc.undo_stack.undo()
    assert line.id not in doc.entities
    doc.undo_stack.redo()
    assert line.id in doc.entities


def test_move_is_undoable(doc):
    c = Circle(center=(1, 1), radius=2)
    doc.undo_stack.push(AddEntities(doc, [c]))
    doc.undo_stack.push(ReplaceEntities(doc, [c.translated(2, 3)], "Mover"))
    assert doc.entities[c.id].center == (3, 4)
    doc.undo_stack.undo()
    assert doc.entities[c.id].center == (1, 1)


def test_remove_and_restore(doc):
    p = Plant(position=(5, 5), species="eugenia-uniflora", canopy=4, height=5)
    doc.undo_stack.push(AddEntities(doc, [p]))
    doc.undo_stack.push(RemoveEntities(doc, [p.id]))
    assert not doc.entities
    doc.undo_stack.undo()
    assert doc.entities[p.id] == p


def test_polyline_area_and_length():
    sq = Polyline(vertices=[(0, 0), (4, 0), (4, 3), (0, 3)], closed=True)
    assert sq.area == pytest.approx(12)
    assert sq.length == pytest.approx(14)
    assert Polyline(vertices=sq.vertices).area == 0


def test_layers(doc):
    layer = doc.add_layer("Pisos", "#ff0000")
    doc.rename_layer(layer.id, "Pavimentação")
    assert doc.layer_by_name("Pavimentação") is layer
    with pytest.raises(ValueError):
        doc.rename_layer(layer.id, "0")
    line = Line(p2=(1, 0), layer=layer.id)
    doc.undo_stack.push(AddEntities(doc, [line]))
    assert not doc.can_remove_layer(layer.id)[0]
    assert not doc.can_remove_layer("0")[0]
    doc.undo_stack.undo()
    doc.remove_layer(layer.id)
    # entidade órfã (ex.: restaurada por redo) cai na camada 0
    assert doc.layer_for(line).id == "0"


def test_save_load_roundtrip(doc, tmp_path):
    ents = [
        Line(p1=(0, 0), p2=(1, 1)),
        Polyline(vertices=[(0, 0), (2, 0), (2, 2)], closed=True, layer="canteiros"),
        Circle(center=(-1, -1), radius=0.5),
        Plant(position=(3, 3), species="handroanthus-albus", canopy=6, height=10, layer="vegetacao"),
    ]
    doc.undo_stack.push(AddEntities(doc, ents))
    doc.update_layer("canteiros", visible=False)
    path = str(tmp_path / "teste.leaf")
    save_document(doc, path)
    assert not doc.is_modified()

    other = Document()
    load_document(other, path)
    assert list(other.entities.values()) == ents
    assert other.layers["canteiros"].visible is False
    assert other.file_path == path
    assert not other.is_modified()


def test_entity_dict_roundtrip():
    p = Polyline(vertices=[(0.5, 1), (2, 3)])
    assert Entity.from_dict(p.to_dict()) == p


def test_catalog_loads():
    cat = default_catalog()
    assert cat.get("handroanthus-albus").nome_popular == "Ipê-amarelo"
    assert "Palmeiras" in cat.categories()
