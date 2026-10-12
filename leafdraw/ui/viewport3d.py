"""Viewport 3D (moderngl dentro de QOpenGLWidget).

Mundo com Z para cima; X/Y iguais aos da planta. A cena é montada em arrays
por ``scene3d`` e enviada à GPU em dois blocos: o estático (tudo que não está
selecionado) e o dinâmico (seleção), para que arrastar o gizmo só reconstrua
o que se move. Plantas são desenhadas por instancing.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from leafdraw.core.entities import Contour, SpotHeight, union_bounds
from leafdraw.core.geom import Affine
from leafdraw.core.terrain import Terrain
from leafdraw.ui import glmath
from leafdraw.ui.gizmo3d import gizmo_triangles, hit_test, point_in_polygon
from leafdraw.ui.plants3d import MESHES
from leafdraw.ui.scene3d import SceneArrays, ZMap, build_scene

LIGHT = """
vec3 shade(vec3 n, vec3 color) {
    vec3 light = normalize(vec3(0.45, -0.35, 0.82));
    float diff = max(dot(n, light), 0.0);
    float sky = 0.5 + 0.5 * n.z;
    return color * (0.28 + 0.22 * sky + 0.62 * diff);
}
"""

MESH_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec3 in_norm;
in vec3 i_off;
in vec3 i_scale;
in vec3 i_color;
in float i_rot;
out vec3 v_norm;
out vec3 v_color;
void main() {
    float c = cos(i_rot), s = sin(i_rot);
    vec3 p = vec3(c * in_pos.x - s * in_pos.y, s * in_pos.x + c * in_pos.y, in_pos.z);
    vec3 n = vec3(c * in_norm.x - s * in_norm.y, s * in_norm.x + c * in_norm.y, in_norm.z);
    gl_Position = mvp * vec4(p * i_scale + i_off, 1.0);
    v_norm = normalize(n / i_scale);
    v_color = i_color;
}
"""

MESH_FS = """
#version 330
in vec3 v_norm;
in vec3 v_color;
out vec4 f_color;
""" + LIGHT + """
void main() { f_color = vec4(shade(normalize(v_norm), v_color), 1.0); }
"""

SURF_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec3 in_norm;
in vec4 in_color;
out vec3 v_norm;
out vec4 v_color;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_norm = in_norm;
    v_color = in_color;
}
"""

SURF_FS = """
#version 330
in vec3 v_norm;
in vec4 v_color;
out vec4 f_color;
""" + LIGHT + """
void main() { f_color = vec4(shade(normalize(v_norm), v_color.rgb), v_color.a); }
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

SKY = (0.62, 0.72, 0.82)
GROUND = (0.36, 0.42, 0.33)
TERRAIN_LOW = np.array([0.38, 0.47, 0.31])
TERRAIN_HIGH = np.array([0.58, 0.53, 0.38])
GROUND_HALF = 3000.0
GRID_LIFT = 0.012
MAX_OFFSCREEN = 4096  # px, lado máximo da imagem 3D para folhas
CLICK_PX = 4
PICK_PX = 7


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

    def state(self) -> dict:
        return {"target": [float(v) for v in self.target], "distance": self.distance, "yaw": self.yaw,
                "pitch": self.pitch, "ortho": self.ortho}

    @staticmethod
    def from_state(d: dict) -> OrbitCamera:
        cam = OrbitCamera()
        cam.target = np.array(d.get("target", [0, 0, 0]), dtype=float)
        cam.distance = float(d.get("distance", 60.0))
        cam.yaw = float(d.get("yaw", -60.0))
        cam.pitch = float(d.get("pitch", 35.0))
        cam.ortho = bool(d.get("ortho", False))
        return cam

    def basis(self):
        """Vetores direita/cima da câmera no mundo (para pan)."""
        v = self.view()
        return v[0, :3], v[1, :3]


class Viewport3D(QOpenGLWidget):
    picked = Signal(str, bool)  # id da entidade ("" = nada), aditivo (Ctrl/Shift)
    transformRequested = Signal(object, str)  # Affine, texto do comando

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
        self.exaggeration = 1.0
        self.selection: set[str] = set()
        self.override: dict = {}  # prévia do gizmo: id -> entidade transformada
        self._terrain: Terrain | None = None
        self._terrain_ids: set[str] = set()
        self._terrain_dirty = True
        self._dirty = True
        self._dyn_dirty = True
        self._static: list = []
        self._dynamic: list = []
        self._terrain_vao: list = []
        self._ground: list = []
        self._pick: dict = {}
        self._static_pick: dict = {}
        self._terrain_mesh_dirty = True
        self._drag = None  # (botão, última posição)
        self._press = None  # posição do clique
        self._gdrag = None  # arrasto do gizmo
        self._hot: str | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        self.setMouseTracking(True)
        doc.entityAdded.connect(self._on_entity)
        doc.entityRemoved.connect(self._on_entity)
        doc.entityChanged.connect(self._on_entity)
        doc.layersChanged.connect(self._on_all)
        doc.documentReset.connect(self._on_all)

    # --- estado ---------------------------------------------------------------

    def _on_entity(self, eid):
        e = self.doc.entities.get(eid)
        if eid in self._terrain_ids or isinstance(e, (Contour, SpotHeight)):
            self._terrain_dirty = True
        self.mark_dirty()

    def _on_all(self, *_):
        self._terrain_dirty = True
        self.mark_dirty()

    def mark_dirty(self, *_):
        self._dirty = True
        self.update()

    def terrain(self) -> Terrain:
        if self._terrain_dirty or self._terrain is None:
            ents = [e for e in self.doc.entities.values()
                    if isinstance(e, (Contour, SpotHeight)) and self.doc.layer_for(e).visible]
            self._terrain = Terrain.from_entities(ents)
            self._terrain_ids = {e.id for e in ents}
            self._terrain_dirty = False
            self._terrain_mesh_dirty = True
        return self._terrain

    def elevation_at(self, x: float, y: float) -> float | None:
        t = self.terrain()
        return t.elevation(x, y) if t.valid else None

    def zmap(self) -> ZMap:
        return ZMap(self.terrain(), self.exaggeration)

    def set_selection(self, ids):
        ids = {i for i in ids if i in self.doc.entities}
        if ids != self.selection:
            self.selection = ids
            self.override = {}
            self.mark_dirty()

    def set_exaggeration(self, k: float):
        self.exaggeration = k
        self._terrain_mesh_dirty = True
        self.mark_dirty()

    # --- câmera ---------------------------------------------------------------

    def set_view(self, name: str):
        yaw, pitch, ortho = self.PRESETS[name]
        self.cam.yaw, self.cam.pitch, self.cam.ortho = yaw, pitch, ortho
        self.update()

    def set_ortho(self, ortho: bool):
        self.cam.ortho = ortho
        self.update()

    def zoom_extents(self, ids=None):
        ents = [self.doc.entities[i] for i in ids if i in self.doc.entities] if ids else list(self.doc.entities.values())
        b = union_bounds(e.bounds() for e in ents)
        zm = self.zmap()
        if b is None:
            self.cam.target = np.array([0.0, 0.0, zm.base])
            self.cam.distance = 40.0
        else:
            heights = [getattr(e, "height", 0.0) for e in ents]
            h = max(heights, default=0.0)
            relief = (self.terrain().top - zm.base) * self.exaggeration if zm.active else 0.0
            size = max(math.hypot(b[2] - b[0], b[3] - b[1]), h + relief, 2.0)
            aspect = min(1.0, self.width() / max(self.height(), 1))
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            self.cam.target = np.array([cx, cy, zm.at(cx, cy) + h / 3])
            self.cam.distance = 0.6 * size / (math.tan(math.radians(self.cam.FOV) / 2) * aspect)
        self.update()

    def focus_selection(self):
        if self.selection:
            self.zoom_extents(self.selection)

    # --- OpenGL ---------------------------------------------------------------

    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.mesh_prog = self.ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        self.surf_prog = self.ctx.program(vertex_shader=SURF_VS, fragment_shader=SURF_FS)
        self.line_prog = self.ctx.program(vertex_shader=LINE_VS, fragment_shader=LINE_FS)
        self.meshes = {}
        sources = {"sphere": glmath.uv_sphere(), "cylinder": glmath.cylinder(), "bush": glmath.bush(),
                   "palm": glmath.palm_crown()}
        for name, (v, i) in sources.items():
            self.meshes[name] = (self.ctx.buffer(v.tobytes()), self.ctx.buffer(i.tobytes()))
        self._terrain_mesh_dirty = True
        self._dirty = True

    def _vao_lines(self, rows, mode=moderngl.LINES):
        if not len(rows):
            return None
        buf = self.ctx.buffer(np.asarray(rows, "f4").tobytes())
        return (self.ctx.vertex_array(self.line_prog, [(buf, "3f 4f", "in_pos", "in_color")]), mode, 1, [buf])

    def _vao_surface(self, rows):
        if not len(rows):
            return None
        buf = self.ctx.buffer(np.asarray(rows, "f4").tobytes())
        vao = self.ctx.vertex_array(self.surf_prog, [(buf, "3f 3f 4f", "in_pos", "in_norm", "in_color")])
        return (vao, moderngl.TRIANGLES, 1, [buf])

    def _vao_instances(self, mesh: str, rows):
        if not len(rows):
            return None
        vbo, ibo = self.meshes[mesh]
        inst = self.ctx.buffer(np.asarray(rows, "f4").tobytes())
        vao = self.ctx.vertex_array(
            self.mesh_prog,
            [(vbo, "3f 3f", "in_pos", "in_norm"), (inst, "3f 3f 3f 1f/i", "i_off", "i_scale", "i_color", "i_rot")],
            index_buffer=ibo)
        return (vao, moderngl.TRIANGLES, len(rows), [inst])

    def _upload(self, arr: SceneArrays) -> dict:
        return {
            "surfaces": [x for x in (self._vao_surface(arr.surfaces),) if x],
            "shadows": [x for x in (self._vao_lines(arr.shadows, moderngl.TRIANGLES),) if x],
            "lines": [x for x in (self._vao_lines(arr.lines),) if x],
            "meshes": [x for m in MESHES if (x := self._vao_instances(m, arr.instances[m]))],
        }

    @staticmethod
    def _release(groups):
        items = []
        if isinstance(groups, dict):
            for v in groups.values():
                items += v
        else:
            items = groups
        for vao, _mode, _n, bufs in items:
            vao.release()
            for b in bufs:
                b.release()

    def _rebuild(self):
        zm = self.zmap()
        if self._terrain_mesh_dirty:
            self._rebuild_terrain(zm)
        static = [e for e in self.doc.entities.values() if e.id not in self.selection]
        sa = build_scene(static, self.doc, self.catalog, zm)
        self._release(self._static)
        self._static = self._upload(sa)
        self._static_pick = sa.pick
        self._dirty = False
        self._rebuild_dynamic(zm)

    def _rebuild_dynamic(self, zm: ZMap | None = None):
        zm = zm or self.zmap()
        dyn = [self.override.get(i, self.doc.entities[i]) for i in self.selection if i in self.doc.entities]
        da = build_scene(dyn, self.doc, self.catalog, zm, self.selection)
        self._release(self._dynamic)
        self._dynamic = self._upload(da)
        self._pick = {**self._static_pick, **da.pick}
        self._dyn_dirty = False

    def _rebuild_terrain(self, zm: ZMap):
        self._release(self._terrain_vao)
        self._release(self._ground)
        self._terrain_vao = []
        t = self.terrain()
        if t.valid:
            v, n, f = t.mesh()
            v = v.copy()
            v[:, 2] = zm.base + (v[:, 2] - zm.base) * self.exaggeration
            span = max(t.top - t.base, 1e-9)
            k = ((t.vertices[:, 2] - t.base) / span)[:, None]
            col = TERRAIN_LOW * (1 - k) + TERRAIN_HIGH * k
            rows = np.concatenate([v, n, col, np.ones((len(v), 1))], axis=1)[f.reshape(-1)]
            item = self._vao_surface(rows)
            if item:
                self._terrain_vao = [item]
        z = zm.base
        g = GROUND_HALF
        ground = [(x, y, z - 0.02, 0, 0, 1, *GROUND, 1.0) for x, y in ((-g, -g), (g, -g), (g, g), (-g, -g), (g, g), (-g, g))]
        grid = []
        for step, extent, alpha in ((1.0, 50, 0.10), (10.0, 500, 0.22)):
            n_ = int(extent / step)
            for i in range(-n_, n_ + 1):
                c = i * step
                col = (1, 1, 1, alpha)
                grid += [(c, -extent, z + GRID_LIFT, *col), (c, extent, z + GRID_LIFT, *col),
                         (-extent, c, z + GRID_LIFT, *col), (extent, c, z + GRID_LIFT, *col)]
        for a, b, col in (((-500, 0), (500, 0), (0.9, 0.3, 0.3, 0.8)), ((0, -500), (0, 500), (0.35, 0.85, 0.35, 0.8))):
            grid += [(*a, z + GRID_LIFT * 1.5, *col), (*b, z + GRID_LIFT * 1.5, *col)]
        self._ground = [x for x in (self._vao_surface(ground), self._vao_lines(grid)) if x]
        self._terrain_mesh_dirty = False

    def paintGL(self):
        if self.ctx is None:
            return
        if self._dirty:
            self._rebuild()
        elif self._dyn_dirty:
            self._rebuild_dynamic()
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        fbo.use()
        self._draw(self.cam, w, h)

    def _mvp(self, cam: OrbitCamera, w: int, h: int) -> np.ndarray:
        return cam.projection(w / h) @ cam.view()

    def _draw(self, cam: OrbitCamera, w: int, h: int, grid: bool = True, gizmo: bool = True):
        ctx = self.ctx
        ctx.viewport = (0, 0, w, h)
        ctx.clear(*SKY, 1.0)
        ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        # alfa separado: o framebuffer continua opaco (senão o Qt compõe o widget translúcido)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        mvp = glmath.gl_bytes(self._mvp(cam, w, h))
        for prog in (self.mesh_prog, self.surf_prog, self.line_prog):
            prog["mvp"].write(mvp)

        def render(items):
            for vao, mode, n, _b in items:
                vao.render(mode, instances=n)

        ground = self._ground if grid else self._ground[:1]
        render(ground[:1])
        render(self._terrain_vao)
        render(ground[1:])
        for key in ("surfaces", "shadows", "lines", "meshes"):
            render(self._static.get(key, []) if isinstance(self._static, dict) else [])
            render(self._dynamic.get(key, []) if isinstance(self._dynamic, dict) else [])
        if gizmo and self.selection and self._gizmo_frame() is not None:
            c, size = self._gizmo_frame()
            tris = gizmo_triangles(c, size, self._hot)
            ctx.disable(moderngl.DEPTH_TEST)
            buf = ctx.buffer(tris.tobytes())
            vao = ctx.vertex_array(self.line_prog, [(buf, "3f 4f", "in_pos", "in_color")])
            vao.render(moderngl.TRIANGLES)
            vao.release()
            buf.release()
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)

    def render_image(self, camera: dict | None, w: int, h: int) -> QImage | None:
        """Renderiza fora da tela (para folhas). None se o OpenGL ainda não foi iniciado."""
        if self.ctx is None:
            return None
        w, h = min(w, MAX_OFFSCREEN), min(h, MAX_OFFSCREEN)
        cam = OrbitCamera.from_state(camera) if camera else self.cam
        self.makeCurrent()
        try:
            if self._dirty:
                self._rebuild()
            samples = min(4, self.ctx.max_samples)
            ms = self.ctx.framebuffer(color_attachments=[self.ctx.renderbuffer((w, h), samples=samples)],
                                      depth_attachment=self.ctx.depth_renderbuffer((w, h), samples=samples))
            out = self.ctx.simple_framebuffer((w, h))
            ms.use()
            self._draw(cam, w, h, grid=False, gizmo=False)
            self.ctx.copy_framebuffer(out, ms)
            data = out.read(components=3, alignment=1)
            img = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888).mirrored(False, True).copy()
            for obj in (ms, out):
                obj.release()
            return img
        finally:
            self.doneCurrent()

    # --- projeção, raios e seleção ---------------------------------------------

    def _screen_mvp(self) -> np.ndarray:
        return self._mvp(self.cam, max(self.width(), 1), max(self.height(), 1))

    def project(self, pts: np.ndarray, with_depth: bool = False):
        """Mundo (n, 3) → pixels lógicos (n, 2); pontos atrás da câmera viram NaN."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        M = self._screen_mvp()
        clip = np.c_[pts, np.ones(len(pts))] @ M.T
        w = clip[:, 3:4]
        ndc = np.where(w > 1e-9, clip[:, :3] / np.where(np.abs(w) < 1e-12, 1e-12, w), np.nan)
        px = np.c_[(ndc[:, 0] + 1) / 2 * self.width(), (1 - ndc[:, 1]) / 2 * self.height()]
        return (px, ndc[:, 2]) if with_depth else px

    def ray(self, pos: QPointF) -> tuple[np.ndarray, np.ndarray]:
        inv = np.linalg.inv(self._screen_mvp())
        x = 2 * pos.x() / max(self.width(), 1) - 1
        y = 1 - 2 * pos.y() / max(self.height(), 1)
        a = inv @ np.array([x, y, -1, 1.0])
        b = inv @ np.array([x, y, 1, 1.0])
        a, b = a[:3] / a[3], b[:3] / b[3]
        d = b - a
        return a, d / np.linalg.norm(d)

    @staticmethod
    def _ray_plane(o, d, p0, n):
        den = float(d @ n)
        if abs(den) < 1e-9:
            return None
        t = float((p0 - o) @ n) / den
        return o + d * t

    def pick_at(self, pos: QPointF) -> str:
        m = np.array([pos.x(), pos.y()])
        right, _up = self.cam.basis()
        best = None
        for eid, shape in self._pick.items():
            if shape.kind == "point":
                c = shape.data[0]
                (p0, p1), depth = self.project(np.array([c, c + right * shape.radius]), True)
                if np.isnan(p0).any():
                    continue
                d = np.linalg.norm(m - p0)
                if d <= max(np.linalg.norm(p1 - p0), PICK_PX):
                    cand = (0, float(depth[0]), eid)
                else:
                    continue
            elif shape.kind == "lines":
                cand = None
                for arr in shape.data:
                    px, depth = self.project(arr, True)
                    for i in range(len(px) - 1):
                        a, b = px[i], px[i + 1]
                        if np.isnan(a).any() or np.isnan(b).any():
                            continue
                        ab = b - a
                        L2 = float(ab @ ab)
                        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, float((m - a) @ ab) / L2))
                        if np.linalg.norm(m - (a + ab * t)) <= PICK_PX:
                            cand = (1, float(depth[i]), eid)
                            break
                    if cand:
                        break
                if cand is None:
                    continue
            else:  # área
                if not shape.data:
                    continue
                px, depth = self.project(shape.data[0], True)
                if np.isnan(px).any() or not point_in_polygon(m, px):
                    continue
                cand = (2, float(np.nanmean(depth)), eid)
            if best is None or cand[:2] < best[:2]:
                best = cand
        return best[2] if best else ""

    # --- gizmo ----------------------------------------------------------------

    def _selected_entities(self):
        return [self.override.get(i, self.doc.entities[i]) for i in self.selection if i in self.doc.entities]

    def _gizmo_frame(self):
        ents = self._selected_entities()
        b = union_bounds(e.bounds() for e in ents)
        if b is None:
            return None
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        c = np.array([cx, cy, self.zmap().at(cx, cy) + 0.05])
        if self.cam.ortho:
            size = self.cam.distance * math.tan(math.radians(self.cam.FOV) / 2) * 0.3
        else:
            size = float(np.linalg.norm(self.cam.eye() - c)) * 0.16
        return c, size

    def _gizmo_handle(self, pos: QPointF) -> str | None:
        frame = self._gizmo_frame() if self.selection else None
        if frame is None:
            return None
        c, size = frame

        def proj(p):
            px = self.project(p)
            return None if np.isnan(px).any() else px

        return hit_test(proj, c, size, (pos.x(), pos.y()))

    def _gizmo_point(self, pos: QPointF, handle: str, c: np.ndarray):
        o, d = self.ray(pos)
        if handle in ("x", "y"):
            axis = np.array([1.0, 0, 0]) if handle == "x" else np.array([0, 1.0, 0])
            n = np.cross(axis, np.cross(d, axis))  # plano que contém o eixo e encara a câmera
            if np.linalg.norm(n) < 1e-9:
                return None
            return self._ray_plane(o, d, c, n / np.linalg.norm(n))
        return self._ray_plane(o, d, c, np.array([0, 0, 1.0]))

    def _gizmo_transform(self, pos: QPointF, mods) -> Affine | None:
        g = self._gdrag
        p = self._gizmo_point(pos, g["handle"], g["center"])
        if p is None or g["start"] is None:
            return None
        c = g["center"]
        if g["handle"] == "rot":
            a0 = math.atan2(g["start"][1] - c[1], g["start"][0] - c[0])
            a1 = math.atan2(p[1] - c[1], p[0] - c[0])
            deg = math.degrees(a1 - a0)
            step = 15.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
            deg = round(deg / step) * step
            return Affine.rotation(float(deg), (float(c[0]), float(c[1])))
        dx, dy = float(p[0] - g["start"][0]), float(p[1] - g["start"][1])  # float nativo: vai para o JSON
        if g["handle"] == "x":
            dy = 0.0
        elif g["handle"] == "y":
            dx = 0.0
        return Affine.translation(dx, dy)

    # --- interação ------------------------------------------------------------

    def mousePressEvent(self, e):
        self.setFocus()
        self._press = e.position()
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self._gizmo_handle(e.position())
            if handle:
                c, _size = self._gizmo_frame()
                self._gdrag = {"handle": handle, "center": c, "start": None, "t": None}
                self._gdrag["start"] = self._gizmo_point(e.position(), handle, c)
                return
        self._drag = (e.button(), e.position())

    def mouseMoveEvent(self, e):
        if self._gdrag is not None:
            t = self._gizmo_transform(e.position(), e.modifiers())
            if t is not None:
                self._gdrag["t"] = t
                ents = [self.doc.entities[i] for i in self.selection if i in self.doc.entities]
                self.override = {x.id: x.transformed(t) for x in ents}
                self._dyn_dirty = True
                self.update()
            return
        if self._drag is None:
            hot = self._gizmo_handle(e.position())
            if hot != self._hot:
                self._hot = hot
                self.setCursor(Qt.CursorShape.SizeAllCursor if hot else Qt.CursorShape.ArrowCursor)
                self.update()
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
        if self._gdrag is not None:
            g, self._gdrag = self._gdrag, None
            t = g["t"]
            self.override = {}
            self._dyn_dirty = True
            self.update()
            if t is not None and (abs(t.e) > 1e-9 or abs(t.f) > 1e-9 or abs(t.b) > 1e-12):
                self.transformRequested.emit(t, "Rotacionar (3D)" if g["handle"] == "rot" else "Mover (3D)")
            return
        moved = self._press is not None and (e.position() - self._press).manhattanLength() > CLICK_PX
        if e.button() == Qt.MouseButton.LeftButton and not moved:
            additive = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            self.picked.emit(self.pick_at(e.position()), additive)
        self._drag = None
        self._press = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._gdrag is not None:
            self._gdrag = None
            self.override = {}
            self._dyn_dirty = True
            self.update()
            return
        if e.key() == Qt.Key.Key_F:
            self.focus_selection()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.cam.distance = min(20_000.0, max(0.5, self.cam.distance * 0.85 ** (e.angleDelta().y() / 120)))
        self.update()

