"""Tests de l'arène : portefeuilles séparés, simulation sur le carnet, résolution, classement, état publié."""
import json
import time

import pytest

from arene import config as C
from arene import runner
from polybot import api
from polybot import config as pconf


def marche(i=1, prix0=0.92, jours=2.0, oui_non=True, **kw):
    now = time.time()
    m = {"id": str(i), "condition_id": "0x" + str(i), "question": f"Question {i} ?", "slug": f"q{i}",
         "evenement": f"e{i}", "url": f"https://polymarket.com/event/q{i}",
         "issues": ["Yes", "No"] if oui_non else ["A", "B"], "jetons": [f"{i}a", f"{i}b"],
         "prix": [prix0, 1 - prix0], "bid": prix0 - 0.005, "ask": prix0 + 0.005, "spread": 0.01,
         "volume24h": 50000.0, "volume": 1e6, "liquidite": 20000.0, "debut": now - 86400 * 30,
         "echeance": now + jours * 86400, "ferme_le": None, "actif": True, "ferme": False, "accepte_ordres": True,
         "uma": "", "neg_risk": False, "frais_bps": 0.0, "parts_min": 5.0, "categorie": "autre"}
    m.update(kw)
    return m


def carnet_autour(p):
    return {"bids": [(round(p - 0.005, 3), 5000.0)], "asks": [(round(p + 0.005, 3), 5000.0)]}


@pytest.fixture
def arene(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "DATA", tmp_path / "out")
    monkeypatch.setattr(runner, "PUBLIER", False)
    monkeypatch.setattr(api, "_attendre_debit", lambda: None)
    monkeypatch.setattr(api.SESSION, "get", lambda *a, **k: pytest.fail("aucun appel réseau dans les tests"))
    monkeypatch.setattr(api.SESSION, "post", lambda *a, **k: pytest.fail("aucun POST ne doit jamais partir"))
    return runner.Arene()


def test_chaque_strategie_a_son_capital(arene):
    assert len(arene.conc) == len(C.CONCURRENTS) >= 10
    assert all(abs(c["pf"].valeur() - C.CAPITAL_DEPART) < 1e-9 for c in arene.conc.values())
    assert len({d["couleur"] for d in C.CONCURRENTS}) == len(C.CONCURRENTS)
    assert sum(1 for d in C.CONCURRENTS if d.get("reference")) == 1


def test_arene_ne_touche_pas_au_bot_en_direct():
    assert runner.BRANCHE == "data-arena" and runner.DATA.name == "arene_out"
    assert pconf.STRATEGIE_FORCEE == "contre_mouvement"


def test_scan_achete_seulement_dans_les_bons_portefeuilles(arene, monkeypatch):
    favori = marche(1, prix0=0.92, jours=2)
    monkeypatch.setattr(api, "marches", lambda params, pages=1, par_page=100: [favori])
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.92 if j == "1a" else 0.08))
    arene.scanner()
    avec = {k for k, c in arene.conc.items() if c["pf"].positions}
    assert {"favori_3j", "favori_7j"} <= avec
    assert "favori_modere" not in avec and "contre_mvt_15_3h" not in avec and "achat_outsider" not in avec
    c = arene.conc["favori_3j"]
    assert c["pf"].cash < C.CAPITAL_DEPART and abs(c["pf"].valeur() - C.CAPITAL_DEPART) < 0.5
    assert arene.conc["contre_mvt_15_3h"]["pf"].cash == C.CAPITAL_DEPART
    # second scan : pas de doublon sur le même marché
    arene.scanner()
    assert len(arene.conc["favori_3j"]["pf"].positions) == 1


def test_outsider_et_contre_outsider(arene, monkeypatch):
    m = marche(2, prix0=0.08, jours=10)
    monkeypatch.setattr(api, "marches", lambda params, pages=1, par_page=100: [m])
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.08 if j == "2a" else 0.92))
    arene.scanner()
    assert "2a" in arene.conc["achat_outsider"]["pf"].positions          # achète le Oui
    assert "2b" in arene.conc["contre_outsider_10"]["pf"].positions      # achète le Non
    assert not arene.conc["contre_outsider_05"]["pf"].positions          # 8 % > seuil de 5 %


def test_carnet_trop_large_aucun_achat(arene, monkeypatch):
    m = marche(3, prix0=0.92)
    monkeypatch.setattr(api, "marches", lambda params, pages=1, par_page=100: [m])
    monkeypatch.setattr(api, "carnet", lambda j: {"bids": [(0.85, 100.0)], "asks": [(0.93, 100.0)]})
    arene.scanner()
    assert all(not c["pf"].positions for c in arene.conc.values())


def test_mouvement_et_resolution_dans_tous_les_portefeuilles(arene, monkeypatch):
    m = marche(4, prix0=0.40, jours=20)
    arene.univers = {m["id"]: m}
    now = time.time()
    pts = [(now - 3600 * k, 0.60) for k in range(12, 1, -1)] + [(now - 3600 * k, 0.40) for k in (1, 0)]
    monkeypatch.setattr(api, "historique", lambda j, **k: pts)
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.40 if j == "4a" else 0.60))
    arene.scanner_mouvements()
    contre = arene.conc["contre_mvt_15_3h"]["pf"].positions
    suivi = arene.conc["suivi_mvt_10_6h"]["pf"].positions
    assert "4a" in contre and "4b" in suivi
    assert arene.conc["contre_mvt_15_3h_24h"]["pf"].positions["4a"]["sortie_le"] is not None
    # résolution : le Oui gagne
    resolu = {**m, "ferme": True, "prix": [1.0, 0.0]}
    monkeypatch.setattr(api, "marche", lambda i: resolu)
    for c in arene.conc.values():
        for p in c["pf"].positions.values():
            p["echeance"] = api.iso(now - 60)
    arene.verifier_resolutions()
    assert all(not c["pf"].positions for c in arene.conc.values())
    gagnant, perdant = arene.conc["contre_mvt_15_3h"], arene.conc["suivi_mvt_10_6h"]
    assert gagnant["pf"].valeur() > C.CAPITAL_DEPART > perdant["pf"].valeur()
    assert gagnant["rendements"][0] > 0 > perdant["rendements"][0]
    r = arene.resume(gagnant)
    assert r["reglees"] == 1 and r["gagnants"] == 1 and r["pnl_regle"] > 0


def test_sortie_programmee(arene, monkeypatch):
    m = marche(5, prix0=0.40, jours=20)
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.40))
    c = arene.conc["contre_mvt_15_3h_24h"]
    assert arene.tenter(c, m, 0, "test", limite=0.95, sortie_h=24) is None
    c["pf"].positions["5a"]["sortie_le"] = time.time() - 1
    arene.tick_prix()
    assert not c["pf"].positions and len(c["rendements"]) == 1
    assert c["refroidissement"].get("5", 0) > time.time()


def test_classement_lecture_tolerante():
    w1, w2 = "0x" + "a" * 40, "0x" + "B" * 40
    l1 = runner.parse_classement([{"proxyWallet": w1, "userName": "alice", "pnl": "1200.5"},
                                  {"proxyWallet": "pas-une-adresse", "pnl": 99999},
                                  {"proxyWallet": w2, "pnl": 5000}])
    assert [x["wallet"] for x in l1] == [w2.lower(), w1] and l1[1]["nom"] == "alice"
    l2 = runner.parse_classement({"data": [{"address": w1, "amount": 10, "name": "bob"}]})
    assert l2 == [{"wallet": w1, "nom": "bob", "pnl": 10.0}]
    assert runner.parse_classement("n'importe quoi") == []


def test_classement_en_veille_si_illisible(arene, monkeypatch):
    def refus(url, params=None, essais=None, delai=15):
        raise api.ErreurAPI("HTTP 410 définitif")
    monkeypatch.setattr(api, "_get", refus)
    for _ in range(C.CLASSEMENT_ECHECS_MAX):
        arene.classement_prochain = 0
        arene.suivre_classement()
    assert arene.classement["etat"] == "en veille" and arene.classement_prochain > time.time() + 3000


def test_classement_copie_un_achat_recent(arene, monkeypatch):
    m = marche(6, prix0=0.55, jours=10)
    arene.univers, arene.par_jeton = {m["id"]: m}, {"6a": (m, 0), "6b": (m, 1)}
    w = "0x" + "c" * 40

    def faux_get(url, params=None, essais=None, delai=15):
        if "leaderboard" in url:
            return [{"proxyWallet": w, "userName": "pro", "pnl": 80000}]
        return [{"asset": "6b", "side": "BUY", "price": 0.45, "size": 2000, "timestamp": int(time.time()) - 120,
                 "transactionHash": "0x1"},
                {"asset": "6a", "side": "SELL", "price": 0.55, "size": 2000, "timestamp": int(time.time()) - 60,
                 "transactionHash": "0x2"}]
    monkeypatch.setattr(api, "_get", faux_get)
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.45 if j == "6b" else 0.55))
    arene.suivre_classement()
    pos = arene.conc["classement"]["pf"].positions
    assert list(pos) == ["6b"] and arene.classement["etat"] == "actif" and arene.classement["copies"] == 1
    assert arene.classement["suivis"][0]["wallet"].startswith("0xcccc")


def test_etat_publie_puis_relu(arene, monkeypatch):
    m = marche(7, prix0=0.92, jours=2)
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.92))
    assert arene.tenter(arene.conc["favori_3j"], m, 0, "test", limite=0.97) is None
    arene.point_courbe()
    arene.sauver()
    e = json.loads((runner.DATA / "state_arena.json").read_text())
    assert "règle de recherche" in e["avertissement"]
    assert len(e["concurrents"]) == len(C.CONCURRENTS) and e["courbe"][-1]["v"]["favori_3j"] > 0
    assert e["derniers_trades"][0]["strategie"] == "favori_3j"
    relu = runner.Arene()
    assert "7a" in relu.conc["favori_3j"]["pf"].positions
    assert abs(relu.conc["favori_3j"]["pf"].cash - arene.conc["favori_3j"]["pf"].cash) < 1e-9


def test_courbe_eclaircie(arene, monkeypatch):
    monkeypatch.setattr(C, "MAX_POINTS_COURBE", 10)
    for _ in range(11):
        arene.point_courbe()
    assert len(arene.courbe) <= 10


def test_t_stat():
    assert runner.t_stat([0.1, 0.2]) is None
    assert runner.t_stat([0.1, 0.12, 0.09, 0.11, 0.1]) > 5


def test_aucune_strategie_n_affame_les_suivantes(arene, monkeypatch):
    # beaucoup de favoris : les premières stratégies ne doivent pas consommer toutes les lectures de carnet
    lot = [marche(100 + i, prix0=0.92, jours=2) for i in range(30)] + [marche(200, prix0=0.08, jours=10)]
    monkeypatch.setattr(api, "marches", lambda params, pages=1, par_page=100: lot)
    monkeypatch.setattr(api, "carnet", lambda j: carnet_autour(0.92 if j.endswith("a") and not j.startswith("200") else
                                                               0.08 if j == "200a" else 0.92 if j == "200b" else 0.08))
    arene.scanner()
    assert "200a" in arene.conc["achat_outsider"]["pf"].positions
    assert "200b" in arene.conc["contre_outsider_10"]["pf"].positions
