"""Registre des features : définition formelle, paramètres typés, version, sorties typées.

Convention de disponibilité (vérifiée par tests de troncature, AT-001) : la
valeur d'une feature à l'index i n'utilise que les barres 0..i et est
disponible à la CLÔTURE de la barre i. Les valeurs non calculables sont NaN
(jamais une valeur favorable par défaut).

Types de sortie (pour le typage des comparaisons dans le génome) :
- price      : niveau de prix, comparable aux autres sorties price ;
- osc100     : borné 0..100 ;
- signed     : oscillateur signé non borné (comparé à une constante ou à la même feature) ;
- ratio      : positif non borné ;
- bool       : événement/état (0/1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..core.hashing import sha256_json


@dataclass(frozen=True)
class Param:
    kind: str  # "int" | "float" | "choice"
    lo: float | None = None
    hi: float | None = None
    default: object = None
    choices: tuple = ()

    def validate(self, v) -> str | None:
        if self.kind == "choice":
            return None if v in self.choices else f"valeur {v!r} hors de {self.choices}"
        if self.kind == "int" and (not isinstance(v, int) or isinstance(v, bool)):
            return f"entier attendu, reçu {v!r}"
        if self.kind == "float" and not isinstance(v, (int, float)):
            return f"nombre attendu, reçu {v!r}"
        if not (self.lo <= v <= self.hi):
            return f"{v} hors de [{self.lo}, {self.hi}]"
        return None


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: str
    family: str  # classic | ict | session | volume | market
    description: str
    params: dict[str, Param]
    outputs: dict[str, str]  # sortie -> type
    compute: Callable = field(compare=False)
    approximate: str | None = None  # limite connue (ex. VWAP en tick volume)


REGISTRY: dict[str, FeatureSpec] = {}


def feature(name: str, version: str, family: str, description: str, params: dict[str, Param],
            outputs: dict[str, str], approximate: str | None = None):
    def deco(fn):
        REGISTRY[name] = FeatureSpec(name, version, family, description, params, outputs, fn, approximate)
        return fn
    return deco


def validate_params(name: str, params: dict) -> list[str]:
    spec = REGISTRY.get(name)
    if spec is None:
        return [f"feature inconnue : {name}"]
    errs = [f"{name}.{k}: paramètre inconnu" for k in params if k not in spec.params]
    for k, p in spec.params.items():
        if k not in params:
            errs.append(f"{name}.{k}: paramètre manquant")
        elif (e := p.validate(params[k])) is not None:
            errs.append(f"{name}.{k}: {e}")
    return errs


class FeatureCache:
    """Cache exact par (dataset, feature, version, paramètres). Une version changée = nouvelle clé (AT-005)."""

    def __init__(self, bars, context: dict | None = None, max_items: int = 512):
        self.bars = bars
        self.context = context or {}  # timeframe -> Bars (HTF)
        self._d: dict[str, dict[str, np.ndarray]] = {}
        self.max_items = max_items
        self.hits = self.misses = 0

    def key(self, name: str, params: dict, tf: str | None) -> str:
        b = self.context[tf] if tf and tf != self.bars.timeframe else self.bars
        return sha256_json([b.content_sha256, b.timeframe, len(b), name, REGISTRY[name].version, params])

    def get(self, name: str, params: dict, tf: str | None = None) -> dict[str, np.ndarray]:
        k = self.key(name, params, tf)
        if k in self._d:
            self.hits += 1
            return self._d[k]
        self.misses += 1
        b = self.context[tf] if tf and tf != self.bars.timeframe else self.bars
        out = REGISTRY[name].compute(b, **params)
        if len(self._d) >= self.max_items:
            self._d.pop(next(iter(self._d)))
        self._d[k] = out
        return out
