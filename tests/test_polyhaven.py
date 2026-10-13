import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

from leafdraw.core.gltf import load_model, write_glb  # noqa: E402
from leafdraw.polyhaven import _alpha_key, _safe_rel, _with_alpha, pick_variants  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def _png(img: QImage, fmt="PNG") -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return bytes(buf.data())


def test_alpha_key_matches_poly_haven_names():
    files = {"leaves_diff": {}, "leaves_alpha": {}, "Diffuse": {}, "Alpha": {}, "trunk_diff": {}}
    assert _alpha_key(files, "textures/jacaranda_tree_leaves_diff_1k.jpg", "jacaranda_tree", "1k") == "leaves_alpha"
    assert _alpha_key(files, "textures/shrub_01_diff_1k.jpg", "shrub_01", "1k") == "Alpha"
    assert _alpha_key({"trunk_diff": {}}, "textures/x_trunk_diff_1k.jpg", "x", "1k") is None
    assert _alpha_key(files, "textures/x_nor_gl_1k.jpg", "x", "1k") is None


def test_safe_rel_rejects_escaping_paths():
    assert str(_safe_rel("textures/a_1k.jpg")) == "textures/a_1k.jpg"
    for bad in ("../x.bin", "/etc/x", "a/../../b", "c:/x.bin", "tex/a b.jpg"):
        with pytest.raises(ValueError):
            _safe_rel(bad)


def test_with_alpha_merges_mask(app):
    color = QImage(5, 3, QImage.Format.Format_RGB888)  # largura ímpar: stride com preenchimento
    color.fill(QColor(10, 200, 30))
    mask = QImage(5, 3, QImage.Format.Format_Grayscale8)
    mask.fill(0)
    for y in range(3):
        mask.setPixelColor(4, y, QColor(255, 255, 255))
    out = QImage.fromData(_with_alpha(_png(color, "JPG"), _png(mask)))
    assert out.hasAlphaChannel()
    assert out.pixelColor(0, 1).alpha() == 0 and out.pixelColor(4, 1).alpha() == 255
    assert out.pixelColor(4, 1).green() > 150


def _box(x, size, h=0.5):
    s = size / 2
    pos = [(x - s, 0, -s), (x + s, 0, -s), (x + s, h, s), (x - s, h, s)]
    return {"positions": pos, "indices": [0, 1, 2, 0, 2, 3]}


def test_pick_variants_splits_sets_and_drops_fragments(tmp_path):
    path = tmp_path / "set.glb"
    write_glb(path, [_box(0, 1.0), _box(3, 0.9), _box(6, 0.05)])  # 2 plantas e um fragmento
    names = [n for n, _m in pick_variants(path)]
    assert names == ["set_01", "set_02"]
    for _n, m in pick_variants(path):
        allp = np.concatenate([p.positions for p in m.primitives])
        assert abs(allp[:, 0].min() + allp[:, 0].max()) < 1e-5 and abs(allp[:, 2].min()) < 1e-5  # centrada

    scatter = tmp_path / "moss.glb"
    write_glb(scatter, [_box(0, 0.03), _box(1, 0.02), _box(2, 0.04)])  # espalhamento: fica inteiro
    (name, model), = pick_variants(scatter)
    assert name == "moss" and model.triangles == load_model(scatter).triangles
