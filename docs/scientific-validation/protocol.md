# Protocole de validation scientifique et limites

## Segments chronologiques (protocole `chrono-4seg` v1.0)
`train` 50 % · `validation` 20 % · `oos` 15 % · `final` 15 %, sans chevauchement. Les features n'utilisent que le passé (test de troncature), donc les calculer sur la série complète ne contamine pas les segments antérieurs. Les trades encore ouverts en fin de fenêtre sont clôturés au dernier prix (`end_of_data`), ce qui peut légèrement biaiser les fenêtres courtes.

## Échelle des statuts (preuve obligatoire à chaque cran)
| Statut | Critère par défaut | Preuve |
|---|---|---|
| screened | ≥ min_trades/2 trades en train (ou front de Pareto final faisable) | id d'évaluation |
| historically_tested | ≥ 30 trades sur train+validation, trades conservés | évaluation + artefact de trades |
| robustness_tested | toutes les vérifications ci-dessous **calculables et réussies** | rapport de robustesse (artefact) |
| oos_evaluated | ≥ 15 trades OOS, expectancy > 0, PF > 1 si défini | évaluation OOS + multiplicité OOS |
| reference_matched | concordance des signaux EA/référence ≥ 98 % dans le Strategy Tester | run de parité + trace |
| mt5_validated | note de parité A ou B, aucune divergence critique | run de parité |
| demo_observed | ≥ 20 trades démo sans alerte de dégradation | observation |
Échec → `rejected` (preuve conservée). Dégradation démo → `quarantined`.

## Vérifications de robustesse (fenêtre train+validation)
- **Walk-forward à paramètres figés** : 4 fenêtres successives ; ≥ 50 % de fenêtres à expectancy > 0. *Limite* : pas de ré-optimisation par fenêtre (c'est un test de stabilité, pas un walk-forward d'optimisation).
- **Sensibilité** : voisins ±1 pas (entiers), ×0,8/×1,2 (réels), constantes ×0,9/×1,1, stop/objectif ×0,8/×1,2 ; ≥ 60 % de voisins à expectancy > 0.
- **Stress de coûts** : spread ×1,5 doit rester à expectancy > 0 (×2, glissement, commission rapportés).
- **Monte Carlo** : bootstrap (1 000) des PnL, p95 du drawdown ≤ 35 %. *Hypothèse* : trades i.i.d. (autocorrélation ignorée) ; permutations d'ordre rapportées.
- **Baseline aléatoire** : 100 jeux d'entrées aléatoires (même fréquence ×3, même part long, mêmes sorties et risque) ; p-valeur empirique ≤ 0,05. *Limite* : complémentaire, jamais suffisant.
- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014) : N = nombre de révisions de la campagne évaluées en train, variance des Sharpe des essais, asymétrie/kurtosis des rendements journaliers ; DSR ≥ 0,90. *Limite* : suppose des essais indépendants ; les candidats génétiques sont corrélés, donc N effectif est surestimé.

## Multiplicité et biais de sélection
Tous les candidats (y compris rejetés) sont enregistrés avec leurs métriques. Le meilleur résultat d'une campagne n'est jamais présenté comme estimation de la performance future (avertissement dans chaque résultat de campagne et passeport). Les évaluations OOS comptent le nombre de révisions évaluées sur le même segment ; le holdout final perd son statut indépendant dès qu'une seconde révision y est évaluée.

## Métriques
Après coûts (spread, commission, swap en mode points, glissement). Sharpe/Sortino journaliers (journée 17:00 NY, jours sans trade = 0) annualisés √252, taux sans risque 0. Profit factor indéfini (`None`) sans perte. Drawdown sur equity de clôture des trades (flottant non inclus ; MAE par trade disponible).

## Régimes
Détection par règles explicables + hystérésis, sept familles de présentation, dimensions non exclusives exposées séparément. L'apport hors échantillon d'un filtre de régime n'est pas supposé : il doit apparaître dans les résultats OOS des génomes qui l'utilisent. *Non fait* : ablation automatique dédiée.

## Limites connues
- Pas de données de ticks dans le moteur de référence : convention conservatrice sur barres ambiguës.
- Valeur du point approximative pour les paires croisées (tick value courant).
- Swaps : seul le mode « points » est modélisé ; autres modes → swap non appliqué et signalé.
- Calendrier économique indisponible : filtre d'annonces inactif.
- Spread historique XAUUSD 2021 partiellement nul chez FTMO : un plancher de spread supposé est requis.
