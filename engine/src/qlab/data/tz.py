"""Fuseaux horaires des serveurs de courtiers.

Un profil n'est JAMAIS deviné silencieusement : il est déclaré dans le dataset
et vérifié à l'import contre l'heure serveur observée (voir check_profile).

Profils :
- "NY+7"   : heure serveur = heure de New York + 7 h (GMT+2 hiver / GMT+3 été
             US). Minuit serveur = 17h00 New York. Convention FTMO et de
             nombreux courtiers MT5 — vérifiée sur FTMO-Demo le 2026-10-13.
- "UTC"    : heure serveur = UTC.
- "UTC+N" / "UTC-N" : décalage fixe sans changement d'heure.
- tout nom IANA (ex. "Europe/Athens").
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

_FIXED = re.compile(r"^UTC([+-]\d{1,2})$")


def _epoch_s(idx: pd.DatetimeIndex) -> np.ndarray:
    # Indépendant de la résolution interne de pandas (ns en 2.x, s possible en 3.x).
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.to_numpy().astype("datetime64[s]").astype(np.int64)


def server_to_utc(ts_server: np.ndarray, profile: str) -> tuple[np.ndarray, np.ndarray]:
    """Convertit des secondes « heure serveur » en secondes UTC.

    Retourne (ts_utc, invalid_mask). invalid_mask marque les heures locales
    ambiguës ou inexistantes (changement d'heure) : elles ne sont pas
    converties arbitrairement.
    """
    ts_server = np.asarray(ts_server, dtype=np.int64)
    if profile == "UTC":
        return ts_server.copy(), np.zeros(len(ts_server), bool)
    m = _FIXED.match(profile)
    if m:
        return ts_server - int(m.group(1)) * 3600, np.zeros(len(ts_server), bool)
    if profile == "NY+7":
        zone, shift = "America/New_York", 7 * 3600
    else:
        zone, shift = profile, 0
    naive = pd.to_datetime(ts_server - shift, unit="s")
    local = naive.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
    invalid = np.asarray(local.isna())
    out = np.zeros(len(ts_server), np.int64)
    out[~invalid] = _epoch_s(local[~invalid])
    return out, invalid


def utc_to_server(ts_utc: np.ndarray, profile: str) -> np.ndarray:
    ts_utc = np.asarray(ts_utc, dtype=np.int64)
    if profile == "UTC":
        return ts_utc.copy()
    m = _FIXED.match(profile)
    if m:
        return ts_utc + int(m.group(1)) * 3600
    zone, shift = ("America/New_York", 7 * 3600) if profile == "NY+7" else (profile, 0)
    loc = pd.to_datetime(ts_utc, unit="s", utc=True).tz_convert(zone).tz_localize(None)
    return _epoch_s(loc) + shift


def expected_offset_hours(profile: str, ts_utc: int) -> float:
    return float(utc_to_server(np.array([ts_utc]), profile)[0] - ts_utc) / 3600


def check_profile(profile: str, observed_server_ts: int, observed_utc_ts: float, tol_s: int = 900) -> dict:
    """Compare l'heure serveur observée (dernier tick) au profil déclaré."""
    observed = round((observed_server_ts - observed_utc_ts) / 3600 * 4) / 4
    expected = expected_offset_hours(profile, int(observed_utc_ts))
    ok = abs((observed_server_ts - observed_utc_ts) - expected * 3600) <= tol_s
    return {"profile": profile, "observed_offset_h": observed, "expected_offset_h": expected, "consistent": ok}
