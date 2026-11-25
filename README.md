# Paper Bot · crypto (argent fictif)

Bot de paper trading crypto qui tourne en continu sur les serveurs GitHub, avec un capital fictif de 100 €.
Aucun argent réel n'est engagé.

- **Tableaux de bord** : https://vapen69.github.io/Paper-bot/ (crypto) et https://vapen69.github.io/Paper-bot/poly.html (Polymarket, 100 USDC fictifs)
- **Commandes** (pause, reprise, tout vendre, remise à 100 €) : onglet Actions > « Commande » > Run workflow
- **Données** : prix publics Kraken (paires EUR), frais 0,40 % + slippage 0,10 % par ordre simulés
- **Stratégie en direct** : tendance long/short sur BTC et ETH (50 % chacun) : achat au-dessus de la moyenne 50 jours, vente à découvert en dessous, décision une fois par jour. Choisie par la recherche hors échantillon (règle fixée à l'avance).
- **Recherche** : workflow « Recherche » (plusieurs années de données, validation hors échantillon)

Fonctionnement : le workflow « Bot » tourne par sessions de 5 h 45 et se relance tout seul chaque heure.
L'état (portefeuille, trades, courbe) est publié toutes les 2 minutes sur la branche `data`.
