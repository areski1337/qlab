"""Taille de fenêtre W qu'un EA doit recalculer pour reproduire chaque feature.

L'EA recalcule les features sur les W dernières barres closes. Pour les
features à mémoire bornée le résultat est identique ; pour les lissages
exponentiels (EMA, Wilder) l'écart résiduel décroît en (1-alpha)^W et est
rendu négligeable (< 1e-9 relatif) par le choix de W. Vérifié par
tests/test_mql5.py::test_window_convergence.
"""
from __future__ import annotations

from ..core.timeutil import tf_seconds

BARS_PER_WEEK = lambda tf: 5 * 86400 // tf_seconds(tf)


def _exp_window(period: int, alpha_kind: str) -> int:
    # (1 - alpha)^W < 1e-12  =>  W > 27.6 / alpha
    alpha = 2 / (period + 1) if alpha_kind == "ema" else 1 / period
    return int(28 / alpha) + period + 5


def feature_window(name: str, p: dict, tf: str) -> int:
    if name in ("price", "spread", "session"):
        return 2
    if name == "sma":
        return p["period"] + 2
    if name == "ema":
        return _exp_window(p["period"], "ema")
    if name in ("rsi", "atr"):
        return _exp_window(p["period"], "wilder") + 1
    if name == "macd":
        return _exp_window(max(p["slow"], p["signal"]), "ema") + p["slow"] + p["signal"]
    if name == "stoch":
        return p["k"] + p["d"] + p["smooth"] + 2
    if name == "bollinger":
        return p["period"] + 2
    if name == "keltner":
        return _exp_window(p["period"], "ema")
    if name == "adx":
        return 2 * _exp_window(p["period"], "wilder") + 2
    if name == "donchian":
        return p["period"] + 2
    if name == "realized_vol":
        return p["period"] + 2
    if name == "momentum":
        return p["period"] + 2
    if name == "compression":
        return _exp_window(p["slow"], "wilder") + 1
    if name == "rel_volume":
        return p["period"] + 2
    if name == "range_position":
        return p["lookback"] + 2
    if name == "swings":
        return 400 * (p["left"] + p["right"])
    if name in ("structure", "liquidity", "order_block", "fvg"):
        # états dépendant du chemin (tendance, zones) : convergence après quelques cassures/expirations
        base = _exp_window(14, "wilder") + 1
        return max(base, 3000)
    if name == "prev_extremes":
        return 2 * BARS_PER_WEEK(tf) + 400
    if name == "vwap":
        return (2 * BARS_PER_WEEK(tf) if p["anchor"] == "week" else 2 * 86400 // tf_seconds(tf)) + 50
    if name in ("judas", "po3"):
        return 2 * 86400 // tf_seconds(tf) + _exp_window(14, "wilder")
    if name == "smt":
        return p["lookback"] + 3
    if name == "mitigation":
        return max(_exp_window(14, "wilder") + 1, 3000)
    if name == "regime":
        return max(_exp_window(p["trend_period"], "ema"), 2 * _exp_window(14, "wilder"), _exp_window(50, "wilder"), 600)
    raise KeyError(name)
