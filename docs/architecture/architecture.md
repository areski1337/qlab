# Architecture

```
┌──────────────────────────── Electron (app/) ────────────────────────────┐
│ renderer React (15 écrans FR)  ──IPC validé──▶  main (proxy + SSE)       │
│ contextIsolation, sandbox, CSP 'self', protocole app://, aucun Node     │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ HTTP 127.0.0.1:<port aléatoire>, en-tête X-QLab-Token
┌───────────────────────────────▼──────── moteur Python (engine/qlab) ────┐
│ api/app.py (FastAPI /api/v1)  ── soumet ──▶ tasks/queue (SQLite)         │
│        ▲ lit                               │ worker thread (runner)      │
│        │                                   ▼                             │
│  storage/ (SQLite+migrations, artefacts SHA-256, sauvegardes)            │
│  data/ (import MT5, UTC, QC, versions Parquet, MTF)                      │
│  features/ (registre typé : classiques, sessions, VWAP, ICT/SMC)         │
│  regime/ (règles + hystérésis, exposé comme feature)                     │
│  genome/ (JSON Schema + validation sémantique, révisions, filiation)     │
│  backtest/ (moteur de référence, coûts) ── risk/ (contrôleur absolu)     │
│  metrics/ · validation/ (segments, robustesse, DSR, pipeline de statuts) │
│  evolution/ (opérateurs typés, NSGA-II, tribus, checkpoints, workers)    │
│  mql5/ (générateur, MetaEditor, Strategy Tester, parité)                 │
│  passport/ · portfolio/ · demo/ (lecture seule, drapeaux de suspension)  │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │ paquet MetaTrader5 (lecture)  │ MetaEditor64 /compile, terminal64 /config
        ┌───────▼────────┐               ┌──────▼────────────────────┐
        │ terminal MT5   │               │ MQL5/Experts/QLab, Common/ │
        └────────────────┘               │ Files/QLab (traces, drapeaux)│
                                         └───────────────────────────┘
```

## Flux principaux
1. **Import** : `mt5_source.fetch_rates` (heure serveur) → `dataset.normalize` (UTC via profil vérifié, corrections listées) → Parquet versionné + brut en artefact → `dataset_versions`.
2. **Évaluation** : `FeatureCache` (clé = empreinte dataset + feature + version + paramètres) → `genome.model.signals` (vectorisé) → `backtest.engine.run` (saute de signal en signal, boucle barre à barre seulement en position) → `metrics.core.compute` → ligne `evaluations` (clé exacte unique).
3. **Campagne** : tâche `campaign` → `Campaign.run` : générations en round-robin par tribu, workers `ProcessPoolExecutor` (calcul pur, aucune écriture), écritures par le seul processus principal, checkpoint atomique par génération.
4. **Validation** : `validation.pipeline.advance` — statut monté d'un cran par preuve (évaluations, rapport de robustesse en artefact, OOS avec multiplicité).
5. **MT5** : `mql5.verify` → génération déterministe → compilation MetaEditor → Strategy Tester (terminal fermé) → trace CSV commune → `parity.compare` → `parity_runs` → statuts `reference_matched` / `mt5_validated`.
6. **Démo** : enregistrement (statut `mt5_validated` requis) → déploiement manuel par l'utilisateur → observation lecture seule → alertes → drapeau de suspension + `quarantined`.

## Conventions
- Temps internes en secondes UTC ; `ts` = ouverture ; disponibilité = clôture.
- Toutes les écritures SQLite passent par une seule connexion par thread (`Lab.attach`) ; WAL activé.
- Artefacts immuables adressés par SHA-256 ; les lignes SQLite ne contiennent que des références.
- Versions de composants (`core/versions.py`) incluses dans chaque clé de cache et chaque évaluation.

## Processus
Un seul processus Python (API + worker thread) + des processus de calcul temporaires pendant les campagnes. Les contrats (API versionnée, tâches persistantes, artefacts par référence) permettent de séparer les modules plus tard sans changer les données.
