"""Paramètres du bot Polymarket (paper trading, argent FICTIF uniquement).

Aucune fonction de ce dossier ne passe d'ordre réel : pas de portefeuille, pas de clé privée, pas de signature.
Le bot lit seulement les API publiques de Polymarket et simule ses exécutions sur le carnet d'ordres réel.
"""

CAPITAL_DEPART = 100.0          # USDC fictifs
DEVISE = "USDC"

# ---------- API publiques (lecture seule, sans authentification) ----------
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
REQUETES_PAR_S = 4.0            # limite volontaire, sous les ~5 requêtes par seconde
ESSAIS_HTTP = 3

# ---------- rythme de la boucle ----------
TICK_S = 10                     # prix des positions ouvertes (carnets CLOB)
SCAN_S = 60                     # scan des marchés actifs (Gamma)
RESOLUTION_S = 120              # vérification des résolutions des marchés détenus
BALEINES_S = 60                 # flux des gros trades (stratégie expérimentale)
MOUVEMENT_S = 300               # historique horaire des marchés les plus actifs (stratégies de mouvement)
CONTROLE_S = 30                 # lecture de control_poly.json
PUBLI_S = 60                    # publication de l'état

# ---------- filtres de marché ----------
PAGES_SCAN = 4                  # pages de 100 marchés triés par volume 24 h
PAGES_ECHEANCE = 3              # pages de marchés qui se terminent bientôt
SPREAD_MAX = 0.02               # on ignore les marchés dont l'écart achat/vente dépasse 2 centimes
LIQUIDITE_MIN = 1000.0          # dollars de liquidité annoncés par Gamma
VOLUME24H_MIN = 1000.0
HEURES_MIN_AVANT_ECHEANCE = 2   # trop près de la fin : le résultat est souvent déjà connu des autres
PRIX_ENTREE_MAX = 0.985         # jamais d'achat au-dessus : plus rien à gagner
CARNETS_PAR_SCAN = 12           # carnets lus par scan pour les candidats (limite de débit)

# ---------- stratégie par défaut (utilisée tant que la recherche n'a rien validé) ----------
STRATEGIE_DEFAUT = "favori_echeance"
PARAMS_DEFAUT = {
    "favori_echeance": {"prix_min": 0.88, "prix_max": 0.97, "jours_max": 3},
    "longshot_fade": {"seuil_oui": 0.10, "prix_max": 0.97, "jours_max": 30},
    "suivi_mouvement": {"ecart": 0.10, "fenetre_h": 6, "sortie_h": 24},
    "contre_mouvement": {"ecart": 0.10, "fenetre_h": 6, "sortie_h": 24},
}

# Choix manuel (25 nov. 2026, décidé avec l'utilisateur) : la recherche a montré que favori_echeance PERD
# hors échantillon (-8,4 % par trade). On teste donc en direct la seule stratégie positive hors échantillon,
# contre_mouvement (+15,5 % par trade, t = 2,04), qui reste NON validée (t < 2,5, pire baisse 64 %) : mises réduites.
# Les paramètres sont repris de la recherche à chaque mise à jour (parametres_retenus). Mettre None pour revenir
# au choix automatique de la recherche.
STRATEGIE_FORCEE = "contre_mouvement"

# ---------- taille des positions ----------
PART_PAR_MARCHE = 0.06          # 6 % de la valeur par marché quand la stratégie est validée par la recherche
PART_PAR_MARCHE_NON_VALIDEE = 0.04   # 4 % seulement tant que rien n'est prouvé
POSITIONS_MAX = 14
RESERVE_CASH = 0.15             # 15 % de la valeur reste toujours en cash
ORDRE_MIN = 1.0                 # dollars (le vrai plancher est le minimum de parts par ordre)
PARTS_MIN = 5.0                 # taille minimale d'un ordre sur Polymarket (5 parts)
REMPLISSAGE_MIN = 0.5           # si le carnet n'absorbe pas au moins la moitié du montant, on passe
GLISSEMENT_MAX = 0.01           # on ne remonte pas le carnet de plus d'un centime au-dessus du meilleur prix

# ---------- stratégie expérimentale « suivi des baleines » (activité, budget plafonné) ----------
BALEINES_ACTIF = True           # se désactive toute seule si la Data API ne répond pas (v1 retirée, v2 non vérifiée)
BALEINES_CHEMINS = ["/v2/trades", "/trades"]   # chemins essayés dans l'ordre
BALEINES_ECHECS_MAX = 3         # après 3 échecs d'affilée, on n'essaie plus qu'une fois par heure
BALEINES_MONTANT_MIN = 5000.0   # dollars engagés par le gros trade suivi
BALEINES_AGE_MAX_S = 600        # on ne suit que les trades de moins de 10 minutes
BALEINES_PRIX_MIN, BALEINES_PRIX_MAX = 0.10, 0.90
BALEINES_PART = 0.02            # 2 % de la valeur par suivi
BALEINES_BUDGET = 0.12          # 12 % de la valeur au total, pour ne jamais dominer le résultat
BALEINES_SORTIE_H = 24          # sortie au prix acheteur après 24 h (ou à la résolution)
BALEINES_ECART_PRIX_MAX = 0.02  # on ne suit pas si le prix a déjà bougé de plus de 2 centimes

# ---------- risque ----------
COUPE_CIRCUIT_DD = 0.20         # -20 % depuis le plus haut : plus aucune entrée, statut « coupe-circuit »
PERTE_JOUR_MAX = 0.08           # -8 % dans la journée (UTC) : plus d'entrée jusqu'au lendemain
PART_MAX_CATEGORIE = 0.35       # 35 % de la valeur au maximum par catégorie (sport, crypto, politique...)
POSITIONS_MAX_PAR_EVENEMENT = 2 # évite 15 paris corrélés sur le même événement

# ---------- coûts ----------
# Frais taker : Gamma expose takerBaseFee en points de base (1000 observé sur des marchés actifs). On ne suppose
# donc PAS zéro. Modèle prudent : frais = (takerBaseFee / 10000) x min(prix, 1 - prix) x nombre de parts,
# payés à l'achat comme à la vente. Aucun frais au règlement d'un marché résolu (hypothèse).
# Si le champ est absent du marché, on applique l'hypothèse ci-dessous. À VÉRIFIER sur la documentation réelle.
FRAIS_BPS_SI_ABSENT = 1000.0

# ---------- historique gardé dans state_poly.json ----------
MAX_POINTS_COURBE = 6000
MAX_TRADES = 400
MAX_JOURNAL = 200
MAX_FLUX = 60
MAX_SURVEILLES = 30

# Catégories déduites du texte de la question et des tags (aucun champ fiable dans l'API)
MOTS_CATEGORIES = {
    "sport": ["nba", "nfl", "nhl", "mlb", "ufc", "premier league", "champions league", "la liga", "serie a", "ligue 1",
              "bundesliga", "tennis", "atp", "wta", "grand prix", "f1", "formula 1", "super bowl", "world cup",
              " vs. ", " vs ", "fc ", "match", "game ", "playoff", "o/u", "spread:", "moneyline", "esports", "lol:",
              "cs2", "dota", "valorant", "golf", "pga", "boxing", "cricket", "rugby", "sports", "soccer", "ncaa"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth ", "solana", "sol ", "xrp", "dogecoin", "crypto", "memecoin",
               "airdrop", "fdv", "up or down", "binance", "coinbase", "stablecoin", "token"],
    "politique": ["election", "president", "trump", "biden", "senate", "congress", "minister", "parliament", "vote",
                  "democrat", "republican", "governor", "mayor", "politics", "putin", "zelensky", "ceasefire",
                  "nato", "war ", "israel", "iran", "ukraine", "china", "tariff", "supreme court", "impeach"],
    "economie": ["fed ", "federal reserve", "interest rate", "rate cut", "inflation", "cpi", "gdp", "recession",
                 "unemployment", "jobs report", "s&p", "nasdaq", "stock", "earnings", "ipo", "oil", "gold",
                 "economy", "finance", "treasury"],
    "culture": ["oscar", "grammy", "emmy", "movie", "box office", "album", "song", "netflix", "youtube", "tiktok",
                "twitter", "tweet", "elon", "mrbeast", "celebrity", "award", "taylor swift", "spotify", "culture"],
    "meteo_science": ["temperature", "weather", "hurricane", "earthquake", "nasa", "spacex", "launch", "climate",
                      "openai", "gpt", "gemini", "claude", " ai ", "model"],
}
