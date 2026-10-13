"""Détection de régimes explicable (règles + hystérésis), exposée comme feature.

Dimensions indépendantes (non exclusives) :
- direction : pente de EMA(n) sur 5 barres, normalisée par ATR(14) ;
- force de tendance : ADX(14) ;
- volatilité : ATR(5)/ATR(50) (compression < 0,7 < normal < 1,5 < expansion) ;
- perturbation : range de barre > 4 × ATR(50) ou spread > 3 × médiane glissante.
Famille de présentation (une à la fois, par priorité) : perturbé > compression >
expansion > tendance haussière/baissière (ADX > 25 et |pente| > 0,1) > range
(ADX < 20) > transition. Un changement de famille n'est retenu qu'après
`confirm` barres consécutives (hystérésis). Confiance = part des 3×confirm
dernières étiquettes brutes égales à la famille retenue.
Limite : seuils fixés a priori, non optimisés ; l'apport hors échantillon d'un
filtre de régime doit être mesuré (ablation), jamais supposé.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..features.classic import atr_arr, ema, f_adx
from ..features.registry import Param, feature

LABELS = ["bull_trend", "bear_trend", "range", "compression", "expansion", "transition", "disturbed"]


def raw_labels(b, trend_period: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    adx = f_adx(b, 14)["adx"]
    e = ema(b.close, trend_period)
    a14, a5, a50 = atr_arr(b, 14), atr_arr(b, 5), atr_arr(b, 50)
    slope = (e - np.concatenate([np.full(5, np.nan), e[:-5]])) / (a14 * 5)
    with np.errstate(invalid="ignore", divide="ignore"):
        comp = a5 / a50
        sp = b.spread.astype(float)
        med = pd.Series(np.where(sp > 0, sp, np.nan)).rolling(500, min_periods=50).median().to_numpy()
        disturbed = ((b.high - b.low) > 4 * a50) | ((sp > 0) & (sp > 3 * med))
    lab = np.full(len(b), -1)
    known = np.isfinite(adx) & np.isfinite(slope) & np.isfinite(comp)
    with np.errstate(invalid="ignore"):
        conds = [disturbed, comp < 0.7, comp > 1.5, (adx > 25) & (slope > 0.1), (adx > 25) & (slope < -0.1), adx < 20]
    codes = [6, 3, 4, 0, 1, 2]
    out = np.where(known, 5, -1)
    for c, code in reversed(list(zip(conds, codes))):
        out = np.where(known & c, code, out)
    return out, slope, comp


@feature("regime", "1.0", "regime", __doc__.split("\n\n")[1].replace("\n", " "),
         {"trend_period": Param("int", 10, 300, 50), "confirm": Param("int", 1, 20, 3)},
         {**{l: "bool" for l in LABELS}, "confidence": "osc100", "trend_slope": "signed", "vol_ratio": "ratio"})
def f_regime(b, trend_period, confirm):
    raw, slope, comp = raw_labels(b, trend_period)
    n = len(b)
    cur = np.full(n, -1)
    state, pend, cnt = -1, -1, 0
    for i in range(n):
        r = raw[i]
        if r == -1:
            state, pend, cnt = -1, -1, 0  # incertain : comportement prudent (aucune famille)
        elif state == -1:
            state = r
        elif r != state:
            cnt = cnt + 1 if r == pend else 1
            pend = r
            if cnt >= confirm:
                state, pend, cnt = r, -1, 0
        else:
            pend, cnt = -1, 0
        cur[i] = state
    w = 3 * confirm
    eq = pd.Series((raw == cur).astype(float)).rolling(w, min_periods=1).mean().to_numpy() * 100
    out = {l: (cur == k).astype(float) for k, l in enumerate(LABELS)}
    out["confidence"] = np.where(cur >= 0, eq, np.nan)
    out["trend_slope"] = slope
    out["vol_ratio"] = comp
    return out
