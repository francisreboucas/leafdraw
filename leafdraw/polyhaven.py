"""Importa modelos do Poly Haven (polyhaven.com, CC0) para a biblioteca de modelos 3D.

    python -m leafdraw.polyhaven fern_02 shrub_01 rock_07
    python -m leafdraw.polyhaven --listar plants

Para cada modelo: baixa o glTF na resolução pedida (padrão 1k) só com a geometria
e as texturas de cor, junta a máscara de transparência das folhas — que o Poly Haven
distribui num arquivo à parte, porque o glTF dele usa JPEG — e grava um .glb
compactado (ver ``leafdraw.compactar``). Também mantém ``POLYHAVEN.md`` na pasta de
saída com a origem, os autores e a licença de cada modelo.

A saída padrão é a biblioteca distribuída com o LeafDraw
(``leafdraw/resources/models/polyhaven``); o catálogo embutido aponta para ela com
caminhos relativos como ``polyhaven/fern_02_01.glb``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

import numpy as np

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage

from leafdraw.compactar import compact_model
from leafdraw.core.catalog import MODELS_DIR
from leafdraw.core.gltf import Model, Primitive, load_model, load_variants

API = "https://api.polyhaven.com"
USER_AGENT = "LeafDraw (https://github.com/francisreboucas/leafdraw)"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _json(url: str):
    return json.loads(_get(url).decode("utf-8"))


def list_models(category: str = "") -> dict:
    return _json(f"{API}/assets?t=models" + (f"&c={category}" if category else ""))


def _safe_rel(path: str) -> PurePosixPath:
    """Caminho relativo vindo da API, sem subir de pasta nem ser absoluto."""
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not all(SAFE_NAME.match(x) for x in p.parts):
        raise ValueError(f"caminho inesperado na API: {path!r}")
    return p


def _alpha_key(files: dict, image_uri: str, asset_id: str, res: str) -> str | None:
    """Mapa de alfa que acompanha uma textura de cor: 'leaves_diff' -> 'leaves_alpha', 'diff' -> 'Alpha'."""
    stem = PurePosixPath(image_uri).stem  # ex.: jacaranda_tree_leaves_diff_1k
    stem = stem.removeprefix(asset_id + "_").removesuffix("_" + res)
    if "diff" not in stem.lower():
        return None
    want = re.sub("diff(use)?", "alpha", stem, flags=re.IGNORECASE).lower()
    return next((k for k in files if k.lower() == want), None)


def _with_alpha(color: bytes, alpha: bytes) -> bytes:
    """PNG RGBA: cor de uma imagem, alfa (tons de cinza) da outra."""
    c = QImage.fromData(color).convertToFormat(QImage.Format.Format_RGBA8888)
    a = QImage.fromData(alpha)
    if c.isNull() or a.isNull():
        raise ValueError("textura ou máscara ilegível")
    if a.size() != c.size():
        a = a.scaled(c.size())
    a = a.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = c.width(), c.height()
    # linhas com o stride de cada imagem (pode haver preenchimento no fim)
    rgba = np.frombuffer(c.bits(), np.uint8).reshape(h, c.bytesPerLine())
    mask = np.frombuffer(a.constBits(), np.uint8).reshape(h, a.bytesPerLine())
    rgba[:, 3:w * 4:4] = mask[:, :w]
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    c.save(buf, "PNG")
    return bytes(buf.data())


def download(asset_id: str, work: Path, res: str = "1k") -> tuple[Path, dict]:
    """Baixa o glTF de ``asset_id`` para ``work/asset_id`` e devolve (caminho do .gltf, info)."""
    if not SAFE_NAME.match(asset_id):
        raise ValueError(f"id inválido: {asset_id!r}")
    info = _json(f"{API}/info/{asset_id}")
    files = _json(f"{API}/files/{asset_id}")
    entry = files.get("gltf", {}).get(res, {}).get("gltf")
    if entry is None:
        raise ValueError(f"{asset_id}: sem glTF {res}")
    folder = work / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    doc = json.loads(_get(entry["url"]).decode("utf-8"))
    # só o necessário: buffers e texturas de cor (normal, rugosidade etc. não são usadas)
    color_images = set()
    for m in doc.get("materials", []):
        t = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if t is not None:
            color_images.add(doc["textures"][t["index"]]["source"])
    wanted = {b["uri"] for b in doc.get("buffers", []) if "uri" in b}
    wanted |= {doc["images"][i]["uri"] for i in color_images if "uri" in doc["images"][i]}
    include = entry.get("include", {})
    for uri in sorted(wanted):
        if uri not in include:
            raise ValueError(f"{asset_id}: {uri} não está na lista de arquivos")
        dst = folder / _safe_rel(uri)
        if not dst.exists() or dst.stat().st_size != include[uri]["size"]:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_get(include[uri]["url"]))
    # máscara das folhas: textura RGBA no lugar do JPEG
    for m in doc.get("materials", []):
        t = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if t is None or m.get("alphaMode", "OPAQUE") == "OPAQUE":
            continue
        img = doc["images"][doc["textures"][t["index"]]["source"]]
        key = _alpha_key(files, img.get("uri", ""), asset_id, res)
        if key is None:
            continue
        fmt = files[key].get(res, {}).get("png") or files[key].get(res, {}).get("jpg")
        if fmt is None:
            continue
        color_path = folder / _safe_rel(img["uri"])
        rgba_rel = str(PurePosixPath(img["uri"]).with_suffix("")) + "_rgba.png"
        (folder / _safe_rel(rgba_rel)).write_bytes(_with_alpha(color_path.read_bytes(), _get(fmt["url"])))
        img["uri"], img["mimeType"] = rgba_rel, "image/png"
    gltf = folder / f"{asset_id}.gltf"
    gltf.write_text(json.dumps(doc), encoding="utf-8")
    return gltf, info


def _centered(model: Model) -> Model:
    """Variação tirada de um conjunto: centro (x, y) na origem e base no chão."""
    allp = np.concatenate([p.positions for p in model.primitives]).astype(float)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    shift = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    return Model([Primitive((p.positions - shift).astype("f4"), p.normals, p.uvs, p.indices, p.material)
                  for p in model.primitives], model.size)


SCATTER_MAX = 0.20  # m: conjunto cuja maior peça é menor que isto é "espalhamento" (folhas, musgo): fica inteiro
FRAGMENT = 0.25  # variações com menos que isto do tamanho da maior são fragmentos soltos e saem


def _footprint(model: Model) -> float:
    allp = np.concatenate([p.positions for p in model.primitives])
    return float((allp.max(axis=0) - allp.min(axis=0))[:2].max())


def pick_variants(gltf: Path) -> list[tuple[str, Model]]:
    """Variações úteis como espécie: separa conjuntos lado a lado, mas mantém inteiros os
    de espalhamento (peças de centímetros) e descarta fragmentos soltos."""
    variants = load_variants(gltf)
    if len(variants) == 1:
        return variants
    sizes = [_footprint(m) for _n, m in variants]
    if max(sizes) < SCATTER_MAX:
        return [(gltf.stem, load_model(gltf, normalize=False))]
    kept = [m for m, s in zip((m for _n, m in variants), sizes) if s >= FRAGMENT * max(sizes)]
    if len(kept) == 1:
        return [(gltf.stem, _centered(kept[0]))]
    return [(f"{gltf.stem}_{k + 1:02d}", _centered(m)) for k, m in enumerate(kept)]


def _credits(out_dir: Path, rows: dict[str, dict]):
    path = out_dir / "POLYHAVEN.md"
    lines = ["# Modelos do Poly Haven", "",
             "Modelos de https://polyhaven.com, licença CC0 1.0 (domínio público): uso livre, inclusive",
             "comercial, sem obrigação de crédito. Mantemos a origem e os autores por cortesia.", "",
             "| Arquivo | Modelo | Autores | Origem |", "|---|---|---|---|"]
    old = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.startswith("| `"):
                old[ln.split("`")[1]] = ln
    for fname, (aid, info) in rows.items():
        authors = ", ".join(info.get("authors", {})) or "?"
        old[fname] = f"| `{fname}` | {info.get('name', aid)} | {authors} | https://polyhaven.com/a/{aid} |"
    path.write_text("\n".join(lines + [old[k] for k in sorted(old)]) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m leafdraw.polyhaven", description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*", help="ids dos modelos (como em polyhaven.com/a/<id>)")
    ap.add_argument("-o", "--saida", type=Path, default=MODELS_DIR / "polyhaven",
                    help="pasta de saída (padrão: a biblioteca distribuída, leafdraw/resources/models/polyhaven)")
    ap.add_argument("--res", default="1k", help="resolução das texturas no Poly Haven (1k, 2k…)")
    ap.add_argument("--max-textura", type=int, default=1024)
    ap.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "leafdraw-polyhaven",
                    help="pasta para os downloads (padrão: pasta temporária do sistema)")
    ap.add_argument("--listar", metavar="CATEGORIA", nargs="?", const="", help="lista os modelos (ex.: plants)")
    args = ap.parse_args(argv)
    if args.listar is not None:
        for aid, v in sorted(list_models(args.listar).items()):
            print(f"{aid:32} {v['name']:32} {v.get('polycount', 0):>10,} polígonos")
        return 0
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (QImage pede o app)
    work = args.cache
    done, failed = {}, 0
    for aid in args.ids:
        try:
            gltf, info = download(aid, work, args.res)
            for name, model in pick_variants(gltf):
                size, tris, _ = compact_model(model, args.saida / f"{name}.glb", args.max_textura)
                done[f"{name}.glb"] = (aid, info)
                print(f"{name}: {size / 2**20:.1f} MB, " + f"{tris:,} triângulos".replace(",", "."), flush=True)
        except Exception as exc:  # um modelo com problema não para os outros
            print(f"{aid}: ERRO {exc}", flush=True)
            failed += 1
    if done:
        _credits(args.saida, done)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
