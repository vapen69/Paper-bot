"""Boucle principale du bot de paper trading.

Tourne en continu (~5 h 45 par session GitHub Actions, puis la session suivante reprend l'état) :
- toutes les 5 s : prix en direct, stops suiveurs, coupe-circuit
- toutes les 30 s : lecture des commandes envoyées depuis le téléphone (control.json)
- chaque jour juste après minuit UTC : bougies journalières, filtre BTC, sélection de la semaine, achats/ventes
- toutes les 2 min (et après chaque trade) : publication de l'état pour le tableau de bord
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import backtest, config, kraken, strategy
from .portfolio import Portefeuille

RACINE = Path(__file__).resolve().parent.parent
DATA = RACINE / "data_out"          # contenu de la branche "data" (state.json, backtest.json)
DUREE_MAX_S = int(os.environ.get("DUREE_MAX_S", 5 * 3600 + 45 * 60))
PUBLIER = os.environ.get("PUBLIER", "1") == "1"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

TICK_S, CONTROLE_S, PUBLI_S = 5, 30, 120


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Bot:
    def __init__(self):
        DATA.mkdir(exist_ok=True)
        f = DATA / "state.json"
        self.etat = json.loads(f.read_text()) if f.exists() else {}
        self.pf = Portefeuille(self.etat)
        self.statut = self.etat.get("statut", "actif")
        self.courbe = self.etat.get("courbe", [])
        self.journal = self.etat.get("journal", [])
        self.dernier_controle = self.etat.get("dernier_controle_id")
        self.demarre_le = self.etat.get("demarre_le") or maintenant()
        self.btc_depart = self.etat.get("btc_prix_depart")
        self.cles = {}            # symbole -> clé de paire Kraken
        self.univers = []
        self.rang = []
        self.marche_ok = None
        self.prix = {}
        self.heure_traitee = None
        self.cible = []
        self.prochain_rebal = None
        self.dirty = True

    # ---------- utilitaires ----------
    def log(self, msg):
        ligne = {"t": maintenant(), "msg": msg}
        print(ligne["t"], msg, flush=True)
        self.journal.append(ligne)
        self.journal = self.journal[-200:]

    def valeur(self):
        return self.pf.valeur(self.prix)

    # ---------- marché ----------
    def maj_univers(self):
        paires = kraken.paires_eur()
        self.cles = {}
        for k, p in paires.items():
            if p["symbole"] in config.UNIVERS and p["symbole"] not in self.cles:
                self.cles[p["symbole"]] = k
        self.univers = [s for s in config.UNIVERS if s in self.cles]
        manquants = set(config.UNIVERS) - set(self.univers)
        if manquants:
            self.log("paires EUR introuvables sur Kraken : " + ", ".join(sorted(manquants)))

    def charger_bougies(self):
        series = {}
        for s in self.univers:
            try:
                series[s] = kraken.bougies(self.cles[s], 1440)
            except Exception as e:
                self.log(f"bougies {s} indisponibles : {e}")
            self.tick_rapide()  # on continue de surveiller pendant le chargement
        return series

    def maj_prix(self):
        suivis = set(self.univers) | set(self.pf.positions) | {"BTC"}
        cles = [self.cles[s] for s in suivis if s in self.cles]
        tick = kraken.tickers(cles)
        inv = {v: k for k, v in self.cles.items()}
        for k, t in tick.items():
            s = inv.get(k)
            if s is None:  # Kraken renvoie parfois une clé différente
                s = next((sym for sym, cle in self.cles.items() if cle.endswith(k) or k.endswith(cle)), None)
            if s:
                self.prix[s] = t["prix"]

    # ---------- logique ----------
    def tick_rapide(self):
        """Stops et coupe-circuit sur les prix en direct."""
        try:
            self.maj_prix()
        except Exception as e:
            self.log(f"prix indisponibles : {e}")
            return
        if self.btc_depart is None and "BTC" in self.prix:
            self.btc_depart = self.prix["BTC"]
        avant = len(self.pf.trades)
        for s in self.pf.maj_prix_et_stops(self.prix, maintenant()):
            self.log(f"VENTE {s} : stop déclenché")
        v = self.valeur()
        self.pf.plus_haut = max(self.pf.plus_haut, v)
        if self.statut == "actif" and v <= self.pf.plus_haut * (1 - config.COUPE_CIRCUIT_DD):
            self.pf.tout_vendre(self.prix, maintenant(), "coupe-circuit : drawdown trop important")
            self.statut = "coupe-circuit"
            self.log(f"COUPE-CIRCUIT : -{config.COUPE_CIRCUIT_DD*100:.0f} % depuis le plus haut, tout est vendu, bot en pause")
        if len(self.pf.trades) != avant:
            self.dirty = True

    def decision_journaliere(self, series):
        clotures = {sym: [b[2] for b in bs] for sym, bs in series.items()}
        if "BTC" not in clotures:
            self.log("pas de données BTC, décision reportée")
            return
        self.marche_ok = strategy.marche_favorable(clotures["BTC"])
        self.rang = strategy.classement(clotures)
        # sélection en vigueur = celle du dernier jour de rebalancement (identique à la recherche)
        ts_btc = [b[0] for b in series["BTC"]]
        dernier_rebal = max((t for t in ts_btc if strategy.jour_de_rebalancement(t)), default=None)
        if dernier_rebal is None:
            return
        tronque = {sym: [b[2] for b in bs if b[0] <= dernier_rebal] for sym, bs in series.items()}
        self.cible = strategy.selection(strategy.classement(tronque))
        self.prochain_rebal = kraken_date(dernier_rebal + (config.REBAL_J + 1) * 86400)
        if self.statut != "actif":
            return
        vendre, acheter = strategy.decisions(list(self.pf.positions), self.cible, self.marche_ok)
        t = maintenant()
        for sym, raison in vendre.items():
            if sym in self.prix:
                self.pf.vendre(sym, self.prix[sym], t, raison)
                self.log(f"VENTE {sym} : {raison}")
        acheter = [(sym, r) for sym, r in acheter if sym in self.prix]
        places = config.NB_POSITIONS - len(self.pf.positions)
        for n, (sym, raison) in enumerate(acheter):
            if self.pf.acheter(sym, self.prix[sym], self.pf.cash / max(1, places - n), t, raison):
                self.log(f"ACHAT {sym} : {raison}")
        if not vendre and not acheter:
            if self.marche_ok:
                det = ", ".join(self.pf.positions) or "aucune"
                self.log(f"Analyse du jour : rien à changer (sélection de la semaine : {', '.join(self.cible) or 'aucune en hausse'} ; positions : {det}).")
            else:
                self.log("Analyse du jour : BTC sous sa moyenne 100 jours, le bot reste en cash.")
        self.dirty = True

    def lire_controle(self):
        if not PUBLIER:
            f = RACINE / "control.json"
            txt = f.read_text() if f.exists() else "{}"
        else:
            try:
                subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=RACINE, check=True, timeout=30)
                txt = subprocess.run(["git", "show", "origin/main:control.json"], cwd=RACINE,
                                     capture_output=True, text=True, timeout=30).stdout or "{}"
            except Exception as e:
                self.log(f"lecture des commandes impossible : {e}")
                return
        try:
            c = json.loads(txt)
        except json.JSONDecodeError:
            return
        if not c.get("id") or c["id"] == self.dernier_controle:
            return
        self.dernier_controle = c["id"]
        cmd = c.get("commande")
        t = maintenant()
        if cmd == "pause":
            self.statut = "pause"
            self.log("Commande reçue : PAUSE (positions conservées, stops actifs)")
        elif cmd == "reprendre":
            self.statut = "actif"
            self.pf.plus_haut = self.valeur()
            self.heure_traitee = None  # nouvelle analyse tout de suite
            self.log("Commande reçue : REPRISE")
        elif cmd == "tout_vendre":
            self.pf.tout_vendre(self.prix, t, "vente manuelle depuis le téléphone")
            self.statut = "pause"
            self.log("Commande reçue : TOUT VENDRE, bot mis en pause")
        elif cmd == "reinitialiser":
            self.pf = Portefeuille()
            self.statut, self.courbe, self.btc_depart = "actif", [], self.prix.get("BTC")
            self.demarre_le = t
            self.heure_traitee = None
            self.log(f"Commande reçue : REMISE À ZÉRO ({config.CAPITAL_DEPART_EUR:.0f} €)")
        self.dirty = True

    # ---------- publication ----------
    def point_courbe(self):
        if self.btc_depart and "BTC" in self.prix:
            self.courbe.append({"t": maintenant(), "v": round(self.valeur(), 3),
                                "btc": round(config.CAPITAL_DEPART_EUR * self.prix["BTC"] / self.btc_depart, 3)})
            self.courbe = self.courbe[-config.MAX_POINTS_COURBE:]

    def sauver(self):
        v = self.valeur()
        par_sym = {x["symbole"]: x for x in self.rang}
        etat = {
            **self.pf.etat(),
            "maj": maintenant(), "demarre_le": self.demarre_le, "statut": self.statut,
            "capital_depart": config.CAPITAL_DEPART_EUR, "valeur": round(v, 4),
            "btc_prix_depart": self.btc_depart, "marche_ok": self.marche_ok,
            "dernier_controle_id": self.dernier_controle,
            "paires": {s: kraken_ws(self.cles.get(s, ""), s) for s in set(self.univers) | set(self.pf.positions)},
            "prix": {s: self.prix[s] for s in set(self.univers) | set(self.pf.positions) if s in self.prix},
            "classement": [{**x, "perf": round(x["perf"] * 100, 2), "selection": x["symbole"] in self.cible} for x in self.rang[:15]],
            "selection_semaine": self.cible, "prochain_rebalancement": self.prochain_rebal,
            "strategie": {"nom": "Rotation momentum hebdomadaire",
                          "resume": f"Les {config.NB_POSITIONS} cryptos les plus fortes sur {config.LOOKBACK_J} jours parmi {len(config.UNIVERS)}, revues tous les {config.REBAL_J} jours, cash si le BTC passe sous sa moyenne {config.SMA_BTC_J} jours."},
            "parametres": {"positions": config.NB_POSITIONS, "stop": config.STOP_SUIVEUR,
                           "coupe_circuit": config.COUPE_CIRCUIT_DD, "frais": config.FRAIS,
                           "lookback_j": config.LOOKBACK_J},
            "courbe": self.courbe, "journal": self.journal,
        }
        for s, p in etat["positions"].items():
            p["rang"] = par_sym.get(s, {}).get("rang")
        (DATA / "state.json").write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")))
        self.dirty = False

    def publier(self):
        self.sauver()
        if not PUBLIER:
            return
        # récupérer les résultats de recherche publiés entre-temps par le workflow « Recherche »
        try:
            subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", "data"], cwd=RACINE, check=True,
                           timeout=30, capture_output=True)
            for nom in ("research.json", "research.md"):
                r = subprocess.run(["git", "show", f"FETCH_HEAD:{nom}"], cwd=RACINE, capture_output=True, timeout=30)
                if r.returncode == 0 and r.stdout:
                    (DATA / nom).write_bytes(r.stdout)
        except Exception:
            pass
        tmp = RACINE / "_pub"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(DATA, tmp, ignore=shutil.ignore_patterns(".git"))
        cmds = [["git", "init", "-q"], ["git", "checkout", "-q", "-b", "data"],
                ["git", "config", "user.name", "paper-bot"],
                ["git", "config", "user.email", "paper-bot@users.noreply.github.com"],
                ["git", "add", "-A"], ["git", "commit", "-q", "-m", f"état {maintenant()}"],
                ["git", "push", "-q", "-f", f"https://x-access-token:{TOKEN}@github.com/{DEPOT}.git", "data"]]
        try:
            for c in cmds:
                subprocess.run(c, cwd=tmp, check=True, timeout=60, capture_output=True)
        except Exception as e:
            print("publication échouée :", e, flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- boucle ----------
    def run(self):
        debut = time.time()
        self.log(f"Démarrage de session. Valeur actuelle : {self.pf.valeur(self.prix):.2f} € (statut : {self.statut})")
        self.maj_univers()
        self.tick_rapide()
        series = self.charger_bougies()
        self.faire_backtest(series)
        dernier_controle = dernier_publi = 0
        while time.time() - debut < DUREE_MAX_S:
            t0 = time.time()
            jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if jour != self.heure_traitee and datetime.now(timezone.utc).hour * 60 + datetime.now(timezone.utc).minute >= 2:
                try:
                    if self.heure_traitee is not None:
                        series = self.charger_bougies()
                    self.decision_journaliere(series)
                    self.heure_traitee = jour
                except Exception as e:
                    self.log(f"analyse du jour échouée, nouvel essai dans 1 min : {e}")
                    time.sleep(55)
            self.tick_rapide()
            if t0 - dernier_controle >= CONTROLE_S:
                self.lire_controle()
                dernier_controle = t0
            if self.dirty or t0 - dernier_publi >= PUBLI_S:
                self.point_courbe()
                self.publier()
                dernier_publi = t0
            time.sleep(max(0.0, TICK_S - (time.time() - t0)))
        self.log("Fin de session (relais automatique par la session suivante).")
        self.point_courbe()
        self.publier()

    def faire_backtest(self, series):
        f = DATA / "backtest.json"
        if f.exists():
            try:
                age = time.time() - f.stat().st_mtime
                ancien = json.loads(f.read_text()).get("genere_le", "")
                if ancien[:10] == maintenant()[:10] and age < 86400:
                    return
            except Exception:
                pass
        try:
            r = backtest.rapport(series)
            f.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            self.log("Backtest du jour : " + r["verdict"])
        except Exception as e:
            self.log(f"backtest impossible : {e}")


def kraken_date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def kraken_ws(cle, sym):
    """Nom de la paire pour le flux WebSocket v2 de Kraken (utilisé par le tableau de bord)."""
    return f"{sym}/EUR"


if __name__ == "__main__":
    Bot().run()
