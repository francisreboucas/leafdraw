"""Versão leve (LOD) de modelos de vegetação — só numpy.

Simplificar vegetação não é como simplificar um objeto contínuo: as copas são
milhares de peças soltas (folhas, pétalas, planos com textura). Um agrupamento
global de vértices transformaria a copa numa massa, então o modelo é dividido em
componentes conectados e tratado assim:

* **peças grandes** (tronco, galhos — maiores que ``BIG_PIECE`` do tamanho do
  modelo): vértices agrupados numa grade do modelo inteiro (vertex clustering);
* **peças pequenas** (folhas, flores): cada peça é simplificada na sua própria
  escala — uma grade de k × k × k células sobre a caixa da peça —, então uma
  folha de 20 triângulos vira uma de 2 a 4 com o mesmo contorno geral;
* se ainda passar da meta, as peças pequenas são *raleadas*: fica uma fração
  delas (sorteio determinístico) e as que ficam crescem em torno do próprio
  centro para a copa manter a cobertura.
"""
from __future__ import annotations

import numpy as np

from leafdraw.core.gltf import Model, Primitive, vertex_normals

BIG_PIECE = 0.15  # fração da diagonal do modelo: peça maior que isto é tronco/galho
TRUNK_SHARE = 0.25  # parte mínima da meta reservada às peças grandes (tronco, galhos)
MAX_GROWTH = 1.6  # aumento máximo de escala das peças que ficam ao ralear
PIECE_GRIDS = (24, 16, 12, 10, 8, 6, 5, 4, 3, 2)  # células por lado, da mais fina para a mais grossa


def position_ids(pos: np.ndarray, tol: float = 1e-5) -> np.ndarray:
    """Id por posição (vértices duplicados por costura de UV/normal ficam com o mesmo id)."""
    q = np.round(pos / tol).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return inv.ravel()


def components(tri: np.ndarray, n: int) -> np.ndarray:
    """Rótulo do componente conectado de cada vértice (union-find vetorizado)."""
    parent = np.arange(n)
    edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]]])
    while True:
        a, b = parent[edges[:, 0]], parent[edges[:, 1]]
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        diff = lo != hi
        if not diff.any():
            break
        np.minimum.at(parent, hi[diff], lo[diff])
        while True:  # salto de ponteiros até cada vértice apontar para a raiz
            nxt = parent[parent]
            if np.array_equal(nxt, parent):
                break
            parent = nxt
    _, lab = np.unique(parent, return_inverse=True)
    return lab.ravel()


def _subset(prim: Primitive, tri_mask: np.ndarray) -> Primitive:
    tri = prim.indices.reshape(-1, 3)[tri_mask]
    used, inv = np.unique(tri, return_inverse=True)
    return Primitive(prim.positions[used], prim.normals[used], prim.uvs[used],
                     inv.reshape(-1).astype("u4"), prim.material)


def _vertex_piece(prim: Primitive, piece_of_tri: np.ndarray) -> np.ndarray:
    vp = np.zeros(len(prim.positions), np.int64)
    vp[prim.indices] = np.repeat(piece_of_tri, 3)
    return vp


def _collapse_keys(prim: Primitive, key: np.ndarray):
    """Triângulos que sobram ao fundir os vértices de mesma chave: (ids de célula, máscara, ordem)."""
    _, cid = np.unique(key, axis=0, return_inverse=True)
    cid = cid.ravel()
    t = cid[prim.indices.reshape(-1, 3)]
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    first = np.unique(np.sort(t[ok], axis=1), axis=0, return_index=True)[1]  # sem triângulos repetidos
    return cid, ok, np.sort(first)


def _collapse(prim: Primitive, cid: np.ndarray, ok: np.ndarray, first: np.ndarray,
              piece_of_tri: np.ndarray | None = None):
    """Funde os vértices de cada célula no centro deles. Devolve a primitiva (e as peças por triângulo)."""
    pos = prim.positions.astype(float)
    tri_sel = np.flatnonzero(ok)[first]
    tri = cid[prim.indices.reshape(-1, 3)][tri_sel]
    n = cid.max() + 1
    cnt = np.maximum(np.bincount(cid, minlength=n), 1).astype(float)
    rep = np.stack([np.bincount(cid, pos[:, k], minlength=n) / cnt for k in range(3)], axis=1)
    # UV do vértice original mais perto do centro (média de UVs cruzaria costuras de textura)
    d = np.linalg.norm(pos - rep[cid], axis=1)
    order = np.lexsort((d, cid))
    cells, at = np.unique(cid[order], return_index=True)
    nearest = np.zeros(n, np.int64)
    nearest[cells] = order[at]
    used, inv = np.unique(tri, return_inverse=True)
    tri = inv.reshape(-1, 3)
    p = rep[used]
    nrm = vertex_normals(p, tri.reshape(-1))
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    out = Primitive(p.astype("f4"), nrm.astype("f4"), prim.uvs[nearest[used]].astype("f4"),
                    tri.reshape(-1).astype("u4"), prim.material)
    return out, (None if piece_of_tri is None else piece_of_tri[tri_sel])


def cluster(prim: Primitive, target_tris: int) -> Primitive:
    """Agrupa vértices numa grade do objeto todo até ficar perto de ``target_tris`` triângulos."""
    if len(prim.indices) // 3 <= target_tris:
        return prim
    pos = prim.positions.astype(float)
    lo = pos.min(0)
    span = max(float((pos.max(0) - lo).max()), 1e-9)
    lo_c, hi_c, best = 2, 1024, None
    while lo_c <= hi_c:  # busca binária nas células por lado
        mid = (lo_c + hi_c) // 2
        res = _collapse_keys(prim, np.floor((pos - lo) / (span / mid)).astype(np.int64))
        if len(res[2]) <= target_tris:
            best, lo_c = res, mid + 1
        else:
            hi_c = mid - 1
    if best is None:
        best = _collapse_keys(prim, np.floor((pos - lo) / (span / 2)).astype(np.int64))
    return _collapse(prim, *best)[0]


def simplify_pieces(prim: Primitive, piece_of_tri: np.ndarray, target_tris: int):
    """Simplifica cada peça na própria escala, com a grade mais fina que cabe na meta.

    Peça que sumiria na grade (folha que vira linha) fica como estava: decidir quais
    folhas saem é papel do raleamento, que compensa o tamanho das que ficam.
    Devolve (primitiva, peça de cada triângulo)."""
    if len(prim.indices) // 3 <= target_tris:
        return prim, piece_of_tri
    pos = prim.positions.astype(float)
    vp = _vertex_piece(prim, piece_of_tri)
    n = piece_of_tri.max() + 1
    lo = np.full((n, 3), np.inf)
    hi = np.full((n, 3), -np.inf)
    np.minimum.at(lo, vp, pos)
    np.maximum.at(hi, vp, pos)
    span = np.maximum((hi - lo).max(axis=1), 1e-9)
    rel = (pos - lo[vp]) / span[vp, None]
    tris_of = np.bincount(piece_of_tri, minlength=n)
    best = None
    for k in PIECE_GRIDS:
        cell = np.minimum(np.floor(rel * k), k - 1).astype(np.int64)
        res = _collapse_keys(prim, np.column_stack([vp, cell]))
        after = np.bincount(piece_of_tri[np.flatnonzero(res[1])[res[2]]], minlength=n)
        survived = after > 0
        after = np.where(survived, after, tris_of)  # peça que sumiria fica como estava
        if best is None or after.sum() < best[0].sum():
            best = (after, k)
        if after.sum() <= target_tris:
            break
    after, k = best
    # simplifica só o necessário, começando pelas peças que mais economizam
    saving = tris_of - after
    order = np.argsort(-saving, kind="stable")
    need = len(prim.indices) // 3 - target_tris
    take = int(np.searchsorted(np.cumsum(saving[order]), need)) + 1
    survived = np.zeros(n, bool)
    survived[order[:take]] = saving[order[:take]] > 0
    keep_mask = ~survived[piece_of_tri]
    parts, pieces = [], []
    if (~keep_mask).any():
        sub = _subset(prim, ~keep_mask)
        sp = piece_of_tri[~keep_mask]
        svp = _vertex_piece(sub, sp)
        srel = (sub.positions.astype(float) - lo[svp]) / span[svp, None]
        cell = np.minimum(np.floor(srel * k), k - 1).astype(np.int64)
        out, op = _collapse(sub, *_collapse_keys(sub, np.column_stack([svp, cell])), sp)
        parts.append(out)
        pieces.append(op)
    if keep_mask.any():
        parts.append(_subset(prim, keep_mask))
        pieces.append(piece_of_tri[keep_mask])
    return _merge(parts), np.concatenate(pieces)


def thin_pieces(prim: Primitive, piece_of_tri: np.ndarray, keep: float, seed: int = 1) -> Primitive:
    """Mantém ``keep`` (0–1) das peças e aumenta as que ficaram para cobrir quase o mesmo."""
    _, piece = np.unique(piece_of_tri, return_inverse=True)
    piece = piece.ravel()
    n = piece.max() + 1
    rnd = np.random.default_rng(seed)
    chosen = rnd.random(n) < keep
    if not chosen.any():
        chosen[rnd.integers(n)] = True
    mask = chosen[piece]
    out = _subset(prim, mask)
    growth = min(MAX_GROWTH, 1 / np.sqrt(max(keep, 1e-6)))
    if growth > 1.0001:
        vp = _vertex_piece(out, piece[mask])
        _, vp = np.unique(vp, return_inverse=True)
        vp = vp.ravel()
        cnt = np.bincount(vp).astype(float)
        center = np.stack([np.bincount(vp, out.positions[:, k]) / cnt for k in range(3)], axis=1)
        pos = center[vp] + (out.positions - center[vp]) * growth
        out = Primitive(pos.astype("f4"), out.normals, out.uvs, out.indices, out.material)
    return out


def _merge(parts: list[Primitive]) -> Primitive | None:
    parts = [p for p in parts if len(p.indices)]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    off = np.cumsum([0] + [len(p.positions) for p in parts[:-1]])
    return Primitive(np.concatenate([p.positions for p in parts]), np.concatenate([p.normals for p in parts]),
                     np.concatenate([p.uvs for p in parts]),
                     np.concatenate([p.indices + o for p, o in zip(parts, off)]).astype("u4"), parts[0].material)


def simplify_primitive(prim: Primitive, ratio: float, model_diag: float, seed: int = 1) -> Primitive | None:
    """Versão com cerca de ``ratio`` (0–1) dos triângulos."""
    tri = prim.indices.reshape(-1, 3)
    if len(tri) == 0 or ratio >= 1:
        return prim
    pid = position_ids(prim.positions)
    lab = components(pid[tri], pid.max() + 1)
    tri_lab = lab[pid[tri[:, 0]]]
    # tamanho de cada peça (diagonal da caixa)
    n = tri_lab.max() + 1
    p0 = prim.positions[tri[:, 0]].astype(float)
    lo = np.full((n, 3), np.inf)
    hi = np.full((n, 3), -np.inf)
    np.minimum.at(lo, tri_lab, p0)
    np.maximum.at(hi, tri_lab, p0)
    big_piece = np.linalg.norm(hi - lo, axis=1) > BIG_PIECE * model_diag
    big = big_piece[tri_lab]
    goal = max(int(len(tri) * ratio), 2)
    parts = []
    if big.any():
        # tronco e galhos são poucos triângulos e mostram muito o corte: reservam parte da meta
        b = _subset(prim, big)
        nb = len(b.indices) // 3
        b = cluster(b, max(min(nb, max(int(nb * ratio), int(goal * TRUNK_SHARE))), 12))
        parts.append(b)
        goal = max(goal - len(b.indices) // 3, 2)
    if (~big).any():
        s = _subset(prim, ~big)
        target = goal
        s, piece = simplify_pieces(s, tri_lab[~big], target)
        have = len(s.indices) // 3
        if have > target * 1.05:
            s = thin_pieces(s, piece, target / have, seed)
        parts.append(s)
    return _merge(parts)


def simplify_model(model: Model, max_tris: int, seed: int = 1) -> Model:
    """Modelo com cerca de ``max_tris`` triângulos ou menos (o que já é leve fica igual)."""
    ratio = min(1.0, max_tris / max(model.triangles, 1))
    if ratio >= 1:
        return model
    allp = np.concatenate([p.positions for p in model.primitives]).astype(float)
    diag = float(np.linalg.norm(allp.max(0) - allp.min(0)))
    prims = [simplify_primitive(p, ratio, diag, seed + i) for i, p in enumerate(model.primitives)]
    return Model([p for p in prims if p is not None], model.size)
