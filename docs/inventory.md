# Inventaire des fonctionnalités

**Complet** = implémenté et testé. **Partiel** = implémenté avec une limite explicite. **Absent** = non implémenté. **Bloqué** = dépend d'un élément externe.

## Données (section 6)
| Élément | État | Détail |
|---|---|---|
| Import OHLC/tick volume/spread/volume réel via MT5 | complet | lecture seule ; vérifié sur FTMO-Demo (XAUUSD, EURUSD) |
| Spécifications symbole (digits, tick size/value, contrat, lots, swaps, devises) | complet | stockées par version ; changements détectés |
| Import de ticks | absent | moteur sur barres ; convention conservatrice intrabar |
| Normalisation UTC, profils de fuseau (NY+7, UTC±N, IANA), DST | complet | heures ambiguës signalées, jamais devinées |
| QC : doublons, trous, incohérences, barre incomplète, spread nul, ancienneté | complet | |
| Données brutes / normalisées / dérivées séparées, versions, empreintes | complet | |
| Synchronisation multi-timeframe | complet | test explicite |
| Sources externes, calendrier économique | absent | non requis pour la recherche de base |

## Features (section 7)
| Élément | État |
|---|---|
| EMA, SMA, RSI, MACD, ATR, Stochastique, Bollinger, Keltner, ADX, Donchian, volatilité réalisée, momentum, compression, volume relatif (tick), spread | complet |
| VWAP ancré jour/semaine + bandes (tick ou réel) | complet (volume réel absent chez FTMO → indisponible, pas approximé) |
| Sessions, Kill Zones (DST géré) | complet |
| Pivots confirmés, BOS, CHOCH, MSS, trend | complet |
| FVG / IFVG, Order Blocks, Breaker Blocks | complet |
| Liquidity sweeps, equal highs/lows, PDH/PDL/PWH/PWL, premium/discount | complet |
| OTE | partiel (via `range_position` 21–38 / 62–79) |
| Mitigation Blocks (concept distinct) | absent (zones « mitigées » à la première touche) |
| Judas Swing, PO3, SMT divergence | absent |
| Internal/external range liquidity (concept nommé) | partiel (swings + range_position) |

## Régimes (section 8)
| Règles explicables + hystérésis, 7 familles, dimensions séparées, confiance | complet |
| Mesure automatique de l'apport OOS (ablation) | absent |
| Export MQL5 des régimes | absent (bloqué explicitement, ADR-011) |

## Génome (section 9) — complet
JSON Schema + sémantique, typage des comparaisons, révisions immuables, filiation, aucun code injectable, exemples valides/invalides. Limite : une position à la fois ; pas de gestion multi-positions/pyramidage.

## Évolution (section 10–11)
| Populations, mutations structurelles/paramétriques, croisements par rôle, élitisme NSGA-II | complet |
| Tribus consistance/croissance/exploration/spécialisation + fusion | complet |
| Diversité structurelle/comportementale/généalogique, stagnation, immigrants | complet |
| Mémoire des opérateurs (globale bornée, par campagne) | complet |
| Mémoire par régime / par type de stratégie | absent |
| Checkpoints, reprise sans doublon, workers parallèles | complet |
| Score de présentation 0–100 | absent (optionnel ; les métriques brutes sont affichées) |

## Validation (sections 12–14)
| Segments chronologiques, holdout final protégé, multiplicité | complet |
| Walk-forward | partiel (paramètres figés, pas de ré-optimisation par fenêtre) |
| Sensibilité, stress de coûts, Monte Carlo, baselines aléatoires, DSR | complet |
| Statuts à preuves | complet |
| Passeport (observations/hypothèses/interprétations/non vérifié), export | complet |
| Backtest : spread, commission, swap (mode points), glissement, gaps | complet |
| Latence, exécutions partielles/refusées, stops level | absent |

## MQL5 / MT5 (section 15)
| Générateur déterministe, traçabilité, blocage des fonctions non supportées | complet |
| Compilation MetaEditor réelle | complet (vérifié réel) |
| Strategy Tester + parité A–F, divergence critique bloquante | complet (vérifié réel : 1 run, note A) |
| Testeur avec terminal ouvert | bloqué (limite MT5 : terminal fermé requis) |

## Risque, portefeuille, démo (sections 16–17)
| Contrôleur de risque indépendant (backtest + EA), plafonds logiciels | complet |
| Refus du compte réel (EA, observation), trading réel non activable | complet |
| Arrêt d'urgence, suspension, verrou inter-robots, paliers 25/50/100 % | complet (EA 1.1) |
| Filtre d'annonces | absent (pas de calendrier : signalé « inactif ») |
| Clôture avant week-end, objectif de gain journalier | absent |
| Portefeuille : corrélations, DD simultanés, concentration, exposition, risque marginal, allocation bornée/adaptative | complet |
| Dépendance aux régimes dans le portefeuille | absent |
| Surveillance démo lecture seule + dégradation + quarantaine | complet (testé sur données injectées) ; aucun déploiement démo réel effectué |
| Déploiement automatique sur graphique | absent volontairement (action manuelle, ADR-010) |

## Auto-amélioration du moteur (section 18)
| Versionnement des composants, non-réécriture des résultats | complet |
| Expérimentation contrôlée sur les méthodes (hypothèse et critères préalables, graines multiples, test des signes, liste blanche de paramètres de méthode) | complet |
| Promotion vers le canal expérimental + retour arrière, jamais automatique | complet |
| Ablations automatiques multi-périodes, recherche autonome de nouvelles méthodes | absent |

## Performance et plateforme (sections 19–23)
| File persistante, priorités, pause/reprise/annulation, cache exact, parallélisme borné | complet |
| Quotas CPU/mémoire par campagne | partiel (nombre de workers seulement) |
| Interface 13 écrans FR connectée | complet |
| Sauvegarde/restauration/vérification, migrations sûres | complet |
| Installateur Windows (.exe) | partiel : scripts d'installation + `npm run dist` (répertoire non empaqueté) ; uv requis sur la machine |
| Canaux stable/bêta/expérimental | partiel (canal déclaré dans les versions ; pas de mécanisme de mise à jour) |
