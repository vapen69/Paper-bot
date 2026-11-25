# Paper Bot · crypto (argent fictif)

Bot de paper trading crypto qui tourne en continu sur les serveurs GitHub, avec un capital fictif de 100 €.
Aucun argent réel n'est engagé.

- **Tableau de bord** : https://vapen69.github.io/Paper-bot/
- **Commandes** (pause, reprise, tout vendre, remise à 100 €) : onglet Actions > « Commande » > Run workflow
- **Données** : prix publics Kraken (paires EUR), frais 0,40 % + slippage 0,10 % par ordre simulés
- **Stratégie en direct** : rotation momentum horaire (2 positions max), filtre de marché BTC, stop suiveur 12 %, coupe-circuit à -25 %
- **Recherche** : workflow « Recherche » (plusieurs années de données, validation hors échantillon)

Fonctionnement : le workflow « Bot » tourne par sessions de 5 h 45 et se relance tout seul chaque heure.
L'état (portefeuille, trades, courbe) est publié toutes les 2 minutes sur la branche `data`.
