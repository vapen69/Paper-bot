"""Tests hors ligne de la recherche « somme des probabilités »."""
import json

import numpy as np

from polybot import research_somme as rs

SILENCE = lambda *_: None


def test_evenements_calibres_rien_n_est_valide(tmp_path):
    r = rs.analyser(rs.synthetique(nb=250, graine=11), {"source": "synthetique"}, journal=SILENCE)
    assert r["choix"]["valide"] is False and all(not s["eligible"] for s in r["strategies"])
    assert r["verdict"].startswith("DONNÉES FICTIVES")
    rs.ecrire(r, tmp_path)
    assert json.loads((tmp_path / "research_somme.json").read_text())["nb_evenements"] == 250
    md = (tmp_path / "research_somme.md").read_text()
    assert "Règle de sélection" in md and "—" not in md and "–" not in md


def test_une_vraie_surcote_est_detectee():
    r = rs.analyser(rs.synthetique(biais=0.25, graine=3), {"source": "synthetique"}, journal=SILENCE)
    assert r["choix"]["valide"] and r["choix"]["nom"] == "panier"
    assert not next(s for s in r["strategies"] if s["nom"] == "hasard")["eligible"]


def test_le_gagnant_ne_sert_qu_au_reglement():
    e = rs.synthetique(nb=1, graine=8, biais=0.2)[0]
    a = rs.simuler_evenement(e, "panier", 0.03)
    autre = dict(e, gagnant=(e["gagnant"] + 1) % len(e["jambes"]))
    b = rs.simuler_evenement(autre, "panier", 0.03)
    assert a and b and a[0]["t_in"] == b[0]["t_in"] and a[0]["cout"] == b[0]["cout"]


def test_prix_trop_ancien_pas_de_decision():
    e = rs.synthetique(nb=1, graine=2)[0]
    j = e["jambes"][0]
    e["jambes"][0] = dict(j, t=j["t"][::10], p=j["p"][::10])          # un point toutes les 10 h
    g, P = rs.panneau(e)
    assert np.isnan(P[:, 0]).any() and not np.isnan(P[:, 1]).any()


def test_panier_paie_n_moins_un():
    e = rs.synthetique(nb=1, graine=8, biais=0.2)[0]
    tr = rs.simuler_evenement(e, "panier", 0.03)[0]
    assert tr["revenu"] == len(e["jambes"]) - 1 and tr["somme"] >= 1.03


def test_panier_sur_vrais_carnets():
    def mk(i, p):
        return {"id": str(i), "question": f"q{i}", "outcomes": '["Yes","No"]', "clobTokenIds": f'["y{i}","n{i}"]',
                "outcomePrices": f'["{p}","{1 - p}"]', "closed": False, "active": True, "takerBaseFee": 0}
    brut = {"id": "e", "title": "t", "markets": [mk(0, 0.5), mk(1, 0.4), mk(2, 0.3)]}
    large = lambda prix: {"asks": [(prix, 100.0)], "bids": []}
    # somme affichée 1,2 mais les Non coûtent ce que le carnet demande : 0,6 + 0,7 + 0,8 = 2,1 > 2
    carnets = {"y0": large(0.52), "n0": large(0.6), "y1": large(0.42), "n1": large(0.7), "y2": large(0.32), "n2": large(0.8)}
    r = rs.evaluer_paniers(brut, carnets)
    assert r["somme_affichee"] == 1.2 and r["gain_panier_non"] < 0 and r["gain_panier_oui"] < 0
    carnets["n0"] = large(0.45)                                         # vrai arbitrage : 0,45 + 0,7 + 0,8 = 1,95
    assert rs.evaluer_paniers(brut, carnets)["gain_panier_non"] > 0
    assert rs.cout_carnet([(0.5, 4.0)]) is None                         # carnet trop mince
