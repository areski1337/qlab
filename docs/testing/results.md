# Résultats observés (2026-10-13)

Environnement : Windows 11 Pro build 26300, i5-9400F (6 cœurs), 16 Go, Python 3.13 (uv 0.13), Node 24.20, Electron 44, MetaTrader 5 build 6254, compte FTMO-Demo (hedging, USD).

## Suite automatisée
```
QLAB_MT5_TESTS=1 uv run pytest -q
154 passed, 1 warning in 51.84s
```
(sans MT5 : 152 passed, 2 skipped). Avertissement unique : dépréciation `httpx` dans `starlette.testclient` (sans effet).

## Intégrations réelles
| Vérification | Résultat |
|---|---|
| Connexion MT5 (lecture) | compte démo, `trade_allowed=False`, 166 symboles |
| Décalage serveur | UTC+3 le 2026-10-13 = profil `NY+7` cohérent |
| Import XAUUSD M5 2020-01-01→2026-10-13 | 476 490 barres, 1,0 s ; 1 correction (barre en cours retirée) ; 2 alertes QC (volume réel absent, 14 trous > 24 h hors week-end) |
| Spread historique XAUUSD | médiane 5–41 points selon l'année ; 18 % de barres M5 à spread nul en 2021 |
| Compilation MetaEditor (2 EA d'exemple) | 0 erreur, 0 avertissement |
| Strategy Tester + parité (génome ICT, XAUUSD M5, 2026-08-01→10-01, OHLC M1) | **note A** : 18/18 signaux, 12/12 trades appariés, lots identiques, écart médian entrée 0 pt / sortie 0,22 pt, motifs 100 %, PnL net −121,39 (MT5) vs −120,28 (référence), écart 0,9 % ; 20,4 s |
| Commission observée dans le testeur | ≈ 3,06 USD / lot / côté (observée, pas supposée) |

## Performance
| Mesure | Valeur |
|---|---|
| Backtest génome ICT, 476 490 barres M5 | 0,94 s (features calculées), 0,27 s (cache) |
| Campagne XAUUSD M5+H1 (4 tribus × 24 × 20 gén. + 8 fusion, 5 workers) | 2 098 candidats, 1 641 évaluations, 5 min 44 s |

## Campagne réelle de démonstration (XAUUSD M5, profil de coûts supposé : spread plancher 20 pts, commission 3,0, glissement 2 pts)
Front final : Sharpe train 0,35–0,55, validation 0,16–0,86, rendements de l'ordre de 2–5 % sur le segment, drawdowns 1,6–4,1 %. Ces chiffres sont le meilleur d'environ 2 000 candidats : biaisés à la hausse.
### Validation du front (pipeline réel)
6 candidats distincts (dédoublonnés par comportement) → tous `historically_tested`, puis **tous rejetés** à l'étape robustesse sur le seul critère Deflated Sharpe Ratio (valeur 0,00 ; seuil 0,90). Toutes les autres vérifications étaient satisfaites :

| Révision | WF positif | Sensibilité | Stress ×1,5 (esp.) | MC p95 DD | Baseline aléatoire p | DSR |
|---|---|---|---|---|---|---|
| …77c5fab6 | 100 % | 100 % | 1,08 | 9,6 % | 0,01 | 0,00 |
| …45118a19 | 75 % | 100 % | 0,31 | 6,5 % | 0,01 | 0,00 |
| …3823e084 | 75 % | 100 % | 0,97 | 8,9 % | 0,01 | 0,00 |
| …4c13208d | 75 % | 100 % | 1,30 | 4,8 % | 0,01 | 0,00 |
| …e022e369 | 75 % | 100 % | 1,20 | 8,1 % | 0,01 | 0,00 |
| …3375c357 | 75 % | 100 % | 0,41 | 6,2 % | 0,01 | 0,00 |

Interprétation : avec N = 1 375 essais et une dispersion des Sharpe annualisés σ ≈ 1,1 (σ ≈ 1,0 en ne gardant que les 1 039 essais faisables, calcul informatif non utilisé pour la décision), le Sharpe maximal attendu par hasard est d'environ 3,3–3,7 annualisé ; les Sharpe observés (0,35–0,55) sont compatibles avec le hasard. **Aucune stratégie n'est validée** à l'issue de cette campagne. Le critère n'a pas été modifié après observation.

### Parité MT5 sur des génomes découverts par le GA (XAUUSD M5, 2026-04-01→10-01, OHLC M1)
Référence rejouée dans les conditions du testeur (spread des barres, commission observée, glissement nul — ADR-013).

| Révision | Features | Signaux | Trades appariés | Écart médian entrée/sortie | PnL net MT5 / réf. | Note |
|---|---|---|---|---|---|---|
| …77c5fab6 | Order Block H1, swings H1, ADX, Bollinger, time stop | 287/287 | 24/24 | 0,0 / 0,38 pt | 24,29 / 13,55 | C — 1 gap à travers le stop (référence à l'ouverture, testeur au prix du stop), diagnostiqué, 0 écart inexpliqué |
| …4c13208d | + sweep de liquidité, break-even, trailing | 287/287 | 24/24 | 0,0 / 0,0 pt | 107,93 / 108,57 | **A** |
| …e022e369 | MSS H1, EMA, break-even | 299/299 | 24/24 | 0,0 / 0,0 pt | 91,41 / 92,20 | **A** |

Statuts inchangés : ces révisions étaient déjà `rejected` (une parité ne valide pas une stratégie rejetée).

## Interface
13 écrans capturés en mode QA (fenêtre cachée) sans erreur console ; moteur démarré par l'interface, jeton et port aléatoires.
