"""Versions des moteurs et composants.

Toute modification produisant des résultats différents DOIT incrémenter la
version correspondante : elle entre dans les clés de cache et dans chaque
expérience, ce qui invalide les résultats dépendants (AT-005) sans jamais
réécrire les anciens.
"""
from __future__ import annotations

ENGINE_VERSION = "0.1.0"
RELEASE_CHANNEL = "beta"  # stable | beta | experimental

COMPONENT_VERSIONS: dict[str, str] = {
    "genome_schema": "1.0",
    "data_normalizer": "1.0",
    "data_qc": "1.0",
    "feature_engine": "1.0",
    "regime_engine": "1.0",
    "backtester_reference": "1.1",  # 1.1 : résolution M1, week-end, annonces, profil d'exécution
    "cost_model": "1.0",
    "metrics": "1.0",
    "validation_protocol": "1.0",
    "evolution_operators": "1.0",
    "nsga2": "1.0",
    "mql5_generator": "1.2",  # 1.2 : week-end, objectif journalier, filtre d'annonces ; 1.1 : InpRiskScale, verrou inter-robots, suspension/arrêt d'urgence
    "parity": "1.0",
    "risk_controller": "1.1",  # 1.1 : objectif journalier, week-end, filtre d'annonces
    "portfolio": "1.0",
}


def versions_snapshot() -> dict[str, str]:
    return {"engine": ENGINE_VERSION, "channel": RELEASE_CHANNEL, **COMPONENT_VERSIONS}
