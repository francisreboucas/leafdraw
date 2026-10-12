import pytest

from leafdraw.core.commands import AddEntities, ReplaceSheets
from leafdraw.core.document import Document
from leafdraw.core.entities import Line
from leafdraw.core.fileio import load_document, save_document
from leafdraw.core.sheets import (PlantTableElement, ScaleBarElement, Sheet, TitleBlockElement, ViewportElement,
                                  default_sheet, fit_scale, nice_bar_length, paper_size)


def test_paper_and_scale():
    assert paper_size("A3", "portrait") == (297, 420)
    # 40 m num retângulo de 500 mm: 1:100 (400 mm) cabe, 1:75 (533 mm) não
    assert fit_scale(40, 10, 500, 300) == 100
    assert nice_bar_length(100, 80) == 5.0


def test_default_sheet_layout():
    sh = default_sheet((0, 0, 40, 25), paper="A1")
    kinds = [e.kind for e in sh.elements]
    assert kinds[0] == "viewport" and "titleblock" in kinds and "planttable" in kinds
    vp = sh.viewports()[0]
    x0, y0, x1, y1 = vp.model_rect()
    assert x0 <= 0 and y0 <= 0 and x1 >= 40 and y1 >= 25  # o modelo inteiro aparece
    fx, fy, fw, fh = sh.frame_rect()
    for e in sh.elements:  # tudo dentro das margens
        assert e.x >= fx - 1e-9 and e.y >= fy - 1e-9
        assert e.x + e.w <= fx + fw + 1e-9 and e.y + e.h <= fy + fh + 1e-9
    a4 = default_sheet((0, 0, 10, 10), paper="A4", orientation="portrait")
    assert not any(isinstance(e, PlantTableElement) for e in a4.elements)


def test_viewport_paper_to_model():
    vp = ViewportElement(x=10, y=20, w=100, h=50, center=(5, 5), scale=100)
    assert vp.paper_to_model(60, 45) == pytest.approx((5, 5))  # centro
    assert vp.paper_to_model(70, 35) == pytest.approx((6, 6))  # +10 mm → +1 m; Y do papel é invertido


def test_sheets_undo_and_file(tmp_path):
    doc = Document()
    doc.undo_stack.push(AddEntities(doc, [Line(p2=(10, 0))]))
    sh = default_sheet(doc.bounds())
    doc.undo_stack.push(ReplaceSheets(doc, [sh], "Nova folha"))
    vp = sh.viewports()[0]
    from dataclasses import replace

    doc.undo_stack.push(ReplaceSheets(doc, [sh.with_element(replace(vp, scale=200))], "Escala"))
    assert doc.sheets[0].viewports()[0].scale == 200
    doc.undo_stack.undo()
    assert doc.sheets[0].viewports()[0].scale == vp.scale
    doc.set_project_info({"projeto": "Jardim da Praça", "cliente": "Prefeitura"})

    path = str(tmp_path / "f.leaf")
    save_document(doc, path)
    other = Document()
    load_document(other, path)
    assert [s.to_dict() for s in other.sheets] == [s.to_dict() for s in doc.sheets]
    assert other.project["projeto"] == "Jardim da Praça"
    got = other.sheets[0]
    assert isinstance(got.elements[0], ViewportElement) and isinstance(got.elements[0].center, tuple)
    assert any(isinstance(e, TitleBlockElement) for e in got.elements)
    assert any(isinstance(e, ScaleBarElement) for e in got.elements)


def test_with_and_without_element():
    sh = Sheet()
    tb = TitleBlockElement()
    sh2 = sh.with_element(tb)
    assert sh.elements == [] and sh2.elements == [tb]
    assert sh2.without_element(tb.id).elements == []
