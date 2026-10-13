"""Profils de coûts versionnés. Les coûts inconnus sont étiquetés 'assumed', jamais présentés comme réels."""
from __future__ import annotations

import numpy as np

from ..core.hashing import sha256_json

# Profil par défaut : toutes les valeurs sont des HYPOTHÈSES à remplacer par des valeurs observées.
DEFAULT_COST_PROFILE = {
    "name": "default-assumed",
    "version": 1,
    "spread_mode": "max",            # bars | fixed | max(bars, fixed)
    "fixed_spread_points": None,     # requis si le spread historique est nul/inconnu
    "commission_per_lot_side": 0.0,  # devise du compte
    "slippage_points": 0,
    "apply_swap": True,
    "provenance": {"spread": "assumed", "commission": "assumed", "slippage": "assumed", "swap": "symbol_spec"},
}


class CostError(ValueError):
    pass


def profile_sha(p: dict) -> str:
    return sha256_json(p)


def spread_series(bars, profile: dict) -> np.ndarray:
    """Spread en points par barre selon le profil ; erreur si inconnu (jamais 0 par défaut)."""
    s = bars.spread.astype(float)
    fixed = profile.get("fixed_spread_points")
    mode = profile["spread_mode"]
    if mode == "fixed":
        if fixed is None:
            raise CostError("spread_mode=fixed sans fixed_spread_points")
        return np.full(len(s), float(fixed))
    if mode == "max":
        if fixed is None:
            if (s <= 0).any():
                raise CostError("spread historique nul/inconnu sur certaines barres : définir fixed_spread_points")
            return s
        return np.maximum(s, float(fixed))
    if (s <= 0).any():
        raise CostError("spread_mode=bars mais spread historique nul/inconnu")
    return s


def value_per_price_unit(spec: dict, price: float) -> tuple[float, bool]:
    """Valeur (devise du compte) d'un mouvement de 1.0 du prix pour 1 lot. Retourne (valeur, approximative)."""
    acc = spec.get("account_currency")
    cs = float(spec["trade_contract_size"])
    if spec.get("currency_profit") == acc:
        return cs, False
    if spec.get("currency_base") == acc:
        return cs / price, False
    return float(spec["trade_tick_value"]) / float(spec["trade_tick_size"]), True
