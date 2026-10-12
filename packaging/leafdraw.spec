# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o LeafDraw (modo pasta: as DLLs do Qt ficam separadas, como pede a LGPL).

Uso:  pyinstaller packaging/leafdraw.spec --noconfirm
"""
import re
import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                  VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH).parent
SITE = Path(sys.prefix) / "Lib" / "site-packages"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "leafdraw" / "__init__.py").read_text()).group(1)
nums = [int(x) for x in re.findall(r"\d+", VERSION)[:4]] + [0, 0, 0, 0]

# --- licenças: projeto, Qt (LGPL) e cada dependência --------------------------
datas = [
    (str(ROOT / "leafdraw" / "resources"), "leafdraw/resources"),
]
licenses = [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt"), "."),
    (str(ROOT / "packaging" / "licenses" / "LGPL-3.0.txt"), "licenses"),
    (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/python"),
]
for pkg in ("moderngl", "glcontext", "numpy", "shapely", "ezdxf", "fonttools", "pyparsing", "typing_extensions"):
    for info in SITE.glob(f"{pkg}-*.dist-info"):
        for f in info.rglob("*"):
            if f.is_file() and re.search(r"LICEN|COPYING|NOTICE", f.name, re.I):
                rel = f.parent.relative_to(info)
                licenses.append((str(f), f"licenses/{pkg}/{rel.as_posix()}".rstrip("/.")))

# módulos do Qt que o LeafDraw não usa (o PySide6 completo passa de 600 MB)
QT_UNUSED = ["Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender", "QtBluetooth",
             "QtCharts", "QtConcurrent", "QtDataVisualization", "QtDesigner", "QtGraphs", "QtGraphsWidgets",
             "QtHelp", "QtHttpServer", "QtLocation", "QtMultimedia", "QtMultimediaWidgets", "QtNetworkAuth",
             "QtNfc", "QtPdf", "QtPdfWidgets", "QtPositioning", "QtQml", "QtQuick", "QtQuick3D",
             "QtQuickControls2", "QtQuickTest", "QtQuickWidgets", "QtRemoteObjects", "QtScxml", "QtSensors",
             "QtSerialBus", "QtSerialPort", "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvgWidgets",
             "QtTest", "QtTextToSpeech", "QtUiTools", "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick",
             "QtWebEngineWidgets", "QtWebSockets", "QtWebView", "QtXml", "QtAxContainer", "QtCanvasPainter"]
excludes = [f"PySide6.{m}" for m in QT_UNUSED] + ["tkinter", "matplotlib", "IPython", "pytest", "pyflakes",
                                                   "PyQt5", "PyQt6", "pydoc_data"]

a = Analysis(
    [str(ROOT / "packaging" / "leafdraw_launcher.py")],
    pathex=[str(ROOT)],
    datas=datas + licenses,
    hiddenimports=["glcontext", "glcontext.wgl", "moderngl"],
    excludes=excludes,
    noarchive=False,
)

# remove DLLs/plugins de módulos Qt excluídos que os hooks ainda trazem
UNUSED_DLL = re.compile(r"Qt6(" + "|".join(m[2:] for m in QT_UNUSED if m.startswith("Qt")) + r")\.dll$|"
                        r"Qt6Qml\w*\.dll$|Qt6VirtualKeyboard\w*\.dll$|[\\/]platforminputcontexts[\\/]|"
                        r"qtwebengine|QtWebEngineProcess|"
                        r"[\\/](qml|translations[\\/]qtwebengine)[\\/]", re.I)
a.binaries = [b for b in a.binaries if not UNUSED_DLL.search(b[0])]
a.datas = [d for d in a.datas if not UNUSED_DLL.search(d[0])]

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=tuple(nums[:4]), prodvers=tuple(nums[:4])),
    kids=[
        StringFileInfo([StringTable("041604B0", [
            StringStruct("CompanyName", "LeafDraw"),
            StringStruct("FileDescription", "LeafDraw — CAD para paisagismo"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "LeafDraw"),
            StringStruct("LegalCopyright", "GPL-3.0 — github.com/francisreboucas/leafdraw"),
            StringStruct("OriginalFilename", "LeafDraw.exe"),
            StringStruct("ProductName", "LeafDraw"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeafDraw",
    icon=str(ROOT / "packaging" / "leafdraw.ico"),
    version=version_info,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LeafDraw", upx=False)
