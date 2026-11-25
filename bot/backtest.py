"""Backtest honnête de la stratégie sur les ~30 derniers jours de bougies horaires Kraken.

- Le signal est calculé sur la clôture d'une bougie et exécuté à l'OUVERTURE de la suivante (pas de triche).
- Frais 0,40 % et slippage 0,10 % par ordre.
- Biais de survie : l'univers testé est celui d'aujourd'hui (les tokens qui ont disparu ne sont pas dedans),
  ce qui rend le backtest un peu trop optimiste. C'est signalé dans le rapport.
"""
from datetime import datetime, timezone

from . import config, strategy
from .portfolio import Portefeuille


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def simuler(series, frais=True):
    """series : {symbole: [(ts, open, close), ...]} ; doit contenir 'BTC'."""
    frais_orig, slip_orig = config.FRAIS, config.SLIPPAGE
    if not frais:
        config.FRAIS, config.SLIPPAGE = 0.0, 0.0
    try:
        timeline = [b[0] for b in series["BTC"]]
        idx = {s: {b[0]: (b[1], b[2]) for b in bs} for s, bs in series.items()}
        pf = Portefeuille()
        courbe = []
        debut = config.SMA_BTC_H
        if len(timeline) < debut + 24:
            raise ValueError("pas assez d'historique pour backtester")
        hist = {s: [] for s in series}
        btc_depart = None
        plus_haut, dd_max = config.CAPITAL_DEPART_EUR, 0.0
        for i, ts in enumerate(timeline[:-1]):
            for s in series:
                if ts in idx[s]:
                    hist[s].append(idx[s][ts][1])
            if i < debut:
                continue
            clot = {s: idx[s][ts][1] for s in series if ts in idx[s]}
            pf.maj_prix_et_stops(clot, iso(ts))
            v = pf.valeur(clot)
            if btc_depart is None:
                btc_depart = clot["BTC"]
            plus_haut = max(plus_haut, v)
            dd_max = max(dd_max, 1 - v / plus_haut)
            courbe.append({"t": iso(ts), "v": round(v, 3),
                           "btc": round(config.CAPITAL_DEPART_EUR * clot["BTC"] / btc_depart, 3)})
            # décision à la clôture, exécution à l'ouverture suivante
            ts_suiv = timeline[i + 1]
            ouv = {s: idx[s][ts_suiv][0] for s in series if ts_suiv in idx[s]}
            rang = strategy.classement({s: h for s, h in hist.items() if s in clot})
            vendre, acheter = strategy.decisions(list(pf.positions), rang, strategy.marche_favorable(hist["BTC"]))
            for s, r in vendre.items():
                if s in ouv:
                    pf.vendre(s, ouv[s], iso(ts_suiv), r)
            acheter = [(s, r) for s, r in acheter if s in ouv]
            for n, (s, r) in enumerate(acheter):
                pf.acheter(s, ouv[s], pf.cash / (len(acheter) - n), iso(ts_suiv), r)
        derniers = {s: hist[s][-1] for s in series if hist[s]}
        v_fin = pf.valeur(derniers)
        ventes = [t for t in pf.trades if t["sens"] == "vente"]
        gagnants = [t for t in ventes if t["pnl"] > 0]
        return {
            "debut": courbe[0]["t"], "fin": courbe[-1]["t"],
            "valeur_finale": round(v_fin, 2),
            "rendement_pct": round((v_fin / config.CAPITAL_DEPART_EUR - 1) * 100, 2),
            "btc_rendement_pct": round((courbe[-1]["btc"] / config.CAPITAL_DEPART_EUR - 1) * 100, 2),
            "drawdown_max_pct": round(dd_max * 100, 2),
            "nb_trades": len(pf.trades),
            "taux_reussite_pct": round(100 * len(gagnants) / len(ventes), 1) if ventes else None,
            "frais_payes": round(pf.frais_total, 2),
            "courbe": courbe[::4] + [courbe[-1]],
        }
    finally:
        config.FRAIS, config.SLIPPAGE = frais_orig, slip_orig


def rapport(series):
    avec = simuler(series, frais=True)
    sans = simuler(series, frais=False)
    if avec["rendement_pct"] > avec["btc_rendement_pct"]:
        verdict = (f"Sur cette période, la stratégie fait mieux que garder du BTC après frais "
                   f"({avec['rendement_pct']:+.1f} % contre {avec['btc_rendement_pct']:+.1f} %). "
                   "Un mois de données ne prouve rien : il faut que ça tienne plusieurs mois en paper trading.")
    else:
        verdict = (f"Sur cette période, la stratégie ne bat PAS le simple fait de garder du BTC après frais "
                   f"({avec['rendement_pct']:+.1f} % contre {avec['btc_rendement_pct']:+.1f} %).")
    return {"genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "avec_frais": avec, "sans_frais": {k: sans[k] for k in ("rendement_pct", "nb_trades")},
            "verdict": verdict,
            "avertissement": "Univers d'aujourd'hui appliqué au passé (biais de survie) et seulement ~3 semaines "
                             "testées : résultats indicatifs, probablement trop optimistes."}
