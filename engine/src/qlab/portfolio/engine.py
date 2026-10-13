"""Analyse et allocation de portefeuille (version COMPONENT_VERSIONS['portfolio']).

Entrée : les PnL de trades conservés (évaluations « research » ou « oos ») de
plusieurs révisions. Les séries sont agrégées en PnL journaliers (journée de
trading 17:00 NY, jours sans trade = 0), normalisés par le capital initial.

Allocation : poids BORNÉS [w_min, w_max], somme 1. Méthodes :
- equal       : poids égaux ;
- inverse_vol : ∝ 1/σ journalier (approximation de parité de risque sans corrélations) ;
- min_corr    : ∝ 1/σ × (1 - corrélation moyenne avec les autres), favorise la complémentarité.
Aucune méthode ne maximise la somme des profits individuels.

Allocation adaptative : multiplicateur de poids ∈ [1 - band, 1 + band] fonction de
l'écart de performance récente standardisé, puis re-bornage : une stratégie ne
peut jamais dépasser w_max, quel que soit son historique récent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..features.sessions import trading_day

METHODS = ("equal", "inverse_vol", "min_corr")


def daily_matrix(series: dict[str, list[dict]], eq0: dict[str, float]) -> pd.DataFrame:
    cols = {}
    for rid, trades in series.items():
        if not trades:
            cols[rid] = pd.Series(dtype=float)
            continue
        d = trading_day(np.array([t["exit_ts"] for t in trades]))
        cols[rid] = pd.Series([t["pnl"] for t in trades]).groupby(d).sum() / eq0[rid]
    df = pd.DataFrame(cols)
    if df.empty:
        return df
    full = np.arange(int(df.index.min()), int(df.index.max()) + 1)
    full = full[(full + 3) % 7 < 5]  # jours ouvrés
    return df.reindex(full).fillna(0.0)


def bounded(w: np.ndarray, lo: float, hi: float, iters: int = 100) -> np.ndarray:
    """Projection simple sur {lo <= w_i <= hi, Σw = 1} (redistribution itérative)."""
    n = len(w)
    if n * lo > 1 + 1e-12 or n * hi < 1 - 1e-12:
        raise ValueError(f"bornes infaisables pour {n} stratégies : [{lo}, {hi}]")
    w = np.clip(np.asarray(w, float), 0, None)
    w = w / w.sum() if w.sum() > 0 else np.full(n, 1 / n)
    for _ in range(iters):
        w = np.clip(w, lo, hi)
        gap = 1 - w.sum()
        if abs(gap) < 1e-12:
            break
        free = (w < hi - 1e-12) if gap > 0 else (w > lo + 1e-12)
        w[free] += gap / free.sum()
    return w


def allocate(R: pd.DataFrame, method: str, w_min: float, w_max: float) -> tuple[np.ndarray, dict]:
    n = R.shape[1]
    sd = R.std(ddof=1).to_numpy()
    sd = np.where(sd > 0, sd, np.nan)
    if method == "equal":
        raw = np.ones(n)
    elif method == "inverse_vol":
        raw = np.nan_to_num(1 / sd, nan=0.0)
    elif method == "min_corr":
        C = R.corr().to_numpy()
        avg = np.array([np.nanmean(np.delete(C[i], i)) if n > 1 else 0.0 for i in range(n)])
        raw = np.nan_to_num(1 / sd, nan=0.0) * np.clip(1 - np.nan_to_num(avg), 0.05, 2)
    else:
        raise ValueError(f"méthode inconnue {method} ({METHODS})")
    w = bounded(raw, w_min, w_max)
    return w, {"raw": raw.tolist(), "daily_sd": np.nan_to_num(sd).tolist()}


def adaptive(w_base: np.ndarray, recent: pd.DataFrame, band: float, w_min: float, w_max: float) -> np.ndarray:
    """Ajustement borné : multiplicateur ∈ [1-band, 1+band] selon le z-score de la moyenne récente."""
    m = recent.mean().to_numpy()
    s = m.std() if len(m) > 1 and m.std() > 0 else 1.0
    z = np.clip((m - m.mean()) / s, -1, 1)
    return bounded(w_base * (1 + band * z), w_min, w_max)


def _dd(eq: np.ndarray) -> tuple[np.ndarray, float]:
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    return dd, float(dd.max() * 100) if len(dd) else 0.0


def analyze(R: pd.DataFrame, w: np.ndarray, meta: dict[str, dict]) -> dict:
    """meta[rid] = {symbol, currency_base, currency_profit, long_share, entry_days(set), costs}"""
    ids = list(R.columns)
    C = R.corr()
    port = R.to_numpy() @ w
    eq = np.cumprod(1 + port)
    dd_p, mdd = _dd(eq)
    in_dd = np.column_stack([_dd(np.cumprod(1 + R[c].to_numpy()))[0] > 0.02 for c in ids]) if ids else np.zeros((0, 0))
    simult = float((in_dd.sum(axis=1) >= 2).mean()) if in_dd.size else 0.0
    cov = R.cov().to_numpy()
    pv = float(w @ cov @ w)
    mrc = (w * (cov @ w) / pv).tolist() if pv > 0 else [None] * len(ids)
    expo_inst, expo_ccy = {}, {}
    for rid, wi in zip(ids, w):
        m = meta[rid]
        expo_inst[m["symbol"]] = expo_inst.get(m["symbol"], 0) + wi
        net_long = 2 * m["long_share"] - 1  # +1 tout long, -1 tout short
        for ccy, sgn in ((m["currency_base"], 1), (m["currency_profit"], -1)):
            if ccy:
                expo_ccy[ccy] = expo_ccy.get(ccy, 0) + wi * net_long * sgn
    overlap = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            A, B = meta[a]["entry_days"], meta[b]["entry_days"]
            overlap[f"{a}|{b}"] = len(A & B) / len(A | B) if A | B else 0.0
    sd = port.std(ddof=1) if len(port) > 1 else 0
    return {
        "strategies": ids, "weights": w.tolist(),
        "correlation": {a: {b: (None if np.isnan(C.loc[a, b]) else float(C.loc[a, b])) for b in ids} for a in ids},
        "portfolio": {"return_pct": float((eq[-1] - 1) * 100) if len(eq) else 0.0, "max_dd_pct": mdd,
                      "sharpe": float(port.mean() / sd * np.sqrt(252)) if sd > 0 else None, "days": int(len(port))},
        "individual_max_dd_pct": {c: _dd(np.cumprod(1 + R[c].to_numpy()))[1] for c in ids},
        "simultaneous_drawdown_ratio": simult,
        "concentration_hhi": float((w ** 2).sum()),
        "marginal_risk_contribution": dict(zip(ids, mrc)),
        "exposure_by_instrument": expo_inst, "net_exposure_by_currency": expo_ccy,
        "signal_overlap_jaccard": overlap,
        "aggregate_costs": {k: float(sum(meta[r]["costs"].get(k, 0) * wi for r, wi in zip(ids, w)))
                            for k in ("commission", "swap", "spread_est")},
        "notes": ["exposition par devise : signe approximatif tiré de la part long/short des trades",
                  "dépendance aux régimes : non mesurée dans cette version"],
    }
