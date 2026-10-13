"""Gera ``examples/modelos/arvore_teste.glb``: uma árvore simples para testar os modelos 3D.

Tronco cilíndrico opaco e copa feita de planos com uma textura de folhas
recortada por alfa (``alphaMode: MASK``, dupla face) — a mesma técnica dos
modelos de vegetação para tempo real. Coordenadas em Y para cima (glTF).

    python examples/make_test_tree.py

O modelo é gerado aqui e distribuído sob CC0 (domínio público).
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leafdraw.core.gltf import write_glb  # noqa: E402

OUT = Path(__file__).resolve().parent / "modelos" / "arvore_teste.glb"
TRUNK_H = 3.2
CROWN_Y, CROWN_RX, CROWN_RY = 5.6, 3.0, 2.4
CARDS = 70


def leaf_texture(size: int = 256, seed: int = 3) -> bytes:
    """Ramo de folhas com fundo transparente, em PNG."""
    rnd = random.Random(seed)
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    p.setPen(QPen(QColor(92, 70, 40), size * 0.012))
    for _ in range(5):  # galhinhos
        a = rnd.uniform(0, 2 * math.pi)
        p.drawLine(QPointF(c, c), QPointF(c + math.cos(a) * size * 0.4, c + math.sin(a) * size * 0.4))
    for _ in range(46):
        a = rnd.uniform(0, 2 * math.pi)
        d = size * 0.42 * math.sqrt(rnd.random())
        x, y = c + math.cos(a) * d, c + math.sin(a) * d
        g = rnd.uniform(0.75, 1.15)
        p.save()
        p.translate(x, y)
        p.rotate(rnd.uniform(0, 360))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(int(min(255, 62 * g)), int(min(255, 128 * g)), int(min(255, 48 * g)))))
        w = size * rnd.uniform(0.05, 0.075)
        p.drawEllipse(QPointF(0, 0), w, w * 0.45)
        p.restore()
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def trunk(segments: int = 10, r0: float = 0.22, r1: float = 0.12):
    pos, nrm, idx = [], [], []
    for i in range(segments + 1):
        a = 2 * math.pi * i / segments
        ca, sa = math.cos(a), math.sin(a)
        pos += [(r0 * ca, 0.0, -r0 * sa), (r1 * ca, TRUNK_H + 0.8, -r1 * sa)]
        nrm += [(ca, 0.0, -sa)] * 2
    for i in range(segments):
        a, b = 2 * i, 2 * i + 2
        idx += [a, b, a + 1, a + 1, b, b + 1]
    return {"name": "tronco", "positions": pos, "normals": nrm, "indices": idx, "color": (0.42, 0.31, 0.21, 1.0)}


def crown(seed: int = 11):
    rnd = random.Random(seed)
    pos, nrm, uv, idx = [], [], [], []
    for k in range(CARDS):
        # ponto na casca de um elipsoide, um pouco para dentro
        u, v = rnd.uniform(0, 2 * math.pi), math.acos(rnd.uniform(-0.85, 1))
        s = rnd.uniform(0.55, 1.0)
        center = np.array([CROWN_RX * s * math.sin(v) * math.cos(u), CROWN_Y + CROWN_RY * s * math.cos(v),
                           CROWN_RX * s * math.sin(v) * math.sin(u)])
        out = center - (0, CROWN_Y, 0)
        n = out / (np.linalg.norm(out) or 1)
        n = n + np.array([rnd.uniform(-0.5, 0.5), rnd.uniform(-0.2, 0.6), rnd.uniform(-0.5, 0.5)])
        n /= np.linalg.norm(n)
        t = np.cross(n, (0, 1, 0))
        if np.linalg.norm(t) < 1e-3:
            t = np.array([1.0, 0, 0])
        t /= np.linalg.norm(t)
        b = np.cross(n, t)
        half = rnd.uniform(0.9, 1.4)
        base = len(pos)
        for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pos.append(tuple(center + (t * du + b * dv) * half))
            nrm.append(tuple(n))
            uv.append(((du + 1) / 2, (1 - dv) / 2))
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return {"name": "folhas", "positions": pos, "normals": nrm, "uvs": uv, "indices": idx,
            "image": leaf_texture(), "alpha_mode": "MASK", "alpha_cutoff": 0.5, "double_sided": True}


def main():
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # QPainter de texto/imagem pede o app
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_glb(OUT, [trunk(), crown()])
    print(f"{OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
