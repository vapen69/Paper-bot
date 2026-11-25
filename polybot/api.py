"""Lecture des API publiques de Polymarket (aucune clé, aucun compte, aucun ordre).

- Gamma  : liste et détail des marchés (questions, prix, échéances, résolution)
- CLOB   : carnets d'ordres, historique des prix
- Data   : flux des trades (optionnel, la v1 a été retirée : tout échec désactive seulement la stratégie expérimentale)

Les champs de Gamma arrivent tantôt en nombres, tantôt en chaînes, tantôt en chaînes JSON ("[\\"Yes\\", \\"No\\"]") :
tous les lecteurs ci-dessous acceptent les trois formes et renvoient None plutôt que de planter.
"""
import json
import math
import threading
import time
from datetime import datetime, timezone

import requests

from . import config

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "paper-bot-poly/1.0"
_verrou = threading.Lock()
_derniere_requete = [0.0]
COMPTEUR = {"requetes": 0, "erreurs": 0}


class ErreurAPI(RuntimeError):
    pass


def _attendre_debit():
    """Limite volontaire du débit (toutes API confondues)."""
    with _verrou:
        ecart = 1.0 / config.REQUETES_PAR_S
        attente = _derniere_requete[0] + ecart - time.time()
        if attente > 0:
            time.sleep(attente)
        _derniere_requete[0] = time.time()


def _get(url, params=None, essais=None, delai=15):
    """GET avec reprises. Les 4xx (sauf 429) ne sont pas réessayés : la réponse ne changera pas."""
    essais = essais or config.ESSAIS_HTTP
    derniere = None
    for i in range(essais):
        _attendre_debit()
        COMPTEUR["requetes"] += 1
        try:
            r = SESSION.get(url, params=params, timeout=delai)
            if r.status_code == 429 or r.status_code >= 500:
                raise ErreurAPI(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                COMPTEUR["erreurs"] += 1
                raise ErreurAPI(f"HTTP {r.status_code} définitif sur {url}")
            return r.json()
        except ErreurAPI as e:
            derniere = e
            if "définitif" in str(e):
                raise
        except Exception as e:  # réseau, JSON invalide...
            derniere = e
        COMPTEUR["erreurs"] += 1
        if i + 1 < essais:
            time.sleep(min(20, 1.5 * (i + 1)))
    raise ErreurAPI(f"échec après {essais} essais sur {url} : {derniere}")


# ---------- lecteurs tolérants ----------
def nombre(x, defaut=None):
    """Nombre fini à partir d'un nombre ou d'une chaîne, sinon defaut."""
    if x is None or isinstance(x, bool):
        return defaut
    try:
        v = float(x)
    except (TypeError, ValueError):
        return defaut
    return v if math.isfinite(v) else defaut


def liste(x):
    """Liste à partir d'une liste ou d'une chaîne JSON, sinon liste vide."""
    if isinstance(x, list):
        return x
    if isinstance(x, str) and x.strip():
        try:
            v = json.loads(x)
            return v if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []
    return []


def horodatage(x):
    """Timestamp (secondes) à partir d'une date ISO, d'un nombre de secondes ou de millisecondes."""
    if x is None or x == "":
        return None
    v = nombre(x)
    if v is not None:
        return v / 1000.0 if v > 1e11 else v
    try:
        s = str(x).strip().replace(" ", "T", 1)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if len(s) > 5 and s[-3] in "+-" and s[-2:].isdigit():   # "+00" -> "+00:00"
            s += ":00"
        if "." in s:                                            # fractions de seconde de longueur variable
            tete, reste = s.split(".", 1)
            i = 0
            while i < len(reste) and reste[i].isdigit():
                i += 1
            s = tete + reste[i:]
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def categorie(texte):
    t = " " + str(texte or "").lower() + " "
    for cat, mots in config.MOTS_CATEGORIES.items():
        if any(m in t for m in mots):
            return cat
    return "autre"


def parse_marche(brut):
    """Marché Gamma -> dictionnaire propre, ou None si le marché n'est pas un marché binaire exploitable."""
    if not isinstance(brut, dict):
        return None
    issues = [str(o) for o in liste(brut.get("outcomes"))]
    jetons = [str(x) for x in liste(brut.get("clobTokenIds"))]
    prix = [nombre(x) for x in liste(brut.get("outcomePrices"))]
    if len(issues) != 2 or len(jetons) != 2 or not all(jetons) or brut.get("id") is None:
        return None
    if len(prix) != 2 or any(p is None for p in prix):
        prix = [None, None]
    evts = brut.get("events") if isinstance(brut.get("events"), list) else []
    evt = evts[0] if evts and isinstance(evts[0], dict) else {}
    propre = lambda x: "".join(c for c in str(x or "") if c.isalnum() or c in "-_")   # un slug ne contient rien d'autre
    slug = propre(brut.get("slug"))
    evt_slug = propre(evt.get("slug"))
    tags = " ".join(str(t.get("label") or t.get("slug") or "") for t in (evt.get("tags") or brut.get("tags") or [])
                    if isinstance(t, dict))
    question = str(brut.get("question") or evt.get("title") or slug)
    frais = nombre(brut.get("takerBaseFee"))
    bid, ask = nombre(brut.get("bestBid")), nombre(brut.get("bestAsk"))
    spread = nombre(brut.get("spread"))
    if spread is None and bid is not None and ask is not None:
        spread = ask - bid
    return {
        "id": str(brut["id"]),
        "condition_id": str(brut.get("conditionId") or ""),
        "question": question[:300],
        "slug": slug,
        "evenement": str(evt.get("id") or evt_slug or brut.get("negRiskMarketID") or brut["id"]),
        "url": "https://polymarket.com/event/" + (evt_slug or slug) if (evt_slug or slug) else "https://polymarket.com",
        "issues": issues, "jetons": jetons, "prix": prix,
        "bid": bid, "ask": ask, "spread": spread,
        "volume24h": nombre(brut.get("volume24hr"), 0.0),
        "volume": nombre(brut.get("volumeNum"), nombre(brut.get("volume"), 0.0)),
        "liquidite": nombre(brut.get("liquidityNum"), nombre(brut.get("liquidity"), 0.0)),
        "debut": horodatage(brut.get("startDate") or brut.get("createdAt")),
        "echeance": horodatage(brut.get("endDate") or brut.get("endDateIso")),
        "ferme_le": horodatage(brut.get("closedTime")),
        "actif": brut.get("active") is not False,
        "ferme": brut.get("closed") is True,
        "accepte_ordres": brut.get("acceptingOrders") is not False and brut.get("enableOrderBook") is not False,
        "uma": str(brut.get("umaResolutionStatus") or ""),
        "neg_risk": bool(brut.get("negRisk")),
        "frais_bps": frais,                     # None si le champ est absent
        "parts_min": nombre(brut.get("orderMinSize"), config.PARTS_MIN),
        "categorie": categorie(question + " " + tags + " " + evt_slug),
    }


def issue_finale(m):
    """Prix de règlement de chaque issue si le marché est résolu : [1, 0], [0, 1] ou [0.5, 0.5]. Sinon None.
    Un marché fermé dont les prix valent [0, 0] (annulé ou jamais résolu) n'est PAS résolu."""
    if not m or not m.get("ferme"):
        return None
    p = m.get("prix") or [None, None]
    if p[0] is None or p[1] is None or m.get("uma") == "disputed":
        return None
    if abs(p[0] + p[1] - 1.0) > 0.02:
        return None
    for a, b in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)):
        if abs(p[0] - a) <= 0.01 and abs(p[1] - b) <= 0.01:
            return [a, b]
    return None


# ---------- Gamma ----------
def marches(params, pages=1, par_page=100):
    """Liste paginée de marchés Gamma (bruts -> propres). Ne lève jamais : renvoie ce qui a pu être lu."""
    out, decalage = [], 0
    for _ in range(pages):
        try:
            lot = _get(config.GAMMA + "/markets", {**params, "limit": par_page, "offset": decalage})
        except Exception:
            break
        if isinstance(lot, dict):
            lot = lot.get("data") or lot.get("markets") or []
        if not isinstance(lot, list) or not lot:
            break
        decalage += len(lot)
        out.extend(m for m in (parse_marche(b) for b in lot) if m)
    return out


def marche(identifiant):
    """Détail d'un marché (même fermé). None si introuvable."""
    try:
        brut = _get(config.GAMMA + "/markets/" + str(identifiant))
    except Exception:
        return None
    if isinstance(brut, list):
        brut = brut[0] if brut else None
    return parse_marche(brut)


# ---------- CLOB ----------
def parse_carnet(brut):
    """Carnet CLOB -> {"bids": [(prix, taille)] du meilleur au pire, "asks": idem}. L'API ne garantit aucun ordre
    (les bids arrivent du plus bas au plus haut) : on trie nous-mêmes."""
    def cote(niveaux):
        res = []
        for n in niveaux if isinstance(niveaux, list) else []:
            if isinstance(n, dict):
                p, s = nombre(n.get("price")), nombre(n.get("size"))
            elif isinstance(n, (list, tuple)) and len(n) >= 2:
                p, s = nombre(n[0]), nombre(n[1])
            else:
                continue
            if p is not None and s is not None and 0 < p < 1 and s > 0:
                res.append((p, s))
        return res
    brut = brut if isinstance(brut, dict) else {}
    return {"bids": sorted(cote(brut.get("bids")), key=lambda x: -x[0]),
            "asks": sorted(cote(brut.get("asks")), key=lambda x: x[0])}


def carnet(jeton):
    """Carnet d'ordres d'une issue. Lève ErreurAPI si indisponible."""
    return parse_carnet(_get(config.CLOB + "/book", {"token_id": jeton}, essais=2, delai=10))


def parse_historique(brut):
    """{history: [{t, p}]} -> liste triée de (t secondes, prix), doublons et valeurs invalides retirés."""
    pts = {}
    for x in (brut.get("history") if isinstance(brut, dict) else None) or []:
        if not isinstance(x, dict):
            continue
        t, p = horodatage(x.get("t")), nombre(x.get("p"))
        if t is not None and p is not None and 0 <= p <= 1:
            pts[int(t)] = p
    return sorted(pts.items())


def historique(jeton, **params):
    """Historique de prix d'une issue. Exemple : historique(j, interval="1d", fidelity=60)."""
    return parse_historique(_get(config.CLOB + "/prices-history", {"market": jeton, **params}, delai=30))


# ---------- Data API (optionnelle) ----------
def parse_trades(brut):
    """Flux de trades -> liste de dictionnaires propres. Accepte une liste ou {"data": [...]} / {"trades": [...]}."""
    if isinstance(brut, dict):
        brut = brut.get("data") or brut.get("trades") or []
    out = []
    for x in brut if isinstance(brut, list) else []:
        if not isinstance(x, dict):
            continue
        prix, taille = nombre(x.get("price")), nombre(x.get("size"))
        jeton = x.get("asset") or x.get("asset_id") or x.get("tokenId")
        t = horodatage(x.get("timestamp") or x.get("matchTime") or x.get("time"))
        if prix is None or taille is None or not jeton or t is None:
            continue
        out.append({"jeton": str(jeton), "cote": str(x.get("side") or "").upper(), "prix": prix, "taille": taille,
                    "montant": prix * taille, "t": t, "titre": str(x.get("title") or "")[:300],
                    "condition_id": str(x.get("conditionId") or x.get("market") or ""),
                    "id": str(x.get("transactionHash") or x.get("id") or f"{jeton}-{t}-{taille}")})
    return out


def gros_trades(chemin, montant_min):
    """Derniers gros trades (toutes marchés confondus). Lève ErreurAPI si l'endpoint ne répond pas."""
    brut = _get(config.DATA_API + chemin, {"limit": 200, "takerOnly": "true", "filterType": "CASH",
                                           "filterAmount": int(montant_min)}, essais=1, delai=10)
    return [x for x in parse_trades(brut) if x["montant"] >= montant_min]
