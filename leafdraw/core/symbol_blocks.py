"""Blocos DXF/DWG como desenho próprio de uma espécie (versão Planta ou Vista).

O bloco é achatado em polilinhas e normalizado (ver ``catalog.Drawing``), então a
unidade do arquivo não importa: o desenho é ajustado à copa e à altura da planta.
"""
from __future__ import annotations

import math

from ezdxf import disassemble

from leafdraw.core.catalog import Drawing

MODEL_SPACE = "*Model_Space"
SKIP_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION", "POINT", "IMAGE", "WIPEOUT", "VIEWPORT"}
MAX_POINTS = 8000


def list_blocks(drawing) -> list[str]:
    """Blocos com geometria (sem os anônimos e os de layout)."""
    names = []
    for blk in drawing.blocks:
        name = blk.name
        if name.startswith("*") or blk.is_any_layout:
            continue
        if any(e.dxftype() not in SKIP_TYPES for e in blk):
            names.append(name)
    return sorted(names, key=str.lower)


def block_drawing(drawing, block_name: str, kind: str) -> Drawing:
    """Converte o bloco (ou ``MODEL_SPACE``) em desenho normalizado. ``kind``: "planta" | "vista"."""
    source = drawing.modelspace() if block_name == MODEL_SPACE else drawing.blocks.get(block_name)
    if source is None:
        raise ValueError(f"Bloco {block_name!r} não encontrado.")
    ents = [e for e in disassemble.recursive_decompose(source) if e.dxftype() not in SKIP_TYPES]
    paths = []
    for path in disassemble.to_paths(disassemble.to_primitives(ents)):
        paths += list(path.sub_paths()) if path.has_sub_paths else [path]
    verts = [v for p in paths for v in p.control_vertices()]
    if not verts:
        raise ValueError("O bloco não tem linhas que possam ser usadas como símbolo.")
    xs, ys = [v.x for v in verts], [v.y for v in verts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    size = max(w, h)
    if size <= 1e-12 or (kind == "vista" and (w <= size * 1e-3 or h <= size * 1e-3)):
        raise ValueError("O bloco não tem largura e altura.")
    if kind == "planta":
        cx, cy, s = (x0 + x1) / 2, (y0 + y1) / 2, size / 2

        def norm(x, y):
            return ((x - cx) / s, (y - cy) / s)
    else:
        cx = (x0 + x1) / 2

        def norm(x, y):
            return ((x - cx) / w, (y - y0) / h)

    out, total = [], 0
    for p in paths:
        pts = [(v.x, v.y) for v in p.flattening(distance=size * 2e-3, segments=8)]
        closed = p.is_closed or (len(pts) > 2 and math.dist(pts[0], pts[-1]) < size * 1e-6)
        if closed and len(pts) > 2 and math.dist(pts[0], pts[-1]) < size * 1e-6:
            pts = pts[:-1]
        clean = []
        for x, y in pts:
            q = tuple(round(c, 4) for c in norm(x, y))
            if not clean or q != clean[-1]:
                clean.append(q)
        if len(clean) < 2:
            continue
        total += len(clean)
        if total > MAX_POINTS:
            raise ValueError("Bloco muito detalhado para símbolo (limite de 8.000 vértices).")
        out.append((closed and len(clean) >= 3, tuple(clean)))
    if not out:
        raise ValueError("O bloco não tem linhas que possam ser usadas como símbolo.")
    return tuple(out)
