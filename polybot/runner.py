"""Boucle principale du bot Polymarket (paper trading, argent fictif, aucun ordre réel).

Tourne en continu (~5 h 40 par session GitHub Actions, puis la session suivante reprend l'état) :
- toutes les 10 s : carnets des positions ouvertes (prix, valeur), sorties programmées, coupe-circuit
- toutes les 30 s : commandes envoyées depuis le téléphone (control_poly.json)
- toutes les 60 s : scan des marchés actifs, recherche d'entrées, flux des gros trades (expérimental)
- toutes les 2 min : résolution des marchés détenus (règlement à 1 ou 0)
- toutes les 60 s et après chaque trade : publication de l'état sur la branche data-poly
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import api, config, execution, strategies
from .portefeuille import Portefeuille

RACINE = Path(__file__).resolve().parent.parent
DATA = RACINE / "polybot_out"                  # contenu de la branche data-poly
CONTROLE = RACINE / "control_poly.json"
BRANCHE = "data-poly"
DUREE_MAX_S = int(os.environ.get("DUREE_MAX_S", 5 * 3600 + 40 * 60))
PUBLIER = os.environ.get("PUBLIER", "1") == "1"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

EXPERIMENTALE = "baleines"
NOMS = {"favori_echeance": "Favori proche de l'échéance", "longshot_fade": "Contre les outsiders",
        "suivi_mouvement": "Suivi des gros mouvements", "contre_mouvement": "Contre les gros mouvements",
        EXPERIMENTALE: "Suivi des baleines (expérimental)"}


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def court(texte, n=70):
    texte = str(texte)
    return texte if len(texte) <= n else texte[:n - 1] + "…"


class Bot:
    def __init__(self):
        DATA.mkdir(exist_ok=True)
        f = DATA / "state_poly.json"
        try:
            self.etat = json.loads(f.read_text()) if f.exists() else {}
        except Exception:
            self.etat = {}
        e = self.etat
        self.pf = Portefeuille(e)
        self.statut = e.get("statut", "actif")
        self.courbe = e.get("courbe", [])
        self.journal = e.get("journal", [])
        self.flux = (e.get("activite") or {}).get("flux", [])
        self.dernier_controle = e.get("dernier_controle_id")
        self.demarre_le = e.get("demarre_le") or maintenant()
        risque = e.get("risque") or {}
        self.jour = risque.get("jour")
        self.valeur_debut_jour = risque.get("valeur_debut_jour")
        self.gel_jour = bool(risque.get("gel_jour"))
        self.refroidissement = {k: v for k, v in (e.get("refroidissement") or {}).items() if v > time.time()}
        self.univers = {}             # id du marché -> marché (dernier scan)
        self.par_jeton = {}           # jeton -> (marché, indice de l'issue)
        self.carnets = {}             # jeton -> dernier carnet lu
        self.surveilles = []
        self.stats = {"marches_scannes": 0, "dans_filtres": 0, "candidats": 0, "signaux_session": 0,
                      "carnets_lus": 0, "dernier_scan": None, "avec_frais": 0}
        self.baleines_vues = set()
        self.baleines_echecs = 0
        self.baleines_prochain = 0.0
        self.baleines_etat = "en attente"
        self.erreurs_vues = {}
        self.ecartes_vus = {}
        self.dirty = True
        self.strat = None
        self.charger_strategie()

    # ---------- utilitaires ----------
    def log(self, msg):
        ligne = {"t": maintenant(), "msg": msg}
        print(ligne["t"], msg, flush=True)
        self.journal.append(ligne)
        self.journal = self.journal[-config.MAX_JOURNAL:]

    def erreur(self, cle, msg):
        """Journalise une erreur au plus une fois toutes les 10 minutes par sujet (la boucle ne s'arrête jamais)."""
        if time.time() - self.erreurs_vues.get(cle, 0) > 600:
            self.erreurs_vues[cle] = time.time()
            self.log(msg)

    def signaler(self, genre, texte, url=""):
        """Ajoute une ligne au flux d'activité du tableau de bord."""
        if genre == "scan" and self.flux and self.flux[-1].get("type") == "scan":
            self.flux.pop()
        self.flux.append({"t": maintenant(), "type": genre, "txt": texte, "url": url})
        self.flux = self.flux[-config.MAX_FLUX:]

    def valeur(self):
        return self.pf.valeur()

    def charger_strategie(self):
        """Stratégie retenue par la recherche si elle existe et qu'on sait l'exécuter, sinon la stratégie par défaut."""
        nom, params = config.STRATEGIE_DEFAUT, dict(config.PARAMS_DEFAUT[config.STRATEGIE_DEFAUT])
        validee, source = False, "défaut (recherche pas encore disponible)"
        try:
            r = json.loads((DATA / "research_poly.json").read_text())
            c = r.get("choix") or {}
            attendus = set(config.PARAMS_DEFAUT.get(c.get("nom"), {}))
            if r.get("source") == "polymarket" and attendus and set(c.get("parametres") or {}) == attendus:
                nom, params, validee = c["nom"], c["parametres"], bool(c.get("valide"))
                source = f"recherche du {str(r.get('genere_le', ''))[:10]}"
        except Exception:
            pass
        nouvelle = {"nom": nom, "parametres": params, "validee": validee, "source": source}
        if self.strat is not None and nouvelle != self.strat:
            self.log(f"Stratégie mise à jour : {NOMS.get(nom, nom)} ({'validée' if validee else 'non validée'}, {source})")
        self.strat = nouvelle

    def part_par_marche(self):
        return config.PART_PAR_MARCHE if self.strat["validee"] else config.PART_PAR_MARCHE_NON_VALIDEE

    # ---------- risque ----------
    def controle_risque(self):
        v = self.valeur()
        self.pf.plus_haut = max(self.pf.plus_haut, v)
        jour = maintenant()[:10]
        if jour != self.jour or self.valeur_debut_jour is None:
            if self.gel_jour:
                self.log("Nouvelle journée : les entrées sont de nouveau autorisées.")
            self.jour, self.valeur_debut_jour, self.gel_jour = jour, v, False
        if not self.gel_jour and v <= self.valeur_debut_jour * (1 - config.PERTE_JOUR_MAX):
            self.gel_jour = True
            self.dirty = True
            self.log(f"Limite de perte du jour atteinte (-{config.PERTE_JOUR_MAX * 100:.0f} %) : plus d'entrée avant demain (UTC).")
        if self.statut == "actif" and v <= self.pf.plus_haut * (1 - config.COUPE_CIRCUIT_DD):
            self.statut = "coupe-circuit"
            self.dirty = True
            self.log(f"COUPE-CIRCUIT : -{config.COUPE_CIRCUIT_DD * 100:.0f} % depuis le plus haut. Plus aucune entrée ; "
                     "les positions ouvertes vont jusqu'à leur résolution (commande « tout_vendre » pour sortir avant).")

    def peut_entrer(self):
        return self.statut == "actif" and not self.gel_jour

    def refus_risque(self, m, mise, strategie):
        """Raison pour laquelle le portefeuille refuse cette entrée, ou None."""
        v = self.valeur()
        pos = self.pf.positions.values()
        if any(p["marche_id"] == m["id"] for p in pos):
            return "déjà en position sur ce marché"
        if self.refroidissement.get(m["id"], 0) > time.time():
            return "marché quitté récemment"
        principales = sum(1 for p in pos if p["strategie"] != EXPERIMENTALE)
        if strategie != EXPERIMENTALE and principales >= config.POSITIONS_MAX:
            return "nombre maximal de positions atteint"
        if strategie == EXPERIMENTALE and \
                self.pf.engage(lambda p: p["strategie"] == EXPERIMENTALE) + mise > config.BALEINES_BUDGET * v:
            return "budget expérimental épuisé"
        if sum(1 for p in pos if p["evenement"] == m["evenement"]) >= config.POSITIONS_MAX_PAR_EVENEMENT:
            return "trop de positions sur le même événement"
        if self.pf.engage(lambda p: p["categorie"] == m["categorie"]) + mise > config.PART_MAX_CATEGORIE * v:
            return f"plafond de la catégorie {m['categorie']} atteint"
        return None

    def mise_possible(self, part):
        v = self.valeur()
        return min(part * v, self.pf.cash - config.RESERVE_CASH * v)

    # ---------- marché ----------
    def filtre_marche(self, m, jours_max=None):
        """Raison d'écarter un marché d'après les données du scan, ou None s'il est acceptable."""
        now = time.time()
        if m["ferme"] or not m["actif"] or not m["accepte_ordres"]:
            return "fermé"
        if m["echeance"] is None or m["echeance"] - now < config.HEURES_MIN_AVANT_ECHEANCE * 3600:
            return "échéance trop proche ou inconnue"
        if jours_max is not None and m["echeance"] - now > jours_max * 86400:
            return "échéance trop lointaine"
        if (m["liquidite"] or 0) < config.LIQUIDITE_MIN:
            return "liquidité insuffisante"
        if (m["volume24h"] or 0) < config.VOLUME24H_MIN:
            return "volume insuffisant"
        if m["spread"] is not None and m["spread"] > config.SPREAD_MAX + 1e-9:
            return f"écart achat/vente trop large ({m['spread'] * 100:.1f} c)"
        return None

    @staticmethod
    def prix_scan(m):
        """Prix de la première issue d'après le scan (milieu bid/ask si disponible)."""
        if m["bid"] is not None and m["ask"] is not None and 0 < m["bid"] <= m["ask"] < 1:
            return (m["bid"] + m["ask"]) / 2
        return m["prix"][0]

    def scanner(self):
        base = {"active": "true", "closed": "false", "order": "volume24hr", "ascending": "false"}
        lot = api.marches(base, pages=config.PAGES_SCAN)
        jours = self.strat["parametres"].get("jours_max")
        if jours:
            now = time.time()
            lot += api.marches({**base, "end_date_min": api.iso(now), "end_date_max": api.iso(now + jours * 86400)},
                               pages=config.PAGES_ECHEANCE)
        if not lot:
            self.erreur("scan", "Scan des marchés impossible (Gamma ne répond pas), nouvel essai dans une minute.")
            return
        self.univers = {m["id"]: m for m in lot}
        self.par_jeton = {j: (m, i) for m in self.univers.values() for i, j in enumerate(m["jetons"])}
        self.stats["marches_scannes"] = len(self.univers)
        self.stats["avec_frais"] = sum(1 for m in self.univers.values() if (m["frais_bps"] or 0) > 0)
        self.stats["dernier_scan"] = maintenant()
        self.chercher_entrees()

    def chercher_entrees(self):
        """Stratégies à fourchette de prix (favori, outsider) : candidats du scan, puis vérification sur le carnet."""
        nom, params = self.strat["nom"], self.strat["parametres"]
        candidats, dans_filtres, now = [], 0, time.time()
        if nom in ("favori_echeance", "longshot_fade"):
            for m in sorted(self.univers.values(), key=lambda x: -(x["volume24h"] or 0)):
                if self.filtre_marche(m, params.get("jours_max")):
                    continue
                dans_filtres += 1
                p0 = self.prix_scan(m)
                if p0 is None:
                    continue
                infos = {"id": m["id"], "oui_non": m["issues"][0].strip().lower() == "yes"}
                cote = strategies.signal_direct(nom, params, [now], [p0], m["echeance"], infos)
                if cote >= 0:
                    candidats.append((m, cote, p0 if cote == 0 else 1 - p0))
        else:
            dans_filtres = sum(1 for m in self.univers.values() if not self.filtre_marche(m))
        self.stats["dans_filtres"], self.stats["candidats"] = dans_filtres, len(candidats)
        self.surveilles, essais = [], 0
        for m, cote, prix in candidats:
            etat = "candidat"
            if any(p["marche_id"] == m["id"] for p in self.pf.positions.values()):
                etat = "en position"
            elif not self.peut_entrer():
                etat = "entrées suspendues"
            elif essais < config.CARNETS_PAR_SCAN:
                mise = self.mise_possible(self.part_par_marche())
                refus = "cash insuffisant (réserve)" if mise < config.ORDRE_MIN else self.refus_risque(m, mise, nom)
                if refus is None:
                    essais += 1
                    refus = self.tenter_entree(m, cote, nom, mise, params.get("prix_max"),
                                               f"{m['issues'][cote]} cotée {prix * 100:.0f} %, échéance dans "
                                               f"{(m['echeance'] - now) / 86400:.1f} j")
                etat = "en position" if refus is None else "écarté : " + refus
            if len(self.surveilles) < config.MAX_SURVEILLES:
                self.surveilles.append({"question": m["question"], "issue": m["issues"][cote], "prix": round(prix, 4),
                                        "spread": m["spread"], "echeance": api.iso(m["echeance"]),
                                        "volume24h": round(m["volume24h"] or 0), "etat": etat, "url": m["url"],
                                        "categorie": m["categorie"]})
        self.signaler("scan", f"{len(self.univers)} marchés scannés, {dans_filtres} dans les filtres, "
                              f"{len(candidats)} candidat(s) pour {NOMS.get(nom, nom)}")

    def tenter_entree(self, m, cote, strategie, mise, limite, raison, sortie_h=None):
        """Lit le carnet réel, vérifie le signal dessus, simule l'achat. Retourne None si acheté, sinon la raison."""
        jeton = m["jetons"][cote]
        try:
            carnet = api.carnet(jeton)
        except Exception:
            return "carnet indisponible"
        self.stats["carnets_lus"] += 1
        refus = None
        if not carnet["asks"] or not carnet["bids"]:
            refus = "carnet vide d'un côté"
        else:
            ask, bid = carnet["asks"][0][0], carnet["bids"][0][0]
            if ask - bid > config.SPREAD_MAX + 1e-9:
                refus = f"écart réel trop large ({(ask - bid) * 100:.1f} c)"
            elif ask > min(limite or 1.0, config.PRIX_ENTREE_MAX) + 1e-9:
                refus = f"prix vendeur trop haut ({ask:.3f})"
            elif strategie in ("favori_echeance", "longshot_fade"):
                # le signal doit rester vrai au prix réellement payable (le scan Gamma peut dater de quelques secondes)
                p0 = ask if cote == 0 else 1 - ask
                infos = {"id": m["id"], "oui_non": m["issues"][0].strip().lower() == "yes"}
                if strategies.signal_direct(strategie, self.strat["parametres"], [time.time()], [p0],
                                            m["echeance"], infos) != cote:
                    refus = f"prix réel hors de la fourchette ({ask:.3f})"
        if refus is None:
            # Polymarket impose un minimum de parts par ordre : on relève la mise si besoin, sans jamais la doubler
            ask = carnet["asks"][0][0]
            plancher = m["parts_min"] * (ask + execution.frais_taker(1.0, ask, m["frais_bps"])) * 1.03
            if plancher > mise:
                if plancher > 2 * mise or plancher > self.pf.cash - config.RESERVE_CASH * self.valeur():
                    refus = "mise trop petite pour le minimum de parts"
                else:
                    mise = plancher
        if refus is None:
            execu = execution.acheter_carnet(carnet["asks"], mise, min(limite or 1.0, config.PRIX_ENTREE_MAX),
                                             m["frais_bps"])
            if execu is None or execu["parts"] < m["parts_min"] or \
                    execu["cout"] + execu["frais"] < config.REMPLISSAGE_MIN * mise:
                refus = "carnet trop mince pour la mise"
        if refus is not None:
            if time.time() - self.ecartes_vus.get(m["id"], 0) > 1800:
                self.ecartes_vus[m["id"]] = time.time()
                self.signaler("ecarte", f"{court(m['question'])} : {refus}", m["url"])
            return refus
        t = maintenant()
        infos = {"marche_id": m["id"], "condition_id": m["condition_id"], "question": m["question"],
                 "issue": m["issues"][cote], "index": cote, "url": m["url"], "strategie": strategie,
                 "categorie": m["categorie"], "evenement": m["evenement"], "frais_bps": m["frais_bps"],
                 "echeance": api.iso(m["echeance"]) if m["echeance"] else None,
                 "sortie_le": time.time() + sortie_h * 3600 if sortie_h else None}
        if not self.pf.acheter(jeton, execu, infos, t, raison):
            return "cash insuffisant"
        self.pf.positions[jeton]["bid"] = carnet["bids"][0][0]
        self.carnets[jeton] = carnet
        self.stats["signaux_session"] += 1
        partiel = "" if execu["complet"] else " (exécution partielle, carnet mince)"
        self.log(f"ACHAT {execu['parts']:.1f} parts « {m['issues'][cote]} » à {execu['prix_moyen']:.3f} sur "
                 f"« {court(m['question'])} » : {raison}{partiel} [{NOMS.get(strategie, strategie)}]")
        self.signaler("achat", f"{m['issues'][cote]} à {execu['prix_moyen'] * 100:.1f} % · {court(m['question'])}", m["url"])
        self.dirty = True
        return None

    def scanner_mouvements(self):
        """Stratégies de mouvement : historique horaire des marchés les plus actifs, signal au dernier point."""
        nom, params = self.strat["nom"], self.strat["parametres"]
        if nom not in ("suivi_mouvement", "contre_mouvement") or not self.peut_entrer():
            return
        now, lus = time.time(), 0
        for m in sorted(self.univers.values(), key=lambda x: -(x["volume24h"] or 0)):
            if lus >= 30:
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
            infos = {"id": m["id"], "oui_non": m["issues"][0].strip().lower() == "yes"}
            cote = strategies.signal_direct(nom, params, [x[0] for x in pts], [x[1] for x in pts], m["echeance"], infos)
            if cote < 0:
                continue
            mise = self.mise_possible(self.part_par_marche())
            if mise < config.ORDRE_MIN or self.refus_risque(m, mise, nom):
                continue
            self.tenter_entree(m, cote, nom, mise, 0.95,
                               f"mouvement d'au moins {params['ecart'] * 100:.0f} points en {params['fenetre_h']} h",
                               sortie_h=params.get("sortie_h"))

    def suivre_baleines(self):
        """Expérimental : suivre les très gros achats récents. Optionnel, se met en veille si la Data API échoue."""
        if not config.BALEINES_ACTIF or time.time() < self.baleines_prochain:
            return
        trades, derniere = None, None
        for chemin in config.BALEINES_CHEMINS:
            try:
                trades = api.gros_trades(chemin, config.BALEINES_MONTANT_MIN)
                break
            except Exception as e:
                derniere = e
        if trades is None:
            self.baleines_echecs += 1
            if self.baleines_echecs >= config.BALEINES_ECHECS_MAX:
                self.baleines_prochain = time.time() + 3600
                if self.baleines_etat != "en veille":
                    self.log(f"Suivi des baleines en veille : la Data API ne répond pas ({derniere}). "
                             "Nouvel essai chaque heure, la stratégie principale n'est pas concernée.")
                self.baleines_etat = "en veille"
            return
        self.baleines_echecs, self.baleines_etat = 0, "actif"
        now = time.time()
        for x in sorted(trades, key=lambda x: x["t"]):
            if x["id"] in self.baleines_vues:
                continue
            self.baleines_vues.add(x["id"])
            if x["cote"] != "BUY" or now - x["t"] > config.BALEINES_AGE_MAX_S or x["jeton"] not in self.par_jeton:
                continue
            if not config.BALEINES_PRIX_MIN <= x["prix"] <= config.BALEINES_PRIX_MAX:
                continue
            m, cote = self.par_jeton[x["jeton"]]
            self.signaler("baleine", f"Gros achat de {x['montant']:,.0f} $ sur {m['issues'][cote]} à "
                                     f"{x['prix'] * 100:.0f} % · {court(m['question'])}".replace(",", " "), m["url"])
            if not self.peut_entrer() or self.filtre_marche(m):
                continue
            mise = self.mise_possible(config.BALEINES_PART)
            if mise < config.ORDRE_MIN or self.refus_risque(m, mise, EXPERIMENTALE):
                continue
            self.tenter_entree(m, cote, EXPERIMENTALE, mise, x["prix"] + config.BALEINES_ECART_PRIX_MAX,
                               f"gros achat de {x['montant']:.0f} $ à {x['prix']:.3f} il y a {(now - x['t']) / 60:.0f} min",
                               sortie_h=config.BALEINES_SORTIE_H)
        if len(self.baleines_vues) > 5000:
            self.baleines_vues = set(list(self.baleines_vues)[-2000:])

    # ---------- positions ----------
    def vendre_position(self, jeton, raison):
        """Vend au prix des acheteurs en descendant le carnet réel. Retourne True si tout est vendu."""
        p = self.pf.positions[jeton]
        try:
            carnet = api.carnet(jeton)
            self.carnets[jeton] = carnet
        except Exception:
            carnet = self.carnets.get(jeton) or {"bids": []}
        execu = execution.vendre_carnet(carnet["bids"], p["parts"], 0.0, p.get("frais_bps"))
        if execu is None:
            self.erreur("vente" + jeton, f"Vente impossible pour l'instant sur « {court(p['question'])} » : aucun acheteur dans le carnet.")
            return False
        question, issue, url, marche_id = p["question"], p["issue"], p.get("url", ""), p["marche_id"]
        pnl = self.pf.vendre(jeton, execu, maintenant(), raison)
        self.refroidissement[marche_id] = time.time() + 86400
        self.log(f"VENTE {execu['parts']:.1f} parts « {issue} » à {execu['prix_moyen']:.3f} sur « {court(question)} » : "
                 f"{raison} ({pnl:+.2f} $)" + ("" if execu["complet"] else " (partielle, carnet mince)"))
        self.signaler("vente", f"{issue} vendu à {execu['prix_moyen'] * 100:.1f} % ({pnl:+.2f} $) · {court(question)}", url)
        self.dirty = True
        return execu["complet"]

    def tick_prix(self):
        """Prix en direct des positions (carnet), sorties programmées, limites de risque."""
        for jeton in list(self.pf.positions):
            p = self.pf.positions[jeton]
            try:
                carnet = api.carnet(jeton)
            except Exception:
                continue        # marché fermé ou API en panne : on garde le dernier prix connu
            self.carnets[jeton] = carnet
            self.stats["carnets_lus"] += 1
            prix = execution.milieu(carnet)
            if prix is not None:
                p["dernier_prix"] = prix
            p["bid"] = carnet["bids"][0][0] if carnet["bids"] else None
            if p.get("sortie_le") and time.time() >= p["sortie_le"] and self.statut != "pause":
                self.vendre_position(jeton, f"sortie programmée ({NOMS.get(p['strategie'], p['strategie'])})")
        self.controle_risque()

    def verifier_resolutions(self):
        """Règle les positions dont le marché est résolu : chaque part paie 1 (issue réalisée) ou 0."""
        vus = {}
        for jeton in list(self.pf.positions):
            p = self.pf.positions[jeton]
            if p["marche_id"] not in vus:
                vus[p["marche_id"]] = api.marche(p["marche_id"])
            m = vus[p["marche_id"]]
            final = api.issue_finale(m)
            if final is None:
                if m and m["echeance"]:
                    p["echeance"] = api.iso(m["echeance"])
                continue
            prix_final = final[p["index"]]
            pnl = self.pf.regler(jeton, prix_final, maintenant(), "marché résolu : issue " +
                                 ("réalisée, 1 $ par part" if prix_final == 1 else
                                  "non réalisée, 0 $ par part" if prix_final == 0 else "partagée, 0,50 $ par part"))
            self.refroidissement[p["marche_id"]] = time.time() + 86400
            mot = "GAGNÉ" if prix_final == 1 else "PERDU" if prix_final == 0 else "PARTAGÉ"
            self.log(f"RÉSOLUTION {mot} « {p['issue']} » sur « {court(p['question'])} » ({pnl:+.2f} $)")
            self.signaler("reglement", f"{mot} {pnl:+.2f} $ · {p['issue']} · {court(p['question'])}", p.get("url", ""))
            self.dirty = True

    def tout_vendre(self, raison):
        for jeton in list(self.pf.positions):
            self.vendre_position(jeton, raison)

    # ---------- commandes ----------
    def lire_controle(self):
        if not PUBLIER:
            txt = CONTROLE.read_text() if CONTROLE.exists() else "{}"
        else:
            try:
                subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=RACINE, check=True, timeout=30)
                txt = subprocess.run(["git", "show", "origin/main:control_poly.json"], cwd=RACINE,
                                     capture_output=True, text=True, timeout=30).stdout or "{}"
            except Exception as e:
                self.erreur("controle", f"lecture des commandes impossible : {e}")
                return
        try:
            c = json.loads(txt)
        except json.JSONDecodeError:
            return
        if not isinstance(c, dict) or not c.get("id") or c["id"] == self.dernier_controle:
            return
        self.dernier_controle = c["id"]
        cmd = c.get("commande")
        if cmd == "pause":
            self.statut = "pause"
            self.log("Commande reçue : PAUSE (positions conservées jusqu'à leur résolution, aucune nouvelle entrée)")
        elif cmd == "reprendre":
            self.statut, self.gel_jour = "actif", False
            self.pf.plus_haut = self.valeur()
            self.valeur_debut_jour = self.valeur()
            self.log("Commande reçue : REPRISE")
        elif cmd == "tout_vendre":
            self.log("Commande reçue : TOUT VENDRE (au prix des acheteurs), bot mis en pause")
            self.tout_vendre("vente manuelle depuis le téléphone")
            self.statut = "pause"
        elif cmd == "reinitialiser":
            self.pf = Portefeuille()
            self.statut, self.courbe, self.flux, self.gel_jour = "actif", [], [], False
            self.refroidissement, self.valeur_debut_jour = {}, None
            self.demarre_le = maintenant()
            self.log(f"Commande reçue : REMISE À ZÉRO ({config.CAPITAL_DEPART:.0f} $ fictifs)")
        else:
            self.log(f"Commande inconnue ignorée : {cmd}")
        self.dirty = True

    # ---------- publication ----------
    def point_courbe(self):
        self.courbe.append({"t": maintenant(), "v": round(self.valeur(), 3)})
        self.courbe = self.courbe[-config.MAX_POINTS_COURBE:]

    def construire_etat(self):
        v = self.valeur()
        nom, params = self.strat["nom"], self.strat["parametres"]
        if nom in ("favori_echeance", "longshot_fade"):
            resume = (f"Achat de l'issue favorite cotée entre {params.get('prix_min', 1 - params.get('seuil_oui', 0)) * 100:.0f} % "
                      f"et {params['prix_max'] * 100:.0f} %, au plus {params['jours_max']} jour(s) avant l'échéance, "
                      "gardée jusqu'à la résolution (1 $ par part si elle se réalise, 0 sinon).")
        else:
            resume = (f"Mouvement d'au moins {params['ecart'] * 100:.0f} points en {params['fenetre_h']} h : "
                      + ("on suit" if nom == "suivi_mouvement" else "on parie sur le retour")
                      + (f", sortie après {params['sortie_h']} h." if params.get("sortie_h") else ", gardé jusqu'à la résolution."))
        expo = {}
        for p in self.pf.positions.values():
            expo[p["categorie"]] = round(expo.get(p["categorie"], 0.0) + p["cout"], 4)
        return {
            **self.pf.etat(),
            "maj": maintenant(), "demarre_le": self.demarre_le, "statut": self.statut,
            "capital_depart": config.CAPITAL_DEPART, "devise": config.DEVISE, "valeur": round(v, 4),
            "dernier_controle_id": self.dernier_controle,
            "strategie": {"id": nom, "nom": NOMS.get(nom, nom), "resume": resume, "validee": self.strat["validee"],
                          "source": self.strat["source"], "parametres": params,
                          "part_par_marche": self.part_par_marche()},
            "experimentale": {"id": EXPERIMENTALE, "nom": NOMS[EXPERIMENTALE], "etat": self.baleines_etat if config.BALEINES_ACTIF else "désactivée",
                              "budget": config.BALEINES_BUDGET, "part": config.BALEINES_PART},
            "parametres": {"positions_max": config.POSITIONS_MAX, "reserve_cash": config.RESERVE_CASH,
                           "spread_max": config.SPREAD_MAX, "liquidite_min": config.LIQUIDITE_MIN,
                           "coupe_circuit": config.COUPE_CIRCUIT_DD, "perte_jour_max": config.PERTE_JOUR_MAX,
                           "part_max_categorie": config.PART_MAX_CATEGORIE,
                           "frais_bps_si_absent": config.FRAIS_BPS_SI_ABSENT},
            "risque": {"jour": self.jour, "valeur_debut_jour": self.valeur_debut_jour, "gel_jour": self.gel_jour,
                       "exposition_categories": expo},
            "refroidissement": self.refroidissement,
            "activite": {**self.stats, "requetes": api.COMPTEUR["requetes"], "erreurs_api": api.COMPTEUR["erreurs"],
                         "flux": self.flux},
            "surveilles": self.surveilles,
            "courbe": self.courbe, "journal": self.journal,
        }

    def sauver(self):
        (DATA / "state_poly.json").write_text(json.dumps(self.construire_etat(), ensure_ascii=False, separators=(",", ":")))
        self.dirty = False

    def publier(self):
        self.sauver()
        if not PUBLIER:
            return
        # récupérer les résultats de recherche publiés entre-temps par le workflow « Recherche Polymarket »
        try:
            subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", BRANCHE], cwd=RACINE, check=True,
                           timeout=30, capture_output=True)
            for nom in ("research_poly.json", "research_poly.md"):
                r = subprocess.run(["git", "show", f"FETCH_HEAD:{nom}"], cwd=RACINE, capture_output=True, timeout=30)
                if r.returncode == 0 and r.stdout:
                    (DATA / nom).write_bytes(r.stdout)
            self.charger_strategie()
        except Exception:
            pass
        tmp = Path(tempfile.mkdtemp(prefix="pub_poly_"))
        try:
            for f in DATA.iterdir():
                if f.is_file():
                    shutil.copy(f, tmp / f.name)
            cmds = [["git", "init", "-q"], ["git", "checkout", "-q", "-b", BRANCHE],
                    ["git", "config", "user.name", "paper-bot"],
                    ["git", "config", "user.email", "paper-bot@users.noreply.github.com"],
                    ["git", "add", "-A"], ["git", "commit", "-q", "-m", f"état polymarket {maintenant()}"],
                    ["git", "push", "-q", "-f", f"https://x-access-token:{TOKEN}@github.com/{DEPOT}.git", BRANCHE]]
            for c in cmds:
                subprocess.run(c, cwd=tmp, check=True, timeout=60, capture_output=True)
        except Exception as e:
            print("publication échouée :", type(e).__name__, flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- boucle ----------
    def etape(self, nom, fn):
        """Exécute une étape sans jamais laisser une erreur arrêter la boucle."""
        try:
            fn()
        except Exception as e:
            self.erreur("etape-" + nom, f"Étape « {nom} » en erreur (la boucle continue) : {type(e).__name__} : {e}")

    def run(self):
        debut = time.time()
        self.log(f"Démarrage de session. Valeur : {self.valeur():.2f} $ fictifs, statut : {self.statut}, stratégie : "
                 f"{NOMS.get(self.strat['nom'], self.strat['nom'])} "
                 f"({'validée par la recherche' if self.strat['validee'] else 'NON validée, mode observation à mises réduites'})")
        derniers = {}
        taches = [("résolutions", config.RESOLUTION_S, self.verifier_resolutions),
                  ("commandes", config.CONTROLE_S, self.lire_controle),
                  ("scan", config.SCAN_S, self.scanner),
                  ("mouvements", config.MOUVEMENT_S, self.scanner_mouvements),
                  ("baleines", config.BALEINES_S, self.suivre_baleines)]
        while time.time() - debut < DUREE_MAX_S:
            t0 = time.time()
            self.etape("prix", self.tick_prix)
            for nom, periode, fn in taches:
                if t0 - derniers.get(nom, 0) >= periode:
                    derniers[nom] = t0
                    self.etape(nom, fn)
            if self.dirty or t0 - derniers.get("publication", 0) >= config.PUBLI_S:
                derniers["publication"] = t0
                self.point_courbe()
                self.etape("publication", self.publier)
            time.sleep(max(0.0, config.TICK_S - (time.time() - t0)))
        self.log("Fin de session (relais automatique par la session suivante).")
        self.point_courbe()
        self.etape("publication", self.publier)


if __name__ == "__main__":
    Bot().run()
