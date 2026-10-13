# Exemples

| Dossier | Contenu | Provenance |
|---|---|---|
| `genomes/valid_*.json` | génomes écrits à la main, valides | exemples du schéma `qlab.genome/1.0` |
| `genomes/invalid_*.json` | génomes invalides (types incompatibles, tentative d'injection de code) | rejetés avec diagnostic (AT-002) |
| `genomes/ga_*_rejected.json` | génomes découverts par la campagne XAUUSD M5 du 2026-10-13 | **rejetés** (Deflated Sharpe Ratio) : ne pas utiliser pour trader |
| `ea/QLab_example_ict_fvg_killzone_gen1.0.mq5` | EA du génome d'exemple ICT | compilé par MetaEditor réel (0 erreur), parité A |
| `ea/QLab_rev_*_gen1.1.mq5` | EA des génomes du GA | compilés réellement (0 erreur, 0 avertissement) ; parité A, A, C (C = un gap à travers le stop, diagnostiqué) |
| `passports/*.html`, `*.json` | passeports de deux génomes du GA | générés depuis la base de développement ; statut `rejected` affiché |

Ces fichiers illustrent la chaîne ; ils ne constituent ni une recommandation ni une stratégie validée.
