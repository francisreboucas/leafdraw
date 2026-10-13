"""Gera modelos 3D (.glb) próprios para as espécies do catálogo.

    python -m leafdraw.modelgen                 # todas as espécies de SPECIES
    python -m leafdraw.modelgen ixora-coccinea  # só algumas

Os modelos são feitos aqui, por código, e distribuídos sob CC0 em
``leafdraw/resources/models/leafdraw``. Usam a técnica de vegetação para tempo real:
planos com textura recortada por alfa (``alphaMode: MASK``, dupla face) para folhas,
flores e frondes, e cilindros para troncos. Cada forma de crescimento tem um gerador
(árvore, palmeira, arbusto, roseta, touceira…) e cada espécie, os seus parâmetros:
cores, forma das folhas, flores, número de frondes etc. O modelo sai no porte do
catálogo (copa × altura), então a vista 3D não precisa esticá-lo.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from leafdraw.core.catalog import MODELS_DIR
from leafdraw.core.gltf import write_glb

OUT_DIR = MODELS_DIR / "leafdraw"
UP = np.array([0.0, 0.0, 1.0])


def rgb(hexstr: str) -> tuple[int, int, int]:
    c = QColor(hexstr)
    return c.red(), c.green(), c.blue()


# --- texturas ------------------------------------------------------------------------

def _canvas(w: int, h: int):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return img, p


def _png(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _shade(c, rnd: random.Random, jitter: float = 0.15, k: float = 1.0) -> QColor:
    f = k * (1 + rnd.uniform(-jitter, jitter))
    r, g, b = c
    return QColor(*(int(max(0, min(255, v * f))) for v in (r, g, b)))


def _leaf_path(length: float, width: float, kind: str = "oval") -> QPainterPath:
    """Folha ao longo de +x, base na origem."""
    L, W = length, width
    p = QPainterPath()
    p.moveTo(0, 0)
    if kind == "bilobed":  # pata-de-vaca: duas metades com chanfro na ponta
        p.cubicTo(L * 0.3, -W * 1.2, L * 1.05, -W * 1.1, L * 0.95, -W * 0.15)
        p.lineTo(L * 0.72, 0)
        p.lineTo(L * 0.95, W * 0.15)
        p.cubicTo(L * 1.05, W * 1.1, L * 0.3, W * 1.2, 0, 0)
    elif kind == "round":
        p.cubicTo(L * 0.1, -W, L * 0.9, -W, L, 0)
        p.cubicTo(L * 0.9, W, L * 0.1, W, 0, 0)
    else:  # oval, narrow, small: ponta aguda
        p.cubicTo(L * 0.25, -W, L * 0.7, -W * 0.85, L, 0)
        p.cubicTo(L * 0.7, W * 0.85, L * 0.25, W, 0, 0)
    return p


LEAF_W = {"oval": 0.42, "narrow": 0.2, "small": 0.45, "bilobed": 0.5, "round": 0.75, "needle": 0.08}


def _flower(p: QPainter, kind: str, color, r: float, rnd: random.Random):
    p.setPen(Qt.PenStyle.NoPen)
    c = _shade(color, rnd, 0.12)
    if kind == "trumpet":  # ipês, jacarandá: cachos de flores tubulares
        for _ in range(rnd.randint(3, 6)):
            p.save()
            p.rotate(rnd.uniform(0, 360))
            p.translate(r * rnd.uniform(0.1, 0.6), 0)
            p.setBrush(_shade(color, rnd, 0.15))
            p.drawEllipse(QPointF(0, 0), r * 0.55, r * 0.32)
            p.restore()
    elif kind in ("ball", "fruit"):  # frutos
        p.setBrush(c)
        p.drawEllipse(QPointF(0, 0), r * 0.5, r * 0.5)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(-r * 0.15, -r * 0.15), r * 0.14, r * 0.14)
    elif kind == "cluster":  # ixora: buquê de florzinhas
        for _ in range(14):
            a, d = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
            p.setBrush(_shade(color, rnd, 0.15))
            p.drawEllipse(QPointF(math.cos(a) * d, math.sin(a) * d), r * 0.2, r * 0.2)
    else:  # star / big: pétalas em volta de um miolo
        n = 5
        pr = r * (0.55 if kind == "big" else 0.45)
        for k in range(n):
            p.save()
            p.rotate(k * 360 / n + rnd.uniform(-8, 8))
            p.setBrush(_shade(color, rnd, 0.1))
            p.drawEllipse(QPointF(pr * 0.9, 0), pr, pr * 0.62)
            p.restore()
        p.setBrush(QColor(240, 210, 80) if kind != "big" else QColor(230, 200, 90))
        p.drawEllipse(QPointF(0, 0), r * 0.16, r * 0.16)


def foliage_texture(leaf, kind: str = "oval", n: int = 80, leaf_len: float = 0.1, flower=None,
                    flower_frac: float = 0.0, flower_kind: str = "star", flower_size: float = 0.06,
                    twig=(96, 74, 50), size: int = 512, seed: int = 1) -> bytes:
    """Ramo com folhas (e flores/frutos) sobre fundo transparente."""
    rnd = random.Random(seed)
    img, p = _canvas(size, size)
    c = size / 2
    L = size * leaf_len
    W = L * LEAF_W.get(kind, 0.42)
    reach = size / 2 - L * 1.05
    p.setPen(QPen(QColor(*twig), size * 0.007))
    for _ in range(6):
        a = rnd.uniform(0, 2 * math.pi)
        p.drawLine(QPointF(c, c), QPointF(c + math.cos(a) * reach, c + math.sin(a) * reach))
    for _ in range(n):
        a, d = rnd.uniform(0, 2 * math.pi), reach * math.sqrt(rnd.random())
        col = _shade(leaf, rnd, 0.2)
        p.save()
        p.translate(c + math.cos(a) * d, c + math.sin(a) * d)
        p.rotate(math.degrees(a) + rnd.uniform(-60, 60))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        ll = L * rnd.uniform(0.8, 1.15)
        p.drawPath(_leaf_path(ll, W * ll / L, kind))
        if kind not in ("small", "needle"):
            p.setPen(QPen(col.darker(130), max(1.0, size * 0.003)))
            p.drawLine(QPointF(0, 0), QPointF(ll * 0.8, 0))
        p.restore()
    if flower is not None and flower_frac > 0:
        fr = size * flower_size
        for _ in range(int(n * flower_frac * 1.4)):
            a, d = rnd.uniform(0, 2 * math.pi), (size / 2 - fr * 1.1) * math.sqrt(rnd.random())
            p.save()
            p.translate(c + math.cos(a) * d, c + math.sin(a) * d)
            _flower(p, flower_kind, flower, fr, rnd)
            p.restore()
    p.end()
    return _png(img)


def pinnate_texture(leaf, plume: bool = False, size: int = 512, seed: int = 1) -> bytes:
    """Fronde pinada: raque no centro (u = 0,5), base embaixo (v = 1), ponta em cima (v = 0)."""
    rnd = random.Random(seed)
    w, h = size // 4, size
    img, p = _canvas(w, h)
    cx = w / 2
    grad = QLinearGradient(0, h, 0, 0)
    grad.setColorAt(0, QColor(110, 100, 60))
    grad.setColorAt(1, _shade(leaf, rnd, 0, 0.8))
    p.setPen(QPen(QBrush(grad), w * 0.035))
    p.drawLine(QPointF(cx, h), QPointF(cx, 2))
    p.setPen(Qt.PenStyle.NoPen)
    y = h * 0.86
    while y > h * 0.02:
        t = 1 - y / h  # 0 base, 1 ponta
        span = (w * 0.48) * math.sin(math.pi * min(1.0, (t - 0.1) / 0.92)) ** 0.5
        for side in (-1, 1):
            for extra in ((0, 1) if plume else (0,)):
                ang = math.radians(rnd.uniform(28, 42) + (rnd.uniform(-55, 25) if extra else 0))
                ll = span / max(math.cos(ang), 0.35) * rnd.uniform(0.85, 1.05)
                p.save()
                p.translate(cx, y)
                p.rotate(-90 + side * math.degrees(math.pi / 2 - ang))
                p.setBrush(_shade(leaf, rnd, 0.15))
                p.drawPath(_leaf_path(ll, ll * 0.07, "narrow"))
                p.restore()
        y -= h * (0.012 if plume else 0.016)
    p.end()
    return _png(img)


def blade_texture(leaf, kind: str = "grass", edge=None, size: int = 256, seed: int = 1) -> bytes:
    """Folha longa (capim, fita, espada): base embaixo, ponta em cima, ocupando a largura."""
    rnd = random.Random(seed)
    w, h = size // 4, size
    img, p = _canvas(w, h)
    grad = QLinearGradient(0, h, 0, 0)
    grad.setColorAt(0, _shade(leaf, rnd, 0, 0.7))
    grad.setColorAt(0.5, _shade(leaf, rnd, 0, 1.0))
    grad.setColorAt(1, _shade(leaf, rnd, 0, 1.15))
    path = QPainterPath()
    m = w * (0.5 if kind == "grass" else 0.08)
    tip = 0.0 if kind != "strap" else h * 0.03
    path.moveTo(m * 0.5 if kind == "grass" else w * 0.06, h)
    path.cubicTo(w * 0.05, h * 0.5, w * 0.25, h * 0.12, w / 2, tip)
    path.cubicTo(w * 0.75, h * 0.12, w * 0.95, h * 0.5, w - (m * 0.5 if kind == "grass" else w * 0.06), h)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawPath(path)
    if edge is not None:  # margem colorida (furcreia, bromélias)
        p.setPen(QPen(QColor(*edge), w * 0.08))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    p.setPen(QPen(_shade(leaf, rnd, 0, 0.75), max(1.0, w * 0.04)))
    p.drawLine(QPointF(w / 2, h), QPointF(w / 2, h * 0.08))
    p.end()
    return _png(img)


def broad_leaf_texture(leaf, kind: str = "paddle", size: int = 256, seed: int = 1) -> bytes:
    """Folha larga: base (pecíolo) embaixo no centro, ponta em cima."""
    rnd = random.Random(seed)
    img, p = _canvas(size, size)
    cx = size / 2
    path = QPainterPath()
    if kind == "monstera":
        path.moveTo(cx, size * 0.92)
        path.cubicTo(size * 0.02, size * 0.95, size * 0.0, size * 0.25, cx, size * 0.04)
        path.cubicTo(size * 1.0, size * 0.25, size * 0.98, size * 0.95, cx, size * 0.92)
    elif kind == "heart":
        path.moveTo(cx, size * 0.8)
        path.cubicTo(size * 0.05, size * 0.98, size * 0.05, size * 0.3, cx, size * 0.04)
        path.cubicTo(size * 0.95, size * 0.3, size * 0.95, size * 0.98, cx, size * 0.8)
    else:  # paddle (ravenala, ave-do-paraíso), oval (orquídea)
        wide = 0.36 if kind == "paddle" else 0.44
        path.moveTo(cx, size * 0.99)
        path.cubicTo(cx - size * wide, size * 0.85, cx - size * wide, size * 0.15, cx, size * 0.01)
        path.cubicTo(cx + size * wide, size * 0.15, cx + size * wide, size * 0.85, cx, size * 0.99)
    grad = QLinearGradient(0, 0, size, 0)
    grad.setColorAt(0, _shade(leaf, rnd, 0, 0.82))
    grad.setColorAt(0.5, _shade(leaf, rnd, 0, 1.08))
    grad.setColorAt(1, _shade(leaf, rnd, 0, 0.82))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawPath(path)
    p.setPen(QPen(_shade(leaf, rnd, 0, 1.3), size * 0.012))
    p.drawLine(QPointF(cx, size * 0.97), QPointF(cx, size * 0.06))
    p.setPen(QPen(_shade(leaf, rnd, 0, 0.7), size * 0.004))
    for k in range(14):  # nervuras
        y = size * (0.15 + 0.75 * k / 14)
        for s in (-1, 1):
            p.drawLine(QPointF(cx, y), QPointF(cx + s * size * 0.4, y - size * 0.1))
    if kind in ("monstera", "paddle"):  # recortes: furos e rasgos
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setPen(QPen(Qt.GlobalColor.transparent, size * (0.022 if kind == "monstera" else 0.008)))
        for k in range(7 if kind == "monstera" else 9):
            y = size * (0.18 + 0.68 * (k + rnd.random() * 0.4) / 7)
            for s in (-1, 1):
                if rnd.random() < (0.9 if kind == "monstera" else 0.5):
                    depth = rnd.uniform(0.18, 0.32) if kind == "monstera" else rnd.uniform(0.15, 0.4)
                    p.drawLine(QPointF(cx + s * size * 0.5, y - size * 0.06),
                               QPointF(cx + s * size * (0.5 - depth), y))
        if kind == "monstera":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Qt.GlobalColor.transparent)
            for k in range(6):
                y = size * (0.3 + 0.45 * k / 6)
                for s in (-1, 1):
                    p.drawEllipse(QPointF(cx + s * size * 0.13, y), size * 0.025, size * 0.045)
    p.end()
    return _png(img)


def flower_card_texture(kind: str, color, size: int = 256, seed: int = 1) -> bytes:
    """Cartão com flor/inflorescência: umbela, ave-do-paraíso, espiga, íris, orquídea."""
    rnd = random.Random(seed)
    if kind == "spike":
        img, p = _canvas(size // 4, size)
        w, h = size // 4, size
        p.setPen(QPen(QColor(90, 110, 70), w * 0.06))
        p.drawLine(QPointF(w / 2, h), QPointF(w / 2, h * 0.05))
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(60):
            y = h * (0.05 + 0.5 * rnd.random())
            p.setBrush(_shade(color, rnd, 0.15))
            p.drawEllipse(QPointF(w / 2 + rnd.uniform(-w * 0.28, w * 0.28), y), w * 0.12, w * 0.1)
        p.end()
        return _png(img)
    img, p = _canvas(size, size)
    c = size / 2
    p.setPen(Qt.PenStyle.NoPen)
    if kind == "umbel":  # agapanto
        p.setPen(QPen(QColor(100, 130, 70), size * 0.008))
        for _ in range(40):
            a, d = rnd.uniform(0, 2 * math.pi), size * 0.4 * math.sqrt(rnd.random())
            p.drawLine(QPointF(c, c), QPointF(c + math.cos(a) * d, c + math.sin(a) * d))
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(55):
            a, d = rnd.uniform(0, 2 * math.pi), size * 0.4 * math.sqrt(rnd.random())
            p.save()
            p.translate(c + math.cos(a) * d, c + math.sin(a) * d)
            _flower(p, "star", color, size * 0.05, rnd)
            p.restore()
    elif kind == "bird":  # ave-do-paraíso: bico horizontal, crista laranja e azul
        p.setBrush(QColor(95, 120, 100))
        beak = QPainterPath()
        beak.moveTo(size * 0.1, c + size * 0.08)
        beak.cubicTo(size * 0.4, c + size * 0.18, size * 0.75, c + size * 0.1, size * 0.95, c - size * 0.02)
        beak.lineTo(size * 0.6, c + size * 0.02)
        beak.closeSubpath()
        p.drawPath(beak)
        for k in range(4):
            p.save()
            p.translate(size * 0.55, c)
            p.rotate(-60 - k * 18)
            p.setBrush(_shade(color, rnd, 0.1))
            p.drawPath(_leaf_path(size * 0.38, size * 0.05, "narrow"))
            p.restore()
        p.save()
        p.translate(size * 0.55, c)
        p.rotate(-100)
        p.setBrush(QColor(60, 70, 190))
        p.drawPath(_leaf_path(size * 0.32, size * 0.035, "narrow"))
        p.restore()
    elif kind == "iris":  # moreia
        for k in range(6):
            p.save()
            p.translate(c, c)
            p.rotate(k * 60)
            p.setBrush(_shade(color, rnd, 0.06))
            p.drawPath(_leaf_path(size * 0.42, size * (0.16 if k % 2 else 0.11), "oval"))
            if k % 2 == 0:
                p.setBrush(QColor(150, 90, 40))
                p.drawEllipse(QPointF(size * 0.12, 0), size * 0.04, size * 0.03)
            p.restore()
    elif kind == "orchid":
        for k in range(5):
            p.save()
            p.translate(c, c)
            p.rotate(k * 72 - 90)
            p.setBrush(_shade(color, rnd, 0.04))
            p.drawPath(_leaf_path(size * 0.42, size * (0.2 if k in (1, 4) else 0.11), "round"))
            p.restore()
        p.setBrush(QColor(200, 60, 120))
        p.drawEllipse(QPointF(c, c + size * 0.08), size * 0.07, size * 0.1)
        p.setBrush(QColor(240, 200, 60))
        p.drawEllipse(QPointF(c, c), size * 0.04, size * 0.04)
    else:  # cluster de florzinhas (orquídea-de-crucifixo, bromélia)
        for _ in range(40):
            a, d = rnd.uniform(0, 2 * math.pi), size * 0.42 * math.sqrt(rnd.random())
            p.save()
            p.translate(c + math.cos(a) * d, c + math.sin(a) * d)
            _flower(p, "star", color, size * 0.06, rnd)
            p.restore()
    p.end()
    return _png(img)


# --- geometria -------------------------------------------------------------------------

def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _perp(n):
    u = np.cross(n, UP)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, (1.0, 0, 0))
    return _unit(u)


class Builder:
    """Malhas por material, em metros e com Z para cima; ``parts()`` converte para glTF."""

    def __init__(self, seed: int = 1):
        self.rnd = random.Random(seed)
        self.mats: dict[str, dict] = {}
        self.data: dict[str, list] = {}

    def material(self, key: str, color=(1, 1, 1, 1), image: bytes | None = None, cutout: bool = False):
        self.mats[key] = {"color": color, "image": image, "alpha_mode": "MASK" if cutout else "OPAQUE",
                          "double_sided": cutout, "name": key}
        self.data.setdefault(key, [[], [], [], []])  # pos, nrm, uv, idx

    def _add(self, key, pos, nrm, uv, tris):
        d = self.data[key]
        base = len(d[0])
        d[0] += [tuple(p) for p in pos]
        d[1] += [tuple(n) for n in nrm]
        d[2] += [tuple(t) for t in uv]
        d[3] += [base + i for t in tris for i in t]

    def quad(self, key, center, u, v, uv=(0.0, 0.0, 1.0, 1.0)):
        """Retângulo centrado em ``center`` com semieixos ``u`` (largura) e ``v`` (altura)."""
        c, u, v = (np.asarray(x, float) for x in (center, u, v))
        n = _unit(np.cross(u, v))
        u0, v0, u1, v1 = uv
        pos = [c - u - v, c + u - v, c + u + v, c - u + v]
        self._add(key, pos, [n] * 4, [(u0, v1), (u1, v1), (u1, v0), (u0, v0)], [(0, 1, 2), (0, 2, 3)])

    def card(self, key, center, normal, half, spin=None, crown=None):
        """Cartão quadrado. Com ``crown`` (centro da copa), a face da frente fica para fora e as
        normais dos vértices apontam a partir do centro: a luz varia suavemente pela copa, sem
        mostrar o plano de cada cartão, e o miolo fica mais escuro."""
        n = _unit(normal)
        center = np.asarray(center, float)
        if crown is not None and np.dot(n, center - crown) < 0:
            n = -n
        u = _perp(n)
        w = np.cross(n, u)
        a = self.rnd.uniform(0, 2 * math.pi) if spin is None else spin
        u, w = u * math.cos(a) + w * math.sin(a), -u * math.sin(a) + w * math.cos(a)
        if crown is None:
            self.quad(key, center, u * half, w * half)
            return
        u, w = u * half, w * half
        pos = [center - u - w, center + u - w, center + u + w, center - u + w]
        if np.dot(np.cross(u, w), n) < 0:
            pos = pos[::-1]
        nrm = [_unit(0.3 * n + 0.7 * _unit(p - crown)) for p in pos]
        self._add(key, pos, nrm, [(0, 1), (1, 1), (1, 0), (0, 0)], [(0, 1, 2), (0, 2, 3)])

    def ribbon(self, key, spine, sides, u_range=(0.0, 1.0)):
        """Fita ao longo de ``spine`` (n, 3); ``sides`` (n, 3) é o deslocamento até a borda.
        A fita vai da espinha (u0) até a borda (u1); v = 1 na base e 0 na ponta."""
        spine, sides = np.asarray(spine, float), np.asarray(sides, float)
        n = len(spine)
        pos, nrm, uv, tris = [], [], [], []
        for i in range(n):
            t = spine[min(i + 1, n - 1)] - spine[max(i - 1, 0)]
            nn = _unit(np.cross(sides[i], t))
            v = 1 - i / (n - 1)
            pos += [spine[i], spine[i] + sides[i]]
            nrm += [nn, nn]
            uv += [(u_range[0], v), (u_range[1], v)]
        for i in range(n - 1):
            a = 2 * i
            tris += [(a, a + 1, a + 3), (a, a + 3, a + 2)]
        self._add(key, pos, nrm, uv, tris)

    def blade(self, key, spine, side_dir, width, fold: float = 0.0):
        """Folha/fronde dos dois lados da espinha; ``fold`` levanta as bordas (perfil em V)."""
        spine = np.asarray(spine, float)
        side_dir = np.asarray(side_dir, float)
        if side_dir.ndim == 1:
            side_dir = np.tile(side_dir, (len(spine), 1))
        w = np.asarray(width, float).reshape(-1, 1) if np.ndim(width) else width
        for s, ur in ((-1, (0.5, 0.0)), (1, (0.5, 1.0))):
            sides = side_dir * s * w + UP * fold * w
            self.ribbon(key, spine, sides, ur)

    def tube(self, key, path, radii, seg: int = 8):
        path = np.asarray(path, float)
        radii = np.broadcast_to(np.asarray(radii, float), (len(path),))
        pos, nrm, uv, tris = [], [], [], []
        for i, (p, r) in enumerate(zip(path, radii)):
            t = _unit(path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)])
            a = _perp(t)
            b = np.cross(t, a)
            for k in range(seg + 1):
                ang = 2 * math.pi * k / seg
                d = a * math.cos(ang) + b * math.sin(ang)
                pos.append(p + d * r)
                nrm.append(d)
                uv.append((k / seg, i / max(len(path) - 1, 1)))
        row = seg + 1
        for i in range(len(path) - 1):
            for k in range(seg):
                a0 = i * row + k
                tris += [(a0, a0 + 1, a0 + row + 1), (a0, a0 + row + 1, a0 + row)]
        self._add(key, pos, nrm, uv, tris)

    def center_xy(self, key: str) -> np.ndarray:
        """Leva o centro da caixa (em planta) das malhas ``key`` para o eixo; devolve o deslocamento."""
        pos = np.array(self.data[key][0])
        lo, hi = pos.min(0), pos.max(0)
        shift = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 0.0])
        self.data[key][0] = [tuple(p - shift) for p in pos]
        return shift

    def fit(self, width: float, height: float):
        """Ajusta tudo à caixa do catálogo: largura (maior lado em planta) e altura."""
        allp = np.array([p for d in self.data.values() for p in d[0]])
        lo, hi = allp.min(0), allp.max(0)
        center = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        k = np.array([width / max(hi[0] - lo[0], hi[1] - lo[1]), 0, height / (hi[2] - lo[2])])
        k[1] = k[0]
        for d in self.data.values():
            d[0] = [tuple((np.array(p) - center) * k) for p in d[0]]
            d[1] = [tuple(_unit(np.array(n) / np.where(k == 0, 1, k))) for n in d[1]]

    def parts(self) -> list[dict]:
        out = []
        for key, (pos, nrm, uv, idx) in self.data.items():
            if not idx:
                continue
            pos, nrm = np.array(pos), np.array(nrm)
            to_y = lambda a: np.stack([a[:, 0], a[:, 2], -a[:, 1]], 1)  # noqa: E731
            m = self.mats[key]
            out.append({"name": key, "positions": to_y(pos), "normals": to_y(nrm),
                        "uvs": np.array(uv) if m["image"] else None, "indices": idx, "color": m["color"],
                        "image": m["image"], "alpha_mode": m["alpha_mode"], "double_sided": m["double_sided"]})
        return out


def _col(hexstr: str, alpha: float = 1.0):
    r, g, b = rgb(hexstr)
    return (r / 255, g / 255, b / 255, alpha)


# --- formas de crescimento -----------------------------------------------------------

def _crown(b: Builder, center, radii, cards: int, half: float, key: str = "folhas", blobs: int = 5,
           top_bias: float = 0.0):
    """Copa irregular: vários "bolos" de folhas dentro do envelope; devolve os centros."""
    rnd = b.rnd
    center, radii = np.asarray(center, float), np.asarray(radii, float)
    centers = []
    for k in range(blobs):
        a = 2 * math.pi * k / blobs + rnd.uniform(-0.4, 0.4)
        r = rnd.uniform(0.35, 0.55) if k else 0.0
        centers.append(center + radii * np.array([math.cos(a) * r, math.sin(a) * r,
                                                  rnd.uniform(-0.25, 0.3) + top_bias * 0.3]))
    # copa centrada no eixo do tronco (o sorteio pode deixá-la pender para um lado)
    shift = np.mean(centers, axis=0) - center
    centers = [c - np.array([shift[0], shift[1], 0.0]) for c in centers]
    blob_r = radii * 0.62
    for i in range(cards):
        c = centers[i % blobs]
        d = _unit([rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1) + top_bias])
        s = rnd.uniform(0.55, 1.0)
        p = c + d * blob_r * s
        n = _unit(d + np.array([rnd.uniform(-0.6, 0.6), rnd.uniform(-0.6, 0.6), rnd.uniform(-0.2, 0.7)]))
        b.card(key, p, n, half * rnd.uniform(0.8, 1.15), crown=center)
    return centers


def _cards_for(radii, half: float, density: float) -> int:
    """Cartões para cobrir a copa: ``density`` m² de cartão por m² de superfície do elipsoide."""
    a, b_, c = radii
    p = 1.6075
    surface = 4 * math.pi * (((a * b_) ** p + (a * c) ** p + (b_ * c) ** p) / 3) ** (1 / p)
    return max(12, int(density * surface / (2 * half) ** 2))


def tree(b: Builder, H, C, leaf_tex, *, trunk_h=0.35, trunk_r=None, bark="#6b4f36", density=2.3, blobs=5,
         stems=1, flat=1.0, top_bias=0.0, card=0.4):
    rnd = b.rnd
    b.material("tronco", _col(bark))
    b.material("folhas", image=leaf_tex, cutout=True)
    tr = trunk_r or max(0.05, C * 0.035)
    th = H * trunk_h
    crown_c = np.array([0, 0, th + (H - th) * 0.5])
    radii = np.array([C / 2 * 0.8, C / 2 * 0.8, (H - th) / 2 * 0.8 * flat])
    half = max(radii) * card
    centers = _crown(b, crown_c, radii, _cards_for(radii, half, density), half, blobs=blobs, top_bias=top_bias)
    shift = b.center_xy("folhas")  # o ponto de inserção é o centro da caixa: a copa fica centrada no tronco
    centers = [c - shift for c in centers]
    tops = []
    # vários troncos: a seção somada é a de um tronco único, e eles sobem juntos, abrindo pouco
    ts = tr if stems == 1 else tr / math.sqrt(stems) * 1.15
    for s in range(stems):
        a = 2 * math.pi * s / stems + rnd.uniform(-0.3, 0.3)
        d = np.array([math.cos(a), math.sin(a), 0])
        if stems == 1:
            base, top = np.zeros(3), np.array([rnd.uniform(-1, 1) * tr, rnd.uniform(-1, 1) * tr, th])
        else:
            base = d * ts * 1.1
            top = d * min(C * 0.1, ts * 4) + UP * th * rnd.uniform(0.9, 1.05)
        mid = (base + top) / 2 + np.array([rnd.uniform(-0.5, 0.5) * ts, rnd.uniform(-0.5, 0.5) * ts, 0])
        b.tube("tronco", [base, mid, top], [ts * (1.25 if stems == 1 else 1.1), ts * 0.95, ts * 0.75], 9)
        tops.append(top)
    for c in centers:  # galhos até cada bolo da copa
        t = tops[rnd.randrange(len(tops))]
        mid = (t + c) / 2 + np.array([0, 0, -0.1 * (c[2] - t[2])])
        b.tube("tronco", [t, mid, c], [ts * 0.6, ts * 0.4, ts * 0.2], 6)
    b.fit(C, H)


def palm(b: Builder, H, C, frond_tex, *, kind="pinnate", fronds=16, trunk_r=0.18, bark="#8a8070", shaft=None,
         lean=0.0, stems=1, droop=0.55, fold=0.35, frond_w=0.22, petiole=0.0, rise=(55, -15), fan_leaf=0.35):
    rnd = b.rnd
    b.material("estipe", _col(bark))
    b.material("fronde", image=frond_tex, cutout=True)
    if shaft:
        b.material("palmito", _col(shaft))
    L = C / 2 * 1.05  # comprimento das frondes
    for s in range(stems):
        sa = 2 * math.pi * s / max(stems, 1) + rnd.uniform(-0.4, 0.4)
        h = H * (rnd.uniform(0.55, 1.0) if stems > 1 else 1.0) - L * 0.35
        lean_s = lean if stems == 1 else rnd.uniform(0.04, 0.12)
        base = np.array([math.cos(sa), math.sin(sa), 0]) * (trunk_r * 2.2 if stems > 1 else 0)
        dirh = np.array([math.cos(sa), math.sin(sa), 0])
        path = [base + dirh * lean_s * h * (t ** 1.6) + UP * h * t for t in np.linspace(0, 1, 7)]
        radii = [trunk_r * (1.15 - 0.25 * t) for t in np.linspace(0, 1, 7)]
        b.tube("estipe", path, radii, 9)
        top = path[-1]
        if shaft:
            b.tube("palmito", [top - UP * h * 0.02, top + UP * h * 0.1], [trunk_r * 1.08, trunk_r * 0.9], 9)
            top = top + UP * h * 0.1
        n = fronds if stems == 1 else max(7, fronds * 2 // 3)
        for k in range(n):
            az = 2 * math.pi * k / n + rnd.uniform(-0.2, 0.2)
            frac = k / max(n - 1, 1)
            el = math.radians(rise[0] + (rise[1] - rise[0]) * (rnd.random() * 0.6 + frac * 0.4))
            d = np.array([math.cos(az), math.sin(az), 0])
            Lk = L * rnd.uniform(0.8, 1.05) * (0.9 if stems > 1 else 1)
            side = np.array([-math.sin(az), math.cos(az), 0])
            if kind == "fan":
                pl = Lk * (petiole or 0.45)
                pts = [top + (d * math.cos(el) * t + UP * (math.sin(el) * t - droop * 0.3 * t * t)) * pl
                       for t in np.linspace(0, 1, 4)]
                b.tube("estipe", pts, trunk_r * 0.12, 5)
                end = pts[-1]
                tang = _unit(pts[-1] - pts[-2])
                fl = Lk * fan_leaf * 2
                lift = _unit(np.cross(side, tang))  # normal do plano do leque
                lift = lift if lift[2] >= 0 else -lift
                out = _unit(np.array([tang[0], tang[1], 0.0]))
                plane_u = _unit(out * 0.45 + UP)  # leque quase em pé, voltado para fora
                lift = _unit(np.cross(side, plane_u))
                for j in range(19):
                    phi = math.radians(-85 + 170 * j / 18 + rnd.uniform(-3, 3))
                    sd = _unit(plane_u * math.cos(phi) + side * math.sin(phi))
                    ll = fl * (0.7 + 0.3 * math.cos(phi)) * rnd.uniform(0.92, 1.05)
                    seg = [end + (sd * t + UP * (-droop * 0.7 * t ** 2.2)) * ll for t in np.linspace(0, 1, 6)]
                    b.blade("fronde", seg, _unit(np.cross(sd, lift)), ll * 0.06, fold=fold)
            else:
                spine = [top + (d * math.cos(el) * t + UP * (math.sin(el) * t - droop * t * t)) * Lk
                         for t in np.linspace(0, 1, 9)]
                b.blade("fronde", spine, side, Lk * frond_w, fold=fold)
    b.fit(C, H)


def shrub(b: Builder, H, C, leaf_tex, *, stems=5, density=2.6, card=0.42, bark="#5d4630", upright=False):
    rnd = b.rnd
    b.material("galhos", _col(bark))
    b.material("folhas", image=leaf_tex, cutout=True)
    zc = H * (0.58 if upright else 0.5)
    radii = np.array([C / 2 * 0.82, C / 2 * 0.82, H / 2 * 0.82])
    for s in range(stems):
        a = rnd.uniform(0, 2 * math.pi)
        top = np.array([math.cos(a) * C * 0.25, math.sin(a) * C * 0.25, zc + rnd.uniform(-0.1, 0.25) * H])
        b.tube("galhos", [np.array([0, 0, 0]), top * 0.5 + np.array([0, 0, H * 0.05]), top],
               [max(0.012, C * 0.015), C * 0.01, C * 0.006], 6)
    half = max(radii) * card
    _crown(b, [0, 0, zc], radii, _cards_for(radii, half, density), half, blobs=4)
    b.fit(C, H)


def rosette(b: Builder, H, C, blade_tex, *, blades=26, width=0.12, rise=(75, 15), droop=0.25, center_tex=None,
            center_blades=0, spike=None, spike_h=1.0, spike_tex=None):
    """Roseta de folhas (bromélias, furcreia): folhas em espiral, internas mais em pé."""
    rnd = b.rnd
    b.material("folhas", image=blade_tex, cutout=True)
    R = C / 2

    def ring(key, n, Lmul, el_range, w):
        for k in range(n):
            az = k * 2.39996 + rnd.uniform(-0.1, 0.1)  # ângulo de ouro
            frac = k / max(n - 1, 1)
            el = math.radians(el_range[0] + (el_range[1] - el_range[0]) * frac)
            d = np.array([math.cos(az), math.sin(az), 0])
            L = R / max(math.cos(el), 0.3) * Lmul * rnd.uniform(0.85, 1.05)
            spine = [(d * math.cos(el) * t + UP * (math.sin(el) * t - droop * t * t)) * L + UP * 0.02
                     for t in np.linspace(0, 1, 7)]
            spine = [np.array([q[0], q[1], max(q[2], 0.005)]) for q in spine]
            side = np.array([-math.sin(az), math.cos(az), 0])
            b.blade(key, spine, side, L * w, fold=0.5)

    ring("folhas", blades, 1.0, rise, width)
    if center_tex is not None and center_blades:
        b.material("centro", image=center_tex, cutout=True)
        ring("centro", center_blades, 0.45, (80, 50), width * 1.2)
    if spike is not None:  # haste floral central
        b.material("haste", _col(spike))
        b.tube("haste", [UP * 0, UP * H * spike_h], [R * 0.03, R * 0.015], 6)
        if spike_tex is not None:
            b.material("flores", image=spike_tex, cutout=True)
            for k in range(8):
                z = H * spike_h * (0.55 + 0.45 * k / 8)
                for a in (0, math.pi / 2):
                    b.quad("flores", UP * z, np.array([math.cos(a), math.sin(a), 0]) * R * 0.18, UP * R * 0.12)
    b.fit(C, H)


def clump(b: Builder, H, C, blade_tex, *, blades=40, width=0.05, leaf_h=0.6, arch=0.6, flower_tex=None,
          flower_kind="umbel", stalks=0, stalk_col="#6f8a50", flower_size=0.12, spread=0.15):
    """Touceira de folhas longas (capins, agapanto, moreia, liríope) com hastes florais opcionais."""
    rnd = b.rnd
    b.material("folhas", image=blade_tex, cutout=True)
    R = C / 2
    Lh = H * leaf_h
    for k in range(blades):
        az = rnd.uniform(0, 2 * math.pi)
        d = np.array([math.cos(az), math.sin(az), 0])
        lean = rnd.uniform(0.15, 1.0) * arch
        L = math.hypot(Lh, R) * rnd.uniform(0.75, 1.05)
        base = d * R * spread * rnd.random()
        spine = [base + (d * lean * t * 0.9 + UP * (t - lean * 0.45 * t * t)) * L for t in np.linspace(0, 1, 7)]
        spine = [np.array([q[0], q[1], max(q[2], 0.005)]) for q in spine]
        side = np.array([-math.sin(az), math.cos(az), 0])
        b.blade("folhas", spine, side, L * width, fold=0.25)
    if stalks and flower_tex is not None:
        b.material("haste", _col(stalk_col))
        b.material("flores", image=flower_tex, cutout=True)
        for k in range(stalks):
            az = rnd.uniform(0, 2 * math.pi)
            d = np.array([math.cos(az), math.sin(az), 0])
            top = d * R * rnd.uniform(0.05, 0.45) + UP * H * rnd.uniform(0.8, 1.0)
            b.tube("haste", [d * R * 0.05, top * 0.5 + UP * H * 0.02, top], [R * 0.012, R * 0.01, R * 0.008], 5)
            fs = C * flower_size
            if flower_kind == "spike":
                for a in (0, math.pi / 2):
                    ax = np.array([math.cos(a + az), math.sin(a + az), 0])
                    b.quad("flores", top - UP * fs * 1.6, ax * fs * 0.5, UP * fs * 2)
            elif flower_kind == "flat":  # flor voltada para cima/fora
                b.card("flores", top, _unit(d * 0.6 + UP), fs)
            else:  # umbela: três cartões cruzados
                for a in range(3):
                    ang = a * math.pi / 3
                    b.quad("flores", top, np.array([math.cos(ang), math.sin(ang), 0]) * fs, UP * fs)
    b.fit(C, H)


def mound(b: Builder, H, C, leaf_tex, *, cards=90, card=0.35):
    """Forração baixa em almofada (azulzinha, grama-preta)."""
    b.material("folhas", image=leaf_tex, cutout=True)
    rnd = b.rnd
    R = C / 2
    for _ in range(cards):
        a, r = rnd.uniform(0, 2 * math.pi), R * math.sqrt(rnd.random()) * 0.85
        z = H * 0.55 * (1 - (r / R) ** 2) ** 0.5 + rnd.uniform(0, H * 0.25)
        p = np.array([math.cos(a) * r, math.sin(a) * r, z])
        n = _unit([math.cos(a) * r / R * 0.8 + rnd.uniform(-0.3, 0.3), math.sin(a) * r / R * 0.8
                   + rnd.uniform(-0.3, 0.3), 1])
        b.card("folhas", p, n, R * card * rnd.uniform(0.8, 1.1))
    b.fit(C, H)


def paddle_plant(b: Builder, H, C, leaf_tex, *, leaves=12, plane=False, trunk_h=0.0, petiole=0.55,
                 bark="#7c7a68", flower_tex=None, flowers=0, leaf_w=0.16):
    """Folhas em remo sobre pecíolos longos: ravenala (leque num plano) e ave-do-paraíso (touceira)."""
    rnd = b.rnd
    b.material("folhas", image=leaf_tex, cutout=True)
    b.material("peciolo", _col("#6e8a52"))
    top = UP * 0.0
    if trunk_h:
        b.material("estipe", _col(bark))
        th = H * trunk_h
        b.tube("estipe", [UP * 0, UP * th], [C * 0.05, C * 0.04], 9)
        top = UP * th
    Ltot = (H - (H * trunk_h if trunk_h else 0))
    for k in range(leaves):
        if plane:  # leque vertical
            ang = math.radians(-75 + 150 * k / max(leaves - 1, 1) + rnd.uniform(-4, 4))
            d = np.array([math.sin(ang), rnd.uniform(-0.05, 0.05), math.cos(ang)])
            side = np.array([math.cos(ang), 0, -math.sin(ang)])
            side = _unit(np.cross(d, [0, 1, 0]))
        else:
            az = rnd.uniform(0, 2 * math.pi)
            tilt = math.radians(rnd.uniform(8, 35))
            d = np.array([math.cos(az) * math.sin(tilt), math.sin(az) * math.sin(tilt), math.cos(tilt)])
            side = _unit(np.cross(d, UP))
        Lp = Ltot * petiole * rnd.uniform(0.85, 1.05)
        p_end = top + d * Lp
        b.tube("peciolo", [top, p_end], [C * 0.012, C * 0.009], 5)
        Ll = Ltot * (1 - petiole) * rnd.uniform(0.9, 1.1)
        bend = UP * -0.15 if plane else UP * 0
        spine = [p_end + (d + bend * t) * Ll * t for t in np.linspace(0, 1, 5)]
        b.blade("folhas", spine, side, Ll * leaf_w, fold=0.15)
    if flower_tex is not None and flowers:
        b.material("flores", image=flower_tex, cutout=True)
        for k in range(flowers):
            az = rnd.uniform(0, 2 * math.pi)
            d = np.array([math.cos(az), math.sin(az), 0])
            topf = d * C * 0.12 + UP * H * rnd.uniform(0.62, 0.75)
            b.tube("peciolo", [d * C * 0.03, topf], [C * 0.01, C * 0.008], 5)
            b.quad("flores", topf + d * C * 0.08, d * C * 0.18, UP * C * 0.18)
    b.fit(C, H)


def monstera(b: Builder, H, C, leaf_tex, *, leaves=14):
    rnd = b.rnd
    b.material("folhas", image=leaf_tex, cutout=True)
    b.material("peciolo", _col("#4f7a3c"))
    for k in range(leaves):
        az = k * 2.39996
        d = np.array([math.cos(az), math.sin(az), 0])
        el = math.radians(rnd.uniform(45, 75))
        Lp = H * rnd.uniform(0.45, 0.8)
        pts = [(d * math.cos(el) * t + UP * (math.sin(el) * t - 0.15 * t * t)) * Lp for t in np.linspace(0, 1, 5)]
        b.tube("peciolo", pts, C * 0.012, 5)
        tip = pts[-1]
        size = C * rnd.uniform(0.18, 0.26)
        lean = _unit(d * 1.0 + UP * rnd.uniform(-0.4, 0.2))  # lâmina quase horizontal, para fora
        side = _unit(np.cross(lean, UP))
        spine = [tip + lean * size * 2 * t + UP * (-0.25 * size * t * t) for t in np.linspace(0, 1, 4)]
        b.blade("folhas", spine, side, size, fold=-0.1)
    b.fit(C, H)


def ponytail(b: Builder, H, C, blade_tex):
    """Pata-de-elefante: base dilatada, tronco e tufos de folhas pendentes."""
    rnd = b.rnd
    b.material("tronco", _col("#8c7b66"))
    b.material("folhas", image=blade_tex, cutout=True)
    prof = [(0, 0.22), (0.05, 0.24), (0.12, 0.2), (0.22, 0.1), (0.4, 0.06), (0.7, 0.05)]
    b.tube("tronco", [UP * H * z for z, _ in prof], [C * r for _, r in prof], 12)
    tops = [UP * H * 0.7]
    for k in range(2):
        a = rnd.uniform(0, 2 * math.pi) + k * math.pi
        t = UP * H * rnd.uniform(0.72, 0.8) + np.array([math.cos(a), math.sin(a), 0]) * C * 0.15
        b.tube("tronco", [UP * H * 0.6, t], [C * 0.035, C * 0.025], 7)
        tops.append(t)
    for top in tops:
        for k in range(26):
            az = rnd.uniform(0, 2 * math.pi)
            d = np.array([math.cos(az), math.sin(az), 0])
            el = math.radians(rnd.uniform(20, 70))
            L = C * rnd.uniform(0.35, 0.5)
            spine = [top + (d * math.cos(el) * t + UP * (math.sin(el) * t - 1.3 * t * t)) * L
                     for t in np.linspace(0, 1, 7)]
            b.blade("folhas", spine, np.array([-math.sin(az), math.cos(az), 0]), L * 0.03, fold=0.2)
    b.fit(C, H)


def cane_orchid(b: Builder, H, C, leaf_tex, flower_tex, *, stems=9):
    """Orquídea de haste (crucifixo/Epidendrum): hastes com folhinhas e buquê no alto."""
    rnd = b.rnd
    b.material("haste", _col("#5f7f45"))
    b.material("folhas", image=leaf_tex, cutout=True)
    b.material("flores", image=flower_tex, cutout=True)
    for k in range(stems):
        az = rnd.uniform(0, 2 * math.pi)
        d = np.array([math.cos(az), math.sin(az), 0])
        top = d * C * rnd.uniform(0.1, 0.35) + UP * H * rnd.uniform(0.75, 1.0)
        b.tube("haste", [d * C * 0.03, top], [C * 0.008, C * 0.006], 5)
        for j in range(4):
            p = top * (0.25 + 0.15 * j)
            b.card("folhas", p, _unit(d + UP * 0.3 + np.array([rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), 0])),
                   C * 0.09)
        b.card("flores", top, _unit(d * 0.5 + UP), C * 0.12)
    b.fit(C, H)


def moth_orchid(b: Builder, H, C, leaf_tex, flower_tex, *, spikes=3):
    """Orquídea-borboleta: folhas largas na base e hastes arqueadas com flores."""
    rnd = b.rnd
    b.material("folhas", image=leaf_tex, cutout=True)
    b.material("haste", _col("#55703f"))
    b.material("flores", image=flower_tex, cutout=True)
    for k in range(6):
        az = k * 2.39996
        d = np.array([math.cos(az), math.sin(az), 0])
        L = C * 0.42
        spine = [(d * t + UP * (0.55 * t - 0.4 * t * t)) * L + UP * H * 0.04 for t in np.linspace(0, 1, 5)]
        b.blade("folhas", spine, np.array([-math.sin(az), math.cos(az), 0]), L * 0.26, fold=0.2)
    for k in range(spikes):
        az = rnd.uniform(0, 2 * math.pi)
        d = np.array([math.cos(az), math.sin(az), 0])
        pts = [UP * H * 0.08 + (d * 0.55 * t * t + UP * (t - 0.25 * t ** 3)) * H * 0.9 for t in np.linspace(0, 1, 7)]
        b.tube("haste", pts, C * 0.006, 5)
        for j in range(4, 7):
            b.card("flores", pts[j] + d * C * 0.02, _unit(d + UP * 0.2), C * 0.12, spin=0.0)
    b.fit(C, H)


# --- espécies ----------------------------------------------------------------------------

def _tex_tree(leaf, kind="oval", flower=None, frac=0.0, fkind="star", n=85, leaf_len=0.1, fsize=0.06, seed=1):
    return foliage_texture(rgb(leaf), kind, n, leaf_len, rgb(flower) if flower else None, frac, fkind, fsize,
                           seed=seed)


def _gen_tree(leaf, kind="oval", flower=None, frac=0.0, fkind="star", n=85, leaf_len=0.1, fsize=0.06, **kw):
    def f(b, H, C):
        tree(b, H, C, _tex_tree(leaf, kind, flower, frac, fkind, n, leaf_len, fsize, seed=b.rnd.randrange(999)),
             **kw)
    return f


def _gen_shrub(leaf, kind="oval", flower=None, frac=0.0, fkind="star", n=95, leaf_len=0.09, fsize=0.06, **kw):
    def f(b, H, C):
        shrub(b, H, C, _tex_tree(leaf, kind, flower, frac, fkind, n, leaf_len, fsize, seed=b.rnd.randrange(999)),
              **kw)
    return f


def _gen_palm(leaf, kind="pinnate", plume=False, **kw):
    def f(b, H, C):
        tex = (blade_texture(rgb(leaf), "strap", seed=b.rnd.randrange(999)) if kind == "fan"
               else pinnate_texture(rgb(leaf), plume, seed=b.rnd.randrange(999)))
        palm(b, H, C, tex, kind=kind, **kw)
    return f


def _gen_rosette(leaf, edge=None, center=None, kind="strap", **kw):
    stex = kw.pop("spike_tex", None)

    def f(b, H, C):
        ctex = blade_texture(rgb(center), "strap") if center else None
        rosette(b, H, C, blade_texture(rgb(leaf), kind, rgb(edge) if edge else None), center_tex=ctex,
                spike_tex=flower_card_texture(*stex) if stex else None, **kw)
    return f


def _gen_clump(leaf, kind="grass", flower=None, fkind="umbel", ftex="umbel", **kw):
    def f(b, H, C):
        ft = flower_card_texture(ftex, rgb(flower)) if flower else None
        clump(b, H, C, blade_texture(rgb(leaf), kind), flower_tex=ft, flower_kind=fkind, **kw)
    return f


def _gen_mound(leaf, kind="small", flower=None, frac=0.0, n=120, leaf_len=0.05, **kw):
    def f(b, H, C):
        mound(b, H, C, foliage_texture(rgb(leaf), kind, n, leaf_len, rgb(flower) if flower else None, frac,
                                       "star", 0.035), **kw)
    return f


def _ravenala(b, H, C):
    paddle_plant(b, H, C, broad_leaf_texture(rgb("#4d8a4a"), "paddle"), leaves=16, plane=True, trunk_h=0.42,
                 petiole=0.45, leaf_w=0.17)


def _strelitzia(b, H, C):
    paddle_plant(b, H, C, broad_leaf_texture(rgb("#4f7d58"), "paddle"), leaves=14, petiole=0.5, leaf_w=0.24,
                 flower_tex=flower_card_texture("bird", rgb("#f08a1c")), flowers=5)


def _monstera(b, H, C):
    monstera(b, H, C, broad_leaf_texture(rgb("#2f6e35"), "monstera"))


def _ponytail(b, H, C):
    ponytail(b, H, C, blade_texture(rgb("#6f9448"), "grass"))


def _lavender(b, H, C):
    clump(b, H, C, blade_texture(rgb("#8fa58a"), "grass"), blades=70, width=0.025, leaf_h=0.55, arch=0.5,
          flower_tex=flower_card_texture("spike", rgb("#8a6cc8")), flower_kind="spike", stalks=28,
          stalk_col="#8fa080", flower_size=0.07)


def _epidendrum(b, H, C):
    cane_orchid(b, H, C, foliage_texture(rgb("#4f8a3c"), "oval", 20, 0.2), flower_card_texture("cluster",
                                                                                                rgb("#c43c9a")))


def _phalaenopsis(b, H, C):
    moth_orchid(b, H, C, broad_leaf_texture(rgb("#3f7a3a"), "oval"), flower_card_texture("orchid", rgb("#f4f2f4")))


SPECIES = {
    # árvores (copas floridas: poucas folhas e cachos de flores espaçados, para a copa ficar vazada)
    "handroanthus-albus": _gen_tree("#7a9a48", "oval", "#f0c419", 1.6, "trumpet", n=22, fsize=0.045,
                                    trunk_h=0.38, top_bias=0.3, bark="#5f4a38"),
    "handroanthus-impetiginosus": _gen_tree("#7a9a48", "oval", "#c45bb8", 1.6, "trumpet", n=22, fsize=0.045,
                                            trunk_h=0.4, top_bias=0.3, bark="#5f4a38"),
    "jacaranda-cuspidifolia": _gen_tree("#5f8f3f", "small", "#7b6fd8", 0.45, "trumpet", n=110, leaf_len=0.045,
                                        fsize=0.04, trunk_h=0.4, top_bias=0.4, flat=0.8),
    "prunus-serrulata": _gen_tree("#6b8f45", "oval", "#f4b3cc", 1.5, "star", n=24, fsize=0.04, trunk_h=0.3,
                                  flat=0.85, top_bias=0.2),
    "pleroma-granulosum": _gen_tree("#4f7f3a", "oval", "#8a4fc8", 0.45, "big", n=50, fsize=0.045, trunk_h=0.3),
    "bauhinia-forficata": _gen_tree("#78a855", "bilobed", "#f4f1e8", 0.2, "star", n=52, fsize=0.045,
                                    trunk_h=0.35, flat=0.75, top_bias=0.3),
    "paubrasilia-echinata": _gen_tree("#3f8a3a", "small", "#f0c020", 0.08, "cluster", n=230, leaf_len=0.045,
                                      fsize=0.035, trunk_h=0.4, bark="#4f3a2c"),
    "plinia-cauliflora": _gen_tree("#2f6b33", "small", "#2a1830", 0.1, "fruit", n=230, leaf_len=0.045,
                                   fsize=0.03, trunk_h=0.3, stems=4, bark="#a08870", density=3.4),
    "citrus-limon": _gen_tree("#3f7f34", "oval", "#e8d830", 0.1, "fruit", n=75, fsize=0.04, trunk_h=0.22,
                              density=3.4),
    "malus-domestica": _gen_tree("#5f9440", "oval", "#c8302a", 0.1, "fruit", n=70, fsize=0.04, trunk_h=0.3),
    "eugenia-uniflora": _gen_tree("#3f7a37", "small", "#d0281e", 0.08, "fruit", n=230, leaf_len=0.045,
                                  fsize=0.028, trunk_h=0.25, stems=2, density=3.4),
    # palmeiras
    "syagrus-romanzoffiana": _gen_palm("#5f9a45", fronds=16, trunk_r=0.17, bark="#8c8478", droop=0.7),
    "dypsis-lutescens": _gen_palm("#9cc65a", stems=7, fronds=14, trunk_r=0.05, bark="#b0b060", droop=0.5,
                                  rise=(70, 10)),
    "roystonea-oleracea": _gen_palm("#5f9445", fronds=18, trunk_r=0.3, bark="#b8b4aa", shaft="#6f9a4a",
                                    droop=0.6),
    "cocos-nucifera": _gen_palm("#7aa042", fronds=22, trunk_r=0.18, bark="#8a7a66", lean=0.18, droop=0.8,
                                rise=(45, -35)),
    "mauritia-flexuosa": _gen_palm("#5f8f3a", "fan", fronds=16, trunk_r=0.28, bark="#8a8478", droop=0.4,
                                   petiole=0.4, fan_leaf=0.45),
    "wodyetia-bifurcata": _gen_palm("#4f8f42", plume=True, fronds=10, trunk_r=0.16, bark="#a8a49a",
                                    shaft="#7ea85a", frond_w=0.3, fold=0.1, droop=0.5),
    "livistona-chinensis": _gen_palm("#5c9447", "fan", fronds=18, trunk_r=0.13, bark="#7a7468", droop=0.9,
                                     petiole=0.5, fan_leaf=0.42),
    "pritchardia-pacifica": _gen_palm("#6aa64a", "fan", fronds=16, trunk_r=0.14, bark="#8a8478", droop=0.3,
                                      petiole=0.4, fan_leaf=0.48),
    "ravenala-madagascariensis": _ravenala,
    "beaucarnea-recurvata": _ponytail,
    # arbustos
    "buxus-sempervirens": _gen_shrub("#3d7a3b", "small", n=260, leaf_len=0.04, density=4.2, card=0.45, stems=3),
    "camellia-japonica": _gen_shrub("#2f5f30", "oval", "#d0414f", 0.2, "big", fsize=0.08,
                                    upright=True),
    "clusia-fluminensis": _gen_shrub("#4c8a48", "round", n=55, leaf_len=0.12, upright=True),
    "hibiscus-rosa-sinensis": _gen_shrub("#3f7a36", "oval", "#d8302e", 0.18, "big", fsize=0.09,
                                         upright=True),
    "ixora-coccinea": _gen_shrub("#2f6a33", "narrow", "#e04a3a", 0.35, "cluster", fsize=0.07),
    "pleroma-mutabile": _gen_tree("#4a7a3c", "oval", "#c27bd1", 0.55, "big", fsize=0.06, trunk_h=0.25,
                                  stems=3),
    "furcraea-foetida": _gen_rosette("#8fbc62", edge="#e8e070", kind="sword", blades=34, width=0.07,
                                     rise=(70, 8), droop=0.15),
    # herbáceas
    "agapanthus-africanus": _gen_clump("#4f8a3c", "strap", "#6f8fe0", blades=30, width=0.05, leaf_h=0.55,
                                       stalks=5, flower_size=0.2),
    "strelitzia-reginae": _strelitzia,
    "guzmania-lingulata": _gen_rosette("#3f8a3a", center="#d8362e", blades=22, width=0.1, center_blades=10),
    "alcantarea-imperialis": _gen_rosette("#6a8a4a", edge="#8a4a6a", blades=30, width=0.13, rise=(70, 12),
                                          spike="#8a6a40", spike_h=1.0, spike_tex=("cluster", rgb("#e8d870"))),
    "monstera-deliciosa": _monstera,
    "lavandula-angustifolia": _lavender,
    "dietes-bicolor": _gen_clump("#5f8a48", "grass", "#f2e070", "flat", "iris", blades=34, width=0.04,
                                 leaf_h=0.85, arch=0.3, stalks=6, flower_size=0.11),
    "dietes-iridioides": _gen_clump("#4f7f44", "grass", "#f4f4f4", "flat", "iris", blades=34, width=0.04,
                                    leaf_h=0.85, arch=0.3, stalks=6, flower_size=0.11),
    "orchidaceae-arbustiva": _epidendrum,
    "orchidaceae-branca": _phalaenopsis,
    # forrações
    "evolvulus-glomeratus": _gen_mound("#7a9a8a", "small", "#4f74e0", 0.3),
    "ophiopogon-japonicus": _gen_clump("#24442a", "grass", blades=60, width=0.06, leaf_h=1.0, arch=0.9,
                                       spread=0.6),
    "liriope-muscari": _gen_clump("#3f6a40", "grass", "#9a7ad8", "spike", "spike", blades=50, width=0.05,
                                  leaf_h=0.8, arch=0.8, stalks=8, flower_size=0.12, spread=0.4),
}


def generate(sid: str, height: float, copa: float, out_dir: Path = OUT_DIR, seed: int | None = None) -> Path:
    b = Builder(seed if seed is not None else sum(map(ord, sid)))
    SPECIES[sid](b, height, copa)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{sid}.glb"
    write_glb(path, b.parts())
    return path


def _notice(out_dir: Path):
    (out_dir / "LEAFDRAW.md").write_text(
        "# Modelos gerados pelo LeafDraw\n\n"
        "Gerados por código (`python -m leafdraw.modelgen`) a partir dos parâmetros de cada espécie.\n"
        "Domínio público (CC0 1.0): uso livre, inclusive comercial, sem obrigação de crédito.\n",
        encoding="utf-8")


def main(argv=None) -> int:
    from leafdraw.core.catalog import default_catalog

    ap = argparse.ArgumentParser(prog="python -m leafdraw.modelgen", description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*", help="ids das espécies (padrão: todas com gerador)")
    ap.add_argument("-o", "--saida", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (QPainter pede o app)
    cat = default_catalog()
    failed = 0
    for sid in args.ids or sorted(SPECIES):
        sp = cat.get(sid)
        if sp is None or sid not in SPECIES:
            print(f"{sid}: sem espécie no catálogo ou sem gerador")
            failed += 1
            continue
        path = generate(sid, sp.altura, sp.copa, args.saida)
        print(f"{sid}: {path.stat().st_size / 1024:.0f} KB", flush=True)
    _notice(args.saida)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
