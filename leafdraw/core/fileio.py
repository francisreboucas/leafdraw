"""Arquivo de projeto ``.leaf``: um zip contendo ``document.json``.

O zip deixa espaço para anexar depois imagens, referências externas e
miniaturas sem mudar o formato. As espécies usadas no projeto vão junto, para
que ele abra igual em outra máquina.
"""
from __future__ import annotations

import json
import zipfile

from leafdraw.core.catalog import Species

DOCUMENT_ENTRY = "document.json"
EXTENSION = ".leaf"


def used_species(doc) -> set[str]:
    return {sid for e in doc.entities.values() if (sid := getattr(e, "species", ""))}


def save_document(doc, path: str, catalog=None):
    data = doc.to_dict()
    if catalog is not None:
        data["species"] = [sp.to_dict() for sid in sorted(used_species(doc)) if (sp := catalog.get(sid))]
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(DOCUMENT_ENTRY, payload)
    doc.mark_saved(path)


def load_document(doc, path: str, catalog=None) -> list[Species]:
    """Carrega o projeto. Espécies embutidas que faltam no ``catalog`` são
    acrescentadas antes de as vistas serem recriadas; retorna essas espécies."""
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read(DOCUMENT_ENTRY).decode("utf-8"))
    species = [Species.from_dict(d) for d in data.get("species", [])]
    added = catalog.add_project_species(species) if catalog is not None else []
    doc.load_dict(data, path)
    return added
