# Registre des exigences (synthèse)

Source : prompt maître du projet (sections 1–28). Ce registre ne recopie pas le prompt ; il fixe les exigences retenues, leur interprétation et leur état. État détaillé : `docs/inventory.md`.

## Principes non négociables (section 5) — appliqués partout
| Exigence | Mécanisme |
|---|---|
| Pas de fuite temporelle | convention « valeur disponible à la clôture », pivots datés à leur confirmation, alignement MTF par clôture, exécution à l'ouverture suivante ; tests de troncature |
| Aucun résultat inventé | métriques indéfinies = `None` ; compilation/testeur réels ou statut `blocked` ; aucune simulation de MT5 |
| Statut de validation = preuves | `genome/store.set_status` : un cran à la fois, preuve obligatoire, historique immuable |
| Pas de modification silencieuse des données | brut conservé (artefact), normalisé versionné, corrections listées, empreinte vérifiée à chaque chargement |
| Aucune recherche ne trade en réel | pas de code d'envoi d'ordre côté Python ; EA refuse les comptes réels ; `live_trading_enabled` non activable |
| Génome ≠ limites de risque | limites dans `risk_limits.json`, hors génome, plafonds logiciels |
| Cache invalidé si dépendance change | clé = génome sémantique + empreintes données/contexte + coûts + limites + protocole + versions de tous les composants |
| Test final non réutilisable silencieusement | segment `final` inaccessible aux campagnes ; chaque usage tracé ; indépendance perdue au-delà d'une révision |
| Valeurs manquantes jamais favorables | NaN propagé ; `NOT` d'une condition non calculable reste faux ; spread inconnu = refus |
| Aucune dépendance payante | Python, Node, Electron, SQLite, numpy/pandas/pyarrow, FastAPI : libres |

## Hypothèses déclarées (non codées en dur ailleurs)
- Fuseau serveur déclaré par dataset et vérifié à l'import (profil `NY+7` constaté sur FTMO-Demo le 2026-10-13).
- Journée de trading : bascule à 17:00 America/New_York.
- Prix OHLC MT5 = Bid ; Ask = Bid + spread de barre.
- Barre OHLC ambiguë (stop et objectif) : stop retenu.
- Valeur du point pour les paires sans la devise du compte : `tick_value/tick_size` courant (approximation signalée).

## Périmètre MVP (section 26) — chaîne démontrée
1 import historique MT5 + QC · 2 génome validé · 3 signaux du moteur de référence · 4 backtest reproductible avec coûts · 5 campagne reprenable · 6 comparaison de candidats (Pareto) · 7 génération EA · 8 compilation MetaEditor réelle · 9 comparaison au Strategy Tester réel · 10 passeport traçable · 11 sauvegarde/restauration vérifiée.
