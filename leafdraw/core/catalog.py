"""Catálogo de espécies vegetais.

Três origens, em ordem de prioridade:

* **usuário** — espécies criadas ou editadas pelo usuário (arquivo próprio,
  vale para todos os projetos);
* **embutido** — o catálogo que acompanha o LeafDraw (somente leitura);
* **projeto** — espécies trazidas por um arquivo ``.leaf`` aberto que não
  existem nesta máquina (não são gravadas no catálogo do usuário).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "resources" / "catalog.json"
MODELS_DIR = DEFAULT_CATALOG.parent / "models"  # modelos 3D (.glb) que acompanham o LeafDraw
PROJECT_MODELS_DIR = DEFAULT_CATALOG.parents[2] / "modelos"  # biblioteca de modelos ao rodar do código-fonte

# Símbolos 2D/3D suportados.
SYMBOLS = {"arvore": "Árvore", "palmeira": "Palmeira", "arbusto": "Arbusto", "forracao": "Forração"}

# Origem da espécie em relação à flora brasileira ("" = não informada).
ORIGENS = {"": "Não informada", "nativa": "Nativa", "exotica": "Exótica"}

# Desenho próprio (bloco importado): ((fechado, ((x, y), ...)), ...) em unidades normalizadas.
# Planta: centrado na origem, cabe no raio 1. Vista: x em [-0,5; 0,5], y em [0; 1] (base no chão).
Drawing = tuple[tuple[bool, tuple[tuple[float, float], ...]], ...]


def drawing_from_json(v) -> Drawing | None:
    if not v:
        return None
    return tuple((bool(closed), tuple((float(x), float(y)) for x, y in pts)) for closed, pts in v)


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
    origem: str = ""  # chave de ORIGENS
    notas: str = ""
    desenho_planta: Drawing | None = None  # None = símbolo automático
    desenho_vista: Drawing | None = None
    modelo_3d: str = ""  # arquivo .glb/.gltf; vazio = forma procedural do símbolo

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Species:
        names = Species.__dataclass_fields__.keys()
        d = {k: v for k, v in d.items() if k in names}
        for k in ("desenho_planta", "desenho_vista"):
            d[k] = drawing_from_json(d.get(k))
        sp = Species(**d)
        if sp.simbolo not in SYMBOLS:
            raise ValueError(f"{sp.id}: símbolo desconhecido {sp.simbolo!r}")
        if sp.origem not in ORIGENS:
            raise ValueError(f"{sp.id}: origem desconhecida {sp.origem!r}")
        return sp


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "especie"


class PlantCatalog:
    def __init__(self, species: list[Species], user_species: list[Species] = (), user_path: Path | None = None):
        self._builtin = {s.id: s for s in species}
        self._user = {s.id: s for s in user_species}
        self._project: dict[str, Species] = {}
        self.user_path = Path(user_path) if user_path else None

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CATALOG, user_path: str | Path | None = None) -> PlantCatalog:
        builtin = _read(path)
        user = _read(user_path) if user_path and Path(user_path).exists() else []
        return cls(builtin, user, user_path)

    # --- consulta ---------------------------------------------------------

    def get(self, sid: str) -> Species | None:
        return self._user.get(sid) or self._builtin.get(sid) or self._project.get(sid)

    def model_file(self, sp: Species | None) -> Path | None:
        """Caminho do modelo 3D da espécie: absoluto, ou relativo à pasta de modelos
        embutida, à biblioteca ``modelos/`` do projeto ou à pasta do catálogo do usuário.
        None se não houver arquivo."""
        if sp is None or not sp.modelo_3d:
            return None
        p = Path(sp.modelo_3d)
        if p.is_absolute():
            return p if p.is_file() else None
        dirs = [MODELS_DIR, PROJECT_MODELS_DIR]
        if self.user_path:
            dirs += [self.user_path.parent / "models", self.user_path.parent]
        return next((d / p for d in dirs if (d / p).is_file()), None)

    def all(self) -> list[Species]:
        merged = {**self._project, **self._builtin, **self._user}
        return list(merged.values())

    def categories(self) -> list[str]:
        return list(dict.fromkeys(s.categoria for s in self.all()))

    def origin(self, sid: str) -> str:
        if sid in self._user:
            return "editada" if sid in self._builtin else "usuário"
        if sid in self._builtin:
            return "embutida"
        return "projeto" if sid in self._project else ""

    # --- edição -----------------------------------------------------------

    def new_id(self, nome_cientifico: str) -> str:
        base = slugify(nome_cientifico)
        sid, n = base, 2
        while self.get(sid) is not None:
            sid = f"{base}-{n}"
            n += 1
        return sid

    def upsert(self, sp: Species):
        """Cria ou edita uma espécie (vai para o catálogo do usuário)."""
        self._user[sp.id] = sp
        self._project.pop(sp.id, None)
        self.save_user()

    def can_remove(self, sid: str) -> bool:
        return sid in self._user

    def remove(self, sid: str, keep_for_project: bool = False):
        """Remove uma espécie do usuário; se ela editava uma embutida, volta ao original.

        ``keep_for_project``: a espécie ainda é usada no projeto aberto, então
        continua disponível nesta sessão (e vai embutida ao salvar o projeto).
        """
        if sid in self._user:
            sp = self._user.pop(sid)
            if keep_for_project and sid not in self._builtin:
                self._project[sid] = sp
            self.save_user()

    def add_project_species(self, species: list[Species]) -> list[Species]:
        """Acrescenta espécies de um projeto que não existem aqui. Retorna as novas."""
        added = []
        for sp in species:
            if self.get(sp.id) is None:
                self._project[sp.id] = sp
                added.append(sp)
        return added

    def save_user(self):
        if self.user_path is None:
            return
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"versao": 1, "especies": [s.to_dict() for s in self._user.values()]}
        tmp = self.user_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.user_path)


def _read(path) -> list[Species]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Species.from_dict(d) for d in data["especies"]]


_default: PlantCatalog | None = None


def default_catalog(user_path: str | Path | None = None) -> PlantCatalog:
    global _default
    if _default is None:
        _default = PlantCatalog.load(user_path=user_path)
    return _default
