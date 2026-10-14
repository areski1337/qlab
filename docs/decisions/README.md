# Décisions techniques (ADR condensés)

### ADR-001 — Moteur scientifique en Python 3.13 (uv)
Benchmark réel (2026-10-13) : backtest d'un génome ICT sur 476 490 barres M5 XAUUSD = 0,94 s (features calculées) puis 0,27 s (cache). Suffisant pour des campagnes de milliers d'évaluations en parallèle. Python 3.15 présent mais trop récent pour les roues binaires ; uv fournit 3.13. Pas de numba/GPU (non mesuré nécessaire).

### ADR-002 — Un seul moteur de backtest de référence ; différentiel contre MT5
Le prompt cite « backtester interne » et « moteur de référence ». Deux implémentations Python partageant les mêmes fonctions de coûts n'apporteraient qu'une indépendance illusoire. Le moteur unique est rapide (saut de signal en signal) et la vérification différentielle indépendante est faite contre le Strategy Tester MT5 (implémentation tierce). Le look-ahead est vérifié séparément par troncature.

### ADR-003 — L'EA recalcule les features sur une fenêtre de W barres
Pas d'indicateurs MT5 natifs (amorçages différents). Chaque feature est réécrite en MQL5 à l'identique ; W est choisi pour que le calcul fenêtré égale le calcul complet (EMA/Wilder : erreur < 1e-12 ; états de chemin bornés par expiration). Vérifié par `test_window_convergence` et par la parité réelle (note A).

### ADR-004 — SQLite + Parquet + artefacts adressés par contenu
Métadonnées transactionnelles en SQLite (WAL, migrations à checksum, sauvegarde avant migration). Séries en Parquet zstd ; empreinte calculée sur les octets canoniques des colonnes (indépendante du format). Artefacts (trades, rapports, logs, ex5) immuables par SHA-256.

### ADR-005 — Sémantique d'exécution
Signal à la clôture de i, ordre au marché à l'ouverture de i+1 ; une position par stratégie ; stop/objectif côté serveur ; BE/trailing/time stop/sortie opposée décidés à la clôture. Choisie parce qu'implémentable à l'identique en MQL5 et sans look-ahead.

### ADR-006 — Barre ambiguë : stop retenu
Sans ticks, si stop et objectif sont touchés dans la même barre, le stop est retenu (pire cas) et la barre est marquée `ambiguous`. Le ratio d'ambiguïté est une contrainte éliminatoire de campagne.

### ADR-007 — NSGA-II à domination contrainte, tribus en round-robin
Les contraintes éliminatoires (trades min, DD max, ambiguïté, exportabilité, spécialisation) ne sont jamais compensées par un objectif. Les tribus avancent génération par génération en alternance (progression parallèle, checkpoint unique). Fusion avec objectifs train + validation.

### ADR-008 — Gouvernance des segments
`train` (fitness), `validation` (sélection/fusion), `oos` (évaluation des retenus, multiplicité comptée), `final` (inaccessible aux campagnes, chaque usage tracé, indépendance perdue au-delà d'une révision évaluée).

### ADR-009 — Sécurité Electron
`contextIsolation`, `sandbox`, `nodeIntegration=false`, CSP `'self'` servie via protocole privilégié `app://` (le chargement `file://` bloquait les modules ES), IPC limité à un motif de chemins `/api/v1/...` et trois méthodes, jeton aléatoire par session, API liée à 127.0.0.1, refus des permissions, navigation et fenêtres bloquées.

### ADR-010 — Déploiement démo manuel, contrôle par fichiers drapeaux
QLab n'attache pas l'EA et n'active pas l'AutoTrading (action à effet externe laissée à l'utilisateur). La suspension/l'arrêt d'urgence passent par des fichiers du dossier commun MT5 lus par l'EA à chaque barre : plus d'entrées, positions conservées.

### ADR-011 — Régimes non exportables en v1 (remplacée par ADR-014)
La médiane glissante de spread du détecteur de régimes est trop coûteuse barre à barre dans le testeur. Export bloqué explicitement ; la contrainte `exportable_only` (défaut) pénalise ces génomes en campagne sans interdire l'exploration.

### ADR-012 — Fermeture du terminal lancé par QLab
Le paquet MetaTrader5 laisse le terminal ouvert après `shutdown()`. Une session de lecture qui a lancé le terminal le referme proprement (WM_CLOSE) ; un terminal déjà ouvert par l'utilisateur n'est jamais fermé. Le Strategy Tester en ligne de commande exige un terminal fermé : sinon statut `blocked`.

### ADR-013 — La parité rejoue la référence dans les conditions du testeur
La comparaison vise la logique d'exécution, pas les hypothèses de coûts de recherche. La référence est donc rejouée avec : spread des barres, commission **observée** dans les deals du testeur, glissement nul (le testeur tourne en `ExecutionMode=0`, sans latence). Constaté sur un génome du GA : avec le glissement de recherche (2 pts) conservé, écart systématique de 2 pts par trade et note C malgré 100 % de signaux et de trades concordants. Les coûts utilisés figurent dans chaque rapport (`reference_costs`).

### ADR-014 — Régimes exportables depuis regime 1.1 (remplace ADR-011)
La médiane glissante de spread a été remplacée par une moyenne glissante, calculable barre à barre dans l'EA. Les régimes sont donc exportables (`mql5/generator.py` : `SUPPORTED = set(REGISTRY)`) et soumis à la même parité que les autres features.

### ADR-015 — Garde compte persistante dans l'EA, hors parité
Le contrôleur de risque de l'EA reproduit celui du moteur de référence (solde, état en mémoire) pour garantir la parité. Il ne protégeait ni contre un redémarrage (pic réinitialisé, arrêt levé), ni contre la perte latente, ni contre le cumul de plusieurs EA. Une garde distincte, active seulement hors Strategy Tester, tient un état commun au compte dans `Common/Files/QLab/guard_<login>.csv` (pic d'équité, arrêt, équité de début de jour) : arrêt définitif au-delà de `max_drawdown_pct` en équité, blocage du jour au-delà de `max_daily_loss_pct`. Levée uniquement manuelle (écran Démo, action tracée). Non reproduite par le moteur Python : elle ne peut que refuser des entrées, jamais en créer. Le refus du compte réel est aussi revérifié avant chaque ordre.

### ADR-016 — Frontières de segments datées et multiplicité par série
Des segments en fractions du nombre de barres glissaient à chaque ré-import plus long : d'anciennes barres oos/final passaient en train/validation et les compteurs de multiplicité repartaient de zéro. Les frontières sont figées en horodatages au premier usage d'une série (table `segment_boundaries`, migration 0009) ; les barres nouvelles forment le segment `forward`. Les compteurs (holdout final, oos) et les essais du DSR sont agrégés par série, toutes versions et campagnes confondues ; la décision OOS est corrigée de ce nombre (Šidák).

### ADR-017 — Manifeste de mise à jour signé (Ed25519)
L'empreinte SHA-512 venait du manifeste publié à côté de l'installateur : intégrité sans authenticité. Le manifeste est désormais signé par `scripts/sign_manifest.mjs` (clé privée hors dépôt, `~/.qlab/update_ed25519.pem`) et vérifié avec la clé publique figée dans `app/electron/updater.ts`, quelle que soit la source. Perte de la clé privée = plus aucune mise à jour automatique possible (réinstallation manuelle d'une version portant une nouvelle clé) : la clé doit être sauvegardée hors du poste.
