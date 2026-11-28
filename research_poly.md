# Recherche Polymarket : quelles stratégies résistent aux coûts ?

Généré le 2026-11-26T02:29Z · source : polymarket · 4448 marchés résolus (2942 événements) du 2025-01-03 au 2026-11-26.
Période jamais vue (test) : à partir du 2026-04-09. Pas médian de l'historique : 60.0 min.

## Verdict

Aucune des 4 stratégies testées ne passe la règle fixée à l'avance : aucun avantage prouvé une fois les coûts déduits. Le bot tourne donc en MODE OBSERVATION, à mises réduites, avec favori_echeance, qui perd de l'argent sur la période jamais vue (-9.50 % par trade, 85 % de gagnants pour un prix moyen payé de 0.940). Il ne faut pas en attendre de gain : la référence au hasard fait -2.55 % par trade.

Choix pour le bot : **favori_echeance** {"prix_min": 0.9, "prix_max": 0.97, "jours_max": 1} (NON validée, mode observation). Aucune stratégie ne remplit la règle de sélection sur la période jamais vue.

## Règle de sélection (fixée avant les résultats)

Éligible si, sur le dernier tiers jamais vu et coûts déduits : au moins 50 trades sur 30 événements, rendement moyen positif avec t par événement >= 2,5, rendement sur capital immobilisé supérieur à la référence hasard, pire baisse du portefeuille simulé <= 25 %, et rendement moyen encore positif avec 1000 points de base de frais taker partout. Parmi les éligibles : meilleur rendement annualisé du portefeuille simulé. Sinon : aucune stratégie validée, mode observation à mises réduites.

## Résultats sur la période jamais vue, coûts déduits

| Stratégie | Trades | Gagnants | Prix moyen payé | Gain par part | Rendement par trade | t | Jours bloqués | Capital immobilisé (par an) | Pire série | Portefeuille 100 $ | Pire baisse | Avec frais actuels | Éligible |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| favori_echeance | 144 | 85 % | 0.940 | -8.53 c | -9,50 % | -2.41 | 2.0 | -1625 % | 4 | -56,31 % (133 trades) | 59 % | -9,50 % | non |
| longshot_fade | 179 | 93 % | 0.968 | -4.08 c | -4,22 % | -2.13 | 8.4 | -182 % | 2 | -32,35 % (130 trades) | 36 % | -4,22 % | non |
| suivi_mouvement | 749 | 56 % | 0.647 | -8.73 c | -11,39 % | -2.84 | 22.0 | -224 % | 10 | +34,94 % (148 trades) | 58 % | -11,39 % | non |
| contre_mouvement | 701 | 46 % | 0.439 | +2.57 c | +13,34 % | 1.65 | 21.5 | +98 % | 13 | +73,16 % (148 trades) | 66 % | +13,34 % | non |
| hasard | 1120 | 50 % | 0.546 | -4.22 c | -2,55 % | -0.86 | 23.0 | -125 % | 7 | -55,07 % (157 trades) | 65 % | -2,55 % | non |

## Détail par stratégie

### favori_echeance

Acheter le favori (issue cotée entre 80-90 % et 97 %) dans les derniers jours avant l'échéance et attendre la résolution.

- Paramètres retenus sur l'apprentissage : `{"prix_min": 0.9, "prix_max": 0.97, "jours_max": 1}` (9 combinaison(s) essayée(s))
- Apprentissage : 130 trades, -9,65 % par trade, t = -2.78
- Test avec écart de prix doublé et frais actuels : -11,01 % par trade
- Refus : rendement moyen négatif ou nul (-9.50 % par trade) ; ne bat pas la référence hasard sur le capital immobilisé ; pire baisse trop forte (59 %) ; ne survit pas aux frais taker actuels

### longshot_fade

Marchés Oui/Non : acheter Non quand le Oui est un outsider (5 à 15 %), jusqu'à 60 jours avant l'échéance, et attendre la résolution.

- Paramètres retenus sur l'apprentissage : `{"seuil_oui": 0.05, "prix_max": 0.97, "jours_max": 14}` (6 combinaison(s) essayée(s))
- Apprentissage : 261 trades, -6,26 % par trade, t = -3.41
- Test avec écart de prix doublé et frais actuels : -5,17 % par trade
- Refus : rendement moyen négatif ou nul (-4.22 % par trade) ; ne bat pas la référence hasard sur le capital immobilisé ; pire baisse trop forte (36 %) ; ne survit pas aux frais taker actuels

### suivi_mouvement

Suivre un gros mouvement de prix (8 à 15 points en quelques heures), sortie après 24 h ou à la résolution.

- Paramètres retenus sur l'apprentissage : `{"ecart": 0.15, "fenetre_h": 12, "sortie_h": null}` (8 combinaison(s) essayée(s))
- Apprentissage : 983 trades, -8,01 % par trade, t = -3.09
- Test avec écart de prix doublé et frais actuels : -13,00 % par trade
- Refus : rendement moyen négatif ou nul (-11.39 % par trade) ; ne bat pas la référence hasard sur le capital immobilisé ; pire baisse trop forte (58 %) ; ne survit pas aux frais taker actuels

### contre_mouvement

Parier contre un gros mouvement de prix (retour après excès), sortie après 24 h ou à la résolution.

- Paramètres retenus sur l'apprentissage : `{"ecart": 0.15, "fenetre_h": 3, "sortie_h": null}` (8 combinaison(s) essayée(s))
- Apprentissage : 911 trades, +10,68 % par trade, t = 1.61
- Test avec écart de prix doublé et frais actuels : +9,74 % par trade
- Refus : avantage non prouvé (t = 1.65, il faut 2.5) ; pire baisse trop forte (66 %)

### hasard

Référence naïve : une issue au hasard, à un moment au hasard, gardée jusqu'à la résolution. Doit perdre à peu près les coûts.

- Paramètres retenus sur l'apprentissage : `{"proba": 0.005}` (1 combinaison(s) essayée(s))
- Apprentissage : 1114 trades, -3,00 % par trade, t = -1.15
- Test avec écart de prix doublé et frais actuels : -5,28 % par trade
- Refus : référence, jamais sélectionnable ; rendement moyen négatif ou nul (-2.55 % par trade) ; ne bat pas la référence hasard sur le capital immobilisé ; pire baisse trop forte (65 %) ; ne survit pas aux frais taker actuels

## Limites à garder en tête

- L'historique ne contient pas le carnet d'ordres : le prix payé est le prix de l'historique plus un demi-écart supposé (1 centime au minimum). Sur un marché peu liquide, l'écart réel peut être bien plus large.
- Frais taker : champ takerBaseFee du marché s'il existe, sinon l'hypothèse de la configuration. Le scénario « frais actuels » applique 1000 points de base à tous les marchés.
- Les marchés sont choisis d'après leur volume final, connu seulement après coup : léger biais favorable.
- L'échéance utilisée est celle affichée par Gamma aujourd'hui ; elle a pu être modifiée pendant la vie du marché.
- Près de l'échéance, un prix de 95 % peut refléter un résultat déjà connu mais pas encore réglé (risque de litige) : le rendement paraît facile mais le capital reste bloqué jusqu'au règlement.
- Le rendement « sur capital immobilisé » suppose que chaque dollar libéré est replacé aussitôt : le portefeuille simulé, lui, respecte les limites réelles du bot.
- 32 combinaisons de paramètres essayées, toutes sur la période d'apprentissage ; la période de test n'a servi qu'une fois par stratégie.
- Les performances passées, même sur une période jamais vue, ne garantissent rien pour la suite.
