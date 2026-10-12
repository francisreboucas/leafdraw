from __future__ import annotations

from dataclasses import asdict, dataclass, field

from leafdraw.core.entities import new_id


@dataclass
class Layer:
    name: str
    color: str = "#e6e6e6"
    visible: bool = True
    locked: bool = False
    id: str = field(default_factory=new_id)
    lineweight: float = 0.25  # mm, na impressão

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Layer:
        names = Layer.__dataclass_fields__.keys()
        return Layer(**{k: v for k, v in d.items() if k in names})


# (id, nome, cor, espessura em mm) — a camada "0" sempre existe e não pode ser excluída.
DEFAULT_LAYERS = [
    ("0", "0", "#e6e6e6", 0.25),
    ("construcao", "Construção", "#9aa5b1", 0.35),
    ("canteiros", "Canteiros", "#c9a26b", 0.25),
    ("vegetacao", "Vegetação", "#6cc070", 0.18),
]
LINEWEIGHTS = [0.05, 0.09, 0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00, 1.40, 2.00]
