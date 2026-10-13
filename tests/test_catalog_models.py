from dataclasses import replace

from leafdraw.core.catalog import MODELS_DIR, PlantCatalog, default_catalog
from leafdraw.core.document import Document
from leafdraw.core.entities import Plant
from leafdraw.core.gltf import load_model
from leafdraw.ui.scene3d import ZMap, build_scene

MAX_STRETCH = 2.15  # quanto o modelo pode ser esticado na vertical em relação à largura


def test_builtin_models_are_distributed_and_fit_species():
    cat = default_catalog()
    with_model = [sp for sp in (cat._builtin[i] for i in cat._builtin) if sp.modelo_3d]
    assert with_model
    for sp in with_model:
        path = MODELS_DIR / sp.modelo_3d  # o catálogo embutido só aponta para a biblioteca distribuída
        assert path.is_file(), f"{sp.id}: {sp.modelo_3d} não está em {MODELS_DIR}"
        w, d, h = load_model(path).size
        k = (sp.altura / sp.copa) / (h / max(w, d))
        assert 1 / MAX_STRETCH < k < MAX_STRETCH, f"{sp.id}: modelo esticado {k:.2f}x"


def test_builtin_species_without_installed_model_falls_back_quietly(tmp_path):
    base = default_catalog().get("handroanthus-albus")
    sp = replace(base, modelo_3d="nao_instalado.glb")
    cat = PlantCatalog([sp])  # embutida
    doc = Document()
    plant = Plant(position=(0, 0), species=sp.id, canopy=6, height=10)
    sa = build_scene([plant], doc, cat, ZMap(None))
    assert sa.instances["bush"] and not sa.model_errors
    user = PlantCatalog([], [sp])  # do usuário: avisa
    assert build_scene([plant], doc, user, ZMap(None)).model_errors
