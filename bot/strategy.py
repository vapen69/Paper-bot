"""Logique de décision, partagée par le bot en direct et par le backtest.
Réplique exacte de research.strategies.rotation_momentum (paramètres retenus dans config.py)."""
from . import config


def sma(valeurs, n):
    if len(valeurs) < n:
        return None
    return sum(valeurs[-n:]) / n


def marche_favorable(clotures_btc_j):
    """Filtre de marché : BTC au-dessus de sa moyenne 100 jours (clôtures journalières terminées)."""
    m = sma(clotures_btc_j, config.SMA_BTC_J)
    return m is not None and clotures_btc_j[-1] > m


def jour_de_rebalancement(ts_jour):
    """ts_jour : timestamp (s) d'ouverture de la bougie journalière qui vient de se terminer."""
    return (ts_jour // 86400) % config.REBAL_J == 0


def classement(clotures_j):
    """clotures_j : {symbole: [clôtures journalières terminées]}. Trié du plus fort au plus faible sur 7 jours."""
    out = []
    for sym, c in clotures_j.items():
        if len(c) < config.LOOKBACK_J + 1:
            continue
        perf = c[-1] / c[-1 - config.LOOKBACK_J] - 1
        out.append({"symbole": sym, "perf": perf, "eligible": perf > 0})
    out.sort(key=lambda x: x["perf"], reverse=True)
    for i, x in enumerate(out):
        x["rang"] = i + 1
    return out


def selection(rang):
    """Les NB_POSITIONS plus fortes, à condition d'être en hausse sur 7 jours."""
    return [x["symbole"] for x in rang[: config.NB_POSITIONS] if x["eligible"]]


def decisions(detenus, cible, marche_ok):
    """detenus : symboles en portefeuille ; cible : sélection en vigueur (revue tous les 7 jours).
    Retourne (a_vendre {sym: raison}, a_acheter [(sym, raison)])."""
    if not marche_ok:
        return {s: "BTC sous sa moyenne 100 jours : passage en cash" for s in detenus}, []
    a_vendre = {s: "ne fait plus partie des 2 plus fortes de la semaine" for s in detenus if s not in cible}
    a_acheter = [(s, "dans les 2 plus fortes sur 7 jours") for s in cible if s not in detenus]
    return a_vendre, a_acheter
