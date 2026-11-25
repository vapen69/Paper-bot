"""Paramètres du bot. Tout est en euros (prix Kraken, paires EUR).

Stratégie en direct : celle retenue par la recherche long terme (research/) avec la règle de sélection fixée
avant les résultats : « tendance_long_short », moyenne 50 jours, BTC et ETH à 50 % chacun.
Hors échantillon (juin 2023 à nov. 2026, frais et financement inclus) : +35 % par an, pire baisse 33 %,
Sharpe 0,92, contre +26 % par an, pire baisse 53 % et Sharpe 0,74 pour le BTC conservé.
Avantage NON prouvé statistiquement (61 %) : c'est l'objet du paper trading.
L'ancienne règle horaire (momentum 24 h) finissait à -100 % sur la même période, détruite par les frais.
"""

CAPITAL_DEPART_EUR = 100.0

# Stablecoins et monnaies fiat, jamais tradés
EXCLUS = {
    "USDT", "USDC", "DAI", "EURT", "EURC", "PYUSD", "USDG", "TUSD", "USDS", "USDE",
    "FDUSD", "RLUSD", "EURR", "EUROP", "USDQ", "USD", "GBP", "CHF", "CAD", "AUD", "JPY",
    "ZUSD", "ZGBP", "ZCAD", "ZJPY", "PAXG", "XAUT",
}

# Univers et stratégie : tendance dans les deux sens
UNIVERS = ["BTC", "ETH"]
POIDS_PAR_ACTIF = 0.5           # 50 % du capital par actif
SMA_J = 50                      # long au-dessus de la moyenne 50 jours, short en dessous (clôtures journalières)

# Risque
STOP_SUIVEUR = None             # pas de stop : la stratégie testée n'en a pas (un stop non testé la changerait)
COUPE_CIRCUIT_DD = 0.50         # sécurité d'urgence seulement (la pire baisse testée était de 33 %)

# Coûts réalistes Kraken (niveau débutant)
FRAIS = 0.0040                  # 0,40 % par ordre (taker)
SLIPPAGE = 0.0010               # 0,10 % d'écart de prix à l'exécution
ORDRE_MIN_EUR = 5.0
FINANCEMENT_SHORT_8H = 0.0001   # coût de détention d'un short : 0,01 % toutes les 8 h (hypothèse prudente, varie en réalité)

# Historique gardé dans state.json
MAX_POINTS_COURBE = 24 * 30 * 6  # environ 6 mois de points
MAX_TRADES = 500

# Utilisé uniquement par research/ (stratégie « rotation_horaire_live », l'ancienne règle, gardée pour comparaison)
NB_POSITIONS = 2
LOOKBACK_H = 24
SMA_ACTIF_H = 48
SMA_BTC_H = 200
RANG_MAX_CONSERVE = 6
