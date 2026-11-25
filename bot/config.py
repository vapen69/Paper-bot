"""Paramètres du bot. Tout est en euros (paires EUR de Kraken)."""

CAPITAL_DEPART_EUR = 100.0

# Univers
NB_PAIRES_UNIVERS = 25          # les paires EUR les plus liquides (volume 24 h)
EXCLUS = {
    # stablecoins et monnaies fiat : pas de momentum à attendre
    "USDT", "USDC", "DAI", "EURT", "EURC", "PYUSD", "USDG", "TUSD", "USDS", "USDE",
    "FDUSD", "RLUSD", "EURR", "EUROP", "USDQ", "USD", "GBP", "CHF", "CAD", "AUD", "JPY",
    "ZUSD", "ZGBP", "ZCAD", "ZJPY", "PAXG", "XAUT",
}

# Stratégie : rotation momentum horaire
LOOKBACK_H = 24                 # performance mesurée sur 24 h
SMA_ACTIF_H = 48                # l'actif doit être au-dessus de sa moyenne 48 h
SMA_BTC_H = 200                 # filtre de marché : BTC au-dessus de sa moyenne 200 h
NB_POSITIONS = 2                # nombre d'actifs détenus en même temps
RANG_MAX_CONSERVE = 6           # on garde un actif tant qu'il reste dans le top 6 (évite de payer des frais pour rien)

# Risque
STOP_SUIVEUR = 0.12             # vente si le prix chute de 12 % depuis son plus haut depuis l'achat
COUPE_CIRCUIT_DD = 0.25         # tout vendre et mettre en pause si -25 % depuis le plus haut du portefeuille

# Coûts réalistes Kraken (niveau débutant)
FRAIS = 0.0040                  # 0,40 % par ordre (taker)
SLIPPAGE = 0.0010               # 0,10 % d'écart de prix à l'exécution
ORDRE_MIN_EUR = 5.0

# Historique gardé dans state.json
MAX_POINTS_COURBE = 24 * 90     # 90 jours de points horaires
MAX_TRADES = 500
