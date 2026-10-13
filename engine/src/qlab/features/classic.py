"""Indicateurs classiques. Définitions documentées ; mêmes formules dans le générateur MQL5."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import Param, feature

P = Param


def _ewm_seeded(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Lissage exponentiel amorcé par la moyenne simple des n premières valeurs finies."""
    out = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(x))
    if len(finite) < n:
        return out
    s = finite[0]
    if s + n > len(x):
        return out
    seed = x[s:s + n].mean()
    tail = np.concatenate([[seed], x[s + n:]])
    out[s + n - 1:] = pd.Series(tail).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return _ewm_seeded(x, n, 2.0 / (n + 1))


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    return _ewm_seeded(x, n, 1.0 / n)


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).mean().to_numpy()


def true_range(b) -> np.ndarray:
    pc = np.concatenate([[np.nan], b.close[:-1]])
    tr = np.maximum(b.high - b.low, np.maximum(np.abs(b.high - pc), np.abs(b.low - pc)))
    tr[0] = b.high[0] - b.low[0]
    return tr


def atr_arr(b, n: int) -> np.ndarray:
    return wilder(true_range(b), n)


@feature("price", "1.0", "market", "OHLC de la barre close courante.", {},
         {"open": "price", "high": "price", "low": "price", "close": "price"})
def f_price(b):
    return {"open": b.open, "high": b.high, "low": b.low, "close": b.close}


@feature("sma", "1.0", "classic", "Moyenne simple des n dernières clôtures.", {"period": P("int", 2, 500, 20)},
         {"value": "price"})
def f_sma(b, period):
    return {"value": sma(b.close, period)}


@feature("ema", "1.0", "classic", "EMA alpha=2/(n+1), amorcée par SMA(n).", {"period": P("int", 2, 500, 20)},
         {"value": "price"})
def f_ema(b, period):
    return {"value": ema(b.close, period)}


@feature("rsi", "1.0", "classic", "RSI de Wilder ; 50 si aucune variation, 100 si aucune baisse.",
         {"period": P("int", 2, 100, 14)}, {"value": "osc100"})
def f_rsi(b, period):
    d = np.diff(b.close, prepend=np.nan)
    g, l = wilder(np.where(d > 0, d, 0.0)[1:], period), wilder(np.where(d < 0, -d, 0.0)[1:], period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(l == 0, np.where(g == 0, 50.0, 100.0), 100 - 100 / (1 + g / l))
    rsi[np.isnan(g)] = np.nan
    return {"value": np.concatenate([[np.nan], rsi])}


@feature("atr", "1.0", "classic", "ATR de Wilder (True Range lissé 1/n).", {"period": P("int", 2, 200, 14)},
         {"value": "ratio"})
def f_atr(b, period):
    return {"value": atr_arr(b, period)}


@feature("macd", "1.0", "classic", "MACD = EMA(fast)-EMA(slow) ; signal = EMA(signal) du MACD.",
         {"fast": P("int", 2, 50, 12), "slow": P("int", 5, 200, 26), "signal": P("int", 2, 50, 9)},
         {"macd": "signed", "signal": "signed", "hist": "signed"})
def f_macd(b, fast, slow, signal):
    m = ema(b.close, fast) - ema(b.close, slow)
    s = ema(m, signal)
    return {"macd": m, "signal": s, "hist": m - s}


@feature("stoch", "1.0", "classic", "Stochastique : %K brut sur k barres, lissé SMA(smooth) ; %D = SMA(d) de %K.",
         {"k": P("int", 3, 100, 14), "d": P("int", 1, 20, 3), "smooth": P("int", 1, 20, 3)},
         {"k": "osc100", "d": "osc100"})
def f_stoch(b, k, d, smooth):
    hh = pd.Series(b.high).rolling(k).max().to_numpy()
    ll = pd.Series(b.low).rolling(k).min().to_numpy()
    rng = hh - ll
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(rng > 0, (b.close - ll) / rng * 100, 50.0)
    raw[np.isnan(rng)] = np.nan
    kk = sma(raw, smooth) if smooth > 1 else raw
    return {"k": kk, "d": sma(kk, d) if d > 1 else kk}


@feature("bollinger", "1.0", "classic", "Bandes de Bollinger : SMA(n) ± dev × écart-type population.",
         {"period": P("int", 5, 200, 20), "dev": P("float", 0.5, 4.0, 2.0)},
         {"upper": "price", "mid": "price", "lower": "price"})
def f_boll(b, period, dev):
    s = pd.Series(b.close).rolling(period)
    m, sd = s.mean().to_numpy(), s.std(ddof=0).to_numpy()
    return {"upper": m + dev * sd, "mid": m, "lower": m - dev * sd}


@feature("keltner", "1.0", "classic", "Canaux de Keltner : EMA(n) ± mult × ATR(n).",
         {"period": P("int", 5, 200, 20), "mult": P("float", 0.5, 5.0, 2.0)},
         {"upper": "price", "mid": "price", "lower": "price"})
def f_keltner(b, period, mult):
    m, a = ema(b.close, period), atr_arr(b, period)
    return {"upper": m + mult * a, "mid": m, "lower": m - mult * a}


@feature("adx", "1.0", "classic", "ADX de Wilder.", {"period": P("int", 5, 100, 14)},
         {"adx": "osc100", "plus_di": "osc100", "minus_di": "osc100"})
def f_adx(b, period):
    up = np.diff(b.high, prepend=np.nan)
    dn = -np.diff(b.low, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)[1:]
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)[1:]
    tr = wilder(true_range(b)[1:], period)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * wilder(pdm, period) / tr
        mdi = 100 * wilder(mdm, period) / tr
        dx = np.where(pdi + mdi > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0.0)
    dx[np.isnan(pdi)] = np.nan
    pad = lambda a: np.concatenate([[np.nan], a])
    return {"adx": pad(wilder(dx, period)), "plus_di": pad(pdi), "minus_di": pad(mdi)}


@feature("donchian", "1.0", "classic", "Canal de Donchian sur les n barres PRÉCÉDENTES (barre courante exclue).",
         {"period": P("int", 5, 500, 20)}, {"upper": "price", "lower": "price", "mid": "price"})
def f_donchian(b, period):
    hh = pd.Series(b.high).rolling(period).max().shift(1).to_numpy()
    ll = pd.Series(b.low).rolling(period).min().shift(1).to_numpy()
    return {"upper": hh, "lower": ll, "mid": (hh + ll) / 2}


@feature("realized_vol", "1.0", "classic", "Écart-type des log-rendements sur n barres, en %.",
         {"period": P("int", 5, 500, 50)}, {"value": "ratio"})
def f_rvol(b, period):
    r = np.diff(np.log(b.close), prepend=np.nan)
    return {"value": pd.Series(r).rolling(period).std(ddof=0).to_numpy() * 100}


@feature("momentum", "1.0", "classic", "Taux de variation en % sur n barres.", {"period": P("int", 1, 500, 10)},
         {"roc": "signed"})
def f_mom(b, period):
    prev = np.concatenate([np.full(period, np.nan), b.close[:-period]])
    return {"roc": (b.close / prev - 1) * 100}


@feature("compression", "1.0", "classic", "ATR(rapide)/ATR(lent) : < 1 compression, > 1 expansion.",
         {"fast": P("int", 2, 50, 5), "slow": P("int", 10, 300, 50)}, {"value": "ratio"})
def f_compression(b, fast, slow):
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"value": atr_arr(b, fast) / atr_arr(b, slow)}


@feature("rel_volume", "1.0", "volume", "Tick volume / SMA(n) du tick volume (PAS du volume réel).",
         {"period": P("int", 5, 500, 20)}, {"value": "ratio"},
         approximate="tick volume : proxy d'activité, pas un volume échangé")
def f_relvol(b, period):
    v = b.tick_volume.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"value": v / sma(v, period)}


@feature("spread", "1.0", "market", "Spread de la barre en points ; NaN si le spread historique est nul (inconnu).",
         {}, {"points": "ratio"})
def f_spread(b):
    s = b.spread.astype(float)
    return {"points": np.where(s > 0, s, np.nan)}
