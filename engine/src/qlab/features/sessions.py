"""Sessions, Kill Zones, journée de trading et VWAP.

Journée de trading : commence à 17:00 America/New_York (convention FX,
= minuit serveur pour un courtier « NY+7 »). Les changements d'heure US sont
gérés via la base IANA.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.tz import utc_to_server
from .registry import Param, feature

# nom -> (zone IANA, début HH:MM, fin HH:MM) en heure locale de la zone.
SESSIONS = {
    "tokyo": ("Asia/Tokyo", "09:00", "18:00"),
    "london": ("Europe/London", "08:00", "17:00"),
    "new_york": ("America/New_York", "08:00", "17:00"),
    "ldn_ny_overlap": ("America/New_York", "08:00", "12:00"),
    "asia_kz": ("America/New_York", "20:00", "00:00"),
    "london_kz": ("America/New_York", "02:00", "05:00"),
    "ny_am_kz": ("America/New_York", "07:00", "10:00"),
    "london_close_kz": ("America/New_York", "10:00", "12:00"),
}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def local_minutes(ts_utc: np.ndarray, zone: str) -> np.ndarray:
    loc = pd.to_datetime(ts_utc, unit="s", utc=True).tz_convert(zone)
    return (loc.hour * 60 + loc.minute).to_numpy()


def in_session(ts_utc: np.ndarray, name: str) -> np.ndarray:
    zone, a, b = SESSIONS[name]
    m, s, e = local_minutes(ts_utc, zone), _minutes(a), _minutes(b)
    return (m >= s) & (m < e) if s < e else (m >= s) | (m < e)


def trading_day(ts_utc: np.ndarray) -> np.ndarray:
    """Index de journée de trading (bascule à 17:00 New York)."""
    return utc_to_server(ts_utc, "NY+7") // 86400


def trading_week(ts_utc: np.ndarray) -> np.ndarray:
    return (trading_day(ts_utc) + 3) // 7  # semaine commençant le lundi serveur (= dimanche 17:00 NY)


@feature("session", "1.0", "session", "Vrai si l'instant de décision (clôture de barre) est dans la session.",
         {"name": Param("choice", choices=tuple(SESSIONS))}, {"active": "bool"})
def f_session(b, name):
    return {"active": in_session(b.ts_close, name).astype(float)}


@feature("vwap", "1.0", "volume", "VWAP ancré (jour/semaine de trading), prix typique (H+L+C)/3, "
         "bandes ± dev × écart-type pondéré ; réinitialisé à chaque ancre.",
         {"anchor": Param("choice", choices=("day", "week")), "volume": Param("choice", choices=("tick", "real")),
          "dev": Param("float", 0.0, 4.0, 1.0)},
         {"vwap": "price", "upper": "price", "lower": "price"},
         approximate="volume=tick : pondération par tick volume, proxy du volume réel")
def f_vwap(b, anchor, volume, dev):
    v = (b.real_volume if volume == "real" else b.tick_volume).astype(float)
    nan = np.full(len(b), np.nan)
    if volume == "real" and not (v > 0).any():
        return {"vwap": nan, "upper": nan, "lower": nan}  # donnée indisponible : feature indisponible
    tp = (b.high + b.low + b.close) / 3
    grp = trading_day(b.ts) if anchor == "day" else trading_week(b.ts)
    df = pd.DataFrame({"g": grp, "pv": tp * v, "v": v, "p2v": tp * tp * v})
    c = df.groupby("g")[["pv", "v", "p2v"]].cumsum()
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = (c["pv"] / c["v"]).to_numpy()
        var = np.maximum((c["p2v"] / c["v"]).to_numpy() - vw * vw, 0)
    sd = np.sqrt(var)
    return {"vwap": vw, "upper": vw + dev * sd, "lower": vw - dev * sd}


def minutes_to_weekly_close(ts_utc: np.ndarray) -> np.ndarray:
    """Minutes jusqu'à la clôture hebdomadaire FX (vendredi 17:00 America/New_York) suivante.

    Calcul en heure locale de New York : les changements d'heure US ont lieu le dimanche à 2 h,
    jamais entre lundi et vendredi 17:00, donc la différence locale est exacte.
    """
    loc = pd.to_datetime(ts_utc, unit="s", utc=True).tz_convert("America/New_York")
    wd = loc.dayofweek.to_numpy()          # 0 = lundi
    mins = (loc.hour * 60 + loc.minute).to_numpy() + loc.second.to_numpy() / 60
    days = (4 - wd) % 7
    out = days * 1440 + (17 * 60 - mins)
    return np.where(out <= 0, out + 7 * 1440, out)
