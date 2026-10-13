"""Modelos 3D procedurais de plantas (instâncias de malhas unitárias).

Cada instância: (x, y, z, sx, sy, sz, r, g, b, rotação em rad). A variação de
tamanho, cor e rotação vem de um gerador determinístico semeado pelo id da
entidade, então a mesma planta sempre tem a mesma cara.
"""
from __future__ import annotations

import math
import random
import zlib

TRUNK = (0.40, 0.29, 0.20)
HIGHLIGHT = (0.30, 0.64, 1.0)
LIGHT_DIR = (0.45, -0.35, 0.82)  # mesma direção do shader
MESHES = ("cylinder", "sphere", "bush", "palm")
MODEL_PREFIX = "glb:"  # chave das instâncias de um modelo importado: "glb:<caminho>"


def rng_for(eid: str) -> random.Random:
    return random.Random(zlib.crc32(eid.encode()))


def jitter(color, rnd: random.Random, amount: float = 0.09):
    k = 1 + rnd.uniform(-amount, amount)
    return tuple(min(1.0, max(0.0, c * k * (1 + rnd.uniform(-0.03, 0.03)))) for c in color)


def tint(color, selected: bool):
    if not selected:
        return color
    return tuple(c * 0.4 + h * 0.6 for c, h in zip(color, HIGHLIGHT))


def plant_instances(simbolo: str, x: float, y: float, z0: float, canopy: float, height: float, color,
                    eid: str, selected: bool = False, model: str | None = None) -> dict[str, list[tuple]]:
    """Instâncias por malha. Com ``model`` (caminho de um modelo normalizado, ver
    ``core.gltf``), a planta é uma única instância dele; a cor da instância
    multiplica a textura, então só varia levemente em torno do branco."""
    rnd = rng_for(eid)
    s = 1 + rnd.uniform(-0.08, 0.08)
    r = max(canopy / 2 * s, 0.05)
    h = max(height * s, 0.05)
    rot = rnd.uniform(0, 2 * math.pi)
    if model:
        return {MODEL_PREFIX + model: [(x, y, z0, r, r, h, *tint(jitter((0.94, 0.94, 0.94), rnd, 0.06), selected), rot)]}
    trunk = tint(TRUNK, selected)
    out: dict[str, list[tuple]] = {m: [] for m in MESHES}
    if simbolo == "arvore":
        crown_h = min(h * 0.42, r * 0.85)
        zc = z0 + h - crown_h
        tr = max(0.08, r * 0.06)
        out["cylinder"].append((x, y, z0, tr, tr, zc - z0 + crown_h * 0.3, *trunk, 0.0))
        out["bush"].append((x, y, zc, r * 0.78, r * 0.78, crown_h * 0.9, *tint(jitter(color, rnd), selected), rot))
        for k in range(4):
            a = rot + k * math.pi / 2 + rnd.uniform(-0.35, 0.35)
            d = r * 0.4
            lr = r * rnd.uniform(0.46, 0.6)
            lz = zc + crown_h * rnd.uniform(-0.25, 0.2)
            out["bush"].append((x + d * math.cos(a), y + d * math.sin(a), lz, lr, lr,
                                crown_h * rnd.uniform(0.5, 0.65), *tint(jitter(color, rnd), selected), a))
    elif simbolo == "palmeira":
        top = z0 + h * 0.9
        tr = max(0.12, r * 0.05)
        out["cylinder"].append((x, y, z0, tr, tr, top - z0, *trunk, 0.0))
        out["palm"].append((x, y, top, r, r, r * 0.9, *tint(jitter(color, rnd, 0.06), selected), rot))
        base = tint(tuple(c * 0.7 for c in color), selected)
        out["sphere"].append((x, y, top, tr * 1.7, tr * 1.7, tr * 2.6, *base, 0.0))
    else:  # arbusto, forração
        hh = max(h, 0.08) / 2
        out["bush"].append((x, y, z0 + hh * 0.85, r, r, hh, *tint(jitter(color, rnd), selected), rot))
    return out


def shadow_disc(x: float, y: float, z_at, r: float, crown_z: float, lift: float, segments: int = 20,
                strength: float = 0.30) -> list[tuple]:
    """Sombra difusa (triângulos com alfa decrescente), deslocada contra a luz.

    ``z_at(x, y)`` dá a cota do chão em cada vértice, para a sombra seguir o terreno.
    """
    lx, ly, lz = LIGHT_DIR
    ox, oy = -lx / lz * crown_z * 0.6, -ly / lz * crown_z * 0.6
    cx, cy = x + ox, y + oy
    rim = [(cx + r * math.cos(2 * math.pi * i / segments), cy + r * math.sin(2 * math.pi * i / segments))
           for i in range(segments)]
    rim = [(px, py, z_at(px, py) + lift) for px, py in rim]
    center = (cx, cy, z_at(cx, cy) + lift)
    out = []
    for i in range(segments):
        out.append((*center, 0.0, 0.0, 0.0, strength))
        out.append((*rim[i], 0.0, 0.0, 0.0, 0.0))
        out.append((*rim[(i + 1) % segments], 0.0, 0.0, 0.0, 0.0))
    return out
