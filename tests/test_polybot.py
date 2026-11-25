"""Tests hors ligne du bot Polymarket : réponses d'API simulées (tests/fixtures_poly), aucune connexion."""
import json
import time
from pathlib import Path

import numpy as np
import pytest

from polybot import api, config, execution, research, runner, strategies
from polybot.portefeuille import Portefeuille

FIX = Path(__file__).parent / "fixtures_poly"


def fixture(nom, **remplacements):
    txt = (FIX / nom).read_text()
    for k, v in remplacements.items():
        txt = txt.replace(k, v)
    return json.loads(txt)


class Reponse:
    def __init__(self, data, code=200):
        self.data, self.status_code = data, code

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FauxPolymarket:
    """Simule Gamma, le CLOB et la Data API. Compte les appels et refuse toute méthode autre que GET."""

    def __init__(self, fin_dans_h=30, data_api=410):
        fin = api.iso(time.time() + fin_dans_h * 3600)
        self.marches = [m for m in fixture("gamma_marches_actifs.json", __FIN_PROCHE__=fin)]
        self.resolus = {}                 # id -> marché brut résolu
        self.book = fixture("clob_book.json")
        self.carnets = {}                 # jeton -> carnet brut particulier
        self.data_api = data_api
        self.appels = []
        self.panne = False

    def get(self, url, params=None, timeout=None):
        params = params or {}
        self.appels.append((url, dict(params)))
        if self.panne:
            raise ConnectionError("panne simulée")
        if url == config.GAMMA + "/markets":
            if params.get("offset", 0) > 0:
                return Reponse([])
            return Reponse([m for m in self.marches
                            if not (isinstance(m, dict) and str(m.get("id")) in self.resolus)])
        if url.startswith(config.GAMMA + "/markets/"):
            ident = url.rsplit("/", 1)[1]
            if ident in self.resolus:
                return Reponse(self.resolus[ident])
            for m in self.marches:
                if isinstance(m, dict) and str(m.get("id")) == ident:
                    return Reponse(m)
            return Reponse({"error": "not found"}, 404)
        if url == config.CLOB + "/book":
            return Reponse(self.carnets.get(params["token_id"], self.book))
        if url == config.CLOB + "/prices-history":
            return Reponse(fixture("clob_prices_history.json"))
        if url.startswith(config.DATA_API):
            if self.data_api != 200 or not url.endswith("/v2/trades"):
                return Reponse({"error": "Data API v1 has been retired"}, 410)
            return Reponse(fixture("data_trades.json", **{'"__RECENT__"': str(int(time.time()) - 60)}))
        return Reponse({"error": "inconnu"}, 404)


@pytest.fixture
def poly(monkeypatch, tmp_path):
    faux = FauxPolymarket()
    monkeypatch.setattr(api.SESSION, "get", faux.get)
    monkeypatch.setattr(api.SESSION, "post", lambda *a, **k: pytest.fail("aucun POST ne doit jamais partir"))
    monkeypatch.setattr(api, "_attendre_debit", lambda: None)
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "DATA", tmp_path / "out")
    monkeypatch.setattr(runner, "CONTROLE", tmp_path / "control_poly.json")
    monkeypatch.setattr(runner, "PUBLIER", False)
    return faux


# ---------- lecture des réponses ----------
def test_lecteurs_tolerants():
    assert api.liste('["Yes", "No"]') == ["Yes", "No"] and api.liste(["a"]) == ["a"]
    assert api.liste("pas du json") == [] and api.liste(None) == [] and api.liste('{"a":1}') == []
    assert api.nombre("0.25") == 0.25 and api.nombre(None, 3) == 3 and api.nombre("x") is None
    assert api.nombre(float("nan")) is None and api.nombre(True) is None
    assert api.horodatage("2026-11-20T12:00:00Z") == 1795176000
    assert api.horodatage("2026-11-20 12:00:00+00") == 1795176000
    assert api.horodatage("2026-11-20T12:00:00.123456Z") == 1795176000
    assert api.horodatage(1795176000000) == 1795176000 and api.horodatage("n'importe quoi") is None


def test_parse_marches_gamma():
    bruts = fixture("gamma_marches_actifs.json", __FIN_PROCHE__="2026-12-01T00:00:00Z")
    ms = [api.parse_marche(b) for b in bruts]
    ok = [m for m in ms if m]
    assert [m["id"] for m in ok] == ["501", "502", "503", "504", "505", "508"]   # 3 issues, abîmés : ignorés
    m = ok[0]
    assert m["issues"] == ["Yes", "No"] and m["prix"] == [0.93, 0.07] and len(m["jetons"]) == 2
    assert m["jetons"][0] == "50100000000000000000001" and m["frais_bps"] == 1000
    assert m["url"] == "https://polymarket.com/event/evenement-1" and m["evenement"] == "9001"
    assert m["categorie"] == "economie" and ok[1]["categorie"] == "sport" and ok[2]["categorie"] == "crypto"
    assert ok[1]["frais_bps"] == 0 and ok[5]["frais_bps"] is None
    assert ok[5]["liquidite"] == 25000.5 and ok[5]["volume24h"] == 70000 and ok[5]["prix"] == [0.9, 0.1]


def test_resolution_et_marche_annule():
    assert api.issue_finale(api.parse_marche(fixture("gamma_marche_resolu.json"))) == [1.0, 0.0]
    assert api.issue_finale(api.parse_marche(fixture("gamma_marche_annule.json"))) is None     # prix ["0","0"]
    actif = api.parse_marche(fixture("gamma_marches_actifs.json", __FIN_PROCHE__="2026-12-01T00:00:00Z")[0])
    assert api.issue_finale(actif) is None
    conteste = api.parse_marche(dict(fixture("gamma_marche_resolu.json"), umaResolutionStatus="disputed"))
    assert api.issue_finale(conteste) is None
    assert api.parse_marche(fixture("gamma_marche_resolu.json"))["ferme_le"] == pytest.approx(1795197791)


def test_carnet_trie_et_historique():
    c = api.parse_carnet(fixture("clob_book.json"))
    assert c["bids"][0] == (0.925, 60.0) and c["bids"][-1] == (0.9, 400.0)      # meilleur acheteur en premier
    assert c["asks"][0] == (0.935, 4.0) and c["asks"][-1] == (0.99, 1000.0)     # meilleur vendeur en premier
    assert api.parse_carnet(None) == {"bids": [], "asks": []}
    assert api.parse_carnet({"bids": [{"price": "x"}, ["0.4", "10"]], "asks": "?"}) == {"bids": [(0.4, 10.0)], "asks": []}
    h = api.parse_historique(fixture("clob_prices_history.json"))
    assert len(h) == 48 and h == sorted(h) and h[0] == (1795000000, 0.5)        # doublon et points invalides retirés
    assert api.parse_historique({}) == [] and api.parse_historique(None) == []


def test_http_reprises_et_erreur_definitive(poly):
    poly.panne = True
    assert api.marches({"active": "true"}) == [] and api.marche("501") is None   # jamais d'exception
    with pytest.raises(api.ErreurAPI):
        api.carnet("1")
    poly.panne = False
    n = len(poly.appels)
    with pytest.raises(api.ErreurAPI):
        api.gros_trades("/trades", 5000)
    assert len(poly.appels) == n + 1                                             # un 410 n'est pas réessayé


# ---------- exécutions sur le carnet ----------
def test_achat_remonte_le_carnet():
    asks = [(0.50, 10), (0.505, 20), (0.51, 100), (0.60, 1000)]
    e = execution.acheter_carnet(asks, 20.0)
    assert e["parts"] == pytest.approx(10 + 20 + (20 - 5 - 10.1) / 0.51) and e["complet"]
    assert e["cout"] == pytest.approx(20.0) and 0.50 < e["prix_moyen"] < 0.51
    partiel = execution.acheter_carnet(asks, 500.0)                              # 0,60 est au-delà du glissement toléré
    assert partiel["parts"] == pytest.approx(130) and not partiel["complet"]
    assert execution.acheter_carnet(asks, 20.0, prix_limite=0.50)["parts"] == pytest.approx(10)
    assert execution.acheter_carnet(asks, 20.0, prix_limite=0.49) is None
    assert execution.acheter_carnet([], 20.0) is None


def test_frais_taker_dans_le_budget():
    e = execution.acheter_carnet([(0.90, 1000)], 9.1, frais_bps=1000)
    assert e["frais"] == pytest.approx(e["parts"] * 0.1 * 0.10)                  # 10 % x min(0,9 ; 0,1) par part
    assert e["cout"] + e["frais"] == pytest.approx(9.1) and e["parts"] == pytest.approx(10)
    assert execution.frais_taker(10, 0.9, 0) == 0
    assert execution.frais_taker(10, 0.9, None) == pytest.approx(10 * 0.1 * config.FRAIS_BPS_SI_ABSENT / 10000)


def test_vente_descend_le_carnet():
    bids = [(0.92, 10), (0.90, 5), (0.50, 100)]
    v = execution.vendre_carnet(bids, 20)
    assert v["brut"] == pytest.approx(9.2 + 4.5 + 2.5) and v["complet"]
    p = execution.vendre_carnet(bids, 20, prix_min=0.9)
    assert p["parts"] == pytest.approx(15) and not p["complet"]
    assert execution.vendre_carnet([], 5) is None
    assert execution.milieu({"bids": [(0.4, 1)], "asks": [(0.42, 1)]}) == pytest.approx(0.41)
    assert execution.milieu({"bids": [(0.2, 1)], "asks": [(0.9, 1)]}) == 0.2     # écart énorme : valorisation au bid
    assert execution.milieu({"bids": [], "asks": [(0.9, 1)]}) is None


def _infos(**k):
    return {"marche_id": "1", "question": "Q ?", "issue": "Yes", "index": 0, "strategie": "favori_echeance",
            "categorie": "autre", "evenement": "e1", "url": "", **k}


def test_reglement_a_la_resolution():
    pf = Portefeuille()
    e = execution.acheter_carnet([(0.90, 100)], 9.0)
    assert pf.acheter("j1", e, _infos(), "t0", "test") and pf.cash == pytest.approx(91.0)
    assert not pf.acheter("j1", e, _infos(), "t0", "doublon")
    assert pf.regler("j1", 1.0, "t1", "gagné") == pytest.approx(1.0)
    assert pf.cash == pytest.approx(101.0) and not pf.positions and pf.trades[-1]["sens"] == "reglement"
    pf.acheter("j2", execution.acheter_carnet([(0.90, 100)], 9.0), _infos(marche_id="2"), "t2", "test")
    assert pf.regler("j2", 0.0, "t3", "perdu") == pytest.approx(-9.0)
    assert pf.cash == pytest.approx(92.0) and pf.valeur() == pytest.approx(92.0)
    s = pf.pnl_strategies["favori_echeance"]
    assert s["clotures"] == 2 and s["gagnants"] == 1 and s["entrees"] == 2 and s["pnl"] == pytest.approx(-8.0)


def test_vente_partielle_garde_le_reste():
    pf = Portefeuille()
    pf.acheter("j", execution.acheter_carnet([(0.50, 100)], 10.0), _infos(), "t0", "test")
    v = execution.vendre_carnet([(0.6, 5)], 20)
    assert pf.vendre("j", v, "t1", "partielle") == pytest.approx(5 * 0.6 - 2.5)
    assert pf.positions["j"]["parts"] == pytest.approx(15) and pf.positions["j"]["cout"] == pytest.approx(7.5)


# ---------- recherche ----------
def test_decisions_sans_regard_vers_le_futur():
    """La décision à l'indice i ne change pas si on efface tout ce qui suit i, pour toutes les stratégies."""
    marches = research.synthetique(nb=25, graine=3)
    for nom, strat in strategies.STRATEGIES.items():
        for params in strat["grille"]:
            for m in marches:
                infos = {"id": m["id"], "oui_non": m["oui_non"]}
                plein = strat["fn"](m["t"], m["p"], m["fin"], infos, **params)
                for i in (5, len(m["t"]) // 2, len(m["t"]) - 2):
                    coupe = strat["fn"](m["t"][:i + 1], m["p"][:i + 1], m["fin"], infos, **params)
                    assert np.array_equal(plein[:i + 1], coupe), (nom, params, m["id"], i)


def test_le_resultat_ne_sert_qu_au_reglement():
    marches = research.synthetique(nb=60, graine=5)
    for nom, strat in strategies.STRATEGIES.items():
        params = strat["grille"][0]
        a = research.tous_les_trades(marches, nom, params)
        inverses = [dict(m, issue0=1.0 - m["issue0"]) for m in marches]
        b = research.tous_les_trades(inverses, nom, params)
        cle = lambda x: (x["marche"], x["t_in"], x["cote"], x["cout"])
        assert [cle(x) for x in a] == [cle(x) for x in b]                        # mêmes entrées, mêmes prix payés
        if any(x["motif"] == "resolution" for x in a):
            assert [x["revenu"] for x in a] != [x["revenu"] for x in b]


def test_execution_au_point_suivant_et_couts():
    t = 1_750_000_000 + 3600.0 * np.arange(6)
    m = {"id": "m", "evenement": "e", "categorie": "autre", "oui_non": True, "fin": float(t[-1] + 7200),
         "cloture": float(t[-1] + 9000), "issue0": 1.0, "frais_bps": 1000.0,
         "t": t, "p": np.array([0.5, 0.5, 0.90, 0.92, 0.93, 0.93])}
    tr = research.simuler_marche(m, "favori_echeance", {"prix_min": 0.85, "prix_max": 0.97, "jours_max": 3})
    assert len(tr) == 1
    x = tr[0]
    assert x["t_in"] == t[3]                                                     # signal vu à t[2], exécuté à t[3]
    assert x["cout"] == pytest.approx(0.93 + 0.1 * 0.07)                         # 0,92 + 1 centime, puis frais
    assert x["revenu"] == 1.0 and x["motif"] == "resolution" and x["t_out"] == m["cloture"]
    perdu = research.simuler_marche(dict(m, issue0=0.0), "favori_echeance", {"prix_min": 0.85, "prix_max": 0.97, "jours_max": 3})
    assert perdu[0]["revenu"] == 0.0 and perdu[0]["rend"] == -1.0
    # signal seulement au dernier point : aucun point suivant, donc aucun trade
    m2 = dict(m, p=np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.9]))
    assert research.simuler_marche(m2, "favori_echeance", {"prix_min": 0.85, "prix_max": 0.97, "jours_max": 3}) == []
    assert research.demi_spread(0.95) == 0.01 and research.demi_spread(0.5) == 0.01


def test_marche_calibre_aucune_strategie_validee(tmp_path):
    r = research.analyser(research.synthetique(nb=250, graine=11), {"source": "synthetique"}, journal=lambda *_: None)
    assert r["choix"]["valide"] is False and r["choix"]["nom"] == config.STRATEGIE_DEFAUT
    assert all(not s["eligible"] and s["refus"] for s in r["strategies"])
    assert r["verdict"].startswith("DONNÉES FICTIVES")
    assert r["periode"]["debut"] < r["periode"]["coupure"] < r["periode"]["fin"]
    research.ecrire(r, tmp_path)
    relu = json.loads((tmp_path / "research_poly.json").read_text())
    assert {s["nom"] for s in relu["strategies"]} == set(strategies.STRATEGIES)
    md = (tmp_path / "research_poly.md").read_text()
    assert "Règle de sélection" in md and "\u2014" not in md and "\u2013" not in md
    for s in relu["strategies"]:
        assert {"nb_trades", "gagnants_pct", "avantage_cts", "rend_capital_temps_an_pct", "pire_serie_pertes",
                "t_stat"} <= set(s["oos"])
        assert {"rendement_pct", "drawdown_max_pct", "nb_trades"} <= set(s["portefeuille"])


def test_un_vrai_avantage_est_detecte():
    """Si les favoris sont nettement sous-cotés (biais injecté), la règle doit valider une stratégie de favoris."""
    r = research.analyser(research.synthetique(nb=900, graine=2, biais=0.9), {"source": "synthetique"},
                          journal=lambda *_: None)
    fav = next(s for s in r["strategies"] if s["nom"] == "favori_echeance")
    assert fav["oos"]["rend_moyen_pct"] > 0 and fav["oos"]["t_stat"] > research.T_MIN
    assert r["choix"]["valide"] and r["choix"]["nom"] in ("favori_echeance", "longshot_fade")
    ref = next(s for s in r["strategies"] if s["nom"] == "hasard")
    assert not ref["eligible"]


def test_coupure_temporelle_stricte():
    marches = research.synthetique(nb=120, graine=4)
    _, _, t_coupe = research.coupure(marches)
    params, essais = research.choisir_parametres(marches, "favori_echeance", t_coupe)
    assert params in strategies.STRATEGIES["favori_echeance"]["grille"] and len(essais) == 9
    # modifier le résultat des marchés réglés après la coupure ne change pas le choix des paramètres
    modifies = [dict(m, issue0=1.0 - m["issue0"]) if m["cloture"] >= t_coupe else m for m in marches]
    assert research.choisir_parametres(modifies, "favori_echeance", t_coupe)[0] == params


def test_portefeuille_simule_respecte_les_limites():
    marches = research.synthetique(nb=200, graine=9)
    par_id = {m["id"]: m for m in marches}
    tr = research.tous_les_trades(marches, "hasard", {"proba": 0.02})
    pf = research.portefeuille_simule(tr, par_id)
    assert pf["nb_trades"] + pf["ignores"] == len(tr) and pf["ignores"] > 0
    assert 0 <= pf["drawdown_max_pct"] <= 100 and pf["exposition_moyenne_pct"] <= 100 * (1 - config.RESERVE_CASH) + 1
    assert research.portefeuille_simule([], par_id)["nb_trades"] == 0


def test_construire_marche_de_recherche():
    m = api.parse_marche(fixture("gamma_marche_resolu.json"))
    pts = [(m["ferme_le"] - 3600 * (40 - i), 0.5 + 0.01 * i) for i in range(40)] + [(m["ferme_le"] + 50000, 1.0)]
    r = research._construire(m, pts)
    assert r["issue0"] == 1.0 and len(r["t"]) == 40 and r["oui_non"] and r["frais_bps"] == 1000
    assert research._construire(m, pts[:10]) is None                             # historique trop court
    assert research._construire(api.parse_marche(fixture("gamma_marche_annule.json")), pts) is None


# ---------- bot en direct ----------
ETAT_CLES = {"maj", "demarre_le", "statut", "capital_depart", "devise", "valeur", "cash", "positions", "trades",
             "frais_total", "plus_haut_portefeuille", "nb_trades", "pnl_strategies", "strategie", "experimentale",
             "parametres", "risque", "activite", "surveilles", "courbe", "journal", "dernier_controle_id"}
POSITION_CLES = {"marche_id", "question", "issue", "index", "url", "strategie", "categorie", "evenement", "echeance",
                 "parts", "prix_entree", "cout", "dernier_prix", "bid", "depuis"}


def test_scan_achete_le_favori_sur_le_carnet(poly):
    bot = runner.Bot()
    assert bot.strat["nom"] == "favori_echeance" and not bot.strat["validee"]
    bot.scanner()
    pos = list(bot.pf.positions.values())
    # 501 : favori à 0,93 -> acheté. 502 : Celtics à 0,89 et 508 : même événement, même carnet simulé -> achetés.
    # 503 : 50/50, 504 : écart trop large, 505 : liquidité trop faible -> ignorés.
    assert {p["marche_id"] for p in pos} == {"501", "502", "508"}
    p = next(x for x in pos if x["marche_id"] == "501")
    assert POSITION_CLES <= set(p) and p["issue"] == "Yes" and p["index"] == 0
    mise = config.PART_PAR_MARCHE_NON_VALIDEE * config.CAPITAL_DEPART
    assert p["parts"] >= 5 and p["cout"] <= 2 * mise and 0.935 < p["prix_entree"] < 0.94   # 4 parts à 0,935 puis 0,94
    assert bot.pf.frais_total > 0 and bot.pf.cash < config.CAPITAL_DEPART
    assert bot.stats["marches_scannes"] == 6 and bot.stats["candidats"] >= 2
    assert any(f["type"] == "scan" for f in bot.flux) and any(f["type"] == "achat" for f in bot.flux)
    # second scan : pas de doublon
    n = bot.pf.nb_trades
    bot.scanner()
    assert bot.pf.nb_trades == n


def test_carnet_mince_ou_ecart_large_pas_d_achat(poly):
    poly.book = {"bids": [{"price": "0.80", "size": "100"}], "asks": [{"price": "0.94", "size": "100"}]}
    bot = runner.Bot()
    bot.scanner()
    assert not bot.pf.positions and any("écart réel trop large" in s["etat"] for s in bot.surveilles)
    poly.book = {"bids": [{"price": "0.93", "size": "100"}], "asks": [{"price": "0.94", "size": "1"}]}
    bot.ecartes_vus = {}
    bot.scanner()
    assert not bot.pf.positions and any("carnet trop mince" in s["etat"] for s in bot.surveilles)


def test_resolution_regle_la_position(poly):
    bot = runner.Bot()
    bot.scanner()
    jeton = next(j for j, p in bot.pf.positions.items() if p["marche_id"] == "501")
    parts, cout = bot.pf.positions[jeton]["parts"], bot.pf.positions[jeton]["cout"]
    bot.verifier_resolutions()
    assert jeton in bot.pf.positions                                             # pas encore résolu
    poly.resolus["501"] = fixture("gamma_marche_resolu.json")
    cash = bot.pf.cash
    bot.verifier_resolutions()
    assert jeton not in bot.pf.positions and bot.pf.cash == pytest.approx(cash + parts)
    t = bot.pf.trades[-1]
    assert t["sens"] == "reglement" and t["pnl"] == pytest.approx(parts - cout, abs=1e-3) and t["frais"] == 0
    bot.scanner()                                                                # marché quitté : pas de retour immédiat
    assert not any(p["marche_id"] == "501" for p in bot.pf.positions.values())


def test_resolution_perdante(poly):
    bot = runner.Bot()
    bot.scanner()
    jeton = next(j for j, p in bot.pf.positions.items() if p["marche_id"] == "501")
    poly.resolus["501"] = dict(fixture("gamma_marche_resolu.json"), outcomePrices='["0", "1"]')
    bot.verifier_resolutions()
    assert jeton not in bot.pf.positions and bot.pf.trades[-1]["pnl_pct"] == -100


def test_coupe_circuit_et_limite_du_jour(poly):
    bot = runner.Bot()
    bot.controle_risque()
    assert bot.peut_entrer()
    bot.pf.cash = config.CAPITAL_DEPART * (1 - config.PERTE_JOUR_MAX) - 0.01
    bot.controle_risque()
    assert bot.gel_jour and bot.statut == "actif" and not bot.peut_entrer()
    bot.scanner()
    assert not bot.pf.positions                                                  # plus aucune entrée
    bot.pf.cash = config.CAPITAL_DEPART * (1 - config.COUPE_CIRCUIT_DD) - 0.01
    bot.controle_risque()
    assert bot.statut == "coupe-circuit"
    bot.scanner()
    assert not bot.pf.positions
    bot.jour = "2000-01-01"                                                      # nouvelle journée : le gel du jour saute,
    bot.controle_risque()                                                        # pas le coupe-circuit
    assert not bot.gel_jour and bot.statut == "coupe-circuit" and not bot.peut_entrer()


def test_plafonds_evenement_et_categorie(poly, monkeypatch):
    bot = runner.Bot()
    m = api.parse_marche(poly.marches[0])
    assert bot.refus_risque(m, 4.0, "favori_echeance") is None
    for i in range(config.POSITIONS_MAX_PAR_EVENEMENT):
        bot.pf.positions[f"x{i}"] = dict(_infos(marche_id=f"a{i}", evenement=m["evenement"]), parts=1, cout=1, dernier_prix=1)
    assert "même événement" in bot.refus_risque(m, 4.0, "favori_echeance")
    bot.pf.positions = {"y": dict(_infos(marche_id="b", categorie=m["categorie"]), parts=34, cout=34, dernier_prix=1)}
    bot.pf.cash = 66
    assert "catégorie" in bot.refus_risque(m, 4.0, "favori_echeance")
    bot.pf.positions = {"z": dict(_infos(marche_id="c", strategie="baleines"), parts=11, cout=11, dernier_prix=1)}
    bot.pf.cash = 89
    assert "budget expérimental" in bot.refus_risque(m, 2.0, "baleines")
    assert bot.refus_risque(m, 2.0, "favori_echeance") is None


def test_commandes(poly):
    bot = runner.Bot()
    bot.scanner()
    assert bot.pf.positions
    ecrire = lambda cmd, ident: runner.CONTROLE.write_text(json.dumps({"commande": cmd, "id": ident}))
    ecrire("pause", "1")
    bot.lire_controle()
    assert bot.statut == "pause" and bot.pf.positions
    n = len(bot.journal)
    bot.lire_controle()                                                          # même id : ignorée
    assert len(bot.journal) == n
    ecrire("reprendre", "2")
    bot.lire_controle()
    assert bot.statut == "actif"
    ecrire("tout_vendre", "3")
    bot.lire_controle()
    assert bot.statut == "pause" and not bot.pf.positions
    ventes = [t for t in bot.pf.trades if t["sens"] == "vente"]
    assert ventes and all(t["prix"] <= 0.925 for t in ventes) and all(t["pnl"] < 0 for t in ventes)   # vendu au bid
    ecrire("reinitialiser", "4")
    bot.lire_controle()
    assert bot.statut == "actif" and bot.pf.cash == config.CAPITAL_DEPART and not bot.pf.trades
    runner.CONTROLE.write_text("{pas du json")
    bot.lire_controle()
    ecrire("n_importe_quoi", "5")
    bot.lire_controle()
    assert bot.statut == "actif" and bot.dernier_controle == "5"


def test_baleines_en_veille_si_data_api_retiree(poly):
    bot = runner.Bot()
    bot.scanner()
    n = bot.pf.nb_trades
    for _ in range(config.BALEINES_ECHECS_MAX + 2):
        bot.suivre_baleines()
    assert bot.baleines_etat == "en veille" and bot.pf.nb_trades == n
    appels = [u for u, _ in poly.appels if u.startswith(config.DATA_API)]
    assert len(appels) == 2 * config.BALEINES_ECHECS_MAX                         # /v2/trades puis /trades, puis silence


def test_baleines_suivies_avec_petit_budget(poly):
    poly.data_api = 200
    poly.carnets["50300000000000000000001"] = {"bids": [{"price": "0.495", "size": "500"}],
                                               "asks": [{"price": "0.505", "size": "500"}]}
    bot = runner.Bot()
    bot.scanner()
    bot.suivre_baleines()
    exp = [p for p in bot.pf.positions.values() if p["strategie"] == "baleines"]
    assert len(exp) == 1 and exp[0]["marche_id"] == "503" and exp[0]["sortie_le"] > time.time()
    assert exp[0]["cout"] <= 2 * config.BALEINES_PART * config.CAPITAL_DEPART            # mise relevée au minimum de parts, jamais doublée
    bot.suivre_baleines()                                                        # trade déjà vu : pas de second achat
    assert len([p for p in bot.pf.positions.values() if p["strategie"] == "baleines"]) == 1
    jeton = next(j for j, p in bot.pf.positions.items() if p["strategie"] == "baleines")
    bot.pf.positions[jeton]["sortie_le"] = time.time() - 1                       # sortie programmée échue
    bot.tick_prix()
    assert jeton not in bot.pf.positions and bot.pf.trades[-1]["sens"] == "vente"


def test_strategie_issue_de_la_recherche(poly):
    runner.DATA.mkdir(parents=True)
    choix = {"nom": "longshot_fade", "parametres": {"seuil_oui": 0.15, "prix_max": 0.97, "jours_max": 14}, "valide": True}
    (runner.DATA / "research_poly.json").write_text(json.dumps({"source": "polymarket", "genere_le": "2026-11-25T00:00Z", "choix": choix}))
    bot = runner.Bot()
    assert bot.strat["nom"] == "longshot_fade" and bot.strat["validee"]
    assert bot.part_par_marche() == config.PART_PAR_MARCHE
    bot.scanner()
    # seul un marché Oui/Non avec un Oui outsider convient : aucun ici (502 n'est pas Oui/Non)
    assert not bot.pf.positions
    # une recherche sur données fictives ou un choix inconnu ne pilote jamais le bot
    for mauvais in ({"source": "synthetique", "choix": choix}, {"source": "polymarket", "choix": {"nom": "hasard", "parametres": {"proba": 1}, "valide": True}},
                    {"source": "polymarket", "choix": {"nom": "favori_echeance", "parametres": {"prix_min": 0.5}, "valide": True}}):
        (runner.DATA / "research_poly.json").write_text(json.dumps(mauvais))
        b = runner.Bot()
        assert b.strat["nom"] == config.STRATEGIE_DEFAUT and not b.strat["validee"]


def test_boucle_complete_et_schema_de_l_etat(poly, monkeypatch):
    monkeypatch.setattr(runner, "DUREE_MAX_S", 2)
    monkeypatch.setattr(config, "TICK_S", 0.3)
    bot = runner.Bot()
    bot.run()
    etat = json.loads((runner.DATA / "state_poly.json").read_text())
    assert ETAT_CLES <= set(etat)
    assert etat["statut"] == "actif" and etat["devise"] == "USDC" and etat["capital_depart"] == 100
    assert etat["positions"] and all(POSITION_CLES <= set(p) for p in etat["positions"].values())
    assert all(j.isdigit() for j in etat["positions"])                           # clé = jeton, utilisable sur le CLOB
    assert etat["valeur"] == pytest.approx(etat["cash"] + sum(p["parts"] * p["dernier_prix"] for p in etat["positions"].values()), abs=1e-3)
    assert etat["trades"] and {"t", "sens", "question", "issue", "prix", "parts", "montant", "frais", "raison", "strategie", "url"} <= set(etat["trades"][0])
    assert len(etat["courbe"]) >= 2 and {"t", "v"} == set(etat["courbe"][0])
    assert {"marches_scannes", "dans_filtres", "candidats", "carnets_lus", "flux", "requetes"} <= set(etat["activite"])
    assert {"id", "nom", "resume", "validee", "parametres"} <= set(etat["strategie"])
    assert etat["surveilles"] and {"question", "issue", "prix", "etat", "url", "echeance"} <= set(etat["surveilles"][0])
    assert all(u.startswith(("https://gamma-api.polymarket.com", "https://clob.polymarket.com", "https://data-api.polymarket.com")) for u, _ in poly.appels)
    # reprise : une nouvelle session retrouve le portefeuille
    bot2 = runner.Bot()
    assert bot2.pf.cash == pytest.approx(bot.pf.cash) and set(bot2.pf.positions) == set(bot.pf.positions)
    assert bot2.pf.nb_trades == bot.pf.nb_trades


def test_la_boucle_survit_a_une_panne_totale(poly, monkeypatch):
    monkeypatch.setattr(runner, "DUREE_MAX_S", 1)
    monkeypatch.setattr(config, "TICK_S", 0.2)
    bot = runner.Bot()
    bot.scanner()
    poly.panne = True
    v = bot.valeur()
    bot.run()                                                                    # aucune exception
    assert bot.valeur() == pytest.approx(v) and (runner.DATA / "state_poly.json").exists()


def test_aucun_code_d_ordre_reel():
    """Garde-fou : le paquet ne contient ni signature, ni clé privée, ni envoi d'ordre."""
    interdits = ["private_key", "privatekey", "eth_account", "web3", "py_clob_client", "/order", "sign(", ".post(", "wallet"]
    for f in (Path(runner.__file__).parent).glob("*.py"):
        txt = f.read_text().lower()
        for mot in interdits:
            assert mot not in txt, (f.name, mot)
