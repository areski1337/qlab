"""Contrôleur de risque indépendant du génome.

Les limites absolues proviennent de la configuration (risk_limits.json), jamais
du génome. Un génome peut DEMANDER un risque ; le contrôleur applique
min(demande, limite) et refuse toute entrée dont les conditions critiques ne
peuvent pas être vérifiées. Aucune mutation ne peut modifier ces limites
(AT-009) : elles ne font pas partie de l'espace de recherche.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..core.hashing import sha256_json

DEFAULT_LIMITS = {
    "max_risk_per_trade_pct": 1.0,
    "max_daily_loss_pct": 4.0,       # valeur initiale configurable, pas une recommandation universelle
    "max_drawdown_pct": 25.0,        # arrêt des nouvelles entrées au-delà
    "max_open_positions": 1,
    "max_lots": 50.0,
    "max_orders_per_day": 50,
    "max_spread_points": None,       # None = pas de filtre de spread configuré
    "live_trading_enabled": False,   # absolu : aucune campagne de recherche ne peut l'activer
}

_HARD_CEILINGS = {"max_risk_per_trade_pct": 5.0, "max_daily_loss_pct": 20.0, "max_drawdown_pct": 60.0}


def load_limits(path: Path | None) -> dict:
    lim = dict(DEFAULT_LIMITS)
    if path and Path(path).exists():
        lim.update(json.loads(Path(path).read_text(encoding="utf-8")))
    for k, ceil in _HARD_CEILINGS.items():
        if not (0 < lim[k] <= ceil):
            raise ValueError(f"limite {k}={lim[k]} hors du plafond logiciel ]0, {ceil}]")
    if lim["live_trading_enabled"]:
        raise ValueError("live_trading_enabled ne peut pas être activé dans cette version")
    return lim


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    day: int = -1
    day_start_equity: float = 0.0
    day_orders: int = 0
    open_positions: int = 0
    halted: str | None = None
    events: list = field(default_factory=list)

    def new_day(self, day: int) -> None:
        if day != self.day:
            self.day, self.day_start_equity, self.day_orders = day, self.equity, 0


class RiskController:
    def __init__(self, limits: dict):
        self.limits = dict(limits)
        self.limits_sha256 = sha256_json(self.limits)

    def effective_risk_pct(self, requested: float) -> float:
        return min(float(requested), self.limits["max_risk_per_trade_pct"])

    def check_entry(self, st: RiskState, *, day: int, spread_points: float | None, lots: float) -> str | None:
        """Retourne None si l'entrée est autorisée, sinon le motif de refus."""
        st.new_day(day)
        L = self.limits
        if st.halted:
            return st.halted
        if not math.isfinite(st.equity) or st.equity <= 0:
            return "equity_invalid"
        if (st.peak_equity - st.equity) / st.peak_equity * 100 >= L["max_drawdown_pct"]:
            st.halted = "max_drawdown_halt"
            return st.halted
        if (st.day_start_equity - st.equity) / st.day_start_equity * 100 >= L["max_daily_loss_pct"]:
            return "daily_loss_limit"
        if st.open_positions >= L["max_open_positions"]:
            return "max_open_positions"
        if st.day_orders >= L["max_orders_per_day"]:
            return "max_orders_per_day"
        if lots > L["max_lots"]:
            return "max_lots"
        if L["max_spread_points"] is not None:
            if spread_points is None or not math.isfinite(spread_points):
                return "spread_unverifiable"
            if spread_points > L["max_spread_points"]:
                return "spread_too_wide"
        return None

    def on_entry(self, st: RiskState) -> None:
        st.day_orders += 1
        st.open_positions += 1

    def on_exit(self, st: RiskState, pnl: float) -> None:
        st.open_positions -= 1
        st.equity += pnl
        st.peak_equity = max(st.peak_equity, st.equity)
