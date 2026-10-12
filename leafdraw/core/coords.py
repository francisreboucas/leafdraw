"""Interpretação da entrada digitada na linha de comando.

Formatos aceitos (no estilo AutoCAD):

* ``10,5``          ponto absoluto
* ``@3,4``          ponto relativo ao último ponto
* ``@5<45``         polar relativo (distância < ângulo)
* ``5<45``          polar absoluto (a partir da origem)
* ``2,5;3``         com ``;`` como separador, a vírgula vira separador decimal
* ``7.5``           número solto: valor (raio, ângulo…) ou distância direta;
                    ``7,5`` também, quando a ferramenta espera um número
* qualquer outra coisa: texto (comando ou opção)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class ParsedInput:
    kind: str  # "point" | "value" | "text"
    point: Point | None = None
    value: float | None = None
    text: str = ""


def _num(s: str, comma_decimal: bool) -> float:
    s = s.strip()
    if comma_decimal:
        s = s.replace(",", ".")
    return float(s)


def parse_input(text: str, base: Point | None = None, prefer_value: bool = False) -> ParsedInput:
    """``prefer_value``: a ferramenta espera um número (raio, ângulo…), então
    ``2,5`` é lido como 2.5 e não como o ponto (2, 5)."""
    t = text.strip()
    if not t:
        raise ValueError("entrada vazia")
    rel = t.startswith("@")
    body = t[1:].strip() if rel else t
    origin = base if (rel and base is not None) else (0.0, 0.0)
    if rel and not body:
        return ParsedInput("point", point=origin)
    try:
        if "<" in body:
            d, a = body.split("<", 1)
            dist, ang = _num(d, True), _num(a, True)
            r = math.radians(ang)
            return ParsedInput("point", point=(origin[0] + dist * math.cos(r), origin[1] + dist * math.sin(r)))
        if prefer_value and not rel and ";" not in body:
            try:
                return ParsedInput("value", value=_num(body, True))
            except ValueError:
                pass
        sep = ";" if ";" in body else ","
        parts = body.split(sep)
        if len(parts) == 2:
            x, y = (_num(p, sep == ";") for p in parts)
            return ParsedInput("point", point=(origin[0] + x, origin[1] + y) if rel else (x, y))
        if len(parts) == 1 and not rel:
            return ParsedInput("value", value=_num(body, False))
    except ValueError:
        pass
    if rel:
        raise ValueError(f"coordenada inválida: {text!r}")
    return ParsedInput("text", text=t)


def direct_distance(base: Point, toward: Point, distance: float) -> Point | None:
    """Ponto a ``distance`` de ``base`` na direção de ``toward`` (entrada de distância direta)."""
    dx, dy = toward[0] - base[0], toward[1] - base[1]
    n = math.hypot(dx, dy)
    if n < 1e-12:
        return None
    return (base[0] + dx / n * distance, base[1] + dy / n * distance)
