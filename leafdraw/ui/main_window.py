from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, QSize, QStandardPaths, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSplitter, QStyle, QTabWidget, QToolBar, QToolButton, QUndoView)

from leafdraw import __version__
from leafdraw.core.catalog import default_catalog
from leafdraw.core.commands import AddEntities, RemoveEntities, ReplaceEntities
from leafdraw.core.document import Document
from leafdraw.core.dxf_io import dwg_supported, export_dxf, import_drawing, read_drawing
from leafdraw.core.fileio import EXTENSION, load_document, save_document, used_species
from leafdraw.core.schedule import area_schedule, plant_schedule, to_csv
from leafdraw.ui import tools as T
from leafdraw.ui.catalog_dialog import CatalogDialog
from leafdraw.ui.commandline import CommandLine
from leafdraw.ui.composer import SheetComposer
from leafdraw.ui.project_dialog import ProjectDialog
from leafdraw.ui.dxf_dialog import DxfImportDialog
from leafdraw.ui.icons import icon
from leafdraw.ui.items2d import SNAP_LABELS
from leafdraw.ui.panels.catalog_panel import CatalogPanel
from leafdraw.ui.panels.layers_panel import LayersPanel
from leafdraw.ui.panels.properties_panel import PropertiesPanel
from leafdraw.ui.panels.schedule_panel import SchedulePanel
from leafdraw.ui.viewport2d import SNAP_MODES, Viewport2D
from leafdraw.ui.viewport3d import Viewport3D

FILE_FILTER = f"Projetos LeafDraw (*{EXTENSION})"


@dataclass(frozen=True)
class ToolCommand:
    name: str
    label: str
    aliases: tuple[str, ...]
    tool: type
    group: str  # "draw" | "modify"


TOOL_COMMANDS = [
    ToolCommand("select", "Selecionar", ("S", "SEL"), T.SelectTool, "draw"),
    ToolCommand("line", "Linha", ("L", "LINHA"), T.LineTool, "draw"),
    ToolCommand("polyline", "Polilinha", ("PL", "PLINE"), T.PolylineTool, "draw"),
    ToolCommand("rect", "Retângulo", ("REC", "RET"), T.RectTool, "draw"),
    ToolCommand("circle", "Círculo", ("C", "CI"), T.CircleTool, "draw"),
    ToolCommand("arc", "Arco", ("A", "ARCO"), T.ArcTool, "draw"),
    ToolCommand("text", "Texto", ("T", "TX", "TEXTO"), T.TextTool, "draw"),
    ToolCommand("dimension", "Cota", ("COT", "DIM"), T.DimensionTool, "draw"),
    ToolCommand("hatch", "Hachura", ("H", "HA", "HACH"), T.HatchTool, "draw"),
    ToolCommand("move", "Mover", ("M", "MOVER"), T.MoveTool, "modify"),
    ToolCommand("copy", "Copiar", ("CO", "CP", "COPIAR"), T.CopyTool, "modify"),
    ToolCommand("rotate", "Rotacionar", ("RO", "ROT"), T.RotateTool, "modify"),
    ToolCommand("scale", "Escalar", ("SC", "ES", "ESCALA"), T.ScaleTool, "modify"),
    ToolCommand("mirror", "Espelhar", ("MI", "ESP"), T.MirrorTool, "modify"),
    ToolCommand("offset", "Offset", ("O", "OF", "OFFSET"), T.OffsetTool, "modify"),
    ToolCommand("explode", "Explodir", ("X", "EXP"), T.ExplodeTool, "modify"),
    ToolCommand("erase", "Apagar", ("E", "APAGAR"), T.EraseTool, "modify"),
    ToolCommand("trim", "Aparar", ("TR", "AP", "APARAR"), T.TrimTool, "modify"),
    ToolCommand("extend", "Estender", ("EST", "EXT", "ESTENDER"), T.ExtendTool, "modify"),
    ToolCommand("distance", "Medir distância", ("DI", "MED"), T.DistanceTool, "modify"),
    ToolCommand("label", "Rótulo de plantas", ("ETQ", "ROTULO"), T.LabelTool, "landscape"),
    ToolCommand("contour", "Curva de nível", ("CN", "CURVA"), T.ContourTool, "landscape"),
    ToolCommand("spot", "Cota de nível", ("NV", "COTANIVEL"), T.SpotHeightTool, "landscape"),
]

# ferramentas que dependem da espécie escolhida no Gerenciador de Objetos
SPECIES_TOOLS = {
    "plant": ("Planta isolada", ("PLANTA",), T.PlantTool),
    "planting": ("Maciço", ("MAC", "MACICO"), T.PlantingTool),
    "plantrow": ("Plantas em linha", ("LIN", "EMLINHA"), T.PlantRowTool),
}


def user_catalog_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "catalogo_usuario.json"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document(self)
        self.catalog = default_catalog(user_catalog_path())
        self.last_command: str | None = None
        self.resize(1500, 900)

        self.view2d = Viewport2D(self.doc, self.catalog)
        self.view3d = Viewport3D(self.doc, self.catalog)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.view2d)
        self.splitter.addWidget(self.view3d)
        self.splitter.setSizes([900, 600])
        self.composer = SheetComposer(self.doc, self.catalog, render3d=self.view3d.render_image,
                                      current_camera=lambda: self.view3d.cam.state())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.splitter, "Modelo")
        self.tabs.addTab(self.composer, "Folhas")
        self.setCentralWidget(self.tabs)

        self._build_docks()
        self._build_actions()
        self._build_menus_and_toolbars()
        self._build_statusbar()
        self._build_aliases()

        self.doc.modifiedChanged.connect(lambda _m: self._update_title())
        v = self.view2d
        v.toolChanged.connect(self._on_tool_changed)
        v.hintChanged.connect(self.cmdline.set_prompt)
        v.message.connect(lambda text: self.cmdline.log(text, "result"))
        v.typed.connect(self.cmdline.inject)
        v.cursorMoved.connect(self._on_cursor)
        self.cmdline.submitted.connect(self.on_command)
        self.cmdline.cancelled.connect(self._on_cmd_cancel)
        self.catalog_panel.speciesActivated.connect(self.start_species_tool)
        self.catalog_panel.editRequested.connect(self.edit_catalog)
        self.schedule_panel.exportRequested.connect(self.export_schedule)
        self.schedule_panel.speciesSelected.connect(self.select_species)
        self.composer.openInModel.connect(self._open_region_in_model)
        self.view3d.picked.connect(self._on_3d_pick)
        self.view3d.transformRequested.connect(self._apply_3d_transform)
        v.scene().selectionChanged.connect(lambda: self.view3d.set_selection(v.selected_ids()))
        self.composer.editProjectRequested.connect(self.edit_project)
        self.cmdline.set_prompt(v.tool.hint())

        self._restore_settings()
        self._update_title()

    # --- construção da interface -----------------------------------------

    def _dock(self, title: str, widget, area, name: str) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self):
        A = Qt.DockWidgetArea
        self.layers_panel = LayersPanel(self.doc)
        self.layers_dock = self._dock("Camadas", self.layers_panel, A.LeftDockWidgetArea, "dock_layers")
        self.history_dock = self._dock("Histórico", QUndoView(self.doc.undo_stack), A.LeftDockWidgetArea,
                                       "dock_history")
        self.tabifyDockWidget(self.layers_dock, self.history_dock)
        self.layers_dock.raise_()

        self.catalog_panel = CatalogPanel(self.catalog)
        self.catalog_dock = self._dock("Gerenciador de Objetos", self.catalog_panel, A.RightDockWidgetArea,
                                       "dock_catalog")
        self.props_panel = PropertiesPanel(self.doc, self.catalog, self.view2d)
        self.props_dock = self._dock("Propriedades", self.props_panel, A.RightDockWidgetArea, "dock_props")
        self.schedule_panel = SchedulePanel(self.doc, self.catalog)
        self.schedule_dock = self._dock("Quantitativos", self.schedule_panel, A.RightDockWidgetArea,
                                        "dock_schedule")
        self.tabifyDockWidget(self.props_dock, self.schedule_dock)
        self.props_dock.raise_()

        self.cmdline = CommandLine()
        self.cmd_dock = self._dock("Linha de comando", self.cmdline, A.BottomDockWidgetArea, "dock_cmd")

    def _action(self, text, slot=None, shortcut=None, icon_name=None, std_icon=None, checkable=False, tip=None):
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
        elif std_icon is not None:
            a.setIcon(self.style().standardIcon(std_icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        tip = tip or text.replace("&", "").rstrip("…")
        if shortcut:
            tip += f" ({QKeySequence(shortcut).toString()})"
        a.setToolTip(tip)
        if slot:
            (a.toggled if checkable else a.triggered).connect(slot)
        return a

    def _build_actions(self):
        SP = QStyle.StandardPixmap
        self.act_new = self._action("&Novo", self.file_new, QKeySequence.StandardKey.New, std_icon=SP.SP_FileIcon)
        self.act_open = self._action("&Abrir…", self.file_open, QKeySequence.StandardKey.Open,
                                     std_icon=SP.SP_DialogOpenButton)
        self.act_save = self._action("&Salvar", self.file_save, QKeySequence.StandardKey.Save,
                                     std_icon=SP.SP_DialogSaveButton)
        self.act_save_as = self._action("Salvar &como…", self.file_save_as, QKeySequence.StandardKey.SaveAs)
        self.act_import = self._action("&Importar DXF/DWG…", self.import_cad, "Ctrl+I", icon_name="import")
        self.act_export = self._action("&Exportar DXF…", self.export_cad, "Ctrl+Shift+E", icon_name="export")
        self.act_project = self._action("Dados do &projeto…", self.edit_project)
        self.act_pdf = self._action("Exportar &PDF das folhas…", lambda: self.composer.export_pdf(all_sheets=True),
                                    "Ctrl+Shift+P")
        self.act_print = self._action("Im&primir folhas…", self.print_sheets, QKeySequence.StandardKey.Print)
        self.act_quit = self._action("Sai&r", self.close, QKeySequence.StandardKey.Quit)

        self.act_undo = self.doc.undo_stack.createUndoAction(self, "&Desfazer")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setIcon(self.style().standardIcon(SP.SP_ArrowBack))
        self.act_redo = self.doc.undo_stack.createRedoAction(self, "&Refazer")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.setIcon(self.style().standardIcon(SP.SP_ArrowForward))
        self.act_delete = self._action("&Excluir", self.delete_selection, QKeySequence.StandardKey.Delete)
        self.act_select_all = self._action("Selecionar &tudo", self.view2d.select_all,
                                           QKeySequence.StandardKey.SelectAll)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[str, QAction] = {}
        for cmd in TOOL_COMMANDS:
            a = self._action(cmd.label, icon_name=cmd.name, checkable=True,
                             tip=f"{cmd.label} [{', '.join(cmd.aliases)}]")
            a.triggered.connect(lambda _c=False, n=cmd.name: self.run_tool(n))
            self.tool_group.addAction(a)
            self.tool_actions[cmd.name] = a
        for mode, (label, aliases, _cls) in SPECIES_TOOLS.items():
            a = self._action(label, None, icon_name=mode, checkable=True,
                             tip=f"{label} com a espécie escolhida no Gerenciador de Objetos [{', '.join(aliases)}]")
            a.triggered.connect(lambda _c=False, m=mode: self._species_tool_from_catalog(m))
            self.tool_group.addAction(a)
            self.tool_actions[mode] = a
        self.tool_actions["select"].setChecked(True)
        self.act_catalog = self._action("&Catálogo de espécies…", self.edit_catalog)
        self.act_export_schedule = self._action("Exportar &quantitativos (CSV)…", self.export_schedule,
                                                icon_name="schedule")

        self.act_zoom_ext = self._action("Zoom &extensão", self.zoom_extents, "Home", icon_name="zoom_extents")
        self.layout_group = QActionGroup(self)
        self.layout_actions = {}
        for name, text, key in (("2d", "Somente 2D", "F5"), ("3d", "Somente 3D", "F6"), ("split", "2D + 3D", "F7")):
            a = self._action(text, None, key, icon_name=f"layout_{name}", checkable=True)
            a.triggered.connect(lambda _c=False, n=name: self.set_layout(n))
            self.layout_group.addAction(a)
            self.layout_actions[name] = a
        self.layout_actions["split"].setChecked(True)

        self.cam_actions = []
        for name, text in (("top", "Topo"), ("front", "Frente"), ("right", "Direita"), ("persp", "Perspectiva")):
            a = self._action(f"3D: {text}", lambda _c=False, n=name: self.set_camera(n), icon_name=f"cam_{name}")
            self.cam_actions.append(a)
        self.act_ortho = self._action("3D: Projeção ortogonal", self.view3d.set_ortho, checkable=True)
        self.act_focus3d = self._action("3D: Focar seleção", self.view3d.focus_selection,
                                        tip="Enquadra a seleção na vista 3D (tecla F na vista 3D)")
        self.exag_group = QActionGroup(self)
        for k in (1, 2, 5, 10):
            a = self._action(f"{k}×", None, checkable=True)
            a.triggered.connect(lambda _c=False, k=k: self.view3d.set_exaggeration(float(k)))
            a.setChecked(k == 1)
            self.exag_group.addAction(a)

        self.act_snap_grid = self._action("Snap na grade", lambda v: setattr(self.view2d, "snap_grid", v),
                                          "F9", checkable=True)
        self.act_snap_obj = self._action("Snap em objetos", lambda v: setattr(self.view2d, "snap_objects", v),
                                         "F3", checkable=True)
        self.act_snap_obj.setChecked(True)
        self.act_ortho2d = self._action("Modo orto", lambda v: setattr(self.view2d, "ortho", v), "F8",
                                        checkable=True)
        self.snap_mode_actions = []
        for mode in SNAP_MODES:
            a = self._action(SNAP_LABELS[mode], None, checkable=True)
            a.setChecked(mode in self.view2d.snap_modes)
            a.toggled.connect(lambda on, m=mode: (self.view2d.snap_modes.add if on else self.view2d.snap_modes.discard)(m))
            self.snap_mode_actions.append(a)

    def _build_menus_and_toolbars(self):
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        m.addActions([self.act_new, self.act_open, self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_import, self.act_export])
        m.addSeparator()
        m.addActions([self.act_project, self.act_pdf, self.act_print])
        m.addSeparator()
        m.addAction(self.act_quit)

        m = mb.addMenu("&Editar")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_delete, self.act_select_all])

        draw = [self.tool_actions[c.name] for c in TOOL_COMMANDS if c.group == "draw"]
        modify = [self.tool_actions[c.name] for c in TOOL_COMMANDS if c.group == "modify"]
        landscape = [self.tool_actions[m] for m in SPECIES_TOOLS] + [
            self.tool_actions[c.name] for c in TOOL_COMMANDS if c.group == "landscape"]
        m = mb.addMenu("&Desenhar")
        m.addActions(draw)
        m = mb.addMenu("&Modificar")
        m.addActions(modify)
        m = mb.addMenu("&Paisagismo")
        m.addActions(landscape)
        m.addSeparator()
        m.addAction(self.schedule_dock.toggleViewAction())
        m.addAction(self.act_export_schedule)
        m.addSeparator()
        m.addAction(self.act_catalog)

        m = mb.addMenu("&Ferramentas")
        m.addActions([self.act_snap_obj, self.act_snap_grid, self.act_ortho2d])
        sm = m.addMenu("Modos de snap")
        sm.addActions(self.snap_mode_actions)

        m = mb.addMenu("&Vistas")
        m.addAction(self._action("&Modelo", lambda: self.tabs.setCurrentIndex(0), "Ctrl+1"))
        m.addAction(self._action("&Folhas", lambda: self.tabs.setCurrentIndex(1), "Ctrl+2"))
        m.addSeparator()
        m.addAction(self.act_zoom_ext)
        m.addSeparator()
        m.addActions(self.layout_group.actions())
        m.addSeparator()
        m.addActions(self.cam_actions)
        m.addAction(self.act_ortho)
        m.addAction(self.act_focus3d)
        em = m.addMenu("3D: Exagero vertical do terreno")
        em.addActions(self.exag_group.actions())

        m = mb.addMenu("&Janelas")
        for dock in (self.layers_dock, self.history_dock, self.catalog_dock, self.props_dock, self.schedule_dock,
                     self.cmd_dock):
            m.addAction(dock.toggleViewAction())

        m = mb.addMenu("Aj&uda")
        m.addAction(self._action("&Comandos e atalhos", self.show_commands_help))
        m.addAction(self._action("&Sobre o LeafDraw", self.about))

        def toolbar(title, name, actions, area=Qt.ToolBarArea.TopToolBarArea):
            tb = QToolBar(title, self)
            tb.setObjectName(name)
            tb.setIconSize(QSize(22, 22))
            tb.addActions(actions)
            self.addToolBar(area, tb)
            return tb

        tb = toolbar("Arquivo", "tb_file", [self.act_new, self.act_open, self.act_save, self.act_import])
        tb.addSeparator()
        tb.addActions([self.act_undo, self.act_redo])

        tb = toolbar("Camada", "tb_layer", [])
        tb.addWidget(QLabel(" Camada: "))
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(150)
        self.layer_combo.activated.connect(lambda i: self.doc.set_current_layer(self.layer_combo.itemData(i)))
        tb.addWidget(self.layer_combo)
        for sig in (self.doc.layersChanged, self.doc.currentLayerChanged, self.doc.documentReset):
            sig.connect(self._refresh_layer_combo)
        self._refresh_layer_combo()

        tb = toolbar("Vistas", "tb_views", [self.act_zoom_ext])
        tb.addSeparator()
        tb.addActions(self.layout_group.actions())
        tb.addSeparator()
        tb.addActions(self.cam_actions)

        toolbar("Desenhar", "tb_draw", draw, Qt.ToolBarArea.LeftToolBarArea)
        toolbar("Modificar", "tb_modify", modify, Qt.ToolBarArea.LeftToolBarArea)
        toolbar("Paisagismo", "tb_landscape", landscape, Qt.ToolBarArea.LeftToolBarArea)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.coord_label = QLabel()
        self.coord_label.setMinimumWidth(240)
        sb.addPermanentWidget(self.coord_label)
        for text, action in (("OBJETO", self.act_snap_obj), ("GRADE", self.act_snap_grid), ("ORTO", self.act_ortho2d)):
            b = QToolButton()
            b.setDefaultAction(action)
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setAutoRaise(True)
            if action is self.act_snap_obj:
                menu = QMenu(b)
                menu.addActions(self.snap_mode_actions)
                b.setMenu(menu)
                b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            sb.addPermanentWidget(b)

    def _build_aliases(self):
        self.aliases: dict[str, Callable[[], None]] = {}
        for cmd in TOOL_COMMANDS:
            for alias in (cmd.name.upper(), *cmd.aliases):
                self.aliases[alias] = lambda n=cmd.name: self.run_tool(n)
        for mode, (_label, aliases, _cls) in SPECIES_TOOLS.items():
            for alias in aliases:
                self.aliases[alias] = lambda m=mode: self._species_tool_from_catalog(m)
        extra = {
            ("CATALOGO",): self.edit_catalog,
            ("FOLHAS", "LAYOUT"): lambda: self.tabs.setCurrentIndex(1),
            ("MODELO", "MODEL"): lambda: self.tabs.setCurrentIndex(0),
            ("PDF",): lambda: self.composer.export_pdf(all_sheets=True),
            ("PROJETO",): self.edit_project,
            ("QUANT", "QTD"): self.show_schedule,
            ("Z", "ZE", "ZOOM"): self.zoom_extents,
            ("U", "DESFAZER"): self.doc.undo_stack.undo,
            ("REFAZER", "REDO"): self.doc.undo_stack.redo,
            ("IMPORTAR", "DXFIN"): self.import_cad,
            ("EXPORTAR", "DXFOUT"): self.export_cad,
            ("AJUDA", "?"): self.show_commands_help,
        }
        for keys, fn in extra.items():
            for k in keys:
                self.aliases[k] = fn

    # --- comandos ---------------------------------------------------------

    def run_tool(self, name: str):
        cmd = next(c for c in TOOL_COMMANDS if c.name == name)
        self.view2d.set_tool(cmd.tool(self.view2d))
        if name != "select":
            self.last_command = name.upper()

    def run_command(self, text: str) -> bool:
        fn = self.aliases.get(text.strip().upper())
        if fn is None:
            return False
        fn()
        return True

    def on_command(self, text: str):
        v = self.view2d
        t = text.strip()
        if not t:
            # Enter vazio: termina a ferramenta atual ou repete o último comando
            if not v.tool.is_select:
                v.tool.finish()
            elif self.last_command:
                self.run_command(self.last_command)
            v.setFocus()
            return
        self.cmdline.log(f"{self.cmdline.prompt.text()} {t}", "cmd")
        try:
            handled = v.submit_input(t)
        except ValueError as exc:
            self.cmdline.log(f"Entrada inválida: {exc}", "error")
            v.setFocus()
            return
        if not handled and not self.run_command(t):
            self.cmdline.log(f"Comando desconhecido: {t}  (digite ? para ver a lista)", "error")
        v.setFocus()

    def _on_cmd_cancel(self):
        self.view2d.escape()
        self.view2d.setFocus()

    def show_commands_help(self):
        lines = [f"{c.label}: {', '.join(c.aliases)}" for c in TOOL_COMMANDS]
        lines += [f"{label}: {', '.join(aliases)}" for label, aliases, _c in SPECIES_TOOLS.values()]
        lines += ["Zoom extensão: Z, ZE", "Desfazer: U", "Importar DXF: IMPORTAR", "Exportar DXF: EXPORTAR",
                  "Quantitativos: QUANT", "Catálogo: CATALOGO", "Folhas/Modelo: FOLHAS, MODELO",
                  "PDF das folhas: PDF", "Dados do projeto: PROJETO"]
        for line in lines:
            self.cmdline.log(line)
        self.cmdline.log("Coordenadas: x,y · @dx,dy · @dist<ângulo · número = distância na direção do cursor "
                         "· use ; como separador para decimais com vírgula (2,5;3)")

    def start_species_tool(self, species_id: str, mode: str = "plant"):
        self.view2d.set_tool(SPECIES_TOOLS[mode][2](self.view2d, species_id))
        self.last_command = SPECIES_TOOLS[mode][1][0]

    def _species_tool_from_catalog(self, mode: str):
        sid = self.catalog_panel.current_species()
        if sid:
            self.start_species_tool(sid, mode)
        else:
            self.tool_actions[self.view2d.tool.name].setChecked(True)
            self.cmdline.log("Escolha uma espécie no Gerenciador de Objetos.", "error")
            self.catalog_dock.show()
            self.catalog_dock.raise_()

    def edit_catalog(self):
        dlg = CatalogDialog(self.catalog, self, select=self.catalog_panel.current_species(),
                            in_use=used_species(self.doc))
        dlg.exec()
        if dlg.changed:
            self._catalog_changed()

    def _catalog_changed(self):
        self.catalog_panel.populate()
        self.view2d.refresh_items()
        self.view3d.mark_dirty()
        self.schedule_panel.refresh()
        self.props_panel.refresh()

    def show_schedule(self):
        self.schedule_dock.show()
        self.schedule_dock.raise_()

    def export_schedule(self):
        base = os.path.splitext(self.doc.file_path)[0] if self.doc.file_path else os.path.join(self._last_dir(), "projeto")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar quantitativos", base + " - quantitativos.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        csv = to_csv(plant_schedule(self.doc, self.catalog), area_schedule(self.doc))
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM: o Excel reconhece UTF-8
                f.write(csv)
        except OSError as exc:
            QMessageBox.critical(self, "Exportar quantitativos", f"Não foi possível salvar {path}:\n{exc}")
            return
        self.cmdline.log(f"Quantitativos exportados para {path}.", "result")

    def select_species(self, sid: str):
        v = self.view2d
        v.set_tool(T.SelectTool(v))
        v.scene().clearSelection()
        n = 0
        for it in v.items_by_id.values():
            if getattr(it.entity, "species", None) == sid and it.isVisible():
                it.setSelected(True)
                n += 1
        sp = self.catalog.get(sid)
        self.cmdline.log(f"{n} objeto(s) de {sp.nome_popular if sp else sid} selecionado(s).", "result")

    def delete_selection(self):
        ids = self.view2d.selected_ids()
        if ids:
            self.doc.undo_stack.push(RemoveEntities(self.doc, ids, f"Excluir {len(ids)} objeto(s)"))

    # --- estado da interface ----------------------------------------------

    def _refresh_layer_combo(self, *_):
        self.layer_combo.clear()
        for lid, layer in self.doc.layers.items():
            self.layer_combo.addItem(layer.name, lid)
        self.layer_combo.setCurrentIndex(list(self.doc.layers).index(self.doc.current_layer))

    def _update_title(self):
        name = os.path.basename(self.doc.file_path) if self.doc.file_path else "Sem título"
        self.setWindowTitle(f"{name}[*] — LeafDraw")
        self.setWindowModified(self.doc.is_modified())

    def _on_tool_changed(self, name):
        a = self.tool_actions.get(name)
        if a is not None:
            a.setChecked(True)

    def _on_cursor(self, x, y):
        text = f"X: {x:10.3f}   Y: {y:10.3f}"
        z = self.view3d.elevation_at(x, y)
        if z is not None:
            text += f"   Z: {z:8.2f}"
        self.coord_label.setText(text.replace(".", ","))

    def _on_3d_pick(self, eid: str, additive: bool):
        v = self.view2d
        if not v.tool.is_select:
            v.set_tool(T.SelectTool(v))
        it = v.items_by_id.get(eid)
        if not additive:
            v.scene().clearSelection()
        if it is not None and it.flags() & it.GraphicsItemFlag.ItemIsSelectable:
            it.setSelected(not it.isSelected() if additive else True)

    def _apply_3d_transform(self, t, text: str):
        ents = [self.doc.entities[i] for i in self.view2d.selected_ids() if i in self.doc.entities]
        if ents:
            self.doc.undo_stack.push(ReplaceEntities(self.doc, [e.transformed(t) for e in ents],
                                                     f"{text}: {len(ents)} objeto(s)"))

    def set_layout(self, name):
        self.tabs.setCurrentIndex(0)
        self.view2d.setVisible(name in ("2d", "split"))
        self.view3d.setVisible(name in ("3d", "split"))
        self.layout_actions[name].setChecked(True)

    def set_camera(self, name):
        if not self.view3d.isVisible():
            self.set_layout("split")
        self.view3d.set_view(name)
        self.act_ortho.setChecked(self.view3d.cam.ortho)

    def _open_region_in_model(self, x0, y0, x1, y1):
        self.tabs.setCurrentIndex(0)
        self.view2d.fitInView(QRectF(x0, y0, x1 - x0, y1 - y0), Qt.AspectRatioMode.KeepAspectRatio)

    def edit_project(self):
        dlg = ProjectDialog(self.doc.project, self)
        if dlg.exec():
            self.doc.set_project_info(dlg.values())

    def print_sheets(self):
        if not self.doc.sheets:
            QMessageBox.information(self, "Imprimir", "Crie uma folha na aba Folhas primeiro.")
            self.tabs.setCurrentIndex(1)
            return
        self.composer.print_sheets()

    def zoom_extents(self):
        self.view2d.zoom_extents()
        self.view3d.zoom_extents()

    # --- DXF / DWG --------------------------------------------------------

    def import_cad(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Importar desenho", self._last_dir(),
                "Desenhos CAD (*.dxf *.dwg);;DXF (*.dxf);;DWG (*.dwg)")
            if not path:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            drawing = read_drawing(path)
            imp = import_drawing(drawing, species_ids=[s.id for s in self.catalog.all()],
                                 existing_layers=self.doc.layers)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Importar desenho", f"Não foi possível ler {path}:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        if not imp.entities:
            QMessageBox.information(self, "Importar desenho", "O arquivo não contém objetos suportados.")
            return
        dlg = DxfImportDialog(path, imp, self)
        if not dlg.exec():
            return
        ents = imp.finalize(dlg.factor(), dlg.to_origin.isChecked())
        if dlg.lock.isChecked():
            for layer in imp.layers:
                layer.locked = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.doc.add_layers(imp.layers)
            name = os.path.basename(path)
            self.doc.undo_stack.push(AddEntities(self.doc, ents, f"Importar {name}"))
        finally:
            QApplication.restoreOverrideCursor()
        QSettings().setValue("last_dir", os.path.dirname(path))
        self.cmdline.log(f"Importados {len(ents)} objetos e {len(imp.layers)} camadas de {name}.", "result")
        self.zoom_extents()

    def export_cad(self):
        filters = "DXF (*.dxf)" + (";;DWG (*.dwg)" if dwg_supported() else "")
        base = os.path.splitext(self.doc.file_path)[0] if self.doc.file_path else os.path.join(self._last_dir(), "desenho")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar desenho", base + ".dxf", filters)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".dxf"
        try:
            export_dxf(self.doc, path, self.catalog)
        except Exception as exc:
            QMessageBox.critical(self, "Exportar desenho", f"Não foi possível exportar {path}:\n{exc}")
            return
        self.cmdline.log(f"Exportado para {path}.", "result")

    # --- arquivos ---------------------------------------------------------

    def maybe_save(self) -> bool:
        if not self.doc.is_modified():
            return True
        r = QMessageBox.question(
            self, "LeafDraw", "O projeto tem alterações não salvas. Deseja salvar?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.file_save()
        return r == QMessageBox.StandardButton.Discard

    def file_new(self):
        if self.maybe_save():
            self.doc.new()
            self.zoom_extents()

    def file_open(self, path: str | None = None):
        if not self.maybe_save():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", self._last_dir(), FILE_FILTER)
            if not path:
                return
        self.open_path(path)

    def open_path(self, path: str):
        if os.path.splitext(path)[1].lower() in (".dxf", ".dwg"):
            self.import_cad(path)
            return
        try:
            added = load_document(self.doc, path, self.catalog)
        except Exception as exc:  # arquivo corrompido, versão incompatível…
            QMessageBox.critical(self, "Abrir projeto", f"Não foi possível abrir {path}:\n{exc}")
            return
        if added:
            self.catalog_panel.populate()
            names = ", ".join(sp.nome_popular for sp in added)
            self.cmdline.log(f"Espécies trazidas pelo projeto (não estão no seu catálogo): {names}.", "result")
        QSettings().setValue("last_dir", os.path.dirname(path))
        self.zoom_extents()
        self._update_title()

    def file_save(self) -> bool:
        if not self.doc.file_path:
            return self.file_save_as()
        return self._save_to(self.doc.file_path)

    def file_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", self._last_dir(), FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        try:
            save_document(self.doc, path, self.catalog)
        except OSError as exc:
            QMessageBox.critical(self, "Salvar projeto", f"Não foi possível salvar {path}:\n{exc}")
            return False
        QSettings().setValue("last_dir", os.path.dirname(path))
        self._update_title()
        self.statusBar().showMessage(f"Salvo em {path}", 4000)
        return True

    def _last_dir(self) -> str:
        return QSettings().value("last_dir", os.path.expanduser("~"))

    def about(self):
        QMessageBox.about(self, "Sobre o LeafDraw",
                          f"<b>LeafDraw {__version__}</b><br>CAD para paisagismo.<br><br>"
                          "Construído com Qt for Python (PySide6, LGPLv3), moderngl, ezdxf e Shapely.")

    # --- janela -----------------------------------------------------------

    def _restore_settings(self):
        s = QSettings()
        if geom := s.value("geometry"):
            self.restoreGeometry(geom)
        if state := s.value("window_state"):
            self.restoreState(state)

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        s = QSettings()
        s.setValue("geometry", self.saveGeometry())
        s.setValue("window_state", self.saveState())
        e.accept()
