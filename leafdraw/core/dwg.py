"""Leitura e gravação de DWG pelo ``dwgconv``, o conversor DWG <-> DXF do LeafDraw.

O ``dwgconv`` (``tools/dwgconv``, em Rust sobre a acadrust) converte o DWG para um
DXF temporário que o ezdxf lê, e o caminho inverso na gravação. Procura o
executável em, nesta ordem: variável ``LEAFDRAW_DWGCONV``, pasta do pacote
instalado, ``tools/dwgconv/target/release`` (rodando do código-fonte) e PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from functools import cache
from pathlib import Path

EXE = "dwgconv.exe" if sys.platform == "win32" else "dwgconv"
DWG_VERSION = "R2018"
TIMEOUT = 600  # s


@cache
def converter() -> str | None:
    env = os.environ.get("LEAFDRAW_DWGCONV")
    candidates = [Path(env)] if env else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "dwgconv" / EXE)
    candidates.append(Path(__file__).resolve().parents[2] / "tools" / "dwgconv" / "target" / "release" / EXE)
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("dwgconv")


def available() -> bool:
    return converter() is not None


def _run(*args: str):
    exe = converter()
    if exe is None:
        raise RuntimeError("Conversor DWG (dwgconv) não encontrado. Rodando do código-fonte, compile-o com "
                           "\"cargo build --release\" em tools/dwgconv.")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT, creationflags=flags)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"A conversão DWG passou de {TIMEOUT // 60} minutos e foi interrompida.") from None
    if r.returncode != 0:
        msg = r.stderr.strip().splitlines()
        raise RuntimeError(msg[-1].removeprefix("erro: ") if msg else f"dwgconv terminou com código {r.returncode}")


def read_dwg(path: str):
    """Abre um DWG e devolve o documento ezdxf."""
    from ezdxf import recover

    with tempfile.TemporaryDirectory(prefix="leafdraw-") as tmp:
        dxf = Path(tmp) / "desenho.dxf"
        _run(str(path), str(dxf), "--failsafe")
        doc, _auditor = recover.readfile(dxf)
    return doc


def write_dwg(drawing, path: str, version: str = DWG_VERSION):
    """Grava um documento ezdxf como DWG (só substitui o arquivo de destino se a conversão der certo)."""
    with tempfile.TemporaryDirectory(prefix="leafdraw-") as tmp:
        dxf, dwg = Path(tmp) / "desenho.dxf", Path(tmp) / "desenho.dwg"
        drawing.saveas(dxf)
        _run(str(dxf), str(dwg), "--as", version)
        shutil.move(dwg, path)
