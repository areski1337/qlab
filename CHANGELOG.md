# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/). Versions des composants : `engine/src/qlab/core/versions.py`.

## [0.1.0] — 2026-10-13 (bêta)
### Ajouté
- Fondations : SQLite (WAL) avec migrations à checksum et sauvegarde préalable, artefacts adressés par SHA-256, file de tâches persistante à états contrôlés, checkpoints atomiques, journaux JSON UTC sans secrets, audit, sauvegarde/restauration vérifiée.
- Données : import MT5 en lecture seule, profils de fuseau serveur vérifiés (NY+7, UTC±N, IANA), normalisation UTC, contrôle qualité, versions immuables, données synthétiques étiquetées, alignement multi-timeframe.
- Features v1.0 (27) dont ICT/SMC et régimes ; tests de troncature sur chaque feature.
- Génome canonique `qlab.genome/1.0` (JSON Schema + validation sémantique), révisions et filiation.
- Moteur de backtest de référence (coûts, gaps, barres ambiguës), contrôleur de risque indépendant, métriques.
- Évolution : opérateurs typés, NSGA-II contraint, 4 tribus + fusion, diversité, stagnation, mémoire des opérateurs, reprise sans doublon, workers parallèles.
- Validation : segments chronologiques, holdout final gouverné, robustesse (WF figé, sensibilité, stress de coûts, Monte Carlo, baselines aléatoires, DSR), statuts à preuves.
- MQL5 : générateur déterministe (bibliothèque miroir), compilation MetaEditor réelle, Strategy Tester, parité A–F.
- Passeport et export ; portefeuille borné ; démo en lecture seule (dégradation, suspension, arrêt d'urgence, paliers de risque).
- API locale v1 et interface Electron/React (13 écrans, français).

### Corrigé pendant le développement (constatés par les tests ou les runs réels)
- Conversion d'époque incorrecte avec pandas 3 (résolution en secondes).
- FVG non détectés en début de série quand aucun seuil ATR n'était demandé.
- Filiation dupliquée lors d'un croisement d'un parent avec lui-même.
- Identifiants de nœuds dupliqués dans la tribu de spécialisation (objet partagé).
- Échappements de chemins MQL5 (`\\`) dans les drapeaux de suspension.
- Renderer vide sous `file://` : passage au protocole `app://`.
- Multiplicité (DSR) sous-estimée quand des évaluations sont réutilisées depuis le cache partagé.
- Paramètre de configuration `memory_limit_mb` non appliqué : supprimé.

### Générateur MQL5
- 1.0 : version initiale (parité A sur XAUUSD M5).
- 1.1 : `InpRiskScale` (réduction uniquement), verrou inter-robots par bougie, suspension/arrêt d'urgence par fichiers drapeaux.
