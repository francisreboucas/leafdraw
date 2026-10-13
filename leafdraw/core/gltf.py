"""Leitura de modelos glTF 2.0 (.glb e .gltf) para a vegetação 3D — só numpy.

O modelo sai "achatado": cada primitiva já com a transformação dos nós
aplicada, convertida de Y para cima (glTF) para Z para cima (LeafDraw) e
normalizada para a unidade das instâncias de planta: base no chão (z = 0),
centro da copa na origem, raio horizontal 1 e altura 1. A espécie então
estica o modelo para a copa e a altura do catálogo, como faz com as formas
procedurais.

Fica de fora: animação, skin, morph targets, câmeras, luzes e as extensões de
compressão (Draco, meshopt). As texturas voltam como bytes (PNG/JPEG); quem
desenha decodifica.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pickle
import struct
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import numpy as np

GLB_MAGIC = 0x46546C67  # "glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
DTYPES = {k: np.dtype(t).newbyteorder("<") for k, t in
          {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}.items()}
NORM_DIV = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
SUPPORTED_EXT = {"KHR_materials_emissive_strength", "KHR_texture_transform", "KHR_materials_unlit",
                 "KHR_mesh_quantization"}
Y_UP_TO_Z_UP = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)


class GltfError(ValueError):
    pass


@dataclass
class Material:
    base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    alpha_mode: str = "OPAQUE"  # OPAQUE | MASK | BLEND
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    image: bytes | None = None  # textura de cor (PNG/JPEG)
    mime: str = ""
    name: str = ""


@dataclass
class Primitive:
    positions: np.ndarray  # (n, 3) f4
    normals: np.ndarray  # (n, 3) f4
    uvs: np.ndarray  # (n, 2) f4
    indices: np.ndarray  # (m,) u4, triângulos
    material: Material = field(default_factory=Material)

    def interleaved(self) -> np.ndarray:
        """Vértices (pos, normal, uv) para o buffer da GPU."""
        return np.concatenate([self.positions, self.normals, self.uvs], axis=1).astype("f4")


@dataclass
class Model:
    primitives: list[Primitive]
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)  # dimensões originais (m): largura, profundidade, altura

    @property
    def triangles(self) -> int:
        return sum(len(p.indices) // 3 for p in self.primitives)


# --- leitura ---------------------------------------------------------------------

def _read_file(path: Path) -> tuple[dict, bytes | None]:
    data = path.read_bytes()
    if data[:4] == b"glTF":
        return _split_glb(data)
    try:
        return json.loads(data.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GltfError(f"{path.name}: não é um arquivo glTF") from exc


def load_model(path: str | Path, normalize: bool = True) -> Model:
    path = Path(path)
    doc, binary = _read_file(path)
    return parse(doc, binary, path.parent, normalize)


MAX_VARIANT_NODES = 400  # acima disto (um nó por folha, como no SketchUp) não tenta separar


def load_variants(path: str | Path) -> list[tuple[str, Model]]:
    """Separa um arquivo com várias variações lado a lado (comum em bibliotecas como o
    Poly Haven) em modelos próprios: nós cujas caixas se sobrepõem em planta ficam
    juntos (o vaso com a planta); grupos afastados viram variações. Sem normalizar."""
    path = Path(path)
    doc, binary = _read_file(path)
    reader = _reader_for(doc, binary, path.parent)
    items = _collect(doc, reader)
    nodes = sorted({it[0] for it in items})
    if len(nodes) < 2 or len(nodes) > MAX_VARIANT_NODES:
        return [(path.stem, _build(doc, reader, items))]
    box = {}
    for node, _mat, piece, m in items:
        xy = piece[0] @ m[:2, :3].T + m[:2, 3]
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        if node in box:
            lo, hi = np.minimum(lo, box[node][0]), np.maximum(hi, box[node][1])
        box[node] = (lo, hi)
    allb = np.array([b for pair in box.values() for b in pair])
    margin = 0.01 * float((allb.max(axis=0) - allb.min(axis=0)).max())
    group = {n: n for n in nodes}

    def root(n):
        while group[n] != n:
            n = group[n]
        return n

    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            (alo, ahi), (blo, bhi) = box[a], box[b]
            if np.all(alo <= bhi + margin) and np.all(blo <= ahi + margin):
                group[root(b)] = root(a)
    clusters: dict[int, list] = {}
    for it in items:
        clusters.setdefault(root(it[0]), []).append(it)
    if len(clusters) == 1:
        return [(path.stem, _build(doc, reader, items))]

    def corner(r):
        los = [box[n][0] for n in nodes if root(n) == r]
        lo = np.min(los, axis=0)
        return (-round(float(lo[1]), 1), float(lo[0]))  # de trás para a frente, da esquerda para a direita

    order = sorted(clusters, key=corner)
    return [(f"{path.stem}_{k + 1:02d}", _build(doc, reader, clusters[r])) for k, r in enumerate(order)]


def parse(doc: dict, binary: bytes | None = None, base_dir: Path | None = None, normalize: bool = True) -> Model:
    reader = _reader_for(doc, binary, base_dir)
    model = _build(doc, reader, _collect(doc, reader))
    return _normalized(model) if normalize else model


def _reader_for(doc: dict, binary: bytes | None, base_dir: Path | None) -> "_Reader":
    version = str(doc.get("asset", {}).get("version", ""))
    if not version.startswith("2"):
        raise GltfError(f"versão glTF {version or '?'} não suportada (use glTF 2.0)")
    missing = set(doc.get("extensionsRequired", [])) - SUPPORTED_EXT
    if missing:
        raise GltfError("extensões não suportadas: " + ", ".join(sorted(missing))
                        + " (exporte o modelo sem compressão)")
    return _Reader(doc, binary, base_dir)


def _collect(doc: dict, reader: "_Reader") -> list[tuple]:
    """(nó, material, peça, matriz de mundo) de cada primitiva com triângulos."""
    items = []
    for node, mesh_idx, matrix in _mesh_nodes(doc):
        for p in doc["meshes"][mesh_idx].get("primitives", []):
            piece = reader.piece(p)
            if piece is not None:
                items.append((node, p.get("material", -1), piece, matrix))
    if not items:
        raise GltfError("o modelo não tem triângulos")
    return items


def _build(doc: dict, reader: "_Reader", items: list[tuple]) -> Model:
    # Uma primitiva por material: exportadores (SketchUp e conversores) chegam a gravar
    # um nó por folha, e cada primitiva seria uma chamada de desenho.
    groups: dict[int, list] = {}
    for _node, mat, piece, matrix in items:
        groups.setdefault(mat, []).append((piece, matrix))
    prims = []
    for m, group in groups.items():
        prim = _assemble(group, reader.material(None if m < 0 else m))
        t = _uv_transform(doc["materials"][m]) if m >= 0 else None
        if t is not None:  # KHR_texture_transform da textura de cor: aplicada direto nas UVs
            prim.uvs = (prim.uvs.astype(float) @ t[:2, :2].T + t[:2, 2]).astype("f4")
        prims.append(prim)
    return Model(prims)


def _uv_transform(material: dict) -> np.ndarray | None:
    """Matriz 3x3 do KHR_texture_transform da textura de cor (offset · rotação · escala)."""
    ext = material.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("extensions", {})
    tt = ext.get("KHR_texture_transform")
    if not tt:
        return None
    ox, oy = tt.get("offset", (0.0, 0.0))
    r = float(tt.get("rotation", 0.0))
    sx, sy = tt.get("scale", (1.0, 1.0))
    c, s = np.cos(r), np.sin(r)
    translate = np.array([[1, 0, ox], [0, 1, oy], [0, 0, 1]], float)
    rotate = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]], float)
    scale = np.diag([sx, sy, 1.0])
    return translate @ rotate @ scale


CHUNK = 262_144  # vértices por bloco ao aplicar as matrizes (limita a memória temporária)


def _assemble(items: list, material: Material) -> Primitive:
    """Junta peças (pos, normal | None, uv, índices locais) aplicando a matriz de cada uma."""
    pieces = [it[0] for it in items]
    counts = np.array([len(pc[0]) for pc in pieces])
    tri_counts = np.array([len(pc[3]) // 3 for pc in pieces])
    mats = np.stack([it[1] for it in items])
    lin, trans = mats[:, :3, :3], mats[:, :3, 3]
    inv = np.linalg.inv(lin)  # normais: (M^-1)^T
    owner = np.repeat(np.arange(len(pieces)), counts)
    pos = np.concatenate([pc[0] for pc in pieces]).astype(float)
    has_n = np.array([pc[1] is not None for pc in pieces])
    nrm = np.concatenate([pc[1] if pc[1] is not None else np.zeros((len(pc[0]), 3)) for pc in pieces]).astype(float)
    for a in range(0, len(pos), CHUNK):
        o = owner[a:a + CHUNK]
        pos[a:a + CHUNK] = np.einsum("vij,vj->vi", lin[o], pos[a:a + CHUNK]) + trans[o]
        nrm[a:a + CHUNK] = np.einsum("vj,vji->vi", nrm[a:a + CHUNK], inv[o])
    base = np.concatenate([[0], np.cumsum(counts)[:-1]])
    tri = np.concatenate([pc[3] for pc in pieces]).reshape(-1, 3) + np.repeat(base, tri_counts)[:, None]
    mirrored = np.repeat(np.linalg.det(lin) < 0, tri_counts)  # escala espelhada inverte a ordem dos vértices
    tri[mirrored] = tri[mirrored][:, ::-1]
    idx = tri.reshape(-1)
    if not has_n.all():
        computed = vertex_normals(pos, idx)
        missing = np.repeat(~has_n, counts)
        nrm[missing] = computed[missing]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    uv = np.concatenate([pc[2] for pc in pieces])
    return Primitive(pos.astype("f4"), nrm.astype("f4"), uv.astype("f4"), idx.astype("u4"), material)


def _split_glb(data: bytes) -> tuple[dict, bytes | None]:
    if len(data) < 20:
        raise GltfError("arquivo .glb truncado")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise GltfError("cabeçalho .glb inválido (use glTF 2.0)")
    doc, binary, off = None, None, 12
    while off + 8 <= min(length, len(data)):
        size, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + size]
        if kind == CHUNK_JSON:
            doc = json.loads(chunk.decode("utf-8"))
        elif kind == CHUNK_BIN and binary is None:
            binary = chunk
        off += 8 + size
    if doc is None:
        raise GltfError("o .glb não tem o bloco JSON")
    return doc, binary


def _node_matrix(node: dict) -> np.ndarray | None:
    """Matriz local do nó; None quando é a identidade (o caso comum, e evita contas)."""
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T  # glTF guarda por colunas
    if "translation" not in node and "rotation" not in node and "scale" not in node:
        return None
    t = np.eye(4)
    t[:3, 3] = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    r = np.eye(4)
    r[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    s = np.diag([*node.get("scale", (1, 1, 1)), 1.0])
    return t @ r @ s


def _mesh_nodes(doc: dict):
    """(nó, índice da malha, matriz de mundo já em Z para cima) para cada nó com malha da cena."""
    nodes = doc.get("nodes", [])
    if not nodes:  # só malhas soltas
        yield from ((-1 - i, i, Y_UP_TO_Z_UP) for i in range(len(doc.get("meshes", []))))
        return
    scenes = doc.get("scenes", [])
    if scenes:
        roots = scenes[doc.get("scene", 0)].get("nodes", [])
    else:  # sem cena: todos os nós que não são filhos de ninguém
        children = {c for n in nodes for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    stack = [(i, Y_UP_TO_Z_UP, 0) for i in roots]
    while stack:
        i, parent, depth = stack.pop()
        if depth > 64:
            raise GltfError("hierarquia de nós cíclica ou profunda demais")
        node = nodes[i]
        local = _node_matrix(node)
        m = parent if local is None else parent @ local
        if "mesh" in node:
            yield i, node["mesh"], m
        stack += [(c, m, depth + 1) for c in node.get("children", [])]


class _Reader:
    def __init__(self, doc: dict, binary: bytes | None, base_dir: Path | None):
        self.doc = doc
        self.binary = binary
        self.base_dir = base_dir
        self._buffers: dict[int, bytes] = {}
        self._materials: dict[int, Material] = {}

    def buffer(self, i: int) -> bytes:
        if i not in self._buffers:
            b = self.doc["buffers"][i]
            uri = b.get("uri")
            if uri is None:
                if self.binary is None:
                    raise GltfError("buffer sem dados")
                data = self.binary
            else:
                data = self._uri(uri)
            self._buffers[i] = data
        return self._buffers[i]

    def _uri(self, uri: str) -> bytes:
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        if self.base_dir is None:
            raise GltfError(f"arquivo externo {uri!r} sem pasta de origem")
        p = (self.base_dir / unquote(uri)).resolve()
        if not p.is_file():
            raise GltfError(f"arquivo externo não encontrado: {uri}")
        return p.read_bytes()

    def view(self, i: int) -> tuple[bytes, int, int, int]:
        v = self.doc["bufferViews"][i]
        return self.buffer(v["buffer"]), v.get("byteOffset", 0), v["byteLength"], v.get("byteStride", 0)

    def accessor(self, i: int) -> np.ndarray:
        a = self.doc["accessors"][i]
        if "sparse" in a:
            raise GltfError("accessors esparsos não são suportados")
        ncomp = COMPONENTS[a["type"]]
        ctype = a["componentType"]
        dtype = DTYPES[ctype]
        count = a["count"]
        if "bufferView" not in a:
            return np.zeros((count, ncomp), "f4")
        data, off, length, stride = self.view(a["bufferView"])
        off += a.get("byteOffset", 0)
        item = dtype.itemsize * ncomp
        stride = stride or item
        if count and off + stride * (count - 1) + item > len(data):
            raise GltfError("accessor fora dos limites do buffer")
        # visão direta sobre o buffer (sem cópia); quem junta as peças copia uma vez só
        raw = np.ndarray((count, ncomp), dtype=dtype, buffer=data, offset=off, strides=(stride, dtype.itemsize))
        if ctype == 5126:
            return raw
        if a.get("normalized") and ctype in NORM_DIV:
            return np.maximum(raw.astype("f4") / NORM_DIV[ctype], -1.0)
        return raw

    def material(self, i: int | None) -> Material:
        if i is None:
            return Material()
        if i not in self._materials:
            m = self.doc["materials"][i]
            pbr = m.get("pbrMetallicRoughness", {})
            image, mime = None, ""
            tex = pbr.get("baseColorTexture")
            if tex is not None:
                image, mime = self.image(tex["index"])
            self._materials[i] = Material(
                base_color=tuple(pbr.get("baseColorFactor", (1, 1, 1, 1))),
                alpha_mode=m.get("alphaMode", "OPAQUE"), alpha_cutoff=float(m.get("alphaCutoff", 0.5)),
                double_sided=bool(m.get("doubleSided", False)), image=image, mime=mime, name=m.get("name", ""))
        return self._materials[i]

    def image(self, tex_idx: int) -> tuple[bytes | None, str]:
        try:
            src = self.doc["textures"][tex_idx].get("source")
            if src is None:
                return None, ""
            img = self.doc["images"][src]
            if "bufferView" in img:
                data, off, length, _ = self.view(img["bufferView"])
                return bytes(data[off:off + length]), img.get("mimeType", "")
            uri = img.get("uri", "")
            mime = uri[5:uri.find(";")] if uri.startswith("data:") else ""
            return self._uri(uri), mime
        except (GltfError, OSError, KeyError, IndexError):
            return None, ""  # textura faltando: o material fica só com a cor

    def piece(self, p: dict) -> tuple | None:
        """(posições, normais | None, uvs, índices em lista de triângulos), no espaço da malha."""
        mode = p.get("mode", 4)
        attrs = p.get("attributes", {})
        if "POSITION" not in attrs or mode not in (4, 5, 6):  # só triângulos (lista, tira, leque)
            return None
        pos = self.accessor(attrs["POSITION"])[:, :3]
        n = len(pos)
        idx = self.accessor(p["indices"])[:, 0].astype(np.int64) if "indices" in p else np.arange(n)
        idx = _triangle_list(idx, mode)
        if len(idx) == 0:
            return None
        if idx.max() >= n:
            raise GltfError("índice de vértice fora dos limites")
        uv = self.accessor(attrs["TEXCOORD_0"])[:, :2] if "TEXCOORD_0" in attrs else np.zeros((n, 2))
        nrm = self.accessor(attrs["NORMAL"])[:, :3] if "NORMAL" in attrs else None
        return pos, nrm, uv, idx


def _triangle_list(idx: np.ndarray, mode: int) -> np.ndarray:
    if mode == 4:
        return idx[: len(idx) // 3 * 3]
    if len(idx) < 3:
        return idx[:0]
    k = np.arange(len(idx) - 2)
    if mode == 5:  # tira: alterna a ordem para manter a orientação
        a, b, c = idx[k], idx[k + 1], idx[k + 2]
        odd = k % 2 == 1
        a, b = np.where(odd, b, a), np.where(odd, a, b)
    else:  # leque
        a, b, c = np.full(len(k), idx[0]), idx[k + 1], idx[k + 2]
    return np.stack([a, b, c], axis=1).reshape(-1)


def vertex_normals(pos: np.ndarray, idx: np.ndarray) -> np.ndarray:
    tri = idx.reshape(-1, 3)
    fn = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
    out = np.zeros_like(pos, dtype=float)
    for j in range(3):
        np.add.at(out, tri[:, j], fn)
    out[np.linalg.norm(out, axis=1) < 1e-12] = (0, 0, 1)
    return out


def _normalized(model: Model) -> Model:
    """Base em z = 0, centro (x, y) da caixa na origem, raio horizontal 1 e altura 1."""
    allp = np.concatenate([p.positions for p in model.primitives]).astype(float)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    size = hi - lo
    center = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    radius = max(size[0], size[1]) / 2
    if radius < 1e-9 or size[2] < 1e-9:
        raise GltfError("o modelo é plano ou vazio")
    k = np.array([1 / radius, 1 / radius, 1 / size[2]])
    prims = []
    for p in model.primitives:
        nrm = p.normals / k  # escala não uniforme: normais pela inversa
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        prims.append(Primitive(((p.positions - center) * k).astype("f4"), nrm.astype("f4"), p.uvs, p.indices,
                               p.material))
    return Model(prims, (float(size[0]), float(size[1]), float(size[2])))


# --- cache (a cena 3D pede o mesmo modelo para cada planta da espécie) --------------

_CACHE: dict[str, tuple[tuple, Model | None, str]] = {}
DISK_CACHE_DIR: Path | None = None  # o app aponta para a pasta de dados do usuário
DISK_CACHE_VERSION = 1  # aumente quando mudar o que ``load_model`` produz


def cached_model(path: str | Path) -> tuple[Model | None, str]:
    """(modelo, erro). Relê o arquivo quando ele muda no disco; erros também ficam no cache.

    Modelos já processados ficam também em ``DISK_CACHE_DIR``: modelos exportados do
    SketchUp chegam a ter centenas de milhares de nós e levam segundos para montar.
    """
    p = Path(path)
    key = str(p.resolve()) if p.exists() else str(p)
    try:
        st = p.stat()
    except OSError:
        return None, f"arquivo não encontrado: {p}"
    stamp = (st.st_size, st.st_mtime_ns)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1], hit[2]
    disk = _disk_path(key, stamp)
    model, err = _disk_read(disk), ""
    if model is None:
        try:
            model = load_model(p)
        except (GltfError, OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            model, err = None, f"{p.name}: {exc}"
        else:
            _disk_write(disk, model)
    _CACHE[key] = (stamp, model, err)
    return model, err


def _disk_path(key: str, stamp: tuple) -> Path | None:
    if DISK_CACHE_DIR is None:
        return None
    h = hashlib.sha1(f"{DISK_CACHE_VERSION}|{key}|{stamp}".encode()).hexdigest()[:24]
    return Path(DISK_CACHE_DIR) / f"{h}.model"


def _disk_read(path: Path | None) -> Model | None:
    if path is None or not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            model = pickle.load(f)  # arquivo gravado por nós na pasta do usuário
        return model if isinstance(model, Model) else None
    except Exception:  # cache corrompido ou de outra versão: refaz
        return None


def _disk_write(path: Path | None, model: Model):
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as f:
            pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
    except OSError:
        pass  # sem cache em disco: só fica mais lento


# --- compactação ---------------------------------------------------------------------

def weld(prim: Primitive) -> Primitive:
    """Funde vértices idênticos (posição, normal e UV) — sem perda."""
    rows = np.ascontiguousarray(prim.interleaved())
    key = rows.view(np.dtype((np.void, rows.dtype.itemsize * rows.shape[1]))).ravel()
    _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
    order = np.argsort(first)  # mantém a ordem original dos vértices (melhor para o cache da GPU)
    remap = np.empty_like(order)
    remap[order] = np.arange(len(order))
    keep = first[order]
    return Primitive(prim.positions[keep], prim.normals[keep], prim.uvs[keep],
                     remap[inverse.ravel()][prim.indices].astype("u4"), prim.material)


def _sniff_mime(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"


def compact_parts(model: Model, image_hook=None) -> list[dict]:
    """Partes para ``write_glb`` a partir de um modelo lido sem normalizar (em metros, Z para cima).

    ``image_hook(bytes, mime, material) -> (bytes, mime, alpha_mode)`` permite reduzir a
    textura e corrigir o modo de alfa (precisa decodificar a imagem, fica com quem chama).
    """
    parts = []
    for prim in model.primitives:
        w = weld(prim)
        m = w.material
        image, mime, alpha_mode = m.image, m.mime, m.alpha_mode
        if image is not None and image_hook is not None:
            image, mime, alpha_mode = image_hook(image, mime, m)
        # Z para cima -> Y para cima (glTF): (x, y, z) -> (x, z, -y)
        to_y = lambda a: np.stack([a[:, 0], a[:, 2], -a[:, 1]], axis=1)  # noqa: E731
        parts.append({"name": m.name, "positions": to_y(w.positions), "normals": to_y(w.normals),
                      "uvs": w.uvs if image is not None else None, "indices": w.indices,
                      "color": m.base_color, "image": image, "mime": mime, "alpha_mode": alpha_mode,
                      "alpha_cutoff": m.alpha_cutoff, "double_sided": m.double_sided})
    return parts


# --- escrita mínima (testes, modelos de exemplo e compactação) ------------------------

def write_glb(path: str | Path, parts: list[dict]):
    """Grava um .glb com uma malha por parte, já em Y para cima.

    Cada parte: ``positions`` (n, 3), ``indices`` (m,), opcionais ``normals``,
    ``uvs``, ``color`` (RGBA), ``image`` (bytes PNG ou JPEG), ``mime``,
    ``alpha_mode``, ``alpha_cutoff``, ``double_sided`` e ``name``. Índices vão em
    16 bits quando cabem; imagens iguais são gravadas uma vez só.
    """
    blob = bytearray()
    views, accessors, meshes, materials, textures, images, nodes = [], [], [], [], [], [], []
    texture_of: dict[bytes, int] = {}

    def add_view(data: bytes, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        v = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            v["target"] = target
        blob.extend(data)
        views.append(v)
        return len(views) - 1

    def add_accessor(arr: np.ndarray, kind: str, ctype: int, target: int, minmax: bool = False) -> int:
        a = {"bufferView": add_view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            a["min"] = arr.min(axis=0).tolist()
            a["max"] = arr.max(axis=0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    for part in parts:
        pos = np.asarray(part["positions"], "f4")
        attrs = {"POSITION": add_accessor(pos, "VEC3", 5126, 34962, True)}
        if part.get("normals") is not None:
            attrs["NORMAL"] = add_accessor(np.asarray(part["normals"], "f4"), "VEC3", 5126, 34962)
        if part.get("uvs") is not None:
            attrs["TEXCOORD_0"] = add_accessor(np.asarray(part["uvs"], "f4"), "VEC2", 5126, 34962)
        ind = np.asarray(part["indices"])
        small = len(ind) == 0 or int(ind.max()) < 65535
        idx = add_accessor(ind.astype("u2" if small else "u4"), "SCALAR", 5123 if small else 5125, 34963)
        pbr = {"baseColorFactor": list(part.get("color", (1, 1, 1, 1))), "metallicFactor": 0.0,
               "roughnessFactor": 0.9}
        if part.get("image") is not None:
            img = bytes(part["image"])
            if img not in texture_of:
                images.append({"bufferView": add_view(img), "mimeType": part.get("mime") or _sniff_mime(img)})
                textures.append({"source": len(images) - 1})
                texture_of[img] = len(textures) - 1
            pbr["baseColorTexture"] = {"index": texture_of[img]}
        mat = {"name": part.get("name", f"mat{len(materials)}"), "pbrMetallicRoughness": pbr,
               "doubleSided": bool(part.get("double_sided", False))}
        if part.get("alpha_mode", "OPAQUE") != "OPAQUE":
            mat["alphaMode"] = part["alpha_mode"]
            if part["alpha_mode"] == "MASK":
                mat["alphaCutoff"] = float(part.get("alpha_cutoff", 0.5))
        materials.append(mat)
        meshes.append({"name": part.get("name", ""),
                       "primitives": [{"attributes": attrs, "indices": idx, "material": len(materials) - 1}]})
        nodes.append({"mesh": len(meshes) - 1, "name": part.get("name", "")})
    while len(blob) % 4:
        blob.append(0)
    doc = {"asset": {"version": "2.0", "generator": "LeafDraw"}, "scene": 0,
           "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
           "materials": materials, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(blob)}]}
    if images:
        doc["images"] = images
        doc["textures"] = textures
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack("<II", len(js), CHUNK_JSON) + js + struct.pack("<II", len(blob), CHUNK_BIN) + bytes(blob)
    Path(path).write_bytes(out)
