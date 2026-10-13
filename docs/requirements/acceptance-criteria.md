# Critères d'acceptation — traçabilité vers les tests

Statuts : **vérifié** = test automatisé exécuté et réussi ; **vérifié (réel)** = vérifié contre MetaTrader 5 / MetaEditor réels ; **partiel** = couvert en partie (limite indiquée).

| ID | Critère | Statut | Preuve (tests) |
|----|---------|--------|----------------|
| AT-001 | Aucune donnée future n'influence un signal passé | vérifié | `test_features.py::test_no_lookahead_by_truncation` (27 features × 3 coupures), `test_data.py::test_mtf_alignment_never_uses_forming_bar`, `test_genome_backtest.py::test_entry_at_next_open_after_signal` |
| AT-002 | Génome invalide rejeté avec diagnostic précis | vérifié | `test_genome_backtest.py::test_invalid_genomes_rejected_with_diagnostic`, `test_semantic_errors` (6 cas), `test_api.py` (HTTP 422) |
| AT-003 | Mutations/croisements : filiation vérifiable | vérifié | `test_evolution.py::test_lineage_traceable` |
| AT-004 | Une reprise ne duplique pas les évaluations | vérifié | `test_evolution.py::test_campaign_resume_does_not_duplicate` (interruption réelle puis reprise, même front qu'une exécution continue) |
| AT-005 | Un changement de dépendance invalide le cache | vérifié | `test_validation.py::test_evaluation_cache_and_invalidation`, `test_features.py::test_cache_key_changes_with_version` |
| AT-006 | Les métriques intègrent les coûts configurés | vérifié | `test_genome_backtest.py::test_commission_and_spread_reduce_pnl`, `test_unknown_spread_is_refused` |
| AT-007 | Tout résultat OOS est traçable jusqu'aux données sources | vérifié | `test_validation.py::test_oos_result_traceable_to_source` |
| AT-008 | Divergence critique référence ↔ MT5 bloque la validation | vérifié (logique) / vérifié (réel, cas concordant) | `mql5/verify.py` (transition conditionnée à `critical == False` et note A/B) ; run réel XAUUSD : note A, aucune divergence critique. Aucun cas divergent réel n'a encore été produit dans MT5. |
| AT-009 | Un génome ne peut pas augmenter les limites absolues | vérifié | `test_genome_backtest.py::test_genome_cannot_exceed_absolute_risk`, `test_evolution.py::test_genome_never_contains_absolute_limits`, `test_mql5.py::test_generation_deterministic_and_traceable` (aucune limite en input) |
| AT-010 | Une sauvegarde restaurée conserve la cohérence des références | vérifié | `test_foundations.py::test_backup_restore_roundtrip`, `test_restore_detects_corruption`, `test_api.py` (vérification via API) |
| AT-011 | Mise à jour échouée : restauration contrôlée | vérifié | `test_foundations.py::test_failed_migration_rolls_back_and_keeps_backup` |
| AT-012 | Une campagne ne peut pas activer le trading réel | vérifié | `test_api.py::test_risk_limits_cannot_enable_live` ; `risk/controller.py::load_limits` refuse `live_trading_enabled` ; EA : refus codé en dur sur compte réel ; démo : `fetch_live_trades` refuse un compte réel |
| AT-013 | Rapports : observations / hypothèses / inconnues distinguées | vérifié | `test_passport.py::test_passport_sections_and_export` |
| AT-014 | Tout EA exporté référence génome, versions et tests | vérifié | `test_mql5.py::test_generation_deterministic_and_traceable`, `test_passport.py` (manifeste d'export) |
| AT-015 | Fonctionnalités incomplètes explicitement signalées | vérifié (manuel) | écrans UI : composant `Incomplete`, blocages d'export, statut « bloqué » du testeur ; inventaire `docs/inventory.md` |

Résultats d'exécution : voir `docs/testing/results.md`.
