"""Logique de décision, partagée par le bot en direct et par le backtest.
Réplique de research.strategies.tendance_long_short (paramètres dans config.py) :
pour chaque actif (BTC, ETH), 50 % du capital, long si la clôture journalière est au-dessus de sa moyenne
SMA_J jours, short si elle est en dessous. Décision une fois par jour, après la clôture."""
from . import config


def sma(valeurs, n):
    if len(valeurs) < n:
        return None
    return sum(valeurs[-n:]) / n


def signaux(clotures_j):
    """clotures_j : {symbole: [clôtures journalières terminées]} -> {symbole: {sens, cloture, moyenne, ecart_pct}}."""
    out = {}
    for s in config.UNIVERS:
        c = clotures_j.get(s, [])
        m = sma(c, config.SMA_J)
        if m is None:
            continue
        sens = "long" if c[-1] > m else "short" if c[-1] < m else None
        out[s] = {"sens": sens, "cloture": c[-1], "moyenne": m, "ecart_pct": (c[-1] / m - 1) * 100}
    return out


def decisions(positions, sig):
    """positions : {symbole: {sens, ...}}. Retourne (a_fermer {sym: raison}, a_ouvrir [(sym, sens, raison)])."""
    a_fermer, a_ouvrir = {}, []
    for s, x in sig.items():
        actuel = positions.get(s, {}).get("sens")
        voulu = x["sens"]
        if actuel == voulu:
            continue
        cote = "au-dessus" if x["ecart_pct"] > 0 else "en dessous"
        raison = f"clôture {cote} de la moyenne {config.SMA_J} jours ({x['ecart_pct']:+.1f} %)"
        if actuel is not None:
            a_fermer[s] = raison
        if voulu is not None:
            a_ouvrir.append((s, voulu, raison))
    return a_fermer, a_ouvrir
