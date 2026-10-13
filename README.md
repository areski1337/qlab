# QLab — plateforme locale de recherche quantitative

Application de bureau Windows qui importe l'historique d'un courtier via MetaTrader 5, fait évoluer des stratégies de trading (algorithme génétique multi-objectif), mesure leur robustesse, génère des Expert Advisors MQL5, les compile avec MetaEditor, compare leur comportement au Strategy Tester et observe un compte démo en lecture seule.

> **Aucune stratégie n'est garantie rentable.** Le meilleur résultat d'une recherche sur de nombreux candidats est biaisé à la hausse. Le trading réel est désactivé et non activable dans cette version.

## Démarrage rapide
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # uv sync, npm ci, build, tests
powershell -ExecutionPolicy Bypass -File scripts\start.ps1     # lance l'interface + le moteur local
```
Détails : [docs/operations/installation.md](docs/operations/installation.md).

## Ce qui fonctionne (vérifié)
- Import MT5 réel (XAUUSD M5 2020→2026 : 476 490 barres), normalisation UTC avec profil de fuseau vérifié contre l'heure serveur, contrôle qualité, versions immuables.
- 27 features typées et versionnées (classiques, sessions/Kill Zones, VWAP ancré, structure ICT/SMC : pivots, BOS/CHOCH/MSS, FVG/IFVG, Order/Breaker Blocks, sweeps, equal highs/lows, PDH/PDL/PWH/PWL, premium/discount, régimes). Aucune fuite temporelle (test de troncature sur chaque feature).
- Génome canonique JSON Schema + validation sémantique, révisions immuables, généalogie.
- Moteur de backtest de référence avec spread/commission/swap/glissement, contrôleur de risque indépendant (limites absolues hors génome).
- Campagnes génétiques NSGA-II à contraintes, 4 tribus + fusion, diversité, stagnation, mémoire des opérateurs, checkpoints et reprise sans doublon, workers parallèles.
- Robustesse : walk-forward à paramètres figés, sensibilité, stress de coûts, Monte Carlo, baselines aléatoires, Deflated Sharpe Ratio ; statuts de validation à preuves.
- Générateur MQL5 déterministe → compilation MetaEditor réelle (0 erreur, 0 avertissement) → Strategy Tester réel → parité : premier run XAUUSD M5 (août–sept. 2026) **note A**, 12/12 trades, 18/18 signaux, écart PnL 0,9 %.
- Passeport de stratégie (observations / hypothèses / interprétations / non vérifié), export ZIP avec manifeste d'empreintes.
- Portefeuille (allocation bornée, corrélations, risque marginal, exposition), démo en lecture seule (dégradation, suspension, arrêt d'urgence, paliers de risque 25/50/100 %).
- Interface Electron/React en français, 13 écrans connectés à l'API locale.

État complet, partiel et absent : [docs/inventory.md](docs/inventory.md). Résultats de tests : [docs/testing/results.md](docs/testing/results.md).

## Structure
```
engine/   moteur Python (qlab) : API, données, features, génome, backtest, évolution, validation, MQL5, démo
app/      interface Electron + React (TypeScript)
examples/ génomes (valides/invalides), EA générés, passeport
docs/     exigences, architecture, décisions, tests, opérations, validation scientifique
scripts/  installation et démarrage
```

## Tests
```powershell
cd engine; uv run pytest -q                      # suite complète (MT5 non requis)
$env:QLAB_MT5_TESTS="1"; uv run pytest -q        # + import MT5 et compilation MetaEditor réels
```

## Limites principales
Moteur sur barres (pas de ticks) avec convention conservatrice ; calendrier économique indisponible (filtre d'annonces inactif) ; déploiement démo manuel ; régimes non exportables en MQL5 v1 ; Strategy Tester en ligne de commande seulement terminal fermé. Voir [docs/scientific-validation/protocol.md](docs/scientific-validation/protocol.md).

## Licences
Dépendances libres : Python (PSF), numpy/pandas (BSD), pyarrow (Apache-2.0), FastAPI/Starlette/uvicorn (MIT/BSD), jsonschema (MIT), MetaTrader5 (paquet MetaQuotes, gratuit), Electron/React/Vite/TypeScript (MIT/Apache-2.0). Aucune télémétrie.
