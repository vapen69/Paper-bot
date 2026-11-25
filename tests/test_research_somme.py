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
