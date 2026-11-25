"""Données publiques Kraken (aucune clé API, aucun compte nécessaire)."""
import time
import requests

from . import config

BASE = "https://api.kraken.com/0/public/"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "paper-bot/1.0"


def _get(endpoint, params=None, essais=4):
    derniere = None
    for i in range(essais):
        try:
            r = SESSION.get(BASE + endpoint, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                raise RuntimeError(f"Kraken {endpoint}: {data['error']}")
            return data["result"]
        except Exception as e:  # réseau, limite de requêtes, etc.
            derniere = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Échec Kraken {endpoint} après {essais} essais : {derniere}")


def nom_lisible(ws):
    """'XBT/EUR' -> 'BTC'"""
    base = ws.split("/")[0]
    return {"XBT": "BTC", "XDG": "DOGE"}.get(base, base)


def paires_eur():
    """Toutes les paires X/EUR en ligne, sauf stablecoins et fiat."""
    res = _get("AssetPairs")
    out = {}
    for cle, p in res.items():
        ws = p.get("wsname", "")
        if not ws.endswith("/EUR") or p.get("status", "online") != "online":
            continue
        if cle.endswith(".d"):
            continue
        sym = nom_lisible(ws)
        if sym in config.EXCLUS or ws.split("/")[0] in config.EXCLUS:
            continue
        out[cle] = {"symbole": sym, "ws": ws,
                    "ordermin": float(p.get("ordermin", 0) or 0),
                    "costmin": float(p.get("costmin", 0) or 0)}
    return out


def tickers(cles):
    """Prix actuel et volume 24 h en euros pour une liste de paires."""
    out = {}
    cles = list(cles)
    for i in range(0, len(cles), 40):
        lot = cles[i:i + 40]
        res = _get("Ticker", {"pair": ",".join(lot)})
        for cle, t in res.items():
            prix = float(t["c"][0])
            vol_eur = float(t["v"][1]) * float(t["p"][1])
            out[cle] = {"prix": prix, "volume_eur": vol_eur}
        time.sleep(1.1)
    return out


def bougies_horaires(cle):
    """Clôtures horaires TERMINÉES (la bougie en cours est retirée : pas de triche sur le futur).
    Retourne une liste de (timestamp, open, close)."""
    res = _get("OHLC", {"pair": cle, "interval": 60})
    lignes = next(v for k, v in res.items() if k != "last")
    lignes = lignes[:-1]  # la dernière bougie n'est pas terminée
    time.sleep(1.1)
    return [(int(l[0]), float(l[1]), float(l[4])) for l in lignes]
