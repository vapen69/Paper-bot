# Recherche de stratégie

Généré le 2026-11-25T02:22Z. Données : coinbase, 12 actifs, en EUR.
Période hors échantillon : du 2023-06-14 au 2026-11-25 (3.45 ans). Paramètres choisis sur 365 jours, puis testés sur les 91 jours suivants, jamais vus au moment du choix.
Coûts : 0.40 % de frais + 0.10 % de slippage par ordre.

## Verdict

Hors échantillon et frais déduits, tendance_long_short fait mieux que garder du BTC à risque égal : Sharpe 0.92 contre 0.74, rendement annuel +35.4 % contre +26.2 %, pire baisse 33 % contre 53 %. Mais l'avantage n'est PAS prouvé statistiquement (probabilité de 61 % que le Sharpe soit réellement supérieur, seuil de chance 1.44) : à confirmer en paper trading avant d'y croire.

**Stratégie retenue : tendance_long_short** avec les paramètres `{"sma_j": 50}`.

Meilleur Calmar (1.06) parmi les 2 stratégie(s) dont le Sharpe hors échantillon (0.92) dépasse celui du BTC conservé (0.74), frais déduits.

## Classement hors échantillon (par Calmar, frais déduits)

| Stratégie | Rendement | Par an | Pire baisse | Sharpe | Sortino | Calmar | Turnover/an | Frais (EUR pour 100) | Temps investi | Proba Sharpe > BTC | Stabilité des paramètres |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tendance_long_short | +184.7 % | +35.4 % | 33.4 % | 0.92 | 1.29 | 1.06 | 21.4 x | 65.14 | 100 % | 61 % | 57 % |
| rotation_momentum | +284.6 % | +47.7 % | 56.6 % | 0.94 | 1.32 | 0.84 | 38.3 x | 249.91 | 53 % | 66 % | 71 % |
| tendance_sma | +82.1 % | +19.0 % | 39.6 % | 0.67 | 0.93 | 0.48 | 11.1 x | 32.81 | 64 % | 44 % | 64 % |
| tendance_vol_cible | +64.1 % | +15.4 % | 35.4 % | 0.66 | 0.93 | 0.44 | 14.6 x | 44.26 | 59 % | 42 % | 29 % |
| donchian | +56.6 % | +13.9 % | 48.0 % | 0.61 | 0.84 | 0.29 | 10.5 x | 31.53 | 50 % | 41 % | 57 % |
| tendance_short_seul | +13.4 % | +3.7 % | 38.5 % | 0.27 | 0.39 | 0.10 | 11.1 x | 15.98 | 48 % | 31 % | 57 % |
| retour_moyenne | -33.5 % | -11.2 % | 52.6 % | -0.32 | -0.44 | -0.21 | 42.5 x | 71.60 | 24 % | 1 % | 86 % |
| rotation_horaire_live | -100.0 % | -97.8 % | 100.0 % | -6.39 | -8.77 | -0.98 | 816.8 x | 122.74 | 47 % | 0 % | 100 % |
| **BTC conservé** | +123.3 % | +26.2 % | 52.6 % | 0.74 | 1.04 | 0.50 | 0.3 x | 0.50 | 100 % | - | - |

Lecture : Sharpe et Sortino = rendement par unité de risque (plus haut = mieux). Calmar = rendement annuel divisé par la pire baisse. Proba Sharpe > BTC : autour de 50 % = aucune différence démontrée, au-dessus de 90 % = avantage crédible. Stabilité : part des trimestres où les mêmes paramètres ont été choisis.

## Apport du short

Même signal (moyenne mobile sur BTC + ETH), trois usages. Financement du short : 0.01 % par 8 h (hypothèse), aucun stop.

| Stratégie | Par an | Pire baisse | Sharpe | Calmar | Temps en short | Financement (EUR pour 100) | Pire hausse subie en short (1 h) | (24 h) |
|---|---|---|---|---|---|---|---|---|
| tendance_sma | +19.0 % | 39.6 % | 0.67 | 0.48 | 0 % | 0.00 | - | - |
| tendance_long_short | +35.4 % | 33.4 % | 0.92 | 1.06 | 48 % | 21.65 | +9.7 % | +18.5 % |
| tendance_short_seul | +3.7 % | 38.5 % | 0.27 | 0.10 | 48 % | 10.68 | +9.7 % | +18.5 % |

Sur cette période, le short a aidé : la version long/short a un meilleur Sharpe que le long seul (0.92 contre 0.67) et le short seul est gagnant (+3.7 % par an).

## Paramètres à utiliser en direct (choisis sur les 12 derniers mois)

- **tendance_sma** : `{"sma_j": 50}` (3 combinaison(s) testée(s)). Suivi de tendance BTC + ETH : détenu si le prix est au-dessus de sa moyenne mobile journalière, sinon cash.
- **tendance_long_short** : `{"sma_j": 50}` (3 combinaison(s) testée(s)). Tendance BTC + ETH dans les deux sens : long au-dessus de la moyenne mobile, vente à découvert en dessous.
- **tendance_short_seul** : `{"sma_j": 50}` (3 combinaison(s) testée(s)). Vente à découvert seule sur BTC + ETH : short sous la moyenne mobile, cash au-dessus.
- **donchian** : `{"entree_j": 80}` (3 combinaison(s) testée(s)). Cassure de canal BTC + ETH : achat sur un plus haut de N jours, vente sur un plus bas de N/2 jours.
- **rotation_momentum** : `{"lookback_j": 7, "k": 2, "rebal_j": 7}` (12 combinaison(s) testée(s)). Rotation momentum lente : les K actifs les plus forts sur N jours, avec filtre de marché BTC (moyenne 100 jours).
- **tendance_vol_cible** : `{"sma_j": 50, "vol_cible": 0.3}` (6 combinaison(s) testée(s)). Tendance BTC avec exposition réglée sur une volatilité cible (moins investi quand le marché s'agite).
- **retour_moyenne** : `{"fenetre_h": 168, "z_entree": 2.5}` (4 combinaison(s) testée(s)). Référence retour à la moyenne sur BTC : achat des fortes baisses horaires, vente au retour à la moyenne.
- **rotation_horaire_live** : `{"lookback_h": 24}` (1 combinaison(s) testée(s)). Règle actuelle du bot en direct (momentum 24 h, top 2, filtre BTC 200 h), sans stop suiveur.

## Règle de sélection (fixée avant de voir les résultats)

Éligible si Sharpe hors échantillon net de frais > Sharpe du BTC conservé, rendement annuel > 0 et Sharpe <= 3. Parmi les éligibles : meilleur Calmar. Sinon : plus faible baisse maximale parmi les stratégies gagnantes investies au moins 10 % du temps, à défaut tendance_sma.

## Limites à garder en tête

- Biais de survie : l'univers est composé d'actifs encore liquides aujourd'hui, ce qui avantage les rotations.
- Les performances passées, même hors échantillon, ne garantissent rien pour la suite.
- 35 combinaisons de paramètres essayées au total : en gardant la meilleure par pure chance, on s'attendrait déjà à un Sharpe d'environ 1.44.
- Ordre minimum de 5 EUR ignoré ; exécution supposée à l'ouverture de l'heure suivante avec 0,10 % de slippage.
- Ventes à découvert : financement supposé constant à 0.01 % par 8 h (hypothèse, il varie en réalité), aucun stop, pas de liquidation simulée. Le bot actuel (achat simple au comptant) ne sait pas vendre à découvert : il faudrait des contrats perpétuels.
- Paires USD converties en EUR avec le taux implicite BTC-USD / BTC-EUR.
