"""Comandos de edição (padrão Command) para o histórico de desfazer."""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from leafdraw.core.entities import Entity


class AddEntities(QUndoCommand):
    def __init__(self, doc, entities: list[Entity], text: str = "Adicionar"):
        super().__init__(text)
        self.doc = doc
        self.entities = list(entities)

    def redo(self):
        for e in self.entities:
            self.doc.add_entity(e)

    def undo(self):
        for e in reversed(self.entities):
            self.doc.remove_entity(e.id)


class RemoveEntities(QUndoCommand):
    def __init__(self, doc, ids: list[str], text: str = "Excluir"):
        super().__init__(text)
        self.doc = doc
        self.entities = [doc.entities[i] for i in ids]

    def redo(self):
        for e in self.entities:
            self.doc.remove_entity(e.id)

    def undo(self):
        for e in self.entities:
            self.doc.add_entity(e)


class ReplaceEntities(QUndoCommand):
    """Troca entidades por novas versões (mesmo id): mover, editar propriedades…"""

    def __init__(self, doc, new_entities: list[Entity], text: str = "Modificar"):
        super().__init__(text)
        self.doc = doc
        self.new = list(new_entities)
        self.old = [doc.entities[e.id] for e in self.new]

    def redo(self):
        for e in self.new:
            self.doc.replace_entity(e)

    def undo(self):
        for e in self.old:
            self.doc.replace_entity(e)


class ReplaceSheets(QUndoCommand):
    """Troca a lista de folhas inteira (folhas são pequenas; simplifica o undo)."""

    def __init__(self, doc, new_sheets, text: str = "Editar folha"):
        super().__init__(text)
        self.doc = doc
        self.old = list(doc.sheets)
        self.new = list(new_sheets)

    def redo(self):
        self.doc.set_sheets(self.new)

    def undo(self):
        self.doc.set_sheets(self.old)
