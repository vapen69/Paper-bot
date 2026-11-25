"""Stratégies candidates. Chacune est une fonction pure : clo (clôtures horaires, une colonne par actif)
-> poids cibles par heure (0 = cash). La ligne t n'utilise que les clôtures jusqu'à t incluse :
c'est vérifié par les tests (modifier le futur ne change pas les poids passés).

Les signaux sont volontairement lents (bougies journalières) : à 0,5 % par ordre, le trading rapide est ruiné
par les frais. Une "clôture journalière" est la clôture de la bougie de 23 h UTC.
Les grilles de paramètres sont petites exprès : moins on essaie de combinaisons, moins on se trompe soi-même.
"""
import numpy as np
import pandas as pd

from bot import config

CHAUFFE_J = 200          # jours d'historique nécessaires au signal le plus lent (moyenne 200 jours)


def _jours(clo):
    return clo[clo.index.hour == 23]


def _horaire(poids_j, clo):
    """Poids journaliers -> poids horaires (maintenus jusqu'à la décision suivante)."""
    return poids_j.reindex(clo.index).ffill().fillna(0.0).reindex(columns=clo.columns, fill_value=0.0)


def _etat(entree, sortie):
    """Position 0/1 : passe à 1 sur un signal d'entrée, à 0 sur un signal de sortie, sinon inchangée."""
    e = pd.DataFrame(np.nan, index=entree.index, columns=entree.columns)
    e = e.mask(entree, 1.0).mask(sortie, 0.0)
    return e.ffill().fillna(0.0)


def _actifs(clo, noms):
    return [a for a in noms if a in clo.columns]


def tendance_sma(clo, sma_j=100):
    """BTC et ETH (50 % chacun) : détenu si la clôture du jour est au-dessus de sa moyenne sma_j jours."""
    j = _jours(clo[_actifs(clo, ["BTC", "ETH"])])
    return _horaire((j > j.rolling(sma_j).mean()) * (1.0 / j.shape[1]), clo)


def donchian(clo, entree_j=40):
    """BTC et ETH : achat sur un plus haut de entree_j jours, vente sur un plus bas de entree_j/2 jours."""
    j = _jours(clo[_actifs(clo, ["BTC", "ETH"])])
    haut = j.rolling(entree_j).max().shift(1)
    bas = j.rolling(entree_j // 2).min().shift(1)
    return _horaire(_etat(j > haut, j < bas) / j.shape[1], clo)


def rotation_momentum(clo, lookback_j=14, k=2, rebal_j=7, sma_btc_j=100):
    """Rotation : les k actifs les plus forts sur lookback_j jours (perf positive exigée), 1/k chacun,
    choix revu tous les rebal_j jours. Tout en cash dès que le BTC passe sous sa moyenne sma_btc_j jours."""
    j = _jours(clo)
    perf = j / j.shift(lookback_j) - 1
    rang = perf.rank(axis=1, ascending=False, method="first")
    choix = ((rang <= k) & (perf > 0)) * (1.0 / k)
    jour_n = (j.index - pd.Timestamp("1970-01-01", tz="UTC")).days
    choix = choix.where(pd.Series(jour_n % rebal_j == 0, index=j.index), np.nan, axis=0).ffill().fillna(0.0)
    regime = j["BTC"] > j["BTC"].rolling(sma_btc_j).mean()
    return _horaire(choix.mul(regime, axis=0), clo)


def tendance_vol_cible(clo, sma_j=100, vol_cible=0.4, vol_j=30, bande=0.10):
    """BTC en tendance (clôture > moyenne sma_j jours), exposition = vol_cible / volatilité réalisée (max 100 %).
    L'exposition n'est ajustée que si elle s'écarte de plus de `bande` de la cible (évite les petits ordres)."""
    j = _jours(clo[["BTC"]])["BTC"]
    vol = np.log(j / j.shift(1)).rolling(vol_j).std() * np.sqrt(365)
    cible = ((vol_cible / vol).clip(upper=1.0) * (j > j.rolling(sma_j).mean())).fillna(0.0).to_numpy()
    w, actuel = np.zeros(len(cible)), 0.0
    for i, c in enumerate(cible):
        if abs(c - actuel) > bande or (c == 0.0) != (actuel == 0.0):
            actuel = c
        w[i] = actuel
    return _horaire(pd.DataFrame({"BTC": w}, index=j.index), clo)


def retour_moyenne(clo, fenetre_h=168, z_entree=2.0):
    """Référence "retour à la moyenne" sur BTC (horaire) : achat quand le prix est z_entree écarts-types
    sous sa moyenne fenetre_h heures, vente dès qu'il la retrouve."""
    c = clo[["BTC"]]
    z = (c - c.rolling(fenetre_h).mean()) / c.rolling(fenetre_h).std()
    return _etat(z < -z_entree, z >= 0).reindex(columns=clo.columns, fill_value=0.0)


def rotation_horaire_live(clo, lookback_h=None, sma_actif_h=None, sma_btc_h=None, nb=None, rang_max=None):
    """La règle du bot en direct (bot/strategy.py), rejouée telle quelle sur l'univers de recherche :
    momentum 24 h, moyenne 48 h, filtre BTC 200 h, 2 positions gardées tant qu'elles restent dans le top 6.
    Le stop suiveur et le coupe-circuit ne sont pas simulés ici."""
    L, sa = lookback_h or config.LOOKBACK_H, sma_actif_h or config.SMA_ACTIF_H
    sb, nb, rmax = sma_btc_h or config.SMA_BTC_H, nb or config.NB_POSITIONS, rang_max or config.RANG_MAX_CONSERVE
    perf = clo / clo.shift(L) - 1
    eligible = ((perf > 0) & (clo > clo.rolling(sa).mean())).to_numpy()
    rang = perf.rank(axis=1, ascending=False, method="first").to_numpy()
    ordre = np.argsort(np.nan_to_num(rang, nan=1e9), axis=1)
    marche = (clo["BTC"] > clo["BTC"].rolling(sb).mean()).to_numpy()
    w, detenus = np.zeros(clo.shape), []
    for t in range(len(clo)):
        if not marche[t]:
            detenus = []
        else:
            detenus = [a for a in detenus if eligible[t, a] and rang[t, a] <= rmax]
            for a in ordre[t]:
                if len(detenus) >= nb:
                    break
                if eligible[t, a] and a not in detenus:
                    detenus.append(a)
        w[t, detenus] = 1.0 / nb
    return pd.DataFrame(w, index=clo.index, columns=clo.columns)


# Grilles fixées AVANT de voir le moindre résultat. Total volontairement faible.
STRATEGIES = [
    {"nom": "tendance_sma", "fonction": tendance_sma,
     "description": "Suivi de tendance BTC + ETH : détenu si le prix est au-dessus de sa moyenne mobile journalière, sinon cash.",
     "grille": {"sma_j": [50, 100, 200]}},
    {"nom": "donchian", "fonction": donchian,
     "description": "Cassure de canal BTC + ETH : achat sur un plus haut de N jours, vente sur un plus bas de N/2 jours.",
     "grille": {"entree_j": [20, 40, 80]}},
    {"nom": "rotation_momentum", "fonction": rotation_momentum,
     "description": "Rotation momentum lente : les K actifs les plus forts sur N jours, avec filtre de marché BTC (moyenne 100 jours).",
     "grille": {"lookback_j": [7, 14, 30], "k": [2, 3], "rebal_j": [1, 7]}},
    {"nom": "tendance_vol_cible", "fonction": tendance_vol_cible,
     "description": "Tendance BTC avec exposition réglée sur une volatilité cible (moins investi quand le marché s'agite).",
     "grille": {"sma_j": [50, 100, 200], "vol_cible": [0.3, 0.5]}},
    {"nom": "retour_moyenne", "fonction": retour_moyenne,
     "description": "Référence retour à la moyenne sur BTC : achat des fortes baisses horaires, vente au retour à la moyenne.",
     "grille": {"fenetre_h": [72, 168], "z_entree": [2.0, 2.5]}},
    {"nom": "rotation_horaire_live", "fonction": rotation_horaire_live,
     "description": "Règle actuelle du bot en direct (momentum 24 h, top 2, filtre BTC 200 h), sans stop suiveur.",
     "grille": {"lookback_h": [config.LOOKBACK_H]}},
]
