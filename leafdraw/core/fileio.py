"""Arquivo de projeto ``.leaf``: um zip contendo ``document.json``.

O zip deixa espaço para anexar depois imagens, referências externas e
miniaturas sem mudar o formato.
"""
from __future__ import annotations

import json
import zipfile

DOCUMENT_ENTRY = "document.json"
EXTENSION = ".leaf"


def save_document(doc, path: str):
    data = json.dumps(doc.to_dict(), ensure_ascii=False, indent=1)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(DOCUMENT_ENTRY, data)
    doc.mark_saved(path)


def load_document(doc, path: str):
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read(DOCUMENT_ENTRY).decode("utf-8"))
    doc.load_dict(data, path)
