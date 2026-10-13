"""Compacta modelos 3D (.glb/.gltf) de vegetação para uso no LeafDraw.

    python -m leafdraw.compactar modelos/ -o modelos/compactados
    python -m leafdraw.compactar arvore.glb --max-textura 1024

O que faz (os originais não são alterados):

* junta as peças por material — exportadores como o SketchUp gravam um nó por
  folha, e a descrição desses nós chega a ser mais de 80% do arquivo;
* funde vértices repetidos;
* textura com partes transparentes passa a ser recorte por alfa (``MASK``), o que
  o exportador costuma esquecer;
* reduz texturas maiores que ``--max-textura`` pixels (padrão 2048; 0 desliga).

Sem ``--leve`` a geometria não é simplificada: forma e triângulos ficam iguais.
Com ``--leve N`` grava uma versão leve de até ~N triângulos (ver ``core.meshlod``):

    python -m leafdraw.compactar modelos/ -o modelos/leves --leve 20000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage

from leafdraw.core.gltf import GltfError, compact_parts, load_model, write_glb
from leafdraw.core.meshlod import simplify_model


def image_hook(max_px: int):
    def hook(data: bytes, mime: str, material):
        img = QImage.fromData(data)
        if img.isNull():
            return data, mime, material.alpha_mode
        rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
        alpha = np.frombuffer(bytes(rgba.constBits()), "u1")[3::4]
        cutout = img.hasAlphaChannel() and np.count_nonzero(alpha < 128) > alpha.size * 0.005
        mode = "MASK" if cutout and material.alpha_mode in ("OPAQUE", "BLEND") else material.alpha_mode
        if max_px and max(img.width(), img.height()) > max_px:
            img = img.scaled(max_px, max_px, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            opaque = not img.hasAlphaChannel() or int(alpha.min(initial=255)) == 255
            fmt, mime = ("JPG", "image/jpeg") if opaque else ("PNG", "image/png")
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, fmt, 90 if fmt == "JPG" else -1)
            data = bytes(buf.data())
        return data, mime, mode
    return hook


def compact_file(src: Path, dst: Path, max_px: int = 2048, max_tris: int = 0) -> tuple[int, int, int, int]:
    """Grava ``dst`` e confere relendo. Devolve (bytes antes, bytes depois, triângulos antes, depois)."""
    b, t0, t1 = compact_model(load_model(src, normalize=False), dst, max_px, max_tris)
    return src.stat().st_size, b, t0, t1


def compact_model(model, dst: Path, max_px: int = 2048, max_tris: int = 0) -> tuple[int, int, int]:
    """Grava um modelo (lido sem normalizar) em ``dst`` e confere relendo.
    Devolve (bytes gravados, triângulos antes, depois)."""
    out = simplify_model(model, max_tris) if max_tris else model
    dst.parent.mkdir(parents=True, exist_ok=True)
    write_glb(dst, compact_parts(out, image_hook(max_px)))
    check = load_model(dst, normalize=False)
    if check.triangles != out.triangles:
        raise GltfError(f"conferência falhou: {check.triangles} triângulos, esperado {out.triangles}")
    box = lambda m: np.concatenate([p.positions for p in m.primitives])  # noqa: E731
    a, b = box(model), box(check)
    tol = 1e-4 if out is model else 0.1 * float(np.linalg.norm(a.max(0) - a.min(0)))
    if not (np.allclose(a.min(0), b.min(0), atol=tol) and np.allclose(a.max(0), b.max(0), atol=tol)):
        raise GltfError("conferência falhou: o modelo mudou de tamanho ou posição")
    return dst.stat().st_size, model.triangles, check.triangles


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m leafdraw.compactar", description=__doc__.split("\n\n")[0])
    ap.add_argument("entradas", nargs="+", type=Path, help="arquivos .glb/.gltf ou pastas")
    ap.add_argument("-o", "--saida", type=Path, help="pasta de saída (padrão: <pasta>/compactados)")
    ap.add_argument("--max-textura", type=int, default=2048, help="lado máximo das texturas em px (0 = não reduz)")
    ap.add_argument("--leve", type=int, default=0, metavar="N",
                    help="versão leve com até ~N triângulos por modelo (0 = sem simplificar)")
    args = ap.parse_args(argv)
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (QImage pede o app)

    files = []
    for e in args.entradas:
        files += sorted(f for f in e.iterdir() if f.suffix.lower() in (".glb", ".gltf")) if e.is_dir() else [e]
    before = after = 0
    failed = 0
    for src in files:
        out_dir = args.saida or src.parent / "compactados"
        dst = out_dir / (src.stem + ".glb")
        if dst.resolve() == src.resolve():
            print(f"{src.name}: a saída seria o próprio arquivo, pulando")
            continue
        try:
            a, b, t0, t1 = compact_file(src, dst, args.max_textura, args.leve)
        except (GltfError, OSError, ValueError) as exc:
            print(f"{src.name}: ERRO {exc}")
            failed += 1
            continue
        before, after = before + a, after + b
        tris = f"{t0:,} triângulos" if t0 == t1 else f"{t0:,} -> {t1:,} triângulos"
        print(f"{src.name}: {a / 2**20:.1f} MB -> {b / 2**20:.1f} MB ({tris})".replace(",", "."), flush=True)
    if before:
        print(f"Total: {before / 2**20:.0f} MB -> {after / 2**20:.0f} MB ({100 * (1 - after / before):.0f}% menor)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
