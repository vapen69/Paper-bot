"""Tests hors ligne du bot (données synthétiques, aucune connexion)."""
import json
import math
import random

import pytest

from bot import backtest, config, strategy
from bot.portfolio import Portefeuille


def serie(n, derive, seed, depart=100.0, pas=86400):
    rnd = random.Random(seed)
    p, out, ts = depart, [], 1_700_000_000
    for i in range(n):
        o = p
        p = p * math.exp(derive + rnd.gauss(0, 0.03))
        out.append((ts + i * pas, o, p))
    return out


def test_frais_aller_retour():
    pf = Portefeuille()
    pf.acheter("X", 10.0, 100.0, "t0", "test")
    pf.vendre("X", 10.0, "t1", "test")
    attendu = 100 * (1 - config.FRAIS) * (1 + config.SLIPPAGE) ** -1 * (1 - config.SLIPPAGE) * (1 - config.FRAIS)
    assert pf.cash == pytest.approx(attendu)
    assert pf.cash < 100  # un aller-retour coûte toujours de l'argent


def test_ordre_minimum():
    pf = Portefeuille()
    assert not pf.acheter("X", 10.0, 2.0, "t", "trop petit")
    assert pf.cash == config.CAPITAL_DEPART_EUR


def test_stop_suiveur(monkeypatch):
    monkeypatch.setattr(config, "STOP_SUIVEUR", 0.12)
    pf = Portefeuille()
    pf.acheter("X", 100.0, 50.0, "t0", "test")
    pf.maj_prix_et_stops({"X": 130.0}, "t1")
    assert "X" in pf.positions
    pf.maj_prix_et_stops({"X": 130.0 * (1 - config.STOP_SUIVEUR) - 0.01}, "t2")
    assert "X" not in pf.positions


def test_classement_selection_decisions():
    clot = {"A": [100 + i for i in range(20)], "B": [100 - i for i in range(20)], "C": [100 + 0.5 * i for i in range(20)]}
    rang = strategy.classement(clot)
    assert [x["symbole"] for x in rang] == ["A", "C", "B"]
    assert strategy.selection(rang) == ["A", "C"]
    clot["C"] = [100 - 0.1 * i for i in range(20)]
    assert strategy.selection(strategy.classement(clot)) == ["A"]  # une crypto en baisse n'est jamais retenue
    vendre, acheter = strategy.decisions(["B"], ["A", "C"], True)
    assert "B" in vendre and [s for s, _ in acheter] == ["A", "C"]
    vendre, acheter = strategy.decisions(["A"], ["A"], False)
    assert "A" in vendre and acheter == []


def test_rebalancement_hebdomadaire():
    jours = [strategy.jour_de_rebalancement(1_700_000_000 // 86400 * 86400 + i * 86400) for i in range(21)]
    assert sum(jours) == 3


def test_backtest_sans_triche():
    """Modifier le futur ne doit pas changer les décisions passées."""
    series = {"BTC": serie(700, 0.0005, 1), "AAA": serie(700, 0.001, 2), "BBB": serie(700, -0.0005, 3)}
    r1 = backtest.simuler(series)
    alt = {s: b[:600] + [(t, o * 3, c * 3) for t, o, c in b[600:]] for s, b in series.items()}
    r2 = backtest.simuler(alt)
    c1 = [p for p in r1["courbe"] if p["t"] < backtest.iso(series["BTC"][599][0])]
    c2 = [p for p in r2["courbe"] if p["t"] < backtest.iso(series["BTC"][599][0])]
    assert c1 == c2


def test_rapport_complet():
    series = {"BTC": serie(700, 0.0003, 4), "AAA": serie(700, 0.0008, 5), "BBB": serie(700, 0.0, 6)}
    r = backtest.rapport(series)
    json.dumps(r)
    assert "verdict" in r and r["avec_frais"]["nb_trades"] >= 0
    assert r["sans_frais"]["rendement_pct"] >= r["avec_frais"]["rendement_pct"] - 1e-9


def test_boucle_complete(tmp_path, monkeypatch):
    """Fait tourner la vraie boucle quelques secondes avec un faux Kraken."""
    from bot import kraken, runner
    series = {s: serie(400, d, i) for i, (s, d) in enumerate([("BTC", 0.004), ("ETH", 0.006), ("SOL", 0.008), ("ADA", -0.002)])}
    cles = {f"K{s}": s for s in series}
    monkeypatch.setattr(kraken, "paires_eur", lambda: {k: {"symbole": s, "ws": s + "/EUR", "ordermin": 0, "costmin": 0} for k, s in cles.items()})
    monkeypatch.setattr(kraken, "tickers", lambda ks: {k: {"prix": series[cles[k]][-1][2], "volume_eur": 1e6} for k in ks})
    monkeypatch.setattr(kraken, "bougies", lambda k, i=1440: series[cles[k]][:-1])
    monkeypatch.setattr(runner, "DATA", tmp_path)
    monkeypatch.setattr(runner, "PUBLIER", False)
    monkeypatch.setattr(runner, "DUREE_MAX_S", 2)
    monkeypatch.setattr(runner, "TICK_S", 0.2)
    monkeypatch.setattr(runner, "RACINE", tmp_path)
    b = runner.Bot()
    b.run()
    etat = json.loads((tmp_path / "state.json").read_text())
    assert etat["valeur"] > 0 and etat["statut"] == "actif"
    assert etat["marche_ok"] is True and etat["selection_semaine"]
    assert set(etat["positions"]) == set(etat["selection_semaine"])  # le bot a acheté la sélection
    (tmp_path / "control.json").write_text('{"commande": "pause", "id": "1"}')
    b2 = runner.Bot()
    b2.run()
    etat = json.loads((tmp_path / "state.json").read_text())
    assert etat["statut"] == "pause"
    assert (tmp_path / "backtest.json").exists()
    assert any("PAUSE" in l["msg"] for l in etat["journal"])
