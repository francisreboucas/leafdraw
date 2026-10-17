from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from leafdraw import __version__
from leafdraw.ui.theme import dark_palette

ICON = Path(__file__).resolve().parent / "resources" / "icon.png"


def configure_opengl():
    """Precisa rodar antes de criar a QApplication."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def create_app(argv=None) -> QApplication:
    configure_opengl()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("LeafDraw")
    app.setOrganizationName("LeafDraw")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    return app


def _smoke_test(app, win, out_path: str):
    """Verifica a instalação: catálogo, documento, 2D, 3D (OpenGL), folhas e DWG; grava o resultado e sai."""
    import tempfile

    from leafdraw.core.commands import AddEntities
    from leafdraw.core.dxf_io import export_dxf, import_drawing, read_drawing
    from leafdraw.core.entities import Contour, Plant, Polyline
    from leafdraw.core.sheets import default_sheet

    code = 1
    try:
        sp = win.catalog.get("handroanthus-albus")
        doc = win.doc
        doc.undo_stack.push(AddEntities(doc, [
            Polyline(vertices=[(0, 0), (20, 0), (20, 10), (0, 10)], closed=True),
            Contour(vertices=[(0, 0), (20, 10)], elevation=1.0),
            Plant(position=(5, 5), species=sp.id, canopy=sp.copa, height=sp.altura),
        ]))
        win.zoom_extents()
        app.processEvents()
        img = win.view3d.render_image(None, 320, 200)
        if img is None:
            raise RuntimeError("OpenGL não inicializou (render_image retornou None)")
        sheet = default_sheet(doc.bounds())
        with tempfile.TemporaryDirectory(prefix="leafdraw-smoke-") as tmp:
            dwg_path = str(Path(tmp) / "teste.dwg")
            export_dxf(doc, dwg_path, win.catalog)
            n_dwg = len(import_drawing(read_drawing(dwg_path), [sp.id]).entities)
        if n_dwg != len(doc.entities):
            raise RuntimeError(f"DWG: {len(doc.entities)} entidades gravadas, {n_dwg} lidas")
        info = win.view3d.gl_info
        # biblioteca de modelos 3D empacotada: todo modelo do catálogo embutido abre
        from leafdraw.core.catalog import MODELS_DIR, PlantCatalog
        from leafdraw.core.gltf import load_model
        builtin = [s for s in PlantCatalog.load().all() if s.modelo_3d]
        for s in builtin:
            load_model(MODELS_DIR / s.modelo_3d)
        n_models = len(list(MODELS_DIR.rglob("*.glb")))
        Path(out_path).write_text(
            f"OK LeafDraw {__version__}\n"
            f"especies={len(win.catalog.all())} entidades={len(doc.entities)} "
            f"folha={sheet.paper} imagem3d={img.width()}x{img.height()} "
            f"modelos3d={n_models} (catálogo: {len(builtin)} abertos) dwg={n_dwg}\n"
            f"GL={info.get('GL_VERSION', '?')} {info.get('GL_RENDERER', '?')}\n", encoding="utf-8")
        code = 0
    except Exception:
        Path(out_path).write_text("FALHA\n" + traceback.format_exc(), encoding="utf-8")
    win.maybe_save = lambda: True
    QTimer.singleShot(0, lambda: app.exit(code))


def main():
    args = sys.argv[1:]
    smoke_out = None
    if "--smoke-test" in args:
        i = args.index("--smoke-test")
        smoke_out = args[i + 1] if i + 1 < len(args) else "leafdraw-smoke.txt"
        del args[i:i + 2]
    app = create_app()
    from leafdraw.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    if smoke_out:
        QTimer.singleShot(1500, lambda: _smoke_test(app, win, smoke_out))
    elif args:
        win.open_path(args[0])
    else:
        win.zoom_extents()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
