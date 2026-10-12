"""Importação e exportação DXF (e DWG via ODA File Converter, se instalado).

A importação acontece em duas etapas: ``import_drawing`` converte tudo nas
unidades nativas do arquivo; depois ``DxfImport.finalize`` aplica o fator de
unidade e o deslocamento escolhidos pelo usuário.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

import ezdxf
from ezdxf import colors as dxfcolors
from ezdxf import path as dxfpath
from ezdxf.addons import odafc

from leafdraw.core.entities import (Arc, Circle, Dimension, Entity, Hatch, Line, Plant, Polyline, Text,
                                    union_bounds)
from leafdraw.core.geom import Affine
from leafdraw.core.layers import Layer

# $INSUNITS -> metros
UNIT_FACTORS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}
UNIT_NAMES = {4: "milímetros", 5: "centímetros", 6: "metros", 1: "polegadas", 2: "pés", 14: "decímetros"}
PLANT_BLOCK_PREFIX = "LD_"
MAX_DEPTH = 12
WHITE = "#e6e6e6"  # ACI 7 (branco/preto) no fundo escuro

PATTERN_TO_DXF = {"diagonal": "ANSI31", "cross": "ANSI37", "horizontal": "LINE", "grass": "GRASS",
                  "dots": "DOTS", "gravel": "AR-CONC"}
DXF_TO_PATTERN = {v: k for k, v in PATTERN_TO_DXF.items()} | {"NET": "cross", "AR-SAND": "dots"}
# espaçamento de referência (unidades do padrão em escala 1) para converter a escala
PATTERN_SPACING = 3.175


def dwg_supported() -> bool:
    return odafc.is_installed()


def read_drawing(path: str):
    if Path(path).suffix.lower() == ".dwg":
        if not dwg_supported():
            raise RuntimeError("Para abrir DWG instale o ODA File Converter (gratuito) "
                               "em https://www.opendesign.com/guestfiles/oda_file_converter")
        return odafc.readfile(path)
    from ezdxf import recover

    doc, _auditor = recover.readfile(path)
    return doc


def _hex(rgb) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _aci_hex(aci: int) -> str:
    aci = abs(aci)
    if aci in (7, 0, 256) or not 1 <= aci <= 255:
        return WHITE
    return _hex(dxfcolors.aci2rgb(aci))


@dataclass
class DxfImport:
    layers: list[Layer]
    entities: list[Entity]
    insunits: int
    skipped: Counter = field(default_factory=Counter)

    def bounds(self):
        return union_bounds(e.bounds() for e in self.entities)

    def guess_factor(self) -> float:
        if self.insunits in UNIT_FACTORS:
            return UNIT_FACTORS[self.insunits]
        b = self.bounds()
        if b is None:
            return 1.0
        size = max(b[2] - b[0], b[3] - b[1])
        return 0.001 if size > 5000 else 0.01 if size > 500 else 1.0

    def finalize(self, factor: float, to_origin: bool) -> list[Entity]:
        t = Affine.scaling(factor)
        if to_origin and (b := self.bounds()) is not None:
            t = Affine.translation(-b[0] * factor, -b[1] * factor) @ t
        out = []
        for e in self.entities:
            ne = e.transformed(t)
            if isinstance(ne, Plant):
                ne = replace(ne, canopy=ne.canopy * factor, height=ne.height * factor)
            out.append(ne)
        return out


class _Importer:
    def __init__(self, drawing, species_ids, existing_layers: dict[str, Layer]):
        self.dwg = drawing
        self.species_ids = set(species_ids or ())
        self.entities: list[Entity] = []
        self.skipped = Counter()
        self.layer_ids: dict[str, str] = {}
        self.layers: list[Layer] = []
        by_name = {l.name.lower(): l for l in existing_layers.values()}
        for dl in drawing.layers:
            name = dl.dxf.name
            if name.lower() in by_name:
                self.layer_ids[name.lower()] = by_name[name.lower()].id
                continue
            color = _hex(dl.rgb) if dl.rgb else _aci_hex(dl.color)
            lw = dl.dxf.get("lineweight", -3)
            layer = Layer(name=name, color=color, visible=not (dl.is_off() or dl.is_frozen()),
                          locked=dl.is_locked(), lineweight=lw / 100 if lw > 0 else 0.25)
            self.layers.append(layer)
            self.layer_ids[name.lower()] = layer.id

    def layer_id(self, name: str) -> str:
        key = (name or "0").lower()
        if key not in self.layer_ids:
            layer = Layer(name=name)
            self.layers.append(layer)
            self.layer_ids[key] = layer.id
        return self.layer_ids[key]

    def color(self, e, parent_color: str) -> str:
        if e.rgb:
            return _hex(e.rgb)
        aci = e.dxf.get("color", 256)
        if aci == 256:
            return ""
        if aci == 0:  # BYBLOCK
            return parent_color
        return _aci_hex(aci)

    def run(self):
        for e in self.dwg.modelspace():
            self.convert(e, "0", "", 0, top=True)

    def add(self, ent: Entity):
        # o ezdxf pode devolver escalares numpy; o documento guarda só float nativo
        for f in fields(ent):
            setattr(ent, f.name, _native(getattr(ent, f.name)))
        self.entities.append(ent)

    def convert(self, e, parent_layer: str, parent_color: str, depth: int, top: bool = False):
        t = e.dxftype()
        layer_name = e.dxf.get("layer", "0")
        if layer_name == "0" and not top:
            layer_name = parent_layer  # entidades na camada 0 herdam a camada do bloco
        base = {"layer": self.layer_id(layer_name), "color": self.color(e, parent_color)}
        try:
            handler = getattr(self, "_" + t.lower(), None)
            if handler is None:
                self.skipped[t] += 1
                return
            handler(e, base, layer_name, depth)
        except Exception:  # entidade malformada: pula sem abortar a importação
            self.skipped[t] += 1

    # --- tipos ------------------------------------------------------------

    def _line(self, e, base, *_):
        s, en = e.dxf.start, e.dxf.end
        self.add(Line(p1=(s.x, s.y), p2=(en.x, en.y), **base))

    def _flatten(self, e, base, closed_hint=False):
        p = dxfpath.make_path(e)
        self._add_path(p, base, closed_hint)

    def _add_path(self, p, base, closed_hint=False):
        cps = list(p.control_vertices())
        if len(cps) < 2:
            return
        xs = [v.x for v in cps]
        ys = [v.y for v in cps]
        size = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        pts = [(v.x, v.y) for v in p.flattening(distance=size * 1e-3, segments=8)]
        closed = closed_hint or (len(pts) > 2 and math.dist(pts[0], pts[-1]) < size * 1e-9)
        if closed and len(pts) > 2 and math.dist(pts[0], pts[-1]) < size * 1e-9:
            pts = pts[:-1]
        if len(pts) >= 2:
            self.add(Polyline(vertices=pts, closed=closed and len(pts) >= 3, **base))

    @staticmethod
    def _default_extrusion(e) -> bool:
        z = e.dxf.get("extrusion", (0, 0, 1))
        return abs(z[0]) < 1e-9 and abs(z[1]) < 1e-9 and z[2] > 0

    def _lwpolyline(self, e, base, *_):
        pts = list(e.get_points("xyb"))
        if self._default_extrusion(e) and all(abs(b) < 1e-12 for _x, _y, b in pts):
            verts = [(x, y) for x, y, _b in pts]
            if len(verts) >= 2:
                self.add(Polyline(vertices=verts, closed=e.closed and len(verts) >= 3, **base))
            return
        self._flatten(e, base, e.closed)

    def _polyline(self, e, base, *_):
        if e.is_2d_polyline or e.is_3d_polyline:
            self._flatten(e, base, e.is_closed)
        else:
            self.skipped["POLYLINE (malha)"] += 1

    def _circle(self, e, base, *_):
        z = e.dxf.extrusion
        if abs(z[0]) > 1e-9 or abs(z[1]) > 1e-9:
            self._flatten(e, base, True)
            return
        c = e.ocs().to_wcs(e.dxf.center)
        self.add(Circle(center=(c.x, c.y), radius=e.dxf.radius, **base))

    def _arc(self, e, base, *_):
        z = e.dxf.extrusion
        if abs(z[0]) > 1e-9 or abs(z[1]) > 1e-9:
            self._flatten(e, base)
            return
        c = e.ocs().to_wcs(e.dxf.center)
        s, en = e.dxf.start_angle, e.dxf.end_angle
        if z[2] < 0:  # OCS espelhado em X
            s, en = 180 - en, 180 - s
        self.add(Arc(center=(c.x, c.y), radius=e.dxf.radius, start=s % 360, end=en % 360, **base))

    def _ellipse(self, e, base, *_):
        self._flatten(e, base)

    def _spline(self, e, base, *_):
        self._flatten(e, base, e.closed)

    def _text(self, e, base, *_):
        txt = e.plain_text()
        if txt.strip():
            ins = e.dxf.insert
            self.add(Text(position=(ins.x, ins.y), text=txt, height=e.dxf.height,
                          rotation=e.dxf.get("rotation", 0.0), **base))

    _attrib = _text

    def _mtext(self, e, base, *_):
        txt = e.plain_text(split=False)
        if not txt.strip():
            return
        h = e.dxf.get("char_height", 1.0)
        rot = e.get_rotation()
        n = txt.count("\n") + 1
        att = e.dxf.get("attachment_point", 1)
        # Text usa a linha de base da 1ª linha; MTEXT ancora pelo canto
        if att in (1, 2, 3):
            down = h
        elif att in (4, 5, 6):
            down = h - (n - 1) * h * Text.LINE_SPACING / 2 - h / 2
        else:
            down = -(n - 1) * h * Text.LINE_SPACING
        ins = e.dxf.insert
        r = math.radians(rot)
        pos = (ins.x + math.sin(r) * down, ins.y - math.cos(r) * down)
        self.add(Text(position=pos, text=txt, height=h, rotation=rot, **base))

    def _hatch(self, e, base, *_):
        loops = []
        for p in dxfpath.from_hatch(e):
            cps = list(p.control_vertices())
            if len(cps) < 3:
                continue
            xs = [v.x for v in cps]
            size = (max(xs) - min(xs)) or 1.0
            pts = [(v.x, v.y) for v in p.flattening(distance=size * 1e-3, segments=8)]
            if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-9:
                pts = pts[:-1]
            if len(pts) >= 3:
                loops.append(pts)
        if not loops:
            return
        loops.sort(key=lambda l: -abs(_area(l)))
        if e.dxf.solid_fill:
            pattern, scale = "solid", 1.0
        else:
            name = (e.dxf.get("pattern_name") or "").upper()
            pattern = DXF_TO_PATTERN.get(name, "diagonal")
            scale = e.dxf.get("pattern_scale", 1.0) * PATTERN_SPACING * math.sqrt(2)
        self.add(Hatch(loops=loops, pattern=pattern, scale=scale, angle=e.dxf.get("pattern_angle", 0.0), **base))

    def _solid(self, e, base, *_):
        vs = [e.dxf.get(f"vtx{i}") for i in range(4)]
        vs = [v for v in vs if v is not None]
        if len(vs) == 4:
            vs = [vs[0], vs[1], vs[3], vs[2]]  # ordem "Z" do SOLID
        pts = []
        for v in vs:
            if not pts or math.dist(pts[-1], (v.x, v.y)) > 1e-12:
                pts.append((v.x, v.y))
        if len(pts) >= 3:
            self.add(Hatch(loops=[pts], pattern="solid", **base))

    _trace = _solid

    def _insert(self, e, base, layer_name, depth):
        if depth >= MAX_DEPTH:
            self.skipped["INSERT (aninhamento excessivo)"] += 1
            return
        name = e.dxf.name
        if name.startswith(PLANT_BLOCK_PREFIX) and name[len(PLANT_BLOCK_PREFIX):] in self.species_ids:
            ins = e.dxf.insert
            r = abs(e.dxf.get("xscale", 1.0))
            self.add(Plant(position=(ins.x, ins.y), species=name[len(PLANT_BLOCK_PREFIX):], canopy=2 * r,
                           height=e.dxf.get("zscale", 1.0) if e.dxf.hasattr("zscale") else 1.0, **base))
            return
        color = base["color"]
        for ins in e.multi_insert():
            for sub in ins.virtual_entities():
                self.convert(sub, layer_name, color, depth + 1)
            for att in ins.attribs:
                if not att.is_invisible:
                    self.convert(att, layer_name, color, depth + 1)

    def _dimension(self, e, base, layer_name, depth):
        if e.dimtype in (0, 1):  # linear/alinhada; só vira Dimension se for paralela a p1→p2
            p1, p2, loc = e.dxf.defpoint2, e.dxf.defpoint3, e.dxf.defpoint
            L = math.hypot(p2.x - p1.x, p2.y - p1.y)
            parallel = e.dimtype == 1
            if e.dimtype == 0 and L > 1e-12:
                a = math.radians(e.dxf.get("angle", 0.0))
                parallel = abs(math.sin(a - math.atan2(p2.y - p1.y, p2.x - p1.x))) < 1e-6
            if L > 1e-12 and parallel:
                off = ((p2.x - p1.x) * (loc.y - p1.y) - (p2.y - p1.y) * (loc.x - p1.x)) / L
                ov = e.override()
                h = (ov.get("dimtxt", 2.5) or 2.5) * (ov.get("dimscale", 1.0) or 1.0)
                txt = e.dxf.get("text", "")
                self.add(Dimension(p1=(p1.x, p1.y), p2=(p2.x, p2.y), offset=off, text_height=h,
                                   decimals=int(ov.get("dimdec", 2) or 2),
                                   text_override="" if txt in ("", "<>") else txt, **base))
                return
        for sub in e.virtual_entities():
            self.convert(sub, layer_name, base["color"], depth + 1)

    def _point(self, e, base, *_):
        self.skipped["POINT"] += 1


def _native(v):
    if isinstance(v, tuple):
        return tuple(float(x) for x in v)
    if isinstance(v, list):
        return [_native(x) for x in v]
    if isinstance(v, (str, bool, int)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _area(pts) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2


def import_drawing(drawing, species_ids=(), existing_layers=None) -> DxfImport:
    imp = _Importer(drawing, species_ids, existing_layers or {})
    imp.run()
    used = {e.layer for e in imp.entities}
    layers = [l for l in imp.layers if l.id in used]
    return DxfImport(layers=layers, entities=imp.entities, insunits=drawing.header.get("$INSUNITS", 0),
                     skipped=imp.skipped)


# --- exportação ------------------------------------------------------------

_INVALID = re.compile(r'[<>/\\":;?*|=`]')


def _table_name(name: str) -> str:
    return _INVALID.sub("_", name).strip() or "_"


def export_dxf(doc, path: str, catalog=None):
    """Exporta em metros (R2018). Plantas viram blocos ``LD_<espécie>`` de raio 1."""
    out = ezdxf.new("R2018", setup=True)
    out.units = ezdxf.units.M
    out.header["$MEASUREMENT"] = 1
    msp = out.modelspace()

    names: dict[str, str] = {}
    for lid, layer in doc.layers.items():
        name = "0" if lid == "0" else _table_name(layer.name)
        names[lid] = name
        dl = out.layers.get(name) if name in out.layers else out.layers.add(name)
        dl.rgb = _rgb(layer.color)
        dl.dxf.lineweight = int(round(layer.lineweight * 100))
        if not layer.visible:
            dl.off()
        if layer.locked:
            dl.lock()

    for e in doc.entities.values():
        layer = doc.layer_for(e)
        attribs = {"layer": names.get(layer.id, "0")}
        if e.color:
            attribs["true_color"] = dxfcolors.rgb2int(_rgb(e.color))
        _export_entity(out, msp, e, attribs, catalog)
    if Path(path).suffix.lower() == ".dwg":
        if not dwg_supported():
            raise RuntimeError("Para salvar DWG instale o ODA File Converter.")
        odafc.export_dwg(out, path, replace=True)
    else:
        out.saveas(path)


def _export_entity(out, msp, e: Entity, attribs: dict, catalog):
    if isinstance(e, Line):
        msp.add_line(e.p1, e.p2, dxfattribs=attribs)
    elif isinstance(e, Polyline):
        msp.add_lwpolyline(e.vertices, close=e.closed, dxfattribs=attribs)
    elif isinstance(e, Circle):
        msp.add_circle(e.center, e.radius, dxfattribs=attribs)
    elif isinstance(e, Arc):
        msp.add_arc(e.center, e.radius, e.start, e.end, dxfattribs=attribs)
    elif isinstance(e, Text):
        if "\n" in e.text:
            r = math.radians(e.rotation)
            top = (e.position[0] - math.sin(r) * e.height, e.position[1] + math.cos(r) * e.height)
            msp.add_mtext(e.text.replace("\n", "\\P"), dxfattribs={
                **attribs, "char_height": e.height, "rotation": e.rotation, "insert": top,
                "attachment_point": 1, "line_spacing_factor": Text.LINE_SPACING / 1.6667})
        else:
            msp.add_text(e.text, height=e.height, rotation=e.rotation,
                         dxfattribs={**attribs, "insert": e.position})
    elif isinstance(e, Dimension):
        h = e.text_height
        dim = msp.add_aligned_dim(p1=e.p1, p2=e.p2, distance=e.offset, dimstyle="EZDXF", override={
            "dimtxt": h, "dimtsz": h * 0.5, "dimasz": h, "dimexe": h * 0.6, "dimexo": h * 0.3,
            "dimgap": h * 0.3, "dimdec": e.decimals, "dimdsep": ord(","), "dimtad": 1},
            dxfattribs=attribs, text=e.text_override or "<>")
        dim.render()
    elif isinstance(e, Hatch):
        h = msp.add_hatch(dxfattribs=attribs)
        if e.pattern == "solid":
            h.set_solid_fill(rgb=_rgb(e.color) if e.color else None)
        else:
            h.set_pattern_fill(PATTERN_TO_DXF.get(e.pattern, "ANSI31"), angle=e.angle,
                               scale=e.scale / (PATTERN_SPACING * math.sqrt(2)))
        for loop in e.loops:
            h.paths.add_polyline_path(loop, is_closed=True)
    elif isinstance(e, Plant):
        name = PLANT_BLOCK_PREFIX + _table_name(e.species or "planta")
        if name not in out.blocks:
            blk = out.blocks.new(name)
            blk.add_circle((0, 0), 1.0)
            blk.add_line((-0.12, 0), (0.12, 0))
            blk.add_line((0, -0.12), (0, 0.12))
        r = e.canopy / 2
        msp.add_blockref(name, e.position, dxfattribs={**attribs, "xscale": r, "yscale": r, "zscale": e.height})
