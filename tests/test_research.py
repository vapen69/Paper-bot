"""Tests hors ligne du module de recherche (données synthétiques, aucune connexion)."""
import json

import numpy as np
import pandas as pd
import pytest

from research import data, run_research, walkforward as wf
from research.strategies import STRATEGIES

COUT = 0.005


@pytest.fixture(scope="module")
def marche():
    return data.synthetique(annees=2.5, graine=3)


def _plat(prix_ouv, prix_clo):
    idx = pd.date_range("2024-01-01", periods=len(prix_clo), freq="h", tz="UTC")
    return pd.DataFrame({"BTC": prix_ouv}, index=idx, dtype=float), pd.DataFrame({"BTC": prix_clo}, index=idx, dtype=float)


# ---------- pas de regard vers le futur ----------
@pytest.mark.parametrize("strat", STRATEGIES, ids=lambda s: s["nom"])
def test_strategie_sans_regard_vers_le_futur(strat, marche):
    """Modifier les prix après l'heure k ne doit changer aucun poids jusqu'à k incluse."""
    _, clo, _ = marche
    rng = np.random.default_rng(1)
    for params in wf.combinaisons(strat["grille"])[:3]:
        base = strat["fonction"](clo, **params)
        assert base.shape == clo.shape and base.abs().sum(axis=1).max() <= 1 + 1e-9      # exposition brute <= 100 %
        assert (base.to_numpy() >= 0).all() or "short" in strat["nom"]
        assert base.abs().to_numpy().sum() > 0, "la stratégie ne prend jamais position : test sans valeur"
        for k in (len(clo) // 2, len(clo) - 500):
            futur = clo.copy()
            futur.iloc[k + 1:] *= rng.uniform(0.3, 3.0, size=futur.iloc[k + 1:].shape)
            modifie = strat["fonction"](futur, **params)
            pd.testing.assert_frame_equal(base.iloc[: k + 1], modifie.iloc[: k + 1])


def test_moteur_sans_regard_vers_le_futur(marche):
    ouv, clo, _ = marche
    poids = STRATEGIES[2]["fonction"](clo)
    k = len(clo) // 2
    o2, c2 = ouv.copy(), clo.copy()
    o2.iloc[k + 1:] *= 2.0
    c2.iloc[k + 1:] *= 0.5
    a, _ = wf.simuler(ouv, clo, poids)
    b, _ = wf.simuler(o2, c2, poids)
    pd.testing.assert_frame_equal(a.iloc[: k + 1], b.iloc[: k + 1])


def test_execution_a_l_ouverture_suivante():
    """Signal à la clôture de l'heure 4. Le saut de prix entre cette clôture et l'ouverture suivante
    ne doit PAS être encaissé : on achète à l'ouverture de l'heure 5, déjà plus chère."""
    clo = [100.0] * 5 + [110.0] * 5
    ouv = [100.0] * 5 + [110.0] * 5
    o, c = _plat(ouv, clo)
    w = pd.DataFrame({"BTC": [0.0] * 4 + [1.0] * 6}, index=c.index)
    df, _ = wf.simuler(o, c, w, cout=0.0)
    assert (1 + df["rend"]).prod() == pytest.approx(1.0)
    # si le signal existait une heure plus tôt, l'achat se fait à 100 et le saut est encaissé
    w2 = pd.DataFrame({"BTC": [0.0] * 3 + [1.0] * 7}, index=c.index)
    df2, _ = wf.simuler(o, c, w2, cout=0.0)
    assert (1 + df2["rend"]).prod() == pytest.approx(1.10)


# ---------- frais ----------
def test_frais_aller_retour():
    o, c = _plat([100.0] * 20, [100.0] * 20)
    w = pd.DataFrame({"BTC": [0.0] * 5 + [1.0] * 5 + [0.0] * 10}, index=c.index)
    df, reels = wf.simuler(o, c, w, cout=COUT)
    final = (1 + df["rend"]).prod()
    assert final == pytest.approx((1 - COUT) / (1 + COUT), rel=1e-9)      # un achat puis une vente, prix inchangé
    assert (df["turnover"] > 0).sum() == 2                                # exactement deux ordres
    assert df["turnover"].iloc[6] == pytest.approx(1 / (1 + COUT)) and df["rend"].iloc[6] == pytest.approx(-COUT / (1 + COUT))
    assert df["frais"].sum() == pytest.approx(COUT / (1 + COUT) + COUT)   # en fraction du capital du moment
    assert reels[7, 0] == pytest.approx(1.0) and reels[15, 0] == 0.0
    m = wf.metriques(df)
    assert m["frais_eur_pour_100"] == pytest.approx(100 * (1 - final), abs=0.01)
    assert m["temps_investi_pct"] == pytest.approx(25.0)


def test_pas_d_ordre_si_la_cible_ne_change_pas():
    """Deux actifs à 50/50 dont les prix divergent : aucun rééquilibrage gratuit ni payant tant que la cible est stable."""
    idx = pd.date_range("2024-01-01", periods=50, freq="h", tz="UTC")
    c = pd.DataFrame({"BTC": np.linspace(100, 200, 50), "ETH": 100.0}, index=idx)
    df, reels = wf.simuler(c.shift(1).bfill(), c, pd.DataFrame(0.5, index=idx, columns=c.columns), cout=COUT)
    assert (df["turnover"] > 0).sum() == 1
    assert reels[-1, 0] > 0.6                                             # la position a dérivé avec le prix


def test_frais_proportionnels_au_changement_de_poids():
    o, c = _plat([100.0] * 12, [100.0] * 12)
    w = pd.DataFrame({"BTC": [0.0] * 3 + [0.5] * 4 + [0.8] * 5}, index=c.index)
    df, _ = wf.simuler(o, c, w, cout=COUT)
    tours = df["turnover"][df["turnover"] > 0].to_numpy()
    assert tours == pytest.approx([0.5, 0.3], rel=0.01)
    assert df["frais"].sum() == pytest.approx(COUT * 0.8, rel=0.01)


# ---------- vente à découvert ----------
def _short(prix, w=-1.0, **k):
    o, c = _plat(prix, prix)
    return wf.simuler(o, c, pd.DataFrame({"BTC": [0.0] * 2 + [w] * (len(prix) - 2)}, index=c.index), **k)


def test_short_a_prix_constant_ne_gagne_rien_et_paie_le_financement():
    n, f = 50, 0.0001
    df, reels = _short([100.0] * n, cout=COUT, financement_8h=f)
    x = 1 / (1 + COUT)                                   # taille du short après frais d'entrée
    heures = n - 3                                       # ouvert à l'heure 3, détenu jusqu'à la fin
    assert (1 + df["rend"]).prod() == pytest.approx(x * (1 - heures * f / 8), rel=1e-9)
    assert (df["financement"] > 0).sum() == heures and (df["turnover"] > 0).sum() == 1
    assert reels[-1, 0] < -0.99 and wf.metriques(df)["temps_short_pct"] == pytest.approx(100 * heures / n)
    sans, _ = _short([100.0] * n, cout=0.0, financement_8h=0.0)
    assert (1 + sans["rend"]).prod() == pytest.approx(1.0)
    # un long au comptant ne paie jamais de financement
    lng, _ = _short([100.0] * n, w=1.0, cout=COUT, financement_8h=f)
    assert lng["financement"].sum() == 0.0 and lng["short"].sum() == 0.0


def test_short_gagne_si_baisse_et_perd_sans_plafond_si_hausse():
    baisse, _ = _short([100.0] * 5 + [80.0] * 5, cout=0.0, financement_8h=0.0)
    assert (1 + baisse["rend"]).prod() == pytest.approx(1.20)            # -20 % sur le prix = +20 % de capital
    hausse, _ = _short([100.0] * 5 + [150.0] * 5, cout=0.0, financement_8h=0.0)
    assert (1 + hausse["rend"]).prod() == pytest.approx(0.50)
    ruine, _ = _short([100.0] * 5 + [250.0] * 5, cout=0.0, financement_8h=0.0)
    assert (1 + ruine["rend"]).prod() == pytest.approx(0.0)             # prix x 2,5 : tout le capital y passe
    assert wf.metriques(ruine)["drawdown_max_pct"] == 100.0
    demi, _ = _short([100.0] * 5 + [150.0] * 5, w=-0.5, cout=0.0, financement_8h=0.0)
    assert (1 + demi["rend"]).prod() == pytest.approx(0.75)


def test_exposition_brute_limitee_a_100_pct():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    c = pd.DataFrame({"BTC": 100.0, "ETH": 100.0}, index=idx)
    w = pd.DataFrame({"BTC": 1.0, "ETH": -1.0}, index=idx)               # 200 % demandé
    df, reels = wf.simuler(c, c, w, cout=0.0, financement_8h=0.0)
    assert df["expo"].max() == pytest.approx(1.0) and reels[-1] == pytest.approx([0.5, -0.5])


def test_pires_hausses_en_short():
    idx = pd.date_range("2024-01-01", periods=60, freq="h", tz="UTC")
    prix = np.full(60, 100.0)
    prix[10] = 130.0                                     # +30 % pendant qu'on est long : ne compte pas
    prix[11:] = 100.0
    prix[40:] = 108.0                                    # +8 % pendant le short
    c = pd.DataFrame({"BTC": prix}, index=idx)
    w = pd.DataFrame({"BTC": [0.5] * 20 + [-0.5] * 40}, index=idx)
    r = wf.pires_hausses_short(c, w)
    assert r["pire_hausse_horaire_short_pct"] == pytest.approx(8.0) and r["pire_hausse_journaliere_short_pct"] == pytest.approx(8.0)
    assert wf.pires_hausses_short(c, w.abs())["pire_hausse_horaire_short_pct"] is None


def test_strategies_short_sens_du_signal(marche):
    _, clo, _ = marche
    par_nom = {s["nom"]: s["fonction"] for s in STRATEGIES}
    lg, ls, sh = (par_nom[n](clo, sma_j=50)[["BTC", "ETH"]] for n in run_research.COMPARAISON_SHORT)
    assert (sh <= 0).all().all() and (sh < 0).any().any() and set(np.unique(ls)) == {-0.5, 0.0, 0.5}
    np.testing.assert_allclose(ls.to_numpy(), np.where(sh < 0, -0.5, lg.to_numpy()))   # long/short = long seul + short seul
    assert not ((lg > 0) & (sh < 0)).any().any()


# ---------- marche avant ----------
def test_fenetres_sans_chevauchement():
    f = wf.fenetres(30000, debut=1000, train=8760, test=2184)
    assert f[0] == (1000, 9760, 11944)
    for (a, b, c), suivant in zip(f, f[1:] + [None]):
        assert a < b < c and b - a == 8760
        if suivant:
            assert suivant[1] == c                                        # le test suivant commence où finit celui-ci
    assert f[-1][2] == 30000


@pytest.mark.parametrize("strat", STRATEGIES[:7], ids=lambda s: s["nom"])
def test_marche_avant_n_utilise_pas_les_donnees_de_test(strat, marche):
    """On saccage tous les prix à partir du début du 2e test : le choix de paramètres des deux premiers
    segments et les rendements du premier test doivent rester identiques."""
    ouv, clo, _ = marche
    base = wf.marche_avant(ouv, clo, strat)
    f = wf.fenetres(len(clo))
    assert len(f) >= 3
    coupe = f[1][1]                                                       # fin du 2e apprentissage = début du 2e test
    rng = np.random.default_rng(5)
    o2, c2 = ouv.copy(), clo.copy()
    bruit = np.exp(np.cumsum(rng.standard_normal(c2.iloc[coupe:].shape) * 0.02, axis=0))
    o2.iloc[coupe:] *= bruit
    c2.iloc[coupe:] *= bruit
    modifie = wf.marche_avant(o2, c2, strat)
    assert [s["parametres"] for s in base["segments"][:2]] == [s["parametres"] for s in modifie["segments"][:2]]
    n1 = f[0][2] - f[0][1]
    pd.testing.assert_frame_equal(base["oos"].iloc[:n1], modifie["oos"].iloc[:n1])
    # la période hors échantillon commence après le premier apprentissage, sans doublon
    assert base["oos"].index[0] == clo.index[f[0][1]] and base["oos"].index.is_unique
    assert len(base["oos"]) == len(clo) - f[0][1]


def test_choix_des_parametres_sur_l_apprentissage_uniquement():
    """Stratégie espionne : le paramètre 'bon' gagne pendant l'apprentissage puis perd pendant le test.
    La marche avant doit quand même choisir 'bon' (elle ne voit pas le test) et encaisser la perte."""
    n = 200 * 24
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    moitie = 100 * 24
    r = np.where(np.arange(n) < moitie, 0.0005, -0.0005)
    c = pd.DataFrame({"BTC": 100 * np.cumprod(1 + r)}, index=idx)
    o = c.shift(1).bfill()
    espion = {"nom": "espion", "grille": {"mode": ["cash", "investi"]},
              "fonction": lambda clo, mode: pd.DataFrame({"BTC": 1.0 if mode == "investi" else 0.0}, index=clo.index)}
    res = wf.marche_avant(o, c, espion, train=moitie, test=50 * 24, debut=0)
    assert res["segments"][0]["parametres"] == {"mode": "investi"}
    assert (1 + res["oos"]["rend"].iloc[: 50 * 24]).prod() < 0.6


def test_btc_hold_et_metriques(marche):
    ouv, clo, _ = marche
    idx = clo.index[5000:]
    df = wf.btc_hold(ouv, clo, idx)
    attendu = clo["BTC"].iloc[-1] / clo["BTC"].iloc[4999] * (1 - COUT) - 1
    m = wf.metriques(df)
    assert m["rendement_total_pct"] == pytest.approx(attendu * 100, abs=0.05)
    assert m["temps_investi_pct"] == 100.0 and 0 <= m["drawdown_max_pct"] <= 100
    r = df["rend"].to_numpy()
    assert m["sharpe"] == pytest.approx(r.mean() / r.std() * np.sqrt(24 * 365), abs=1e-3)


def test_sharpe_suspect_et_seuil_du_hasard():
    idx = pd.date_range("2024-01-01", periods=5000, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"rend": 0.0005 + rng.standard_normal(5000) * 0.001, "turnover": 0.0, "frais": 0.0, "financement": 0.0,
                       "expo": 1.0, "short": 0.0}, index=idx)
    assert wf.metriques(df)["sharpe_suspect"] is True
    assert wf.sharpe_du_hasard(30, 4) > wf.sharpe_du_hasard(5, 4) > 0
    assert wf.proba_sharpe_superieur(df["rend"], df["rend"] - 0.0005, tirages=50) > 0.95


# ---------- règle de sélection ----------
def _s(nom, sharpe, cagr, dd, investi=50.0, suspect=False):
    return {"nom": nom, "oos": {"sharpe": sharpe, "cagr_pct": cagr, "drawdown_max_pct": dd, "calmar": cagr / dd,
                                "temps_investi_pct": investi, "sharpe_suspect": suspect}}


def test_regle_de_selection():
    btc = {"sharpe": 1.0}
    # meilleur Calmar parmi celles qui battent le BTC en Sharpe ; les suspectes et les perdantes sont écartées
    nom, _, bat = run_research.choisir([_s("a", 1.2, 20, 40), _s("b", 1.1, 30, 30), _s("c", 0.9, 90, 10),
                                        _s("d", 3.5, 99, 5, suspect=True)], btc)
    assert (nom, bat) == ("b", True)
    # aucune éligible : la plus faible baisse parmi les gagnantes assez investies
    nom, _, bat = run_research.choisir([_s("a", 0.5, 10, 40), _s("b", 0.6, 5, 20), _s("c", 0.1, 1, 2, investi=3.0),
                                        _s("d", -0.2, -5, 10)], btc)
    assert (nom, bat) == ("b", False)
    # rien de gagnant : choix par défaut
    nom, _, bat = run_research.choisir([_s("a", -0.5, -10, 40)], btc)
    assert (nom, bat) == (run_research.DEFAUT, False)


# ---------- données : pagination Coinbase simulée ----------
def _faux_coinbase(monkeypatch, tmp_path, cotation=0):
    appels = []

    def faux(produit, debut, fin, essais=6):
        appels.append((produit, debut, fin))
        assert (fin - debut) // 3600 + 1 <= data.PAR_REQUETE
        if produit == "SOL-EUR":
            return None                                                   # produit inexistant
        k = 1.1 if produit.endswith("USD") else 1.0
        ts = [t for t in range(fin, debut - 1, -3600) if t >= cotation and (t // 3600) % 50 != 7]   # trous réalistes
        return [(t, k * (100 + t % 977), 0.0, 0.0, k * (101 + t % 977), 1.0) for t in ts]

    monkeypatch.setattr(data, "_requete", faux)
    monkeypatch.setattr(data, "CACHE", tmp_path)
    monkeypatch.setattr(data, "PAUSE_S", 0.0)
    return appels


def test_telechargement_pagine_et_cache(monkeypatch, tmp_path):
    appels = _faux_coinbase(monkeypatch, tmp_path)
    debut, fin = 1_700_000_000 // 3600 * 3600, 1_700_000_000 // 3600 * 3600 + 999 * 3600
    df = data.telecharger("BTC-USD", debut, fin)
    assert len(appels) == 4 and df["t"].is_monotonic_increasing and df["t"].is_unique
    assert df["t"].min() == debut and df["t"].max() == fin and len(df) == 1000 - 20
    appels.clear()
    df2 = data.telecharger("BTC-USD", debut, fin + 10 * 3600)             # seul le morceau manquant est demandé
    assert len(appels) == 1 and appels[0][1] == fin + 3600 and len(df2) == len(df) + 10
    assert data.telecharger("SOL-EUR", debut, fin) is None


def test_panneau_converti_en_eur(monkeypatch, tmp_path):
    _faux_coinbase(monkeypatch, tmp_path)
    ouv, clo, infos = data.panneau(annees=0.1, journal=lambda m: None)
    assert infos["devise"] == "EUR" and list(clo.columns) == data.UNIVERS
    assert len(clo) == int(0.1 * 365 * 24) + 1 and not clo.isna().any().any() and not ouv.isna().any().any()
    # les paires USD (prix x 1,1) reviennent au prix EUR une fois converties
    t = clo.index[100]
    assert clo["XRP"].loc[t] == pytest.approx(101 + (t.value // 10 ** 9) % 977, rel=1e-9)
    assert clo["BTC"].loc[t] == pytest.approx(clo["XRP"].loc[t])


# ---------- bout en bout ----------
def test_bout_en_bout_synthetique(tmp_path):
    r = run_research.main(["--synthetic", "--annees", "2.5", "--sortie", str(tmp_path)])
    j = json.loads((tmp_path / "research.json").read_text(encoding="utf-8"))
    for cle in ("genere_le", "periode", "strategies", "btc_hold", "choix", "verdict"):
        assert cle in j
    assert j["source"] == "synthetique" and len(j["strategies"]) == len(STRATEGIES)
    noms = [s["nom"] for s in j["strategies"]]
    assert j["choix"]["nom"] in noms and set(j["classement"]) == set(noms)
    for s in j["strategies"] + [j["btc_hold"]]:
        assert {"t", "v"} <= set(s["courbe"][0]) and len(s["courbe"]) == len(j["btc_hold"]["courbe"])
        assert {"rendement_total_pct", "cagr_pct", "drawdown_max_pct", "sharpe", "sortino", "calmar", "turnover_annuel",
                "frais_eur_pour_100", "temps_investi_pct", "financement_eur_pour_100", "temps_short_pct"} <= set(s["oos"])
    assert j["nb_combos_total"] == sum(len(wf.combinaisons(s["grille"])) for s in STRATEGIES)
    md = (tmp_path / "research.md").read_text(encoding="utf-8")
    assert "DONNÉES FICTIVES" in md and r["choix"]["nom"] in md and "## Apport du short" in md
    assert j["apport_short"]["conclusion"] in md and j["couts"]["financement_short_8h"] == wf.FUNDING_SHORT_8H
    short = next(s for s in j["strategies"] if s["nom"] == "tendance_short_seul")["oos"]
    assert short["temps_short_pct"] > 0 and short["financement_eur_pour_100"] > 0 and short["pire_hausse_horaire_short_pct"] > 0
    for texte in (md, json.dumps(j, ensure_ascii=False)):
        assert chr(8212) not in texte and chr(8211) not in texte
