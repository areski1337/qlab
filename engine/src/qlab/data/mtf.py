"""Synchronisation multi-timeframe sans fuite temporelle.

Une barre de timeframe supérieur (HTF) n'est utilisable qu'à partir de sa
clôture. Pour une barre LTF évaluée à sa clôture `t`, la dernière barre HTF
utilisable est celle dont la clôture est <= t.
"""
from __future__ import annotations

import numpy as np


def align_index(ltf_close: np.ndarray, htf_close: np.ndarray) -> np.ndarray:
    """Index de la dernière barre HTF close à chaque clôture LTF (-1 si aucune)."""
    return np.searchsorted(htf_close, ltf_close, side="right") - 1


def align_values(ltf_close: np.ndarray, htf_close: np.ndarray, values: np.ndarray) -> np.ndarray:
    idx = align_index(ltf_close, htf_close)
    out = np.full(len(ltf_close), np.nan) if values.dtype.kind == "f" else np.zeros(len(ltf_close), values.dtype)
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out
