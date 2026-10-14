# Protocole de validation scientifique et limites

## Segments chronologiques (protocole `chrono-4seg` v1.0)
`train` 50 % · `validation` 20 % · `oos` 15 % · `final` 15 %, sans chevauchement. **Frontières datées** (protocole 1.1, ADR-016) : au premier usage d'une série (dataset), les fractions sont converties en horodatages et figées ; toute version ultérieure (ré-import plus long) réutilise ces dates, et les barres postérieures forment le segment `forward`. Une barre oos/final ne revient jamais en train/validation. Les features n'utilisent que le passé (test de troncature), donc les calculer sur la série complète ne contamine pas les segments antérieurs. Les trades encore ouverts en fin de fenêtre sont clôturés au dernier prix (`end_of_data`), ce qui peut légèrement biaiser les fenêtres courtes.

## Échelle des statuts (preuve obligatoire à chaque cran)
| Statut | Critère par défaut | Preuve |
|---|---|---|
| screened | ≥ min_trades/2 trades en train (ou front de Pareto final faisable) | id d'évaluation |
| historically_tested | ≥ 30 trades sur train+validation, trades conservés | évaluation + artefact de trades |
| robustness_tested | toutes les vérifications ci-dessous **calculables et réussies** | rapport de robustesse (artefact) |
| oos_evaluated | ≥ 15 trades OOS, expectancy > 0, PF > 1 si défini, **et** test t unilatéral de la moyenne des R nets (commission et swap compris) au seuil corrigé α_eff = 1 − (1 − 0,05)^(1/m), m = révisions déjà évaluées sur le segment oos de la série | évaluation OOS + test + multiplicité |
| reference_matched | concordance des signaux EA/référence ≥ 98 % dans le Strategy Tester | run de parité + trace |
| mt5_validated | note de parité A ou B, aucune divergence critique | run de parité |
| demo_observed | ≥ 20 trades démo sans alerte de dégradation | observation |
Échec → `rejected` (preuve conservée). Dégradation démo → `quarantined`.

## Vérifications de robustesse (fenêtre train+validation)
- **Walk-forward à paramètres figés** : 4 fenêtres successives ; ≥ 50 % de fenêtres à expectancy > 0.
- **Walk-forward ré-optimisé** : structure figée, paramètres/constantes/sorties ré-optimisés (24 essais) sur la fenêtre ancrée de chaque pli, jeu au meilleur Sharpe (≥ 10 trades) évalué sur le pli suivant ; ≥ 50 % de plis positifs et profit total des plis > 0 ; WFE rapporté.
- *Limite commune* : les deux walk-forward s'exécutent dans train+validation, où la structure a été découverte et sélectionnée : tests de **stabilité in-sample** (`in_sample: true` dans le rapport), jamais une preuve hors échantillon.
- **Sensibilité** : voisins ±1 pas (entiers), ×0,8/×1,2 (réels), constantes ×0,9/×1,1, stop/objectif ×0,8/×1,2 ; ≥ 60 % de voisins à expectancy > 0.
- **Stress de coûts** : le spread effectif (barres, plancher ou fixe) est **multiplié** par 1,5 (éliminatoire : expectancy > 0) et 2 ; glissement (+25 % du spread médian) et commission (+3,5/lot/côté) rapportés.
- **Monte Carlo** : bootstrap (1 000) des PnL, p95 du drawdown ≤ 35 %. *Hypothèse* : trades i.i.d. (autocorrélation ignorée) ; permutations d'ordre rapportées.
- **Baseline aléatoire** : 100 jeux d'entrées aléatoires (même fréquence ×3, même part long, mêmes sorties et risque) ; p-valeur empirique ≤ 0,05. *Limite* : complémentaire, jamais suffisant.
- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014), sur la fenêtre train : N = toutes les révisions évaluées en train sur la même série (toutes campagnes, relances et versions du dataset), variance des Sharpe de ces essais, asymétrie/kurtosis des rendements journaliers ; DSR ≥ 0,90. Avant une campagne, l'interface estime le Sharpe requis pour N essais (budget d'essais).
- **Transfert multi-instruments** : mêmes règles sur d'autres instruments (fenêtre de recherche de chacun) ; informatif, non éliminatoire.
- **Ordre d'exécution** : coûts, Monte Carlo, DSR, walk-forward, sensibilité, baseline, WFO ; au premier critère en échec, les tests restants ne sont pas exécutés (`skipped`) et la stratégie est rejetée. *Limite* : suppose des essais indépendants ; les candidats génétiques sont corrélés, donc N effectif est surestimé.

## Multiplicité et biais de sélection
Tous les candidats (y compris rejetés) sont enregistrés avec leurs métriques. Le meilleur résultat d'une campagne n'est jamais présenté comme estimation de la performance future (avertissement dans chaque résultat de campagne et passeport). Les évaluations OOS comptent le nombre de révisions évaluées sur le même segment de la série (toutes versions), et ce nombre resserre le seuil de décision ; le holdout final perd son statut indépendant dès qu'une seconde révision y est évaluée, toutes versions du dataset confondues. Une relance de campagne n'accepte comme graines que des révisions qui n'ont pas vu le segment oos (statut ≤ `robustness_tested`) : sinon le test OOS deviendrait une étape de sélection. Les expériences de méthode exigent une série sans campagne de recherche. Une estimation (budget d'essais) ne fige jamais les frontières de segments ; l'écran Campagnes les affiche.

## Métriques
Après coûts (spread, commission, swap en mode points, glissement). Sharpe/Sortino journaliers (journée 17:00 NY, jours sans trade = 0) annualisés √252, taux sans risque 0. Profit factor indéfini (`None`) sans perte. Drawdown sur equity de clôture des trades (flottant non inclus ; MAE par trade disponible).

## Régimes
Détection par règles explicables + hystérésis, sept familles de présentation, dimensions non exclusives exposées séparément. L'apport hors échantillon d'un filtre de régime n'est pas supposé : il doit apparaître dans les résultats OOS des génomes qui l'utilisent. *Non fait* : ablation automatique dédiée.

## Limites connues
- Pas de données de ticks dans le moteur de référence : convention conservatrice sur barres ambiguës.
- Valeur du point approximative pour les paires croisées (tick value courant).
- Swaps : seul le mode « points » est modélisé ; autres modes → swap non appliqué et signalé.
- Filtre d'annonces : dépend de la couverture du calendrier FXStreet ; période non couverte = entrée refusée.
- Spread historique XAUUSD 2021 partiellement nul chez FTMO : un plancher de spread supposé est requis.
