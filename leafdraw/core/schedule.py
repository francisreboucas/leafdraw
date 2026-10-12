"""Quantitativos: plantas por espécie e áreas por tipo de revestimento."""
from __future__ import annotations

from dataclasses import dataclass

from leafdraw.core.entities import HATCH_PATTERNS, Hatch, Plant, PlantingArea


@dataclass
class PlantRow:
    species: str
    nome_popular: str
    nome_cientifico: str
    categoria: str
    altura: float
    copa: float
    individual: int = 0  # plantas isoladas
    massed: int = 0  # mudas em maciços
    massed_area: float = 0.0  # m² de maciços

    @property
    def total(self) -> int:
        return self.individual + self.massed


@dataclass
class AreaRow:
    label: str
    area: float
    count: int


def plant_schedule(doc, catalog) -> list[PlantRow]:
    rows: dict[str, PlantRow] = {}

    def row(sid: str) -> PlantRow:
        if sid not in rows:
            sp = catalog.get(sid)
            rows[sid] = PlantRow(
                species=sid,
                nome_popular=sp.nome_popular if sp else sid,
                nome_cientifico=sp.nome_cientifico if sp else "",
                categoria=sp.categoria if sp else "",
                altura=sp.altura if sp else 0.0,
                copa=sp.copa if sp else 0.0,
            )
        return rows[sid]

    for e in doc.entities.values():
        if isinstance(e, Plant):
            row(e.species).individual += 1
        elif isinstance(e, PlantingArea):
            r = row(e.species)
            r.massed += e.count
            r.massed_area += e.area
    order = {c: i for i, c in enumerate(catalog.categories())}
    return sorted(rows.values(), key=lambda r: (order.get(r.categoria, len(order)), r.nome_popular))


def area_schedule(doc) -> list[AreaRow]:
    rows: dict[str, AreaRow] = {}
    for e in doc.entities.values():
        if isinstance(e, Hatch):
            label = HATCH_PATTERNS.get(e.pattern, e.pattern)
            r = rows.setdefault(label, AreaRow(label, 0.0, 0))
            r.area += e.area
            r.count += 1
    return sorted(rows.values(), key=lambda r: -r.area)


def _n(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}".replace(".", ",")


def to_csv(plants: list[PlantRow], areas: list[AreaRow]) -> str:
    """CSV com ';' e vírgula decimal (abre direto no Excel em pt-BR)."""
    lines = ["Categoria;Nome popular;Nome científico;Altura (m);Copa (m);Isoladas;Em maciço;"
             "Área de maciço (m²);Total (un)"]
    for r in plants:
        lines.append(";".join([r.categoria, r.nome_popular, r.nome_cientifico, _n(r.altura), _n(r.copa),
                               str(r.individual), str(r.massed), _n(r.massed_area), str(r.total)]))
    lines.append(f";;;;;;;Total de mudas;{sum(r.total for r in plants)}")
    if areas:
        lines += ["", "Revestimento;Área (m²);Hachuras"]
        lines += [f"{a.label};{_n(a.area)};{a.count}" for a in areas]
    return "\r\n".join(lines) + "\r\n"
