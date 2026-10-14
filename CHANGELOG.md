# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/). Versions des composants : `engine/src/qlab/core/versions.py`.

## [Non publié]
### Corrigé
- Campagne « bloquée à 0 % » : la progression n'avançait qu'en fin de génération (très longue avec de grandes populations). Les évaluations se font maintenant par lots : progression visible dans la génération, temps restant estimé, pause et arrêt pris en compte en quelques secondes (la génération interrompue est rejouée à la reprise, évaluations déjà faites réutilisées depuis le cache).
- Boutons Pause / Reprendre / Arrêter sur toute tâche en cours (laboratoire, Tâches & journaux, panneau d'activité) ; l'arrêt d'une campagne en cours n'était pas proposé. Avertissement pour les campagnes de plus de 50 000 évaluations.
### Ajouté
- Validation automatique : `auto_validate_top` (défaut 5 dans l'interface) soumet en fin de campagne la validation complète (filtrage → hors échantillon) des N meilleures du front, classées par Sharpe de validation.
- Éditeur visuel de stratégie (écran Génome) : arbre ET / OU / NON, comparaisons et événements sur tous les indicateurs, sorties, risque et gestion ; validation et description en direct par le moteur ; bascule JSON.
- Bibliothèque de stratégies : favoris, étiquettes, notes (migration 0008 `strategy_notes`), filtres, comparaison côte à côte de 2 à 4 stratégies (métriques et règles).
- Planification (migration 0008 `schedules`) : campagnes programmées (une fois / chaque jour / chaque semaine), mise à jour quotidienne des données MT5 ; une planification invalide est suspendue avec son erreur. Notifications Windows à la fin ou en échec d'une tâche.
- Guide pas à pas : 6 étapes (MT5, données, campagne, validation, parité MT5, démo) cochées d'après l'état réel, avec l'action suivante.
- Bases de stratégie : suivi de tendance, retour à la moyenne, cassure de range, cassure de session, ICT / Smart Money, repli dans la tendance (paramètres tirés au hasard, 60 % de la population de départ et des immigrants, le reste aléatoire). API `GET /strategy-bases`.
- Relance d'une campagne depuis les stratégies retenues d'une campagne précédente (front final + statut ≥ filtrée, 40 au plus) : au plus la moitié de chaque tribu, réglages repris, filiation « reseed » conservée ; stratégies devenues invalides sur le nouveau marché écartées.
- Création de campagne simplifiée : 4 étapes (marché, bases, repartir de, effort), préréglages Rapide / Standard / Approfondie, contexte supérieur choisi automatiquement, spread demandé seulement si les données en manquent, options avancées repliées ; bouton « Relancer » dans la liste et le laboratoire.
- `build_installer.ps1 -NotesFile` : notes de version lues en UTF-8.
- Refonte de l'interface (identité « Nocturne ») : barre haute avec écrans favoris, rail d'icônes groupé, palette de commandes (Ctrl+K : écrans, campagnes, révisions, thèmes), panneau d'activité (tâches + flux d'événements), barre d'état (moteur, worker, schéma, disque, heure UTC), raccourcis Alt+1…9 / Ctrl+J / Ctrl+B / Ctrl+,.
- Personnalisation (préférences locales au poste) : 4 thèmes (Nocturne, Graphite, Ivoire, Ambre), couleur d'accent, palettes hausse/baisse (dont daltonienne), densité, type de graphique de prix, grille, réticule aimanté, favoris, écran de départ.
- Graphiques : prix en bougies et capital + drawdown via `lightweight-charts` 5.2.1 (TradingView, Apache-2.0, logo d'attribution conservé) ; graphiques explicatifs SVG (walk-forward, WFO, Monte Carlo, hasard, sensibilité, stress de coûts, distribution des R, profit mensuel, heure × jour, corrélations, contribution au risque, entonnoir de validation, parité MT5), chacun accompagné d'une « lecture » en clair.
- Mode capture QA : défilement page par page et vue détaillée ; `QLAB_UI_SNAPSHOT_THEME` pour capturer dans un thème donné.
- Mises à jour de l'application : source configurable (dossier local, partage réseau ou URL https) contenant `latest.json` et l'installateur ; vérification au démarrage, téléchargement et installation uniquement sur action de l'utilisateur, empreinte SHA-512 et taille contrôlées avant exécution, installation NSIS silencieuse puis redémarrage ; tâches en cours signalées avant installation (reprises en pause au redémarrage).
- `scripts/build_installer.ps1 -Version x.y.z -Publish <dossier> -Notes "…"` : fixe la version, génère `latest.json` et publie.

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
- API locale v1 et interface Electron/React (13 écrans, français), empaquetage `electron-builder` (répertoire).
- Expériences contrôlées sur les méthodes de recherche (section 18) avec canal expérimental et retour arrière.
- Diagnostics de parité (écarts classés : gap, ambiguïté intrabar, non expliqué).

### Corrigé pendant le développement (constatés par les tests ou les runs réels)
- Conversion d'époque incorrecte avec pandas 3 (résolution en secondes).
- FVG non détectés en début de série quand aucun seuil ATR n'était demandé.
- Filiation dupliquée lors d'un croisement d'un parent avec lui-même.
- Identifiants de nœuds dupliqués dans la tribu de spécialisation (objet partagé).
- Échappements de chemins MQL5 (`\\`) dans les drapeaux de suspension.
- Renderer vide sous `file://` : passage au protocole `app://`.
- Multiplicité (DSR) sous-estimée quand des évaluations sont réutilisées depuis le cache partagé.
- Paramètre de configuration `memory_limit_mb` non appliqué : supprimé.
- Versions de composants inexistants (`backtester_fast`, `presentation_score`) retirées.
- Parité : la référence appliquait le glissement de recherche alors que le testeur n'en a pas (ADR-013).

### Générateur MQL5
- 1.0 : version initiale (parité A sur XAUUSD M5).
- 1.1 : `InpRiskScale` (réduction uniquement), verrou inter-robots par bougie, suspension/arrêt d'urgence par fichiers drapeaux.
