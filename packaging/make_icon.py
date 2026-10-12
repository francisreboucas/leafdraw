"""Gera os ícones do LeafDraw a partir de packaging/leaf.png:

* leafdraw/resources/icon.png — ícone da janela (256 px)
* packaging/leafdraw.ico      — ícone do executável e do instalador (16 a 256 px)

Uso: python packaging/make_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging" / "leaf.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def scaled(src: QImage, size: int) -> QImage:
    # reduz em etapas de no máximo 2× para manter a nitidez nos tamanhos pequenos
    img = src
    while img.width() > size * 2:
        img = img.scaled(img.width() // 2, img.height() // 2, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path, images: list[tuple[int, bytes]]):
    """ICO com entradas PNG (aceito pelo Windows Vista em diante)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.write_bytes(header + entries + blobs)


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    src = QImage(str(SOURCE)).convertToFormat(QImage.Format.Format_ARGB32)
    if src.isNull():
        raise SystemExit(f"não foi possível ler {SOURCE}")
    imgs = {s: scaled(src, s) for s in SIZES}
    imgs[256].save(str(ROOT / "leafdraw" / "resources" / "icon.png"))
    write_ico(ROOT / "packaging" / "leafdraw.ico", [(s, png_bytes(imgs[s])) for s in SIZES])
    print("icones gerados")
    del app


if __name__ == "__main__":
    main()
