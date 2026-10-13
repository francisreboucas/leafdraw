import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from leafdraw.core.catalog import default_catalog  # noqa: E402
from leafdraw.core.gltf import load_model  # noqa: E402
from leafdraw.modelgen import SPECIES, generate  # noqa: E402

# uma espécie de cada forma de crescimento
SAMPLE = ["handroanthus-albus", "plinia-cauliflora", "syagrus-romanzoffiana", "livistona-chinensis",
          "dypsis-lutescens", "ravenala-madagascariensis", "beaucarnea-recurvata", "ixora-coccinea",
          "furcraea-foetida", "agapanthus-africanus", "strelitzia-reginae", "monstera-deliciosa",
          "orchidaceae-arbustiva", "orchidaceae-branca", "evolvulus-glomeratus"]


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.mark.parametrize("sid", SAMPLE)
def test_generated_model_matches_catalog_size(app, tmp_path, sid):
    sp = default_catalog().get(sid)
    path = generate(sid, sp.altura, sp.copa, tmp_path)
    model = load_model(path)
    w, d, h = model.size
    assert max(w, d) == pytest.approx(sp.copa, rel=1e-3)  # sai no porte do catálogo: a vista 3D não estica
    assert h == pytest.approx(sp.altura, rel=1e-3)
    leaves = [p for p in model.primitives if p.material.image is not None]
    assert leaves and all(p.material.alpha_mode == "MASK" and p.material.double_sided for p in leaves)
    allp = np.concatenate([p.positions for p in model.primitives])
    assert allp[:, 2].min() == pytest.approx(0, abs=1e-6)


def test_generation_is_deterministic(app, tmp_path):
    a = generate("ixora-coccinea", 1.5, 1.2, tmp_path / "a").read_bytes()
    b = generate("ixora-coccinea", 1.5, 1.2, tmp_path / "b").read_bytes()
    assert a == b


def test_every_builtin_species_has_a_generator_or_model():
    cat = default_catalog()
    for sid, sp in cat._builtin.items():
        assert sid in SPECIES or sp.modelo_3d.startswith("polyhaven/"), sid
