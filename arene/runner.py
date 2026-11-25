"""Boucle de l'arène Polymarket (argent fictif, aucun ordre réel). Voir arene/config.py.

Une seule boucle lit les marchés pour tout le monde (scan Gamma, carnets CLOB, historiques), puis chaque stratégie
décide et simule ses achats dans son propre portefeuille de 100 $ fictifs. L'état est publié sur la branche
data-arena (state_arena.json), séparée de data-poly : le bot en direct n'est jamais touché.
"""
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from polybot import api, execution, strategies
from polybot import config as pconf
from polybot.portefeuille import Portefeuille
from . import config as C

RACINE = Path(__file__).resolve().parent.parent
DATA = RACINE / "arene_out"
BRANCHE = "data-arena"
DUREE_MAX_S = int(os.environ.get("DUREE_MAX_S", 5 * 3600 + 40 * 60))
PUBLIER = os.environ.get("PUBLIER", "1") == "1"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Sources possibles du classement (aucune n'est documentée comme stable) : on essaie dans l'ordre.
SOURCES_CLASSEMENT = [
    (pconf.DATA_API + "/v1/leaderboard", {"timePeriod": "MONTH", "orderBy": "PNL", "category": "OVERALL"}),
    ("https://lb-api.polymarket.com/profit", {"window": "1m"}),
]
SOURCES_TRADES = [
    (pconf.DATA_API + "/trades", {"takerOnly": "false"}),
    (pconf.DATA_API + "/activity", {"type": "TRADE"}),
]


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def court(texte, n=70):
    texte = str(texte)
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def achat_outsider(t, p, fin, infos, prix_min, prix_max, jours_max):
    """Marchés Oui/Non : acheter le Oui quand il est coté entre prix_min et prix_max (outsider)."""
    cote = np.full(len(t), -1)
    if not infos.get("oui_non"):
        return cote
    r = (fin - t) if fin is not None else np.full(len(t), np.inf)
    ok = (r >= strategies.MARGE_FIN_S) & (r <= jours_max * strategies.JOUR) & (p >= prix_min) & (p <= prix_max)
    cote[ok] = 0
    return cote


REGLES = {**{k: v["fn"] for k, v in strategies.STRATEGIES.items()}, "achat_outsider": achat_outsider}


def signal(regle, params, t, p, fin, infos):
    """Côté voulu (-1, 0 ou 1) au dernier point connu, avec les mêmes fonctions que la recherche."""
    if regle not in REGLES or len(t) == 0:
        return -1
    t, p = np.asarray(t, dtype=float), np.asarray(p, dtype=float)
    return int(REGLES[regle](t, p, fin, infos, **params)[-1])


def parse_classement(brut):
    """Classement -> [{"wallet", "nom", "pnl"}] trié par gain décroissant. Accepte une liste ou {"data": [...]}.
    Les champs varient selon la source : on accepte plusieurs noms."""
    if isinstance(brut, dict):
        brut = brut.get("data") or brut.get("leaderboard") or brut.get("results") or []
    out, vus = [], set()
    for x in brut if isinstance(brut, list) else []:
        if not isinstance(x, dict):
            continue
        w = str(x.get("proxyWallet") or x.get("wallet") or x.get("address") or x.get("user") or "").lower()
        if not (w.startswith("0x") and len(w) == 42 and all(c in "0123456789abcdef" for c in w[2:])) or w in vus:
            continue
        pnl = api.nombre(x.get("pnl"), api.nombre(x.get("amount"), api.nombre(x.get("profit"))))
        if pnl is None:
            continue
        vus.add(w)
        nom = str(x.get("userName") or x.get("name") or x.get("pseudonym") or "")[:40]
        out.append({"wallet": w, "nom": nom, "pnl": pnl})
    return sorted(out, key=lambda x: -x["pnl"])


def t_stat(rendements):
    """Moyenne / erreur type des rendements par pari (None sous 5 paris)."""
    r = [x for x in rendements if isinstance(x, (int, float)) and math.isfinite(x)]
    if len(r) < 5:
        return None
    m, s = float(np.mean(r)), float(np.std(r, ddof=1))
    return None if s <= 0 else m / (s / math.sqrt(len(r)))


class Arene:
    def __init__(self):
        DATA.mkdir(exist_ok=True)
        f = DATA / "state_arena.json"
        try:
            e = json.loads(f.read_text()) if f.exists() else {}
        except Exception:
            e = {}
        pconf.REQUETES_PAR_S = C.REQUETES_PAR_S          # ce processus seulement (le bot en direct est ailleurs)
        self.demarre_le = e.get("demarre_le") or maintenant()
        self.journal = e.get("journal", [])
        self.courbe = e.get("courbe", [])
        anciens = {c.get("id"): c for c in e.get("concurrents", []) if isinstance(c, dict)}
        self.conc = {}
        for d in C.CONCURRENTS:
            a = anciens.get(d["id"]) or {}
            pf = Portefeuille(a.get("portefeuille") or {"cash": C.CAPITAL_DEPART,
                                                        "plus_haut_portefeuille": C.CAPITAL_DEPART})
            self.conc[d["id"]] = {"def": d, "pf": pf, "rendements": list(a.get("rendements") or []),
                                  "refroidissement": {k: v for k, v in (a.get("refroidissement") or {}).items()
                                                      if v > time.time()},
                                  "creee_le": a.get("creee_le") or maintenant()}
        cl = e.get("classement") or {}
        self.classement = {"etat": "en attente", "source": None, "suivis": cl.get("suivis", []), "erreur": None,
                           "copies": int(cl.get("copies", 0))}
        self.classement_echecs, self.classement_prochain, self.trades_vus = 0, 0.0, set()
        self.univers, self.par_jeton, self.carnets = {}, {}, {}
        self.rotation_prix, self.rotation_resol = 0, 0
        self.stats = {"marches_scannes": 0, "dans_filtres": 0, "carnets_lus": 0, "achats_session": 0,
                      "dernier_scan": None}
        self.erreurs_vues = {}
        self.dirty = True

    # ---------- utilitaires ----------
    def log(self, msg):
        ligne = {"t": maintenant(), "msg": msg}
        print(ligne["t"], msg, flush=True)
        self.journal.append(ligne)
        self.journal = self.journal[-C.MAX_JOURNAL:]

    def erreur(self, cle, msg):
        if time.time() - self.erreurs_vues.get(cle, 0) > 600:
            self.erreurs_vues[cle] = time.time()
            self.log(msg)

    def lire_carnet(self, jeton, frais=False):
        """Carnet d'une issue, avec un petit cache commun à toutes les stratégies. None si indisponible."""
        c = self.carnets.get(jeton)
        if c and time.time() - c[0] < C.CARNET_CACHE_S and not frais:
            return c[1]
        try:
            carnet = api.carnet(jeton)
        except Exception:
            return None
        self.stats["carnets_lus"] += 1
        self.carnets[jeton] = (time.time(), carnet)
        return carnet

    @staticmethod
    def filtre_marche(m, jours_max=None):
        now = time.time()
        if m["ferme"] or not m["actif"] or not m["accepte_ordres"]:
            return "fermé"
        if m["echeance"] is None or m["echeance"] - now < pconf.HEURES_MIN_AVANT_ECHEANCE * 3600:
            return "échéance trop proche ou inconnue"
        if jours_max is not None and m["echeance"] - now > jours_max * 86400:
            return "échéance trop lointaine"
        if (m["liquidite"] or 0) < pconf.LIQUIDITE_MIN or (m["volume24h"] or 0) < pconf.VOLUME24H_MIN:
            return "liquidité ou volume insuffisant"
        if m["spread"] is not None and m["spread"] > pconf.SPREAD_MAX + 1e-9:
            return "écart achat/vente trop large"
        return None

    @staticmethod
    def prix_scan(m):
        if m["bid"] is not None and m["ask"] is not None and 0 < m["bid"] <= m["ask"] < 1:
            return (m["bid"] + m["ask"]) / 2
        return m["prix"][0]

    @staticmethod
    def infos_marche(m):
        return {"id": m["id"], "oui_non": m["issues"][0].strip().lower() == "yes"}

    # ---------- portefeuille d'une stratégie ----------
    def refus(self, c, m, mise):
        pf = c["pf"]
        pos = pf.positions.values()
        if mise < pconf.ORDRE_MIN:
            return "cash insuffisant"
        if any(p["marche_id"] == m["id"] for p in pos):
            return "déjà en position"
        if c["refroidissement"].get(m["id"], 0) > time.time():
            return "marché quitté récemment"
        if len(pf.positions) >= C.POSITIONS_MAX:
            return "positions max"
        if sum(1 for p in pos if p["evenement"] == m["evenement"]) >= C.POSITIONS_MAX_PAR_EVENEMENT:
            return "trop de positions sur l'événement"
        return None

    @staticmethod
    def mise(c):
        v = c["pf"].valeur()
        return min(C.PART_PAR_MARCHE * v, c["pf"].cash - C.RESERVE_CASH * v)

    def tenter(self, c, m, cote, raison, limite=None, sortie_h=None, budget=None):
        """Simule un achat pour une stratégie sur le carnet réel. Retourne None si acheté, sinon la raison.
        budget : liste [carnets restants] partagée pendant un scan (None = pas de limite)."""
        d = c["def"]
        mise = self.mise(c)
        r = self.refus(c, m, mise)
        if r:
            return r
        jeton = m["jetons"][cote]
        en_cache = jeton in self.carnets and time.time() - self.carnets[jeton][0] < C.CARNET_CACHE_S
        if budget is not None and not en_cache:
            if budget[0] <= 0:
                return "plus de lecture de carnet pour ce scan"
            budget[0] -= 1
        carnet = self.lire_carnet(jeton)
        if carnet is None:
            return "carnet indisponible"
        if not carnet["asks"] or not carnet["bids"]:
            return "carnet vide d'un côté"
        ask, bid = carnet["asks"][0][0], carnet["bids"][0][0]
        plafond = min(limite or 1.0, pconf.PRIX_ENTREE_MAX)
        if ask - bid > pconf.SPREAD_MAX + 1e-9:
            return "écart réel trop large"
        if ask > plafond + 1e-9:
            return "prix vendeur trop haut"
        if d["famille"] == "fourchette":
            p0 = ask if cote == 0 else 1 - ask
            if signal(d["regle"], d["params"], [time.time()], [p0], m["echeance"], self.infos_marche(m)) != cote:
                return "prix réel hors de la fourchette"
        frais_u = execution.frais_taker(1.0, ask, m["frais_bps"])
        plancher = m["parts_min"] * (ask + frais_u) * 1.03
        if plancher > mise:
            v = c["pf"].valeur()
            if plancher > 2 * mise or plancher > c["pf"].cash - C.RESERVE_CASH * v:
                return "mise trop petite pour le minimum de parts"
            mise = plancher
        execu = execution.acheter_carnet(carnet["asks"], mise, plafond, m["frais_bps"])
        if execu is None or execu["parts"] < m["parts_min"] or \
                execu["cout"] + execu["frais"] < pconf.REMPLISSAGE_MIN * mise:
            return "carnet trop mince"
        infos = {"marche_id": m["id"], "condition_id": m["condition_id"], "question": m["question"],
                 "issue": m["issues"][cote], "index": cote, "url": m["url"], "strategie": d["id"],
                 "categorie": m["categorie"], "evenement": m["evenement"], "frais_bps": m["frais_bps"],
                 "echeance": api.iso(m["echeance"]) if m["echeance"] else None,
                 "sortie_le": time.time() + sortie_h * 3600 if sortie_h else None}
        if not c["pf"].acheter(jeton, execu, infos, maintenant(), raison):
            return "cash insuffisant"
        c["pf"].positions[jeton]["bid"] = bid
        self.stats["achats_session"] += 1
        self.log(f"[{d['nom']}] ACHAT « {m['issues'][cote]} » à {execu['prix_moyen']:.3f} sur "
                 f"« {court(m['question'])} » : {raison}")
        self.dirty = True
        return None

    def fermer(self, c, jeton, pnl):
        """Après une vente ou un règlement : rendement du pari et refroidissement du marché."""
        dernier = c["pf"].trades[-1] if c["pf"].trades else {}
        if "pnl_pct" in dernier:
            c["rendements"].append(round(dernier["pnl_pct"] / 100, 5))
        c["refroidissement"][dernier.get("marche_id") or ""] = time.time() + C.REFROIDISSEMENT_S
        self.dirty = True

    # ---------- marchés ----------
    def scanner(self):
        base = {"active": "true", "closed": "false", "order": "volume24hr", "ascending": "false"}
        now = time.time()
        lot = api.marches(base, pages=pconf.PAGES_SCAN)
        lot += api.marches({**base, "end_date_min": api.iso(now),
                            "end_date_max": api.iso(now + C.JOURS_SCAN_ECHEANCE * 86400)}, pages=pconf.PAGES_ECHEANCE)
        if not lot:
            self.erreur("scan", "Scan des marchés impossible (Gamma ne répond pas), nouvel essai dans une minute.")
            return
        self.univers = {m["id"]: m for m in lot}
        self.par_jeton = {j: (m, i) for m in self.univers.values() for i, j in enumerate(m["jetons"])}
        filtres = [m for m in sorted(self.univers.values(), key=lambda x: -(x["volume24h"] or 0))
                   if not self.filtre_marche(m)]
        self.stats.update(marches_scannes=len(self.univers), dans_filtres=len(filtres), dernier_scan=maintenant())
        heure = math.floor(now / 3600) * 3600
        for c in self.conc.values():
            d = c["def"]
            if d["famille"] not in ("fourchette", "hasard"):
                continue
            budget = [C.CARNETS_PAR_STRATEGIE]     # chaque stratégie a sa part : aucune n'affame les suivantes
            for m in filtres:
                if budget[0] <= 0:
                    break
                if d["famille"] == "fourchette" and self.filtre_marche(m, d["params"].get("jours_max")):
                    continue
                p0 = self.prix_scan(m)
                if p0 is None:
                    continue
                # le hasard tire une fois par marché et par heure (proba fixe), les autres décident au prix du scan
                t = heure if d["famille"] == "hasard" else now
                cote = signal(d["regle"], d["params"], [t], [p0], m["echeance"], self.infos_marche(m))
                if cote < 0:
                    continue
                prix = p0 if cote == 0 else 1 - p0
                self.tenter(c, m, cote, f"{m['issues'][cote]} cotée {prix * 100:.0f} %, échéance dans "
                                        f"{(m['echeance'] - now) / 86400:.1f} j",
                            limite=d["params"].get("prix_max") if d["regle"] != "achat_outsider" else
                            d["params"]["prix_max"] + 0.01, budget=budget)

    def scanner_mouvements(self):
        concs = [c for c in self.conc.values() if c["def"]["famille"] == "mouvement"]
        if not concs:
            return
        now, lus = time.time(), 0
        for m in sorted(self.univers.values(), key=lambda x: -(x["volume24h"] or 0)):
            if lus >= C.MARCHES_MOUVEMENT:
                break
            if self.filtre_marche(m):
                continue
            lus += 1
            try:
                pts = api.historique(m["jetons"][0], interval="1w", fidelity=60)
            except Exception:
                continue
            if len(pts) < 3 or now - pts[-1][0] > 2 * 3600:
                continue
            t, p = [x[0] for x in pts], [x[1] for x in pts]
            for c in concs:
                d = c["def"]
                cote = signal(d["regle"], d["params"], t, p, m["echeance"], self.infos_marche(m))
                if cote >= 0:
                    self.tenter(c, m, cote, f"mouvement d'au moins {d['params']['ecart'] * 100:.0f} points en "
                                            f"{d['params']['fenetre_h']} h", limite=0.95,
                                sortie_h=d["params"].get("sortie_h"))

    # ---------- copie du classement (expérimental) ----------
    def _essayer(self, sources, extra):
        derniere = None
        for url, params in sources:
            try:
                return url, api._get(url, {**params, **extra}, essais=1, delai=15)
            except Exception as e:
                derniere = e
        raise api.ErreurAPI(str(derniere))

    def suivre_classement(self):
        c = self.conc.get("classement")
        if c is None or time.time() < self.classement_prochain:
            return
        try:
            url, brut = self._essayer(SOURCES_CLASSEMENT, {"limit": 50})
            top = [x for x in parse_classement(brut) if x["pnl"] > 0][:C.CLASSEMENT_TOP]
            if not top:
                raise api.ErreurAPI("classement vide ou illisible")
        except Exception as e:
            self.classement_echecs += 1
            self.classement["erreur"] = court(str(e), 160)
            if self.classement_echecs >= C.CLASSEMENT_ECHECS_MAX:
                self.classement_prochain = time.time() + 3600
                if self.classement["etat"] != "en veille":
                    self.log(f"Copie du classement en veille : classement Polymarket illisible depuis GitHub ({court(str(e), 120)}). "
                             "Nouvel essai chaque heure.")
                self.classement["etat"] = "en veille"
            self.dirty = True
            return
        if self.classement["etat"] != "actif":
            self.log(f"Copie du classement active (source : {url.split('//')[1].split('/')[0]}).")
        self.classement_echecs = 0
        self.classement.update(etat="actif", source=url, erreur=None,
                               suivis=[{"wallet": x["wallet"][:6] + "…" + x["wallet"][-4:], "nom": x["nom"],
                                        "pnl": round(x["pnl"])} for x in top])
        now, recherches = time.time(), 0
        for x in top:
            try:
                _, brut = self._essayer(SOURCES_TRADES, {"user": x["wallet"], "limit": 50})
            except Exception:
                continue
            for tr in sorted(api.parse_trades(brut), key=lambda y: y["t"]):
                if tr["id"] in self.trades_vus:
                    continue
                self.trades_vus.add(tr["id"])
                if tr["cote"] != "BUY" or now - tr["t"] > C.CLASSEMENT_AGE_MAX_S:
                    continue
                if not C.CLASSEMENT_PRIX_MIN <= tr["prix"] <= C.CLASSEMENT_PRIX_MAX:
                    continue
                if tr["jeton"] not in self.par_jeton and recherches < C.CLASSEMENT_RECHERCHES_MARCHE:
                    recherches += 1
                    for m in api.marches({"clob_token_ids": tr["jeton"]}, pages=1, par_page=5):
                        for i, j in enumerate(m["jetons"]):
                            self.par_jeton[j] = (m, i)
                if tr["jeton"] not in self.par_jeton:
                    continue
                m, cote = self.par_jeton[tr["jeton"]]
                if self.filtre_marche(m):
                    continue
                nom = x["nom"] or (x["wallet"][:6] + "…")
                if self.tenter(c, m, cote, f"copie de {nom} (classement, +{x['pnl']:,.0f} $ ce mois) : achat de "
                                           f"{tr['montant']:,.0f} $ à {tr['prix']:.3f}".replace(",", " "),
                               limite=tr["prix"] + C.CLASSEMENT_ECART_PRIX) is None:
                    self.classement["copies"] += 1
        if len(self.trades_vus) > 20000:
            self.trades_vus = set(list(self.trades_vus)[-5000:])

    # ---------- positions ----------
    def detenteurs(self, jeton):
        return [c for c in self.conc.values() if jeton in c["pf"].positions]

    def tick_prix(self):
        """Valorise les positions (carnets en rotation) et exécute les sorties programmées."""
        jetons = sorted({j for c in self.conc.values() for j in c["pf"].positions})
        if jetons:
            k = self.rotation_prix % len(jetons)
            lot = (jetons[k:] + jetons[:k])[:C.PRIX_PAR_TICK]
            self.rotation_prix += len(lot)
            for j in lot:
                carnet = self.lire_carnet(j, frais=True)
                if carnet is None:
                    continue
                prix = execution.milieu(carnet)
                for c in self.detenteurs(j):
                    p = c["pf"].positions[j]
                    if prix is not None:
                        p["dernier_prix"] = prix
                    p["bid"] = carnet["bids"][0][0] if carnet["bids"] else None
        now = time.time()
        for c in self.conc.values():
            for j in list(c["pf"].positions):
                p = c["pf"].positions[j]
                if p.get("sortie_le") and now >= p["sortie_le"]:
                    self.vendre(c, j, "sortie programmée")
            c["pf"].plus_haut = max(c["pf"].plus_haut, c["pf"].valeur())

    def vendre(self, c, jeton, raison):
        p = c["pf"].positions[jeton]
        carnet = self.lire_carnet(jeton, frais=True) or {"bids": []}
        execu = execution.vendre_carnet(carnet["bids"], p["parts"], 0.0, p.get("frais_bps"))
        if execu is None:
            return False
        marche_id, question = p["marche_id"], p["question"]
        pnl = c["pf"].vendre(jeton, execu, maintenant(), raison)
        c["pf"].trades[-1]["marche_id"] = marche_id
        self.fermer(c, jeton, pnl)
        self.log(f"[{c['def']['nom']}] VENTE à {execu['prix_moyen']:.3f} sur « {court(question)} » : {raison} ({pnl:+.2f} $)")
        return True

    def verifier_resolutions(self):
        """Règle, dans toutes les stratégies, les positions dont le marché est résolu. Les marchés dont l'échéance
        est passée sont vérifiés à chaque passage, les autres en rotation."""
        now = time.time()
        marches = {}
        for c in self.conc.values():
            for p in c["pf"].positions.values():
                marches[p["marche_id"]] = min(marches.get(p["marche_id"], math.inf),
                                              api.horodatage(p.get("echeance")) or math.inf)
        proches = [i for i, e in marches.items() if e <= now + 3600]
        loin = sorted(i for i, e in marches.items() if e > now + 3600)
        if loin:
            k = self.rotation_resol % len(loin)
            loin = (loin[k:] + loin[:k])[:C.RESOLUTIONS_LOINTAINES]
            self.rotation_resol += len(loin)
        for mid in proches + loin:
            m = api.marche(mid)
            final = api.issue_finale(m)
            if final is None:
                continue
            for c in self.conc.values():
                for j in [j for j, p in c["pf"].positions.items() if p["marche_id"] == mid]:
                    p = c["pf"].positions[j]
                    prix_final = final[p["index"]]
                    pnl = c["pf"].regler(j, prix_final, maintenant(), "marché résolu")
                    c["pf"].trades[-1]["marche_id"] = mid
                    self.fermer(c, j, pnl)
                    mot = "GAGNÉ" if prix_final == 1 else "PERDU" if prix_final == 0 else "PARTAGÉ"
                    self.log(f"[{c['def']['nom']}] {mot} {pnl:+.2f} $ « {p['issue']} » sur « {court(p['question'])} »")

    # ---------- publication ----------
    def point_courbe(self):
        self.courbe.append({"t": maintenant(), "v": {k: round(c["pf"].valeur(), 2) for k, c in self.conc.items()}})
        if len(self.courbe) > C.MAX_POINTS_COURBE:
            moitie = len(self.courbe) // 2          # on éclaircit la moitié la plus ancienne (un point sur deux)
            self.courbe = self.courbe[:moitie:2] + self.courbe[moitie:]

    def resume(self, c):
        d, pf = c["def"], c["pf"]
        s = pf.pnl_strategies.get(d["id"], {})
        v = pf.valeur()
        ts = t_stat(c["rendements"])
        return {
            "id": d["id"], "nom": d["nom"], "famille": d["famille"], "couleur": d["couleur"], "desc": d["desc"],
            "params": d["params"], "reference": bool(d.get("reference")), "experimental": bool(d.get("experimental")),
            "valeur": round(v, 3), "cash": round(pf.cash, 3), "pnl_total": round(v - C.CAPITAL_DEPART, 3),
            "positions_ouvertes": len(pf.positions), "entrees": int(s.get("entrees", 0)),
            "reglees": int(s.get("clotures", 0)), "gagnants": int(s.get("gagnants", 0)),
            "pnl_regle": round(float(s.get("pnl", 0.0)), 3), "frais": round(pf.frais_total, 3),
            "rendement_moyen": round(float(np.mean(c["rendements"])), 4) if c["rendements"] else None,
            "t": round(ts, 2) if ts is not None else None,
            "baisse_max": round(1 - v / pf.plus_haut, 4) if pf.plus_haut > 0 else 0.0,
            "creee_le": c["creee_le"],
        }

    def construire_etat(self):
        concurrents = []
        for c in self.conc.values():
            pf = c["pf"]
            etat_pf = pf.etat()
            etat_pf["trades"] = etat_pf["trades"][-C.MAX_TRADES_PAR_STRATEGIE:]
            concurrents.append({**self.resume(c), "portefeuille": etat_pf, "rendements": c["rendements"],
                                "refroidissement": c["refroidissement"]})
        recents = sorted(((t, c["def"]) for c in self.conc.values() for t in c["pf"].trades[-15:]),
                         key=lambda x: x[0].get("t", ""), reverse=True)[:60]
        return {
            "maj": maintenant(), "demarre_le": self.demarre_le, "capital_depart": C.CAPITAL_DEPART, "devise": "USDC",
            "avertissement": "Arène de repérage : avec autant de courbes, l'une d'elles monte toujours par chance. "
                             "Aucune stratégie ne passe dans le bot en direct sans réussir la règle de recherche "
                             "fixée à l'avance (t >= 2,5, pire baisse <= 25 %, survit aux frais, bat le hasard).",
            "parametres": {"part_par_marche": C.PART_PAR_MARCHE, "positions_max": C.POSITIONS_MAX,
                           "reserve_cash": C.RESERVE_CASH, "frais_bps_si_absent": pconf.FRAIS_BPS_SI_ABSENT},
            "concurrents": concurrents,
            "derniers_trades": [{**{k: t.get(k) for k in ("t", "sens", "question", "issue", "prix", "montant", "pnl",
                                                         "url")}, "strategie": d["id"], "nom": d["nom"],
                                 "couleur": d["couleur"]} for t, d in recents],
            "classement": self.classement,
            "activite": {**self.stats, "requetes": api.COMPTEUR["requetes"], "erreurs_api": api.COMPTEUR["erreurs"]},
            "courbe": self.courbe, "journal": self.journal,
        }

    def sauver(self):
        (DATA / "state_arena.json").write_text(json.dumps(self.construire_etat(), ensure_ascii=False,
                                                          separators=(",", ":")))
        self.dirty = False

    def publier(self):
        self.sauver()
        if not PUBLIER:
            return
        tmp = Path(tempfile.mkdtemp(prefix="pub_arene_"))
        try:
            for f in DATA.iterdir():
                if f.is_file():
                    shutil.copy(f, tmp / f.name)
            cmds = [["git", "init", "-q"], ["git", "checkout", "-q", "-b", BRANCHE],
                    ["git", "config", "user.name", "paper-bot"],
                    ["git", "config", "user.email", "paper-bot@users.noreply.github.com"],
                    ["git", "add", "-A"], ["git", "commit", "-q", "-m", f"état arène {maintenant()}"],
                    ["git", "push", "-q", "-f", f"https://x-access-token:{TOKEN}@github.com/{DEPOT}.git", BRANCHE]]
            for cmd in cmds:
                subprocess.run(cmd, cwd=tmp, check=True, timeout=60, capture_output=True)
        except Exception as e:
            print("publication échouée :", type(e).__name__, flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- boucle ----------
    def etape(self, nom, fn):
        try:
            fn()
        except Exception as e:
            self.erreur("etape-" + nom, f"Étape « {nom} » en erreur (la boucle continue) : {type(e).__name__} : {e}")

    def run(self):
        debut = time.time()
        self.log(f"Démarrage de session de l'arène : {len(self.conc)} stratégies, valeur totale "
                 f"{sum(c['pf'].valeur() for c in self.conc.values()):.2f} $ fictifs.")
        derniers = {}
        taches = [("résolutions", C.RESOLUTION_S, self.verifier_resolutions),
                  ("prix", C.PRIX_S, self.tick_prix),
                  ("scan", C.SCAN_S, self.scanner),
                  ("mouvements", C.MOUVEMENT_S, self.scanner_mouvements),
                  ("classement", C.CLASSEMENT_S, self.suivre_classement)]
        if not self.courbe:
            self.point_courbe()
        while time.time() - debut < DUREE_MAX_S:
            t0 = time.time()
            for nom, periode, fn in taches:
                if t0 - derniers.get(nom, 0) >= periode:
                    derniers[nom] = t0
                    self.etape(nom, fn)
            if t0 - derniers.get("courbe", t0 - C.POINT_COURBE_S + 60) >= C.POINT_COURBE_S:
                derniers["courbe"] = t0
                self.point_courbe()
                self.dirty = True
            if self.dirty and t0 - derniers.get("publication", 0) >= 30 or \
                    t0 - derniers.get("publication", 0) >= C.PUBLI_S:
                derniers["publication"] = t0
                self.etape("publication", self.publier)
            time.sleep(max(0.0, C.TICK_S - (time.time() - t0)))
        self.log("Fin de session de l'arène (relais automatique par la session suivante).")
        self.point_courbe()
        self.etape("publication", self.publier)


if __name__ == "__main__":
    Arene().run()
