# Stratégie de test

| Niveau | Où | Contenu |
|---|---|---|
| Unitaires | `engine/tests/test_foundations.py`, `test_data.py`, `test_features.py`, `test_genome_backtest.py`, `test_portfolio_demo.py` | migrations, tâches, fuseaux, QC, chaque feature, validation de génome, scénarios d'exécution déterministes (stop/objectif même barre, gap, coûts, lots, perte journalière) |
| Non-régression scientifique | `test_features.py::test_no_lookahead_by_truncation` (toutes features), `test_mql5.py::test_window_convergence` (toutes features) | un changement de formule qui introduit une dépendance au futur ou casse la parité fenêtrée échoue |
| Intégration | `test_evolution.py`, `test_validation.py`, `test_passport.py`, `test_api.py` | campagnes complètes, reprise après interruption, parallèle ≡ local, pipeline de statuts, API de bout en bout |
| Différentiel réel (opt-in `QLAB_MT5_TESTS=1`) | `test_data.py::test_real_mt5_import`, `test_mql5.py::test_real_metaeditor_compiles_examples` | terminal MT5 et MetaEditor réels |
| Parité MT5 (manuel/tâche) | `mql5/verify.py` via l'API ou l'interface | Strategy Tester réel ; rapport archivé en base |
| Sécurité | `test_api.py` (jeton, chemins), contrôles Electron (IPC, CSP, origine `app://`) | |
| UI (QA) | `QLAB_UI_SNAPSHOT_DIR=<dossier> npx electron .` | captures de chaque écran dans une fenêtre cachée + journal console du renderer |

Jeux de données synthétiques déterministes (graines fixes) : barres à régimes de volatilité (`make_bars`), barres écrites à la main (`from_closes`) pour FVG, pivots, BOS, sessions/DST, stop/objectif, gaps, lots, risque, reprise.

Règle : un test qui échoue est diagnostiqué ; il n'est jamais supprimé ni assoupli pour passer. Les corrections de tests faites pendant le développement portaient sur des scénarios mal construits (ex. : scénario de perte journalière qui générait des gains), documentées dans l'historique git.
