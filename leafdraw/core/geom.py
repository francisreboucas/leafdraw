"""Geometria 2D: transformações afins e primitivas exatas (segmento e arco).

As primitivas alimentam snaps (interseção, perpendicular, próximo), offset e
a tesselação para a vista 3D. Ângulos em graus, sentido anti-horário.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]
EPS = 1e-9


def norm_angle(a: float) -> float:
    """Ângulo em [0, 360)."""
    a = math.fmod(a, 360.0)
    return a + 360.0 if a < 0 else a


def angle_of(c: Point, p: Point) -> float:
    return norm_angle(math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])))


def polar(c: Point, r: float, deg: float) -> Point:
    a = math.radians(deg)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def sweep(a0: float, a1: float) -> float:
    """Varredura anti-horária de a0 até a1, em (0, 360]."""
    s = norm_angle(a1 - a0)
    return 360.0 if s < EPS else s


# --- transformações ------------------------------------------------------

@dataclass(frozen=True)
class Affine:
    """x' = a·x + b·y + e ;  y' = c·x + d·y + f"""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, p: Point) -> Point:
        x, y = p
        return (self.a * x + self.b * y + self.e, self.c * x + self.d * y + self.f)

    def apply_vector(self, v: Point) -> Point:
        return (self.a * v[0] + self.b * v[1], self.c * v[0] + self.d * v[1])

    def __matmul__(self, o: Affine) -> Affine:
        """self ∘ o (aplica ``o`` primeiro)."""
        return Affine(
            self.a * o.a + self.b * o.c, self.a * o.b + self.b * o.d,
            self.c * o.a + self.d * o.c, self.c * o.b + self.d * o.d,
            self.a * o.e + self.b * o.f + self.e, self.c * o.e + self.d * o.f + self.f,
        )

    @property
    def det(self) -> float:
        return self.a * self.d - self.b * self.c

    @property
    def mirrored(self) -> bool:
        return self.det < 0

    @property
    def scale(self) -> float:
        """Fator de escala uniforme (transformações conformes)."""
        return math.sqrt(abs(self.det))

    def map_angle(self, deg: float) -> float:
        vx, vy = self.apply_vector((math.cos(math.radians(deg)), math.sin(math.radians(deg))))
        return norm_angle(math.degrees(math.atan2(vy, vx)))

    @staticmethod
    def translation(dx: float, dy: float) -> Affine:
        return Affine(e=dx, f=dy)

    @staticmethod
    def rotation(deg: float, about: Point = (0.0, 0.0)) -> Affine:
        r = math.radians(deg)
        cs, sn = math.cos(r), math.sin(r)
        cx, cy = about
        return Affine(cs, -sn, sn, cs, cx - cs * cx + sn * cy, cy - sn * cx - cs * cy)

    @staticmethod
    def scaling(s: float, about: Point = (0.0, 0.0)) -> Affine:
        cx, cy = about
        return Affine(s, 0, 0, s, cx * (1 - s), cy * (1 - s))

    @staticmethod
    def mirror(p1: Point, p2: Point) -> Affine:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        n = math.hypot(dx, dy)
        if n < EPS:
            raise ValueError("eixo de espelhamento degenerado")
        ux, uy = dx / n, dy / n
        a, b = 2 * ux * ux - 1, 2 * ux * uy
        d = 2 * uy * uy - 1
        x0, y0 = p1
        return Affine(a, b, b, d, x0 - a * x0 - b * y0, y0 - b * x0 - d * y0)


# --- primitivas ------------------------------------------------------------

@dataclass(frozen=True)
class Seg:
    a: Point
    b: Point


@dataclass(frozen=True)
class ArcP:
    c: Point
    r: float
    a0: float = 0.0
    a1: float = 360.0

    @property
    def full(self) -> bool:
        return sweep(self.a0, self.a1) >= 360.0 - EPS

    def contains_angle(self, deg: float) -> bool:
        if self.full:
            return True
        return norm_angle(deg - self.a0) <= sweep(self.a0, self.a1) + 1e-7


Primitive = Seg | ArcP


def _on_seg(t: float) -> bool:
    return -1e-9 <= t <= 1 + 1e-9


def nearest_on(pr: Primitive, p: Point) -> Point:
    if isinstance(pr, Seg):
        (ax, ay), (bx, by) = pr.a, pr.b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            return pr.a
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
        return (ax + t * dx, ay + t * dy)
    ang = angle_of(pr.c, p) if math.dist(pr.c, p) > EPS else pr.a0
    if pr.contains_angle(ang):
        return polar(pr.c, pr.r, ang)
    e0, e1 = polar(pr.c, pr.r, pr.a0), polar(pr.c, pr.r, pr.a1)
    return e0 if math.dist(e0, p) <= math.dist(e1, p) else e1


def perpendicular_feet(pr: Primitive, base: Point) -> list[Point]:
    """Pés da perpendicular traçada a partir de ``base``."""
    if isinstance(pr, Seg):
        (ax, ay), (bx, by) = pr.a, pr.b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            return []
        t = ((base[0] - ax) * dx + (base[1] - ay) * dy) / L2
        return [(ax + t * dx, ay + t * dy)] if _on_seg(t) else []
    if math.dist(pr.c, base) < EPS:
        return []
    ang = angle_of(pr.c, base)
    return [polar(pr.c, pr.r, a) for a in (ang, ang + 180) if pr.contains_angle(norm_angle(a))]


def intersections(p: Primitive, q: Primitive) -> list[Point]:
    if isinstance(p, Seg) and isinstance(q, Seg):
        return _seg_seg(p, q)
    if isinstance(p, Seg):
        return _seg_arc(p, q)
    if isinstance(q, Seg):
        return _seg_arc(q, p)
    return _arc_arc(p, q)


def _seg_seg(s: Seg, t: Seg) -> list[Point]:
    (x1, y1), (x2, y2) = s.a, s.b
    (x3, y3), (x4, y4) = t.a, t.b
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < EPS:
        return []
    u = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    v = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    if _on_seg(u) and _on_seg(v):
        return [(x1 + u * (x2 - x1), y1 + u * (y2 - y1))]
    return []


def _seg_arc(s: Seg, arc: ArcP) -> list[Point]:
    (ax, ay), (bx, by) = s.a, s.b
    cx, cy = arc.c
    dx, dy = bx - ax, by - ay
    fx, fy = ax - cx, ay - cy
    A = dx * dx + dy * dy
    if A < EPS:
        return []
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - arc.r * arc.r
    disc = B * B - 4 * A * C
    if disc < -EPS:
        return []
    sq = math.sqrt(max(disc, 0.0))
    out = []
    for t in {(-B - sq) / (2 * A), (-B + sq) / (2 * A)}:
        if _on_seg(t):
            pt = (ax + t * dx, ay + t * dy)
            if arc.contains_angle(angle_of(arc.c, pt)):
                out.append(pt)
    return out


def _arc_arc(p: ArcP, q: ArcP) -> list[Point]:
    d = math.dist(p.c, q.c)
    if d < EPS or d > p.r + q.r + EPS or d < abs(p.r - q.r) - EPS:
        return []
    a = (p.r * p.r - q.r * q.r + d * d) / (2 * d)
    h = math.sqrt(max(p.r * p.r - a * a, 0.0))
    ux, uy = (q.c[0] - p.c[0]) / d, (q.c[1] - p.c[1]) / d
    mx, my = p.c[0] + a * ux, p.c[1] + a * uy
    cands = {(mx - h * uy, my + h * ux), (mx + h * uy, my - h * ux)}
    return [pt for pt in cands if p.contains_angle(angle_of(p.c, pt)) and q.contains_angle(angle_of(q.c, pt))]


def tessellate(pr: Primitive, max_step_deg: float = 5.0) -> list[Point]:
    if isinstance(pr, Seg):
        return [pr.a, pr.b]
    sw = sweep(pr.a0, pr.a1)
    n = max(2, math.ceil(sw / max_step_deg))
    return [polar(pr.c, pr.r, pr.a0 + sw * i / n) for i in range(n + 1)]


def circle_from_3_points(p1: Point, p2: Point, p3: Point) -> tuple[Point, float] | None:
    (ax, ay), (bx, by), (cx, cy) = p1, p2, p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < EPS:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.dist((ux, uy), p1)


def arc_from_3_points(p1: Point, p2: Point, p3: Point) -> tuple[Point, float, float, float] | None:
    """Arco que começa em p1, passa por p2 e termina em p3: (centro, raio, início, fim)."""
    res = circle_from_3_points(p1, p2, p3)
    if res is None:
        return None
    c, r = res
    a1, a2, a3 = angle_of(c, p1), angle_of(c, p2), angle_of(c, p3)
    if norm_angle(a2 - a1) <= norm_angle(a3 - a1):
        return c, r, a1, a3
    return c, r, a3, a1


def point_side(a: Point, b: Point, p: Point) -> float:
    """> 0 se p está à esquerda de a→b."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
