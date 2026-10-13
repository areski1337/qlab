"""Métriques de performance après coûts.

Toute métrique non calculable vaut None (jamais un infini ni une valeur
fabriquée). Sharpe/Sortino : rendements JOURNALIERS (journée de trading 17:00
NY, jours sans trade inclus à 0), annualisés par sqrt(252), taux sans risque 0.
Le drawdown est mesuré sur l'equity de clôture des trades (le flottant
intra-trade n'est pas inclus ; voir mae_r par trade).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..features.sessions import trading_day


def _f(x):
    return None if x is None or not math.isfinite(x) else float(x)


def compute(result: dict, ts_window: tuple[int, int] | None = None) -> dict:
    trades = result["trades"]
    eq0 = result["initial_equity"]
    n = len(trades)
    m: dict = {"n_trades": n, "initial_equity": eq0, "final_equity": result["final_equity"],
               "skipped": result["skipped"], "halted": result["halted"]}
    if n == 0:
        m.update({k: None for k in ("net_profit", "return_pct", "expectancy", "expectancy_r", "win_rate",
                                    "profit_factor", "sharpe", "sortino", "max_dd_pct", "max_dd_abs",
                                    "longest_underwater_days", "r2_equity", "avg_bars_held",
                                    "positive_months_ratio", "trades_per_month", "ambiguous_ratio")})
        m["by_year"] = {}
        m["costs"] = {"commission": 0.0, "swap": 0.0, "spread_est": 0.0}
        return m
    pnl = np.array([t["pnl"] for t in trades])
    r = np.array([t["r"] for t in trades])
    eq = eq0 + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[eq0], eq]))[1:]
    dd_abs = peak - eq
    i_dd = int(np.argmax(dd_abs / peak))
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()

    start_ts = ts_window[0] if ts_window else trades[0]["entry_ts"]
    end_ts = ts_window[1] if ts_window else trades[-1]["exit_ts"]
    d0, d1 = int(trading_day(np.array([start_ts]))[0]), int(trading_day(np.array([end_ts]))[0])
    days = np.arange(d0, d1 + 1)
    days = days[(days + 3) % 7 < 5]  # jours ouvrés (lundi..vendredi serveur)
    exit_days = trading_day(np.array([t["exit_ts"] for t in trades]))
    daily = pd.Series(pnl).groupby(exit_days).sum().reindex(days, fill_value=0.0).to_numpy()
    deq = eq0 + np.concatenate([[0.0], np.cumsum(daily)])
    dret = daily / deq[:-1]
    sd = dret.std(ddof=1) if len(dret) > 1 else float("nan")
    down = dret[dret < 0]
    dsd = math.sqrt((down ** 2).sum() / len(dret)) if len(dret) > 1 and len(down) else float("nan")

    # durée maximale sous l'eau (jours de trading)
    under, longest, cur = deq < np.maximum.accumulate(deq), 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)

    x = np.arange(n)
    r2 = None
    if n >= 3 and eq.std() > 0:
        r2 = float(np.corrcoef(x, eq)[0, 1] ** 2) * (1 if eq[-1] >= eq0 else -1)

    month = pd.to_datetime([t["exit_ts"] for t in trades], unit="s").to_period("M")
    by_month = pd.Series(pnl).groupby(month).sum()
    span_months = max((end_ts - start_ts) / (86400 * 30.44), 1e-9)
    year = pd.to_datetime([t["exit_ts"] for t in trades], unit="s").year
    by_year = pd.Series(pnl).groupby(year).agg(["sum", "count"])
    m.update({
        "net_profit": float(pnl.sum()),
        "return_pct": float(pnl.sum() / eq0 * 100),
        "expectancy": float(pnl.mean()),
        "expectancy_r": float(r.mean()),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": _f(wins / losses) if losses > 0 else None,
        "sharpe": _f(dret.mean() / sd * math.sqrt(252)) if sd and sd > 0 else None,
        "sortino": _f(dret.mean() / dsd * math.sqrt(252)) if dsd and dsd > 0 else None,
        "max_dd_pct": float((dd_abs / peak).max() * 100),
        "max_dd_abs": float(dd_abs.max()),
        "max_dd_at": trades[i_dd]["exit_ts"],
        "longest_underwater_days": int(longest),
        "r2_equity": r2,
        "avg_bars_held": float(np.mean([t["bars_held"] for t in trades])),
        "positive_months_ratio": float((by_month > 0).mean()),
        "trades_per_month": float(n / span_months),
        "ambiguous_ratio": float(np.mean([t["ambiguous"] for t in trades])),
        "by_year": {int(k): {"net": float(v["sum"]), "n": int(v["count"])} for k, v in by_year.iterrows()},
        "costs": {"commission": float(sum(t["commission"] for t in trades)),
                  "swap": float(sum(t["swap"] for t in trades)),
                  "spread_est": float(sum(t["spread_cost"] for t in trades))},
        "daily_returns_n": int(len(dret)),
    })
    return m
