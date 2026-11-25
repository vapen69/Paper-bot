"""Paramètres du bot. Tout est en euros (paires EUR de Kraken).

Stratégie en direct : celle retenue par la recherche long terme (research/), règle de sélection
fixée avant les résultats : « rotation_momentum », lookback 7 jours, 2 actifs, rebalancement tous les 7 jours,
filtre de marché BTC au-dessus de sa moyenne 100 jours. Hors échantillon (juin 2023 à nov. 2026, frais inclus) :
Sharpe 1,00 contre 0,74 pour le BTC conservé, mais avantage NON prouvé statistiquement (71 %).
L'ancienne règle horaire (momentum 24 h) finissait à -100 % sur la même période, détruite par les frais.
"""

CAPITAL_DEPART_EUR = 100.0

# Univers : le même que celui de la recherche (cryptos liquides présentes depuis plusieurs années)
UNIVERS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "BCH", "ATOM"]

# Stratégie : rotation momentum hebdomadaire
LOOKBACK_J = 7                  # performance mesurée sur 7 jours
NB_POSITIONS = 2                # les 2 plus fortes, 50 % chacune
REBAL_J = 7                     # choix revu tous les 7 jours (jours où nb de jours depuis 1970 % 7 == 0)
SMA_BTC_J = 100                 # filtre de marché vérifié chaque jour : BTC au-dessus de sa moyenne 100 jours

# Risque
STOP_SUIVEUR = None             # pas de stop : la stratégie testée n'en a pas (un stop non testé la changerait)
COUPE_CIRCUIT_DD = 0.50         # sécurité d'urgence seulement (la pire baisse testée était de 57 %)

# Coûts réalistes Kraken (niveau débutant)
FRAIS = 0.0040                  # 0,40 % par ordre (taker)
SLIPPAGE = 0.0010               # 0,10 % d'écart de prix à l'exécution
ORDRE_MIN_EUR = 5.0

# Historique gardé dans state.json
MAX_POINTS_COURBE = 24 * 30 * 6  # environ 6 mois de points
MAX_TRADES = 500

# Utilisé uniquement par research/ (stratégie « rotation_horaire_live », l'ancienne règle, gardée pour comparaison)
LOOKBACK_H = 24
SMA_ACTIF_H = 48
SMA_BTC_H = 200
RANG_MAX_CONSERVE = 6
