"""Viewport 3D (moderngl dentro de QOpenGLWidget).

Mundo com Z para cima; X/Y iguais aos da planta. Plantas são desenhadas por
instancing (uma chamada por malha), o que escala para milhares de árvores.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from leafdraw.core.entities import Plant, PlantingArea
from leafdraw.core.geom import tessellate
from leafdraw.ui import glmath

MESH_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec3 in_norm;
in vec3 i_off;
in vec3 i_scale;
in vec3 i_color;
out vec3 v_norm;
out vec3 v_color;
void main() {
    gl_Position = mvp * vec4(in_pos * i_scale + i_off, 1.0);
    v_norm = normalize(in_norm / i_scale);
    v_color = i_color;
}
"""

MESH_FS = """
#version 330
in vec3 v_norm;
in vec3 v_color;
out vec4 f_color;
void main() {
    vec3 light = normalize(vec3(0.45, -0.35, 0.82));
    float diff = max(dot(normalize(v_norm), light), 0.0);
    float sky = 0.5 + 0.5 * normalize(v_norm).z;
    f_color = vec4(v_color * (0.25 + 0.2 * sky + 0.65 * diff), 1.0);
}
"""

LINE_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec4 in_color;
out vec4 v_color;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color;
}
"""

LINE_FS = """
#version 330
in vec4 v_color;
out vec4 f_color;
void main() { f_color = v_color; }
"""

SKY = (0.55, 0.66, 0.76)
GROUND = (0.33, 0.39, 0.31)
TRUNK = (0.40, 0.29, 0.20)
GROUND_HALF = 2000.0
LINE_Z = 0.03
GRID_Z = 0.015
CIRCLE_SEGMENTS = 64
MAX_MASSED_3D = 30_000  # mudas de maciço desenhadas no 3D


def _rgb(color: str):
    c = QColor(color)
    return (c.redF(), c.greenF(), c.blueF())


class OrbitCamera:
    FOV = 45.0

    def __init__(self):
        self.target = np.array([0.0, 0.0, 0.0])
        self.distance = 60.0
        self.yaw = -60.0  # graus, em torno de Z
        self.pitch = 35.0  # graus acima do plano
        self.ortho = False

    def eye(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        d = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
        return self.target + self.distance * d

    def view(self) -> np.ndarray:
        return glmath.look_at(self.eye(), self.target, np.array([0.0, 0.0, 1.0]))

    def projection(self, aspect: float) -> np.ndarray:
        if self.ortho:
            h = self.distance * math.tan(math.radians(self.FOV) / 2)
            far = self.distance * 4 + 10_000
            return glmath.orthographic(-h * aspect, h * aspect, -h, h, -far, far)
        near = max(0.05, self.distance * 0.01)
        return glmath.perspective(self.FOV, aspect, near, self.distance * 50 + 5_000)

    def basis(self):
        """Vetores direita/cima da câmera no mundo (para pan)."""
        v = self.view()
        return v[0, :3], v[1, :3]


class Viewport3D(QOpenGLWidget):
    PRESETS = {
        "top": (-90.0, 89.9, True),
        "front": (-90.0, 0.0, True),
        "right": (0.0, 0.0, True),
        "persp": (-60.0, 35.0, False),
    }

    def __init__(self, doc, catalog, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.catalog = catalog
        self.cam = OrbitCamera()
        self.ctx: moderngl.Context | None = None
        self._dirty = True
        self._drag: tuple[Qt.MouseButton, QPointF] | None = None
        self._scene_vaos: list[tuple] = []  # (vao, modo, instâncias, buffer)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        for sig in (doc.entityAdded, doc.entityRemoved, doc.entityChanged, doc.layersChanged):
            sig.connect(self.mark_dirty)
        doc.documentReset.connect(self.mark_dirty)

    def mark_dirty(self, *_):
        self._dirty = True
        self.update()

    # --- câmera -----------------------------------------------------------

    def set_view(self, name: str):
        yaw, pitch, ortho = self.PRESETS[name]
        self.cam.yaw, self.cam.pitch, self.cam.ortho = yaw, pitch, ortho
        self.update()

    def set_ortho(self, ortho: bool):
        self.cam.ortho = ortho
        self.update()

    def zoom_extents(self):
        b = self.doc.bounds()
        if b is None:
            self.cam.target = np.zeros(3)
            self.cam.distance = 40.0
        else:
            heights = [e.height for e in self.doc.entities.values() if isinstance(e, Plant)]
            h = max(heights, default=0.0)
            size = max(math.hypot(b[2] - b[0], b[3] - b[1]), h, 2.0)
            aspect = min(1.0, self.width() / max(self.height(), 1))
            self.cam.target = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, h / 3])
            self.cam.distance = 0.6 * size / (math.tan(math.radians(self.cam.FOV) / 2) * aspect)
        self.update()

    # --- OpenGL -----------------------------------------------------------

    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.mesh_prog = self.ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        self.line_prog = self.ctx.program(vertex_shader=LINE_VS, fragment_shader=LINE_FS)
        self.meshes = {}
        for name, (v, i) in {"sphere": glmath.uv_sphere(), "cylinder": glmath.cylinder(),
                             "quad": glmath.quad()}.items():
            self.meshes[name] = (self.ctx.buffer(v.tobytes()), self.ctx.buffer(i.tobytes()))
        self._ground = self._instanced("quad", [(0, 0, 0, GROUND_HALF, GROUND_HALF, 1, *GROUND)])
        self._grid = self._lines(self._grid_vertices())
        self._dirty = True

    def _instanced(self, mesh: str, instances) -> tuple | None:
        if not instances:
            return None
        vbo, ibo = self.meshes[mesh]
        inst = self.ctx.buffer(np.array(instances, "f4").tobytes())
        vao = self.ctx.vertex_array(
            self.mesh_prog,
            [(vbo, "3f 3f", "in_pos", "in_norm"), (inst, "3f 3f 3f/i", "i_off", "i_scale", "i_color")],
            index_buffer=ibo,
        )
        return vao, moderngl.TRIANGLES, len(instances), inst

    def _lines(self, verts) -> tuple | None:
        if not verts:
            return None
        buf = self.ctx.buffer(np.array(verts, "f4").tobytes())
        vao = self.ctx.vertex_array(self.line_prog, [(buf, "3f 4f", "in_pos", "in_color")])
        return vao, moderngl.LINES, 1, buf

    @staticmethod
    def _grid_vertices():
        verts = []
        for step, extent, alpha in ((1.0, 50, 0.10), (10.0, 500, 0.22)):
            n = int(extent / step)
            for i in range(-n, n + 1):
                c = i * step
                col = (1, 1, 1, alpha)
                verts += [(c, -extent, GRID_Z, *col), (c, extent, GRID_Z, *col)]
                verts += [(-extent, c, GRID_Z, *col), (extent, c, GRID_Z, *col)]
        for a, b, col in (((-500, 0), (500, 0), (0.9, 0.3, 0.3, 0.8)), ((0, -500), (0, 500), (0.35, 0.85, 0.35, 0.8))):
            verts += [(*a, GRID_Z * 1.5, *col), (*b, GRID_Z * 1.5, *col)]
        return verts

    def _release_scene(self):
        for vao, _mode, _n, buf in self._scene_vaos:
            vao.release()
            buf.release()
        self._scene_vaos = []

    def _rebuild(self):
        self._release_scene()
        lines, trunks, crowns = [], [], []
        massed_budget = MAX_MASSED_3D
        for e in self.doc.entities.values():
            layer = self.doc.layer_for(e)
            if not layer.visible:
                continue
            if isinstance(e, Plant):
                self._plant_instances(e, trunks, crowns)
                continue
            if isinstance(e, PlantingArea) and massed_budget > 0:
                pts = e.points()[:massed_budget]
                massed_budget -= len(pts)
                sp = self.catalog.get(e.species)
                color = _rgb(e.color or (sp.cor if sp else "#6cc070"))
                r = min(e.spacing * 0.5, sp.copa / 2 if sp else e.spacing * 0.5)
                h = (sp.altura if sp else 0.3) / 2
                crowns += [(x, y, h, r, r, h, *color) for x, y in pts]
            col = (*_rgb(e.color or layer.color), 1.0)
            for pr in e.primitives():
                pts = tessellate(pr, 360 / CIRCLE_SEGMENTS)
                for a, b in zip(pts, pts[1:]):
                    lines += [(*a, LINE_Z, *col), (*b, LINE_Z, *col)]
        for item in (self._lines(lines), self._instanced("cylinder", trunks), self._instanced("sphere", crowns)):
            if item is not None:
                self._scene_vaos.append(item)
        self._dirty = False

    def _plant_instances(self, e: Plant, trunks, crowns):
        sp = self.catalog.get(e.species)
        simbolo = sp.simbolo if sp else "arvore"
        color = _rgb(e.color or sp.cor) if (e.color or sp) else (0.4, 0.7, 0.4)
        x, y = e.position
        r, h = e.canopy / 2, e.height
        if simbolo == "palmeira":
            trunk_h = h * 0.88
            tr = max(0.12, r * 0.06)
            trunks.append((x, y, 0, tr, tr, trunk_h, *TRUNK))
            crowns.append((x, y, trunk_h, r, r, max(r * 0.28, 0.3), *color))
        elif simbolo == "arvore":
            crown_h = min(h * 0.4, r * 0.8)
            tr = max(0.08, r * 0.06)
            trunks.append((x, y, 0, tr, tr, h - crown_h, *TRUNK))
            crowns.append((x, y, h - crown_h, r, r, crown_h, *color))
        else:  # arbusto, forração
            crowns.append((x, y, h / 2, r, r, h / 2, *color))

    def paintGL(self):
        if self.ctx is None:
            return
        if self._dirty:
            self._rebuild()
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        fbo.use()
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.clear(*SKY, 1.0)
        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        mvp = glmath.gl_bytes(self.cam.projection(w / h) @ self.cam.view())
        self.mesh_prog["mvp"].write(mvp)
        self.line_prog["mvp"].write(mvp)
        for vao, mode, n, _buf in [self._ground, self._grid, *self._scene_vaos]:
            vao.render(mode, instances=n)
        self.ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)

    # --- interação --------------------------------------------------------

    def mousePressEvent(self, e):
        self._drag = (e.button(), e.position())
        self.setFocus()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        button, last = self._drag
        d = e.position() - last
        self._drag = (button, e.position())
        pan = button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) or (
            e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if pan:
            right, up = self.cam.basis()
            k = self.cam.distance * 2 * math.tan(math.radians(self.cam.FOV) / 2) / max(self.height(), 1)
            self.cam.target = self.cam.target - right * d.x() * k + up * d.y() * k
        else:
            self.cam.yaw -= d.x() * 0.4
            self.cam.pitch = min(89.9, max(-89.0, self.cam.pitch + d.y() * 0.4))
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def wheelEvent(self, e):
        self.cam.distance = min(20_000.0, max(0.5, self.cam.distance * 0.85 ** (e.angleDelta().y() / 120)))
        self.update()
