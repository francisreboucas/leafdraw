"""Matrizes 4x4 (numpy, convenção de linha; transpor ao enviar ao GLSL) e malhas."""
from __future__ import annotations

import math

import numpy as np


def normalize(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def orthographic(left, right, bottom, top, near, far) -> np.ndarray:
    m = np.identity(4)
    m[0, 0] = 2 / (right - left)
    m[1, 1] = 2 / (top - bottom)
    m[2, 2] = -2 / (far - near)
    m[0, 3] = -(right + left) / (right - left)
    m[1, 3] = -(top + bottom) / (top - bottom)
    m[2, 3] = -(far + near) / (far - near)
    return m


def look_at(eye, target, up) -> np.ndarray:
    f = normalize(np.asarray(target, float) - eye)
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.identity(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def gl_bytes(m: np.ndarray) -> bytes:
    """Matriz em ordem de coluna (column-major), como o GLSL espera."""
    return np.ascontiguousarray(m.T, dtype="f4").tobytes()


def uv_sphere(stacks: int = 10, slices: int = 16):
    """Esfera unitária. Retorna (vértices Nx6 [pos, normal], índices)."""
    verts = []
    for i in range(stacks + 1):
        phi = math.pi * i / stacks
        for j in range(slices + 1):
            th = 2 * math.pi * j / slices
            x, y, z = math.sin(phi) * math.cos(th), math.sin(phi) * math.sin(th), math.cos(phi)
            verts.append((x, y, z, x, y, z))
    idx = []
    row = slices + 1
    for i in range(stacks):
        for j in range(slices):
            a = i * row + j
            b = a + row
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return np.array(verts, "f4"), np.array(idx, "u4")


def cylinder(slices: int = 12):
    """Cilindro de raio 1, de z=0 a z=1, sem tampas."""
    verts = []
    for j in range(slices + 1):
        th = 2 * math.pi * j / slices
        x, y = math.cos(th), math.sin(th)
        verts.append((x, y, 0, x, y, 0))
        verts.append((x, y, 1, x, y, 0))
    idx = []
    for j in range(slices):
        a = 2 * j
        idx += [a, a + 2, a + 1, a + 1, a + 2, a + 3]
    return np.array(verts, "f4"), np.array(idx, "u4")


def quad():
    """Quadrado unitário em z=0, de -1 a 1, normal +Z."""
    verts = [(-1, -1, 0, 0, 0, 1), (1, -1, 0, 0, 0, 1), (1, 1, 0, 0, 0, 1), (-1, 1, 0, 0, 0, 1)]
    return np.array(verts, "f4"), np.array([0, 1, 2, 0, 2, 3], "u4")
