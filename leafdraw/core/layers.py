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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Layer:
        return Layer(**d)


# (id, nome, cor) — a camada "0" sempre existe e não pode ser excluída.
DEFAULT_LAYERS = [
    ("0", "0", "#e6e6e6"),
    ("construcao", "Construção", "#9aa5b1"),
    ("canteiros", "Canteiros", "#c9a26b"),
    ("vegetacao", "Vegetação", "#6cc070"),
]
