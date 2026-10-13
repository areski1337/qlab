"""Données SYNTHÉTIQUES déterministes, toujours étiquetées comme telles."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.timeutil import iso_to_ts, tf_seconds

SYNTHETIC_SPEC = {
    "symbol": "SYNTH_XAU", "digits": 2, "point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0,
    "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0,
    "currency_base": "XAU", "currency_profit": "USD", "currency_margin": "USD", "account_currency": "USD",
    "swap_mode": 1, "swap_long": -10.0, "swap_short": -2.0, "swap_rollover3days": 3,
    "trade_stops_level": 0, "synthetic": True,
}


def make_bars(n: int, timeframe: str = "M5", seed: int = 7, start: str = "2024-01-01T00:00:00Z",
              price: float = 2000.0, spread_points: int = 30) -> pd.DataFrame:
    """Marche aléatoire à régimes de volatilité, week-ends exclus. Heure « serveur » = UTC."""
    rng = np.random.default_rng(seed)
    tf = tf_seconds(timeframe)
    # Horodatages hors week-end (vendredi 22:00 UTC → dimanche 22:00 UTC exclus).
    t0 = iso_to_ts(start)
    cand = t0 + np.arange(int(n * 1.6) + 10) * tf
    dt = pd.to_datetime(cand, unit="s")
    dow, hour = dt.dayofweek.to_numpy(), dt.hour.to_numpy()
    closed = (dow == 5) | ((dow == 4) & (hour >= 22)) | ((dow == 6) & (hour < 22))
    ts = cand[~closed][:n]

    regime = np.cumsum(rng.random(n) < 0.002) % 3  # changements de régime rares
    vol = np.array([0.0004, 0.0009, 0.0018])[regime] * np.sqrt(tf / 300)
    drift = np.array([0.00002, -0.00002, 0.0])[regime]
    ret = drift + vol * rng.standard_t(5, n) / np.sqrt(5 / 3)
    close = price * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[price], close[:-1]])
    wig = np.abs(rng.normal(0, vol * 0.6, (2, n))) * close
    high = np.maximum(open_, close) + wig[0]
    low = np.minimum(open_, close) - wig[1]
    r = lambda x: np.round(x, 2)
    return pd.DataFrame({"ts": ts, "open": r(open_), "high": r(high), "low": r(low), "close": r(close),
                         "tick_volume": rng.integers(50, 500, n), "spread": np.full(n, spread_points),
                         "real_volume": np.zeros(n, np.int64)})


def from_closes(closes, timeframe: str = "M5", start: str = "2024-01-01T00:00:00Z",
                highs=None, lows=None, opens=None, spread_points: int = 0) -> pd.DataFrame:
    """Petits jeux de barres écrits à la main pour les tests de référence."""
    c = np.asarray(closes, float)
    o = np.asarray(opens, float) if opens is not None else np.concatenate([[c[0]], c[:-1]])
    h = np.asarray(highs, float) if highs is not None else np.maximum(o, c)
    l = np.asarray(lows, float) if lows is not None else np.minimum(o, c)
    n = len(c)
    return pd.DataFrame({"ts": iso_to_ts(start) + np.arange(n) * tf_seconds(timeframe), "open": o, "high": h,
                         "low": l, "close": c, "tick_volume": np.ones(n, np.int64) * 100,
                         "spread": np.full(n, spread_points), "real_volume": np.zeros(n, np.int64)})
