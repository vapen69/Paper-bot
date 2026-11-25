"""Historique horaire long (API publique Coinbase Exchange, sans clé) + données synthétiques hors ligne.

- Coinbase renvoie 300 bougies max par requête : on pagine vers le passé, ~3 requêtes/s, avec reprises.
- Chaque produit est mis en cache dans research/cache/<PRODUIT>.csv (mise à jour incrémentale).
- Le panneau final est en EUR : les paires USD sont converties avec le taux implicite BTC-USD / BTC-EUR.
"""
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://api.exchange.coinbase.com/products/{}/candles"
CACHE = Path(__file__).resolve().parent / "cache"
UNIVERS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "BCH", "ATOM"]
EUR_DIRECT = ["BTC", "ETH", "SOL"]      # paires EUR téléchargées en direct
H = 3600
PAR_REQUETE = 300
PAUSE_S = 0.35                           # ~3 requêtes par seconde au maximum
VIDES_MAX = 8                            # 8 fenêtres vides d'affilée (100 jours) : le produit n'existait pas encore
COLONNES = ["t", "open", "high", "low", "close", "volume"]

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "paper-bot-research/1.0"


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _requete(produit, debut, fin, essais=6):
    """Bougies de [debut, fin] (timestamps inclus). Retourne None si le produit n'existe pas."""
    derniere = None
    for i in range(essais):
        try:
            r = SESSION.get(BASE.format(produit), timeout=30,
                            params={"granularity": H, "start": _iso(debut), "end": _iso(fin)})
            if r.status_code == 404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            # format Coinbase : [time, low, high, open, close, volume]
            return [(int(x[0]), float(x[3]), float(x[2]), float(x[1]), float(x[4]), float(x[5])) for x in r.json()]
        except Exception as e:  # réseau, limite de débit, erreur serveur
            derniere = e
            time.sleep(min(60, 2 ** i))
    raise RuntimeError(f"Coinbase {produit} : échec après {essais} essais ({derniere})")


def _paginer(produit, debut, fin):
    """Remonte le temps de fin vers debut par fenêtres de 300 bougies."""
    lignes, vides, e = [], 0, fin
    while e >= debut:
        s = max(debut, e - (PAR_REQUETE - 1) * H)
        lot = _requete(produit, s, e)
        time.sleep(PAUSE_S)
        if lot is None:
            return None
        lignes.extend(lot)
        vides = 0 if lot else vides + 1
        if vides >= VIDES_MAX:
            break
        e = s - H
    return lignes


def telecharger(produit, debut, fin):
    """Série horaire d'un produit entre deux timestamps, avec cache CSV. None si produit inconnu."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{produit}.csv"
    df = pd.read_csv(f) if f.exists() else pd.DataFrame(columns=COLONNES)
    trous = [(debut, fin)]
    if len(df):
        t0, t1 = int(df["t"].min()), int(df["t"].max())
        trous = [(a, b) for a, b in ((debut, t0 - H), (t1 + H, fin)) if b >= a]
    for a, b in trous:
        lignes = _paginer(produit, a, b)
        if lignes is None:
            return None
        if lignes:
            df = pd.concat([df, pd.DataFrame(lignes, columns=COLONNES)], ignore_index=True)
    df["t"] = df["t"].astype("int64")
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    if len(df):
        df.to_csv(f, index=False)
    return df[(df["t"] >= debut) & (df["t"] <= fin)]


def _indexer(df):
    df = df.copy()
    df.index = pd.to_datetime(df["t"].astype("int64"), unit="s", utc=True)
    return df[["open", "close"]].astype(float)


def panneau(annees=5.0, journal=print):
    """Retourne (ouv, clo, infos) : ouvertures et clôtures horaires en EUR, une colonne par actif.
    Les heures sans échange sont comblées (clôture précédente). Avant la cotation d'un actif : NaN."""
    fin = (int(time.time()) // H - 1) * H            # dernière bougie terminée
    debut = fin - int(annees * 365 * 24) * H
    brut = {}
    for produit in [f"{s}-EUR" for s in EUR_DIRECT] + [f"{s}-USD" for s in UNIVERS]:
        try:
            df = telecharger(produit, debut, fin)
        except Exception as e:
            journal(f"  {produit} : abandonné ({e})")
            continue
        if df is None or df.empty:
            journal(f"  {produit} : indisponible sur Coinbase")
            continue
        brut[produit] = _indexer(df)
        journal(f"  {produit} : {len(df)} bougies depuis {_iso(int(df['t'].min()))[:10]}")
    if "BTC-USD" not in brut and "BTC-EUR" not in brut:
        raise RuntimeError("aucune donnée BTC : recherche impossible")
    index = pd.date_range(pd.Timestamp(debut, unit="s", tz="UTC"), pd.Timestamp(fin, unit="s", tz="UTC"), freq="h")
    devise = "EUR"
    if "BTC-USD" in brut and "BTC-EUR" in brut:
        # taux de change implicite USD par EUR, heure par heure
        fx = (brut["BTC-USD"] / brut["BTC-EUR"]).reindex(index).ffill().bfill()
    else:
        fx, devise = None, ("USD" if "BTC-USD" in brut else "EUR")
        journal(f"  pas de conversion possible : panneau en {devise}")
    ouv, clo = {}, {}
    for s in UNIVERS:
        serie = brut.get(f"{s}-EUR") if devise == "EUR" else None
        usd = brut.get(f"{s}-USD")
        if usd is not None and (fx is not None or devise == "USD"):
            conv = usd.reindex(index) / fx if fx is not None else usd
            serie = conv if serie is None else serie.reindex(index).combine_first(conv)
        if serie is None:
            continue
        serie = serie.reindex(index)
        c = serie["close"].ffill()
        clo[s], ouv[s] = c, serie["open"].fillna(c)
    return pd.DataFrame(ouv), pd.DataFrame(clo), {"source": "coinbase", "devise": devise, "actifs": list(clo)}


def synthetique(annees=4.0, graine=7, nb_actifs=12):
    """Marché fictif pour les tests hors ligne : facteur commun avec régimes haussiers/baissiers,
    plus un bruit propre à chaque actif. Même format que panneau()."""
    rng = np.random.default_rng(graine)
    n = int(annees * 365 * 24)
    index = pd.date_range("2021-01-01", periods=n, freq="h", tz="UTC")
    regime = np.repeat(rng.choice([-1.0, 0.0, 1.5], size=n // (24 * 45) + 1), 24 * 45)[:n]   # régimes de 45 jours
    marche = regime * 0.8 / 8760 + rng.standard_normal(n) * 0.6 / np.sqrt(8760)
    ouv, clo = {}, {}
    for i, s in enumerate(UNIVERS[:nb_actifs]):
        beta = 1.0 if i == 0 else rng.uniform(0.8, 1.6)
        propre = 0.0 if i == 0 else rng.standard_normal(n) * rng.uniform(0.3, 0.8) / np.sqrt(8760)
        c = 100.0 * np.exp(np.cumsum(beta * marche + propre))
        o = np.concatenate([[100.0], c[:-1]]) * np.exp(rng.standard_normal(n) * 0.0005)
        if i >= nb_actifs - 2:              # deux actifs cotés plus tard, comme dans la réalité
            c[: n // 4], o[: n // 4] = np.nan, np.nan
        clo[s], ouv[s] = c, o
    return (pd.DataFrame(ouv, index=index), pd.DataFrame(clo, index=index),
            {"source": "synthetique", "devise": "EUR", "actifs": list(clo)})
