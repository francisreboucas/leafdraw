import numpy as np

from leafdraw.core.gltf import Material, Model, Primitive
from leafdraw.core.meshlod import components, position_ids, simplify_model


def _prim(pos, tri):
    pos = np.asarray(pos, "f4")
    nrm = np.tile(np.array([0, 0, 1], "f4"), (len(pos), 1))
    return Primitive(pos, nrm, np.zeros((len(pos), 2), "f4"), np.asarray(tri, "u4").reshape(-1), Material())


def _leaf(cx, cy, cz, n=6, r=0.15):
    """Folha em leque com ``n`` triângulos, centrada em (cx, cy, cz)."""
    pos = [(cx, cy, cz)] + [(cx + r * np.cos(a), cy + r * np.sin(a), cz + 0.02 * np.sin(3 * a))
                            for a in np.linspace(0, 2 * np.pi, n + 1)[:-1]]
    tri = [(0, 1 + i, 1 + (i + 1) % n) for i in range(n)]
    return pos, tri


def _tree(leaves=400, seed=0):
    rnd = np.random.default_rng(seed)
    pos, tri = [], []
    # tronco: cilindro fino e denso (uma peça grande)
    for i in range(41):
        for j in range(12):
            a = 2 * np.pi * j / 12
            pos.append((0.1 * np.cos(a), 0.1 * np.sin(a), 4 * i / 40))
    for i in range(40):
        for j in range(12):
            a, b, c, d = i * 12 + j, i * 12 + (j + 1) % 12, (i + 1) * 12 + j, (i + 1) * 12 + (j + 1) % 12
            tri += [(a, b, d), (a, d, c)]
    for _ in range(leaves):
        c = rnd.normal(0, 1, 3) * (1.2, 1.2, 0.8) + (0, 0, 4)
        lp, lt = _leaf(*c, n=10)
        base = len(pos)
        pos += lp
        tri += [(base + a, base + b, base + c_) for a, b, c_ in lt]
    return Model([_prim(pos, tri)])


def test_components_find_separate_pieces():
    p1, t1 = _leaf(0, 0, 0)
    p2, t2 = _leaf(5, 0, 0)
    tri = np.array(t1 + [(a + len(p1), b + len(p1), c + len(p1)) for a, b, c in t2])
    pid = position_ids(np.array(p1 + p2))
    lab = components(pid[tri], pid.max() + 1)
    assert len(np.unique(lab[pid[tri[:, 0]]])) == 2


def test_simplify_hits_budget_and_keeps_shape():
    m = _tree()
    light = simplify_model(m, 1500)
    assert 1000 < light.triangles <= 1500 * 1.05
    a = np.concatenate([p.positions for p in m.primitives])
    b = np.concatenate([p.positions for p in light.primitives])
    span = a.max(0) - a.min(0)
    assert np.all(np.abs(a.max(0) - b.max(0)) < 0.25 * span)
    assert np.all(np.abs(a.min(0) - b.min(0)) < 0.25 * span)
    # o tronco continua lá: há triângulos perto do eixo, embaixo da copa
    low = b[b[:, 2] < 1.5]
    assert len(low) and np.abs(low[:, :2]).max() < 0.3


def test_simplify_is_deterministic_and_noop_when_light():
    m = _tree(100)
    a, b = simplify_model(m, 800), simplify_model(m, 800)
    assert np.array_equal(a.primitives[0].positions, b.primitives[0].positions)
    assert simplify_model(m, 10**6) is m
