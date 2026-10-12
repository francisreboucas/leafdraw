"""Documento: fonte única da verdade para todas as vistas.

Alterações em entidades devem passar por comandos (``core.commands``) para
entrarem no histórico de desfazer. Os métodos ``add_entity``/``remove_entity``/
``replace_entity`` são as operações de baixo nível usadas por esses comandos.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from leafdraw.core.entities import Entity, union_bounds
from leafdraw.core.layers import DEFAULT_LAYERS, Layer

FORMAT_NAME = "leafdraw"
FORMAT_VERSION = 1


class Document(QObject):
    entityAdded = Signal(str)
    entityRemoved = Signal(str)
    entityChanged = Signal(str)
    layersChanged = Signal()
    currentLayerChanged = Signal(str)
    documentReset = Signal()
    modifiedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.file_path: str | None = None
        self.entities: dict[str, Entity] = {}
        self.layers: dict[str, Layer] = {}
        self.current_layer = "0"
        self._layers_dirty = False
        self._init_defaults()

    def _init_defaults(self):
        self.entities.clear()
        self.layers.clear()
        for lid, name, color in DEFAULT_LAYERS:
            self.layers[lid] = Layer(name=name, color=color, id=lid)
        self.current_layer = "0"

    def new(self):
        self._init_defaults()
        self.file_path = None
        self.undo_stack.clear()
        self._layers_dirty = False
        self.documentReset.emit()
        self._emit_modified()

    # --- estado de modificação -------------------------------------------

    def is_modified(self) -> bool:
        return self._layers_dirty or not self.undo_stack.isClean()

    def mark_saved(self, path: str):
        self.file_path = path
        self._layers_dirty = False
        self.undo_stack.setClean()
        self._emit_modified()

    def _touch_layers(self):
        self._layers_dirty = True
        self.layersChanged.emit()
        self._emit_modified()

    def _on_clean_changed(self, _clean: bool):
        self._emit_modified()

    def _emit_modified(self):
        self.modifiedChanged.emit(self.is_modified())

    # --- entidades (baixo nível, usado pelos comandos) -------------------

    def add_entity(self, e: Entity):
        if e.id in self.entities:
            raise ValueError(f"entidade duplicada: {e.id}")
        self.entities[e.id] = e
        self.entityAdded.emit(e.id)

    def remove_entity(self, eid: str) -> Entity:
        e = self.entities.pop(eid)
        self.entityRemoved.emit(eid)
        return e

    def replace_entity(self, e: Entity):
        if e.id not in self.entities:
            raise KeyError(e.id)
        self.entities[e.id] = e
        self.entityChanged.emit(e.id)

    def bounds(self):
        return union_bounds(e.bounds() for e in self.entities.values())

    # --- camadas ----------------------------------------------------------

    def layer_for(self, e: Entity) -> Layer:
        """Camada da entidade; cai na camada "0" se a camada não existir mais."""
        return self.layers.get(e.layer) or self.layers["0"]

    def layer_by_name(self, name: str) -> Layer | None:
        return next((l for l in self.layers.values() if l.name == name), None)

    def entities_on_layer(self, lid: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.layer == lid]

    def add_layer(self, name: str | None = None, color: str = "#e6e6e6") -> Layer:
        if name is None:
            n = len(self.layers)
            while self.layer_by_name(f"Camada {n}"):
                n += 1
            name = f"Camada {n}"
        elif self.layer_by_name(name):
            raise ValueError(f"já existe uma camada chamada {name!r}")
        layer = Layer(name=name, color=color)
        self.layers[layer.id] = layer
        self._touch_layers()
        return layer

    def add_layers(self, layers: list[Layer]):
        """Acrescenta camadas prontas (ex.: vindas de um DXF), garantindo nomes únicos."""
        if not layers:
            return
        for layer in layers:
            base, n = layer.name, 2
            while self.layer_by_name(layer.name):
                layer.name = f"{base} ({n})"
                n += 1
            self.layers[layer.id] = layer
        self._touch_layers()

    def can_remove_layer(self, lid: str) -> tuple[bool, str]:
        if lid == "0":
            return False, "A camada 0 não pode ser excluída."
        if lid == self.current_layer:
            return False, "A camada atual não pode ser excluída."
        if self.entities_on_layer(lid):
            return False, "A camada contém objetos. Mova ou exclua os objetos antes."
        return True, ""

    def remove_layer(self, lid: str):
        ok, reason = self.can_remove_layer(lid)
        if not ok:
            raise ValueError(reason)
        del self.layers[lid]
        self._touch_layers()

    def rename_layer(self, lid: str, name: str):
        name = name.strip()
        if not name:
            raise ValueError("O nome da camada não pode ser vazio.")
        other = self.layer_by_name(name)
        if other and other.id != lid:
            raise ValueError(f"Já existe uma camada chamada {name!r}.")
        self.update_layer(lid, name=name)

    def update_layer(self, lid: str, **changes):
        layer = self.layers[lid]
        for k, v in changes.items():
            if not hasattr(layer, k) or k == "id":
                raise AttributeError(k)
            setattr(layer, k, v)
        self._touch_layers()

    def set_current_layer(self, lid: str):
        if lid not in self.layers or lid == self.current_layer:
            return
        self.current_layer = lid
        self.currentLayerChanged.emit(lid)

    # --- serialização -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "current_layer": self.current_layer,
            "layers": [l.to_dict() for l in self.layers.values()],
            "entities": [e.to_dict() for e in self.entities.values()],
        }

    def load_dict(self, data: dict, path: str | None = None):
        if data.get("format") != FORMAT_NAME:
            raise ValueError("Arquivo não é um projeto LeafDraw.")
        if data.get("version", 0) > FORMAT_VERSION:
            raise ValueError("Projeto criado em uma versão mais nova do LeafDraw.")
        layers = [Layer.from_dict(d) for d in data.get("layers", [])]
        entities = [Entity.from_dict(d) for d in data.get("entities", [])]
        self.layers = {l.id: l for l in layers}
        if "0" not in self.layers:
            self.layers = {"0": Layer(name="0", id="0"), **self.layers}
        self.entities = {e.id: e for e in entities}
        cur = data.get("current_layer", "0")
        self.current_layer = cur if cur in self.layers else "0"
        self.undo_stack.clear()
        if path:
            self.mark_saved(path)
        else:
            self._layers_dirty = True
            self._emit_modified()
        self.documentReset.emit()
