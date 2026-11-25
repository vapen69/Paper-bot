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


def test_signaux_et_decisions():
    hausse = [100 + i for i in range(60)]
    baisse = [200 - i for i in range(60)]
    sig = strategy.signaux({"BTC": hausse, "ETH": baisse})
    assert sig["BTC"]["sens"] == "long" and sig["ETH"]["sens"] == "short"
    fermer, ouvrir = strategy.decisions({}, sig)
    assert fermer == {} and sorted((s, sens) for s, sens, _ in ouvrir) == [("BTC", "long"), ("ETH", "short")]
    fermer, ouvrir = strategy.decisions({"BTC": {"sens": "short"}, "ETH": {"sens": "short"}}, sig)
    assert list(fermer) == ["BTC"] and [(s, sens) for s, sens, _ in ouvrir] == [("BTC", "long")]


def test_short_gagne_a_la_baisse_et_paie_le_financement(monkeypatch):
    monkeypatch.setattr(config, "FRAIS", 0.0)
    monkeypatch.setattr(config, "SLIPPAGE", 0.0)
    pf = Portefeuille()
    pf.ouvrir("BTC", "short", 100.0, 50.0, "t0", "test")
    assert pf.valeur({"BTC": 100.0}) == pytest.approx(100.0)
    assert pf.valeur({"BTC": 80.0}) == pytest.approx(110.0)   # -20 % sur le prix = +10 € sur 50 € engagés
    assert pf.valeur({"BTC": 130.0}) == pytest.approx(85.0)
    pf.financer({"BTC": 100.0}, 8)
    assert pf.financement_total == pytest.approx(50.0 * config.FINANCEMENT_SHORT_8H)
    pf.vendre("BTC", 80.0, "t1", "test")
    assert pf.cash == pytest.approx(110.0 - 50.0 * config.FINANCEMENT_SHORT_8H)


def test_short_liquide_si_le_prix_double():
    pf = Portefeuille()
    pf.ouvrir("ETH", "short", 100.0, 50.0, "t0", "test")
    pf.maj_prix_et_stops({"ETH": 205.0}, "t1")
    assert "ETH" not in pf.positions and pf.trades[-1]["raison"].startswith("liquidation")
    assert pf.valeur({}) == pytest.approx(50.0)  # perte limitée à la garantie engagée


def test_backtest_sans_triche():
    """Modifier le futur ne doit pas changer les décisions passées."""
    series = {"BTC": serie(700, 0.0005, 1), "ETH": serie(700, -0.001, 2)}
    r1 = backtest.simuler(series)
    alt = {s: b[:600] + [(t, o * 3, c * 3) for t, o, c in b[600:]] for s, b in series.items()}
    r2 = backtest.simuler(alt)
    c1 = [p for p in r1["courbe"] if p["t"] < backtest.iso(series["BTC"][599][0])]
    c2 = [p for p in r2["courbe"] if p["t"] < backtest.iso(series["BTC"][599][0])]
    assert c1 == c2


def test_rapport_complet():
    series = {"BTC": serie(700, 0.0003, 4), "ETH": serie(700, 0.0008, 5)}
    r = backtest.rapport(series)
    json.dumps(r)
    assert "verdict" in r and r["avec_frais"]["nb_trades"] >= 0
    assert r["sans_frais"]["rendement_pct"] >= r["avec_frais"]["rendement_pct"] - 1e-9


def test_boucle_complete(tmp_path, monkeypatch):
    """Fait tourner la vraie boucle quelques secondes avec un faux Kraken."""
    from bot import kraken, runner
    series = {s: serie(400, d, i) for i, (s, d) in enumerate([("BTC", 0.004), ("ETH", -0.006), ("SOL", 0.008)])}
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
    assert etat["positions"]["BTC"]["sens"] == "long" and etat["positions"]["ETH"]["sens"] == "short"
    assert "SOL" not in etat["positions"]
    assert 99 < etat["valeur"] < 100  # seuls les frais ont été payés
    (tmp_path / "control.json").write_text('{"commande": "pause", "id": "1"}')
    b2 = runner.Bot()
    b2.run()
    etat = json.loads((tmp_path / "state.json").read_text())
    assert etat["statut"] == "pause"
    assert (tmp_path / "backtest.json").exists()
    assert any("PAUSE" in l["msg"] for l in etat["journal"])


def test_kraken_paires_eur(monkeypatch):
    """Analyse réelle de la réponse AssetPairs (avec une réponse Kraken simulée)."""
    from bot import kraken
    rep = {"XXBTZEUR": {"wsname": "XBT/EUR", "status": "online", "ordermin": "0.00005", "costmin": "0.5"},
           "USDTEUR": {"wsname": "USDT/EUR", "status": "online"},
           "XETHZUSD": {"wsname": "ETH/USD", "status": "online"},
           "XDGEUR": {"wsname": "XDG/EUR", "status": "online"}}
    monkeypatch.setattr(kraken, "_get", lambda e, p=None: rep)
    out = kraken.paires_eur()
    assert {v["symbole"] for v in out.values()} == {"BTC", "DOGE"}
