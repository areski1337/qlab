"""Utilitaires temporels. Toutes les dates internes sont en UTC."""
from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ts_to_iso(ts: int | float) -> str:
    return dt.datetime.fromtimestamp(int(ts), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_ts(s: str) -> int:
    s = s.strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise ValueError(f"date sans fuseau refusée (ambiguë) : {s!r}")
    return int(d.timestamp())


TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


def tf_seconds(tf: str) -> int:
    try:
        return TIMEFRAME_SECONDS[tf]
    except KeyError as e:
        raise ValueError(f"timeframe non supporté : {tf}") from e
