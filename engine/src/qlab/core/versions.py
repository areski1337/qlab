"""Versions des moteurs et composants.

Toute modification produisant des résultats différents DOIT incrémenter la
version correspondante : elle entre dans les clés de cache et dans chaque
expérience, ce qui invalide les résultats dépendants (AT-005) sans jamais
réécrire les anciens.
"""
from __future__ import annotations

# Version du format moteur, présente dans chaque clé de cache : volontairement découplée de la version de
# l'application (0.6.x) ; la changer invaliderait toutes les évaluations existantes sans changer un résultat.
ENGINE_VERSION = "0.1.0"
RELEASE_CHANNEL = "beta"  # stable | beta | experimental

COMPONENT_VERSIONS: dict[str, str] = {
    "genome_schema": "1.0",
    "data_normalizer": "1.0",
    "data_qc": "1.0",
    "feature_engine": "1.0",
    "regime_engine": "1.0",
    "backtester_reference": "1.1",  # 1.1 : résolution M1, week-end, annonces, profil d'exécution
    "cost_model": "1.1",  # 1.1 : spread_scale (stress multiplicatif)
    "metrics": "1.0",
    "validation_protocol": "1.2",  # 1.2 : décision OOS sur le R net, estimation sans figer les frontières ; 1.1 : frontières datées par série, OOS corrigé de la multiplicité, DSR par série
    "evolution_operators": "1.0",
    "nsga2": "1.0",
    "mql5_generator": "1.4",  # 1.4 : arrêt de la garde compte dans un fichier séparé, lecture ratée = refus, écriture atomique ; 1.3 : garde compte persistante en équité (hors testeur), refus du réel revérifié avant chaque ordre ; 1.2 : week-end, objectif journalier, filtre d'annonces ; 1.1 : InpRiskScale, verrou inter-robots, suspension/arrêt d'urgence
    "parity": "1.0",
    "risk_controller": "1.1",  # 1.1 : objectif journalier, week-end, filtre d'annonces
    "portfolio": "1.1",  # 1.1 : rapport hors échantillon avec les poids de recherche
}


def versions_snapshot() -> dict[str, str]:
    return {"engine": ENGINE_VERSION, "channel": RELEASE_CHANNEL, **COMPONENT_VERSIONS}
