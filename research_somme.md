# Recherche Polymarket : somme des probabilités d'un événement

Généré le 2026-11-26T02:30Z · source : polymarket · 600 événements (4583 issues) du 2025-01-29 au 2026-11-25. Période jamais vue : à partir du 2026-04-17.

## Verdict

DÉMENTI PAR LES VRAIS CARNETS. panier (seuil 0.1) passe la règle fixée à l'avance sur la période jamais vue : 111 trades, +8.10 % par trade, t = 7.40. À confirmer en paper trading sur le vrai carnet avant tout usage. Mais sur 33 événements ouverts lus au carnet, aucun panier n'est gagnant une fois payé le vrai prix demandé : l'écart vu dans l'historique vient des prix affichés, pas de prix qu'on peut obtenir. Stratégie NON validée.

## Règle de sélection (fixée avant les résultats)

Éligible si, sur le dernier tiers jamais vu et coûts déduits : au moins 50 trades sur 30 événements, rendement moyen positif avec t par événement >= 2,5, rendement sur capital immobilisé supérieur à la référence hasard, pire baisse (mises de 4 %) <= 25 %, et rendement moyen encore positif avec 1000 points de base de frais taker partout. Sinon : aucune stratégie validée, le bot en direct ne change pas.

## Période jamais vue, coûts déduits

| Stratégie | Seuil | Trades | Gagnants | Rendement par trade | t | Somme médiane au signal | Mises de 4 % | Pire baisse | Avec frais actuels | Éligible |
|---|---|---|---|---|---|---|---|---|---|---|
| panier | 0.1 | 111 | 75 % | +8,10 % | 7.40 | 1.455 | +43,05 % | 0 % | +8,10 % | oui |
| jambe_favori | 0.1 | 109 | 73 % | +9,93 % | 1.40 | 1.455 | +46,93 % | 20 % | +9,93 % | non |
| hasard | 0.0 | 254 | 52 % | -4,81 % | -0.38 | 1.005 | -65,65 % | 81 % | -4,81 % | non |

## Détail

### panier

Si la somme des Oui dépasse 1 + seuil, acheter le Non de toutes les issues ; sous 1 - seuil, acheter le Oui de toutes les issues. Gardé jusqu'à la résolution.

- Essais sur l'apprentissage : [{"seuil": 0.03, "nb_trades": 263, "t_stat": 9.99}, {"seuil": 0.05, "nb_trades": 236, "t_stat": 10.56}, {"seuil": 0.1, "nb_trades": 220, "t_stat": 11.02}]
- Détail sur la période jamais vue : {"somme_trop_haute": 7.89, "somme_trop_basse": 15.72, "nb_somme_trop_haute": 108, "rend_median_pct": 4.41, "issues_mediane": 3.0}
- Refus : aucun, stratégie éligible

### jambe_favori

Même signal, mais une seule jambe : le Non (somme trop haute) ou le Oui (somme trop basse) de l'issue la plus chère. Gardé jusqu'à la résolution.

- Essais sur l'apprentissage : [{"seuil": 0.03, "nb_trades": 259, "t_stat": 1.18}, {"seuil": 0.05, "nb_trades": 232, "t_stat": 1.75}, {"seuil": 0.1, "nb_trades": 215, "t_stat": 1.75}]
- Détail sur la période jamais vue : {"somme_trop_haute": 10.17, "somme_trop_basse": 1.29, "nb_somme_trop_haute": 106, "rend_median_pct": 20.63, "issues_mediane": 3.0}
- Refus : avantage non prouvé (t = 1.40, il faut 2.5)

### hasard

Référence : une issue au hasard, un côté au hasard, un instant au hasard. Doit perdre les coûts.

- Essais sur l'apprentissage : [{"seuil": 0.0, "nb_trades": 243, "t_stat": 0.14}]
- Détail sur la période jamais vue : {"somme_trop_haute": 0.31, "somme_trop_basse": -10.1, "nb_somme_trop_haute": 164, "rend_median_pct": 2.78, "issues_mediane": 3.0}
- Refus : référence, jamais sélectionnable ; rendement moyen négatif ou nul (-4.81 % par trade) ; ne bat pas la référence hasard sur le capital immobilisé ; pire baisse trop forte (81 %) ; ne survit pas aux frais taker actuels

## Limites

- L'historique donne un prix par issue, pas le carnet : une somme qui s'écarte de 1 peut venir d'issues peu échangées dont le dernier prix est ancien. Le demi-écart d'au moins 1 centime par jambe en tient compte.
- Les événements sont choisis d'après leur volume final, connu après coup.
- Les performances passées ne garantissent rien.

## Vérification sur les vrais carnets d'ordres (événements ouverts)

2026-11-26T02:42Z : 125 événements ouverts lus, 33 avec un carnet complet. Écart médian affiché entre la somme des Oui et 1 : 0.015. Événements dont la somme affichée s'écarte d'au moins 10 points : 0. Paniers gagnants si on achète vraiment 10 parts de chaque jambe au carnet, frais compris : **0**.

| Événement | Issues | Somme affichée | Gain panier Non | Gain panier Oui |
|---|---|---|---|---|
| What day will the 2026 Macy’s Thanksgiving Day Parade begin? | 9 | 0.9775 | -0.050 | -0.009 |
| Sportivo Trinidense vs. Recoleta FC | 3 | 0.978 | -0.060 | -0.013 |
| Deportivo Toluca FC vs. Atlas FC | 3 | 1.007 | -0.018 | -0.014 |
| Fed Decision in December? | 5 | 1.0045 | -0.017 | -0.025 |
| Bitcoin vs. Gold vs. S&P 500 in 2026 | 3 | 0.9815 | -0.066 | -0.043 |
| FC Red Bull Salzburg vs. Ararat-Armenia FA | 3 | 1.005 | -0.048 | -0.050 |
| Beşiktaş JK vs. MH Hapoel Be'er Sheva | 3 | 1.005 | -0.055 | -0.066 |
| Bank of Brazil decision in December? | 5 | 1.003 | -0.056 | -0.066 |
| Nvidia’s Market Cap end of 2026? | 7 | 0.977 | -0.095 | -0.062 |
| Which Millennium Prize Problem will AI solve next? | 6 | 0.994 | -0.079 | -0.064 |
