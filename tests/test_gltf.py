import base64
import json
import struct
from dataclasses import replace

import numpy as np
import pytest

from leafdraw.core.catalog import default_catalog
from leafdraw.core.document import Document
from leafdraw.core.entities import Plant
from leafdraw.core.gltf import GltfError, cached_model, load_model, parse, write_glb
from leafdraw.ui.plants3d import MODEL_PREFIX
from leafdraw.ui.scene3d import ZMap, build_scene

QUAD = {"positions": [(-1, 0, 0), (1, 0, 0), (1, 2, 0), (-1, 2, 0)], "indices": [0, 1, 2, 0, 2, 3],
        "uvs": [(0, 1), (1, 1), (1, 0), (0, 0)]}


def _doc(positions, indices=None, mode=None, nodes=None, extra=None):
    """glTF em JSON com o buffer embutido (data URI)."""
    pos = np.asarray(positions, "f4")
    blob = pos.tobytes()
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3"}]
    prim = {"attributes": {"POSITION": 0}}
    if indices is not None:
        ib = np.asarray(indices, "u2").tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(ib)})
        accessors.append({"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"})
        blob += ib
        prim["indices"] = 1
    if mode is not None:
        prim["mode"] = mode
    doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [prim]}],
           "nodes": nodes or [{"mesh": 0}], "scenes": [{"nodes": [0]}],
           "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(blob),
                        "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode()}]}
    doc.update(extra or {})
    return doc


def test_glb_roundtrip_converts_to_z_up_and_normalizes(tmp_path):
    path = tmp_path / "a.glb"
    write_glb(path, [dict(QUAD, alpha_mode="MASK", double_sided=True, color=(0.5, 1, 0.5, 1))])
    raw = load_model(path, normalize=False)
    p = raw.primitives[0]
    assert np.allclose(p.positions[2], (1, 0, 2))  # Y (glTF) vira Z
    assert np.allclose(p.normals, (0, -1, 0), atol=1e-6)  # +Z do glTF aponta para -Y
    m = load_model(path).primitives[0]
    assert m.positions[:, 2].min() == pytest.approx(0) and m.positions[:, 2].max() == pytest.approx(1)
    assert np.abs(m.positions[:, :2]).max() == pytest.approx(1)
    assert m.material.alpha_mode == "MASK" and m.material.double_sided
    assert m.material.base_color == (0.5, 1, 0.5, 1)
    assert m.interleaved().shape == (4, 8)
    assert load_model(path).size == pytest.approx((2, 0, 2))


def test_node_transforms_strip_and_missing_normals():
    # nó pai transladado e filho girado 90° em Y (quatérnio) — tudo vira matriz de mundo
    q = (0, np.sin(np.pi / 4), 0, np.cos(np.pi / 4))
    nodes = [{"translation": (10, 0, 0), "children": [1]}, {"mesh": 0, "rotation": q}]
    tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    m = parse(_doc(tri, nodes=nodes), normalize=False)
    pts = m.primitives[0].positions
    assert np.allclose(pts[1], (10, 1, 0), atol=1e-6)  # (1,0,0) girado → (0,0,-1) glTF → (0,1,0) Z para cima
    assert np.allclose(np.linalg.norm(m.primitives[0].normals, axis=1), 1)
    strip = parse(_doc([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], indices=[0, 1, 2, 3], mode=5),
                  normalize=False)
    assert len(strip.primitives[0].indices) == 6
    n = strip.primitives[0].normals
    assert np.allclose(n, n[0])  # a tira alterna a ordem: as duas faces ficam para o mesmo lado


def test_matrix_node_and_mirrored_scale_keep_winding():
    mirror = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    plain = parse(_doc(tri), normalize=False).primitives[0]
    flipped = parse(_doc(tri, nodes=[{"mesh": 0, "matrix": mirror}]), normalize=False).primitives[0]
    assert list(flipped.indices) == [2, 1, 0]
    assert np.allclose(plain.normals[0], flipped.normals[0])


def test_rejects_compressed_and_bad_files(tmp_path):
    with pytest.raises(GltfError, match="draco"):
        parse(_doc([(0, 0, 0), (1, 0, 0), (0, 1, 0)], extra={"extensionsRequired": ["KHR_draco_mesh_compression"]}))
    with pytest.raises(GltfError, match="2.0"):
        parse({"asset": {"version": "1.0"}})
    bad = tmp_path / "x.glb"
    bad.write_bytes(b"glTF" + struct.pack("<II", 1, 12))
    model, err = cached_model(bad)
    assert model is None and "x.glb" in err
    assert cached_model(tmp_path / "nao_existe.glb")[0] is None


def test_gltf_json_with_external_bin(tmp_path):
    doc = _doc([(0, 0, 0), (2, 0, 0), (0, 3, 0)])
    blob = base64.b64decode(doc["buffers"][0]["uri"].split(",", 1)[1])
    (tmp_path / "geo.bin").write_bytes(blob)
    doc["buffers"][0]["uri"] = "geo.bin"
    (tmp_path / "m.gltf").write_text(json.dumps(doc))
    assert load_model(tmp_path / "m.gltf").size == pytest.approx((2, 0, 3))


def test_species_with_model_uses_glb_instances(tmp_path):
    path = tmp_path / "arvore.glb"
    write_glb(path, [QUAD])
    cat = default_catalog()
    sp = cat.get("handroanthus-albus")
    cat._user[sp.id] = replace(sp, modelo_3d=str(path))
    doc = Document()
    plant = Plant(position=(3, 4), species=sp.id, canopy=6, height=10)
    doc.entities[plant.id] = plant
    sa = build_scene([plant], doc, cat, ZMap(None))
    key = MODEL_PREFIX + str(path)
    assert len(sa.instances[key]) == 1 and not sa.instances["bush"]
    x, y, z, sx, sy, sz = sa.instances[key][0][:6]
    assert (x, y, z) == (3, 4, 0) and sx == pytest.approx(3, rel=0.1) and sz == pytest.approx(10, rel=0.1)
    assert str(path) in sa.models and not sa.model_errors
    # arquivo sumiu: volta à forma procedural e avisa
    cat._user[sp.id] = replace(sp, modelo_3d=str(tmp_path / "sumiu.glb"))
    sa = build_scene([plant], doc, cat, ZMap(None))
    assert sa.instances["bush"] and sa.model_errors


def test_textured_model_renders_with_alpha_cutout(tmp_path):
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as exc:  # máquina sem OpenGL (CI)
        pytest.skip(f"sem contexto OpenGL: {exc}")
    from leafdraw.ui.viewport3d import TEX_FS, TEX_VS

    # textura 2x1: metade esquerda opaca verde, direita transparente
    img = np.array([[[40, 200, 40, 255], [0, 0, 0, 0]]], "u1")
    prog = ctx.program(vertex_shader=TEX_VS, fragment_shader=TEX_FS)
    tex = ctx.texture((2, 1), 4, img.tobytes())
    tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    # quadrado cobrindo a tela (em clip space com mvp = identidade), u de 0 a 1 da esquerda para a direita
    verts = np.array([(-1, -1, 0, 0, 0, 1, 0, 0), (1, -1, 0, 0, 0, 1, 1, 0), (1, 1, 0, 0, 0, 1, 1, 1),
                      (-1, 1, 0, 0, 0, 1, 0, 1)], "f4")
    inst = np.array([(0, 0, 0, 1, 1, 1, 1, 1, 1, 0)], "f4")
    vao = ctx.vertex_array(prog, [(ctx.buffer(verts.tobytes()), "3f 3f 2f", "in_pos", "in_norm", "in_uv"),
                                  (ctx.buffer(inst.tobytes()), "3f 3f 3f 1f/i", "i_off", "i_scale", "i_color",
                                   "i_rot")],
                           index_buffer=ctx.buffer(np.array([0, 1, 2, 0, 2, 3], "u4").tobytes()))
    prog["mvp"].write(np.eye(4, dtype="f4").tobytes())
    prog["base_color"].value = (1, 1, 1, 1)
    prog["alpha_cutoff"].value = 0.5
    prog["two_sided"].value = True
    prog["blend"].value = False
    prog["has_tex"].value = True
    tex.use(0)
    prog["tex"].value = 0
    fbo = ctx.simple_framebuffer((8, 8))
    fbo.use()
    fbo.clear(1, 0, 0, 1)
    vao.render(moderngl.TRIANGLES, instances=1)
    px = np.frombuffer(fbo.read(components=3), "u1").reshape(8, 8, 3)
    left, right = px[4, 1], px[4, 6]
    assert left[1] > left[0] and left[1] > 100  # folha verde iluminada
    assert tuple(right) == (255, 0, 0)  # recortado: aparece o fundo
    ctx.release()


def test_many_nodes_merge_into_one_primitive_per_material():
    # como no SketchUp: um nó por folha, todos com o mesmo material
    nodes = [{"children": list(range(1, 501))}] + [{"mesh": 0, "translation": (i, 0, 0)} for i in range(500)]
    doc = _doc([(0, 0, 0), (1, 0, 0), (0, 1, 0)], nodes=nodes,
               extra={"materials": [{"doubleSided": True}]})
    doc["meshes"][0]["primitives"][0]["material"] = 0
    m = parse(doc, normalize=False)
    assert len(m.primitives) == 1 and m.triangles == 500
    assert m.primitives[0].indices.max() == 1499
    assert m.primitives[0].positions[:, 0].max() == pytest.approx(500)


def test_transparent_texture_turns_into_cutout():
    from leafdraw.core.gltf import Material
    from leafdraw.ui.viewport3d import effective_alpha_mode

    assert effective_alpha_mode(Material(alpha_mode="OPAQUE"), cutout=True) == "MASK"
    assert effective_alpha_mode(Material(alpha_mode="BLEND"), cutout=True) == "MASK"
    assert effective_alpha_mode(Material(alpha_mode="OPAQUE"), cutout=False) == "OPAQUE"
    assert effective_alpha_mode(Material(alpha_mode="BLEND"), cutout=False) == "BLEND"  # vidro, sem textura


def test_disk_cache_roundtrip(tmp_path, monkeypatch):
    from leafdraw.core import gltf

    path = tmp_path / "a.glb"
    write_glb(path, [QUAD])
    monkeypatch.setattr(gltf, "DISK_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gltf, "_CACHE", {})
    first, _ = cached_model(path)
    assert list((tmp_path / "cache").glob("*.model"))
    gltf._CACHE.clear()
    monkeypatch.setattr(gltf, "load_model", lambda *_a, **_k: pytest.fail("deveria vir do cache em disco"))
    again, err = cached_model(path)
    assert not err and np.array_equal(again.primitives[0].positions, first.primitives[0].positions)


def test_compact_roundtrip_keeps_geometry(tmp_path):
    from leafdraw.core.gltf import compact_parts, weld

    nodes = [{"children": list(range(1, 51))}] + [{"mesh": 0, "translation": (2 * i, 0, 0)} for i in range(50)]
    # dois triângulos repetindo vértices (sem índices): 6 vértices, 4 distintos
    quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 0), (1, 1, 0), (0, 1, 0)]
    doc = _doc(quad, nodes=nodes, extra={"materials": [{"doubleSided": True}]})
    doc["meshes"][0]["primitives"][0]["material"] = 0
    src = parse(doc, normalize=False)
    assert len(weld(src.primitives[0]).positions) == 4 * 50
    out = tmp_path / "c.glb"
    write_glb(out, compact_parts(src))
    back = load_model(out, normalize=False)
    assert back.triangles == src.triangles
    a = np.concatenate([p.positions for p in src.primitives])
    b = np.concatenate([p.positions for p in back.primitives])
    assert np.allclose(a.min(0), b.min(0)) and np.allclose(a.max(0), b.max(0))
    assert back.primitives[0].material.double_sided
    assert len(load_model(out).primitives[0].indices) == len(src.primitives[0].indices)


def test_compact_cli(tmp_path):
    pytest.importorskip("PySide6")
    from leafdraw.compactar import main

    write_glb(tmp_path / "a.glb", [QUAD])
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 0
    assert load_model(tmp_path / "out" / "a.glb").triangles == 2


def test_texture_transform_is_baked_into_uvs():
    doc = _doc([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    uv = np.array([(0, 0), (1, 0), (0, 1)], "f4").tobytes()
    blob = base64.b64decode(doc["buffers"][0]["uri"].split(",", 1)[1]) + uv
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob) - len(uv), "byteLength": len(uv)})
    doc["accessors"].append({"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"})
    doc["buffers"][0] = {"byteLength": len(blob),
                         "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode()}
    prim = doc["meshes"][0]["primitives"][0]
    prim["attributes"]["TEXCOORD_0"] = 1
    prim["material"] = 0
    doc["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {
        "index": 0, "extensions": {"KHR_texture_transform": {"offset": [0.5, 0.25], "scale": [2, 3]}}}}}]
    doc["extensionsRequired"] = ["KHR_texture_transform"]
    uvs = parse(doc, normalize=False).primitives[0].uvs
    assert np.allclose(uvs, [(0.5, 0.25), (2.5, 0.25), (0.5, 3.25)])
