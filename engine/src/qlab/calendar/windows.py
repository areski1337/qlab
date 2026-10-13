"""Fenêtres d'interdiction autour des annonces économiques (structure pure, partagée moteur/EA).

`blocked` : intervalles [début, fin) UTC pendant lesquels aucune entrée n'est permise.
`coverage` : intervalles pour lesquels le calendrier a effectivement été récupéré. Hors
couverture, le filtre ne peut pas être vérifié et l'entrée est refusée (prudence).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.hashing import sha256_json

VOL_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _merge(iv: list[tuple[int, int]]) -> np.ndarray:
    if not iv:
        return np.zeros((0, 2), np.int64)
    iv = sorted(iv)
    out = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return np.array(out, np.int64)


def _inside(iv: np.ndarray, t: int) -> bool:
    if len(iv) == 0:
        return False
    k = int(np.searchsorted(iv[:, 0], t, side="right")) - 1
    return k >= 0 and t < iv[k, 1]


@dataclass
class NewsWindows:
    blocked: np.ndarray
    coverage: np.ndarray
    source: str

    def blocked_at(self, t: int) -> bool:
        return _inside(self.blocked, int(t))

    def covered(self, t: int) -> bool:
        return _inside(self.coverage, int(t))

    def sha(self) -> str:
        return sha256_json({"b": self.blocked.tolist(), "c": self.coverage.tolist(), "s": self.source})


def build(events: list[dict], coverage: list[tuple[int, int]], currencies: set[str], before_min: int, after_min: int,
          min_volatility: str, source: str) -> NewsWindows:
    """events : dicts {date_ts, currency, volatility, is_tentative, is_all_day}.

    Événement horaire : [t - before, t + after). Événement à l'heure incertaine (tentative/journée
    entière) : toute la journée UTC est bloquée (convention prudente documentée).
    """
    lvl = VOL_ORDER[min_volatility]
    iv = []
    for ev in events:
        if ev["currency"] not in currencies or VOL_ORDER.get(ev["volatility"] or "NONE", 0) < lvl:
            continue
        t = int(ev["date_ts"])
        if ev.get("is_tentative") or ev.get("is_all_day"):
            d0 = t - t % 86400
            iv.append((d0, d0 + 86400))
        else:
            iv.append((t - before_min * 60, t + after_min * 60))
    return NewsWindows(_merge(iv), _merge(list(coverage)), source)


def symbol_currencies(spec: dict) -> set[str]:
    return {c for c in (spec.get("currency_base"), spec.get("currency_profit")) if c}
