"""Catálogo de espécies vegetais."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "resources" / "catalog.json"

# Símbolos 2D/3D suportados.
SYMBOLS = ("arvore", "palmeira", "arbusto", "forracao")


@dataclass(frozen=True)
class Species:
    id: str
    nome_popular: str
    nome_cientifico: str
    categoria: str
    altura: float  # m, porte adulto
    copa: float  # m, diâmetro da copa adulta
    cor: str  # cor do símbolo
    simbolo: str = "arvore"
    insolacao: str = ""
    notas: str = ""


class PlantCatalog:
    def __init__(self, species: list[Species]):
        self._by_id = {s.id: s for s in species}

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CATALOG) -> PlantCatalog:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        species = [Species(**d) for d in data["especies"]]
        for s in species:
            if s.simbolo not in SYMBOLS:
                raise ValueError(f"{s.id}: símbolo desconhecido {s.simbolo!r}")
        return cls(species)

    def get(self, sid: str) -> Species | None:
        return self._by_id.get(sid)

    def all(self) -> list[Species]:
        return list(self._by_id.values())

    def categories(self) -> list[str]:
        return list(dict.fromkeys(s.categoria for s in self._by_id.values()))


_default: PlantCatalog | None = None


def default_catalog() -> PlantCatalog:
    global _default
    if _default is None:
        _default = PlantCatalog.load()
    return _default
