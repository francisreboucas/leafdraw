from pathlib import Path

from leafdraw.core.catalog import PlantCatalog
from leafdraw.core.document import Document
from leafdraw.core.entities import ENTITY_TYPES
from leafdraw.core.fileio import load_document

EXAMPLE = Path(__file__).parent.parent / "examples" / "jardim_residencial.leaf"


def test_example_opens(tmp_path):
    doc = Document()
    load_document(doc, str(EXAMPLE), PlantCatalog.load(user_path=tmp_path / "user.json"))
    assert {e.kind for e in doc.entities.values()} == set(ENTITY_TYPES)  # usa todos os tipos de entidade
    assert [s.paper for s in doc.sheets] == ["A2"] * 3
    assert {el.kind for s in doc.sheets for el in s.elements} == {
        "viewport", "titleblock", "planttable", "text", "north", "scalebar"}
