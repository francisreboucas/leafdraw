"""Gera os ícones do LeafDraw a partir de packaging/leaf.png:

* leafdraw/resources/icon.png — ícone da janela (256 px)
* packaging/leafdraw.ico      — ícone do executável e do instalador (16 a 256 px)
* packaging/leafdraw.icns     — ícone do aplicativo no macOS (16 a 512 px)

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
# tipos PNG do ICNS: (código, lado em px)
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"icp6", 64), (b"ic12", 64), (b"ic07", 128),
              (b"ic08", 256), (b"ic13", 256), (b"ic09", 512), (b"ic14", 512))


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


def write_icns(path: Path, images: dict[int, bytes]):
    """ICNS com entradas PNG (macOS 10.7 em diante)."""
    body = b"".join(code + struct.pack(">I", 8 + len(images[size])) + images[size] for code, size in ICNS_TYPES)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    src = QImage(str(SOURCE)).convertToFormat(QImage.Format.Format_ARGB32)
    if src.isNull():
        raise SystemExit(f"não foi possível ler {SOURCE}")
    imgs = {s: scaled(src, s) for s in SIZES}
    imgs[256].save(str(ROOT / "leafdraw" / "resources" / "icon.png"))
    write_ico(ROOT / "packaging" / "leafdraw.ico", [(s, png_bytes(imgs[s])) for s in SIZES])
    imgs[512] = scaled(src, 512)
    write_icns(ROOT / "packaging" / "leafdraw.icns", {size: png_bytes(imgs[size]) for _, size in ICNS_TYPES})
    print("icones gerados")
    del app


if __name__ == "__main__":
    main()
