# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o LeafDraw (modo pasta: as DLLs do Qt ficam separadas, como pede a LGPL).

Uso:  pyinstaller packaging/leafdraw.spec --noconfirm
"""
import json
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(SPECPATH).parent
SITE = Path(sysconfig.get_paths()["purelib"])
WINDOWS, MACOS = sys.platform == "win32", sys.platform == "darwin"
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
]
for lic in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"):
    if lic.is_file():
        licenses.append((str(lic), "licenses/python"))
        break
for pkg in ("moderngl", "glcontext", "numpy", "shapely", "ezdxf", "fonttools", "pyparsing", "typing_extensions"):
    for info in SITE.glob(f"{pkg}-*.dist-info"):
        for f in info.rglob("*"):
            if f.is_file() and re.search(r"LICEN|COPYING|NOTICE", f.name, re.I):
                rel = f.parent.relative_to(info)
                licenses.append((str(f), f"licenses/{pkg}/{rel.as_posix()}".rstrip("/.")))

# --- conversor DWG (tools/dwgconv, compilado pelo build.ps1/build.sh) e licenças das crates Rust ---
DWGCONV = ROOT / "tools" / "dwgconv"
DWGCONV_EXE = DWGCONV / "target" / "release" / ("dwgconv.exe" if WINDOWS else "dwgconv")
if not DWGCONV_EXE.is_file():
    raise SystemExit(f"{DWGCONV_EXE} não existe: rode 'cargo build --release' em tools/dwgconv")
binaries = [(str(DWGCONV_EXE), "dwgconv")]
meta = json.loads(subprocess.run(["cargo", "metadata", "--format-version", "1", "--locked"], cwd=DWGCONV,
                                 capture_output=True, text=True, check=True).stdout)
used = {n["id"] for n in meta["resolve"]["nodes"]}
for pkg in meta["packages"]:
    if pkg["id"] not in used or pkg["name"] == "dwgconv":
        continue
    for f in Path(pkg["manifest_path"]).parent.iterdir():
        if f.is_file() and re.search(r"LICEN|COPYING|NOTICE|COPYRIGHT", f.name, re.I):
            licenses.append((str(f), f"licenses/dwgconv/{pkg['name']}"))

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
    binaries=binaries,
    datas=datas + licenses,
    hiddenimports=["glcontext", "moderngl"] + (["glcontext.wgl"] if WINDOWS else
                                               ["glcontext.darwin"] if MACOS else ["glcontext.x11", "glcontext.egl"]),
    excludes=excludes,
    noarchive=False,
)

# remove bibliotecas/plugins de módulos Qt excluídos que os hooks ainda trazem
# (Windows: Qt6X.dll; Linux: libQt6X.so.6; macOS: QtX.framework)
UNUSED_LIB = "|".join(m[2:] for m in QT_UNUSED if m.startswith("Qt")) + r"|Qml\w*|VirtualKeyboard\w*"
# no Linux/macOS os plugins de entrada (IBus, compose) ficam: sem eles não há acento por tecla morta
UNUSED_DLL = re.compile(r"Qt6?(" + UNUSED_LIB + r")(\.dll$|\.so|\.framework|$)|"
                        + (r"[\\/]platforminputcontexts[\\/]|" if WINDOWS else "") +
                        r"qtwebengine|QtWebEngineProcess|"
                        r"[\\/](qml|translations[\\/]qtwebengine)[\\/]", re.I)
a.binaries = [b for b in a.binaries if not UNUSED_DLL.search(b[0])]
a.datas = [d for d in a.datas if not UNUSED_DLL.search(d[0])]

version_info = None
if WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                      VarFileInfo, VarStruct, VSVersionInfo)
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

ICON = ROOT / "packaging" / ("leafdraw.icns" if MACOS else "leafdraw.ico")
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeafDraw",
    icon=str(ICON),
    version=version_info,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LeafDraw", upx=False)

if MACOS:
    app = BUNDLE(
        coll,
        name="LeafDraw.app",
        icon=str(ICON),
        bundle_identifier="io.github.francisreboucas.leafdraw",
        version=VERSION,
        info_plist={
            "CFBundleName": "LeafDraw",
            "CFBundleDisplayName": "LeafDraw",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "CFBundleDevelopmentRegion": "pt_BR",
            "NSHumanReadableCopyright": "GPL-3.0 — github.com/francisreboucas/leafdraw",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Projeto LeafDraw",
                "CFBundleTypeExtensions": ["leaf"],
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
            }],
        },
    )
