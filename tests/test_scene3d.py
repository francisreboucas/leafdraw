import math

import numpy as np
import pytest

from leafdraw.core.catalog import default_catalog
from leafdraw.core.commands import AddEntities
from leafdraw.core.document import Document
from leafdraw.core.entities import Contour, Hatch, Line, Plant
from leafdraw.core.terrain import Terrain
from leafdraw.ui.gizmo3d import gizmo_triangles, hit_test
from leafdraw.ui.plants3d import plant_instances
from leafdraw.ui.scene3d import ZMap, build_scene


def test_plant_models_are_deterministic_and_typed():
    a = plant_instances("arvore", 0, 0, 0, 6, 10, (1, 1, 0), "abc")
    b = plant_instances("arvore", 0, 0, 0, 6, 10, (1, 1, 0), "abc")
    assert a == b  # mesma planta, mesma forma
    assert len(a["cylinder"]) == 1 and len(a["bush"]) == 5
    palm = plant_instances("palmeira", 0, 0, 0, 5, 12, (0, 1, 0), "p")
    assert len(palm["palm"]) == 1 and palm["cylinder"][0][5] > 9  # tronco alto
    sel = plant_instances("arbusto", 0, 0, 0, 1, 1, (1, 0, 0), "s", selected=True)["bush"][0]
    assert sel[8] > 0.5  # destaque azulado


def test_scene_drapes_on_terrain():
    doc = Document()
    slope = [Contour(vertices=[(x, -10), (x, 30)], elevation=x / 10) for x in (0, 10, 20)]
    tree = Plant(position=(15, 5), species="handroanthus-albus", canopy=6, height=10)
    line = Line(p1=(0, 0), p2=(20, 0))
    grass = Hatch(loops=[[(2, 2), (18, 2), (18, 8), (2, 8)]], pattern="grass")
    doc.undo_stack.push(AddEntities(doc, [*slope, tree, line, grass]))
    zm = ZMap(Terrain.from_entities(slope), 2.0)
    sa = build_scene(doc.entities.values(), doc, default_catalog(), zm, {tree.id})
    trunk = sa.instances["cylinder"][0]
    assert trunk[2] == pytest.approx(3.0)  # 1,5 m × exagero 2
    zs = [row[2] for row in sa.lines]
    assert max(zs) == pytest.approx(4.0 + 0.04, abs=1e-6)  # contorno em x=20 (cota 2 → 4)
    surf = np.array(sa.surfaces)
    assert len(surf) and np.allclose(surf[:, 2], surf[:, 0] / 10 * 2 + 0.015)
    assert sa.pick[tree.id].kind == "point" and sa.pick[line.id].kind == "lines"
    assert sa.shadows  # sombras das plantas


def test_gizmo_hit_test_top_view():
    # projeção ortogonal de topo: 10 px por metro, origem no centro
    def proj(p):
        p = np.asarray(p, float)
        return np.c_[p[:, 0] * 10 + 500, -p[:, 1] * 10 + 500]

    c, size = (0.0, 0.0, 0.0), 10.0
    assert hit_test(proj, c, size, (500 + 60, 500)) == "x"
    assert hit_test(proj, c, size, (500, 500 - 60)) == "y"
    assert hit_test(proj, c, size, (500 + 33, 500 - 33)) == "xy"
    r = size * 0.85 * 10
    assert hit_test(proj, c, size, (500 - r * math.cos(0.7), 500 + r * math.sin(0.7))) == "rot"
    assert hit_test(proj, c, size, (900, 900)) is None
    tris = gizmo_triangles(c, size, "x")
    assert tris.shape[1] == 7 and len(tris) % 3 == 0
