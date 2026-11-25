"""Backtest du CODE en direct sur ~2 ans de bougies journalières Kraken (paires EUR).

Sert à vérifier que le bot applique bien la stratégie retenue par la recherche :
- décision à la clôture journalière, exécution à l'OUVERTURE du jour suivant (pas de triche) ;
- frais 0,40 % et slippage 0,10 % par ordre ;
- les paramètres ont été choisis par la recherche sur une période qui recouvre celle-ci : ce n'est donc PAS
  une preuve hors échantillon (la vraie validation est dans research.json).
"""
from datetime import datetime, timezone

from . import config, strategy
from .portfolio import Portefeuille


ID_STRATEGIE = f"tendance_long_short_sma{config.SMA_J}"


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def simuler(series, frais=True):
    """series : {symbole: [(ts, open, close), ...]} journalières ; doit contenir 'BTC' (et 'ETH')."""
    frais_orig, slip_orig = config.FRAIS, config.SLIPPAGE
    if not frais:
        config.FRAIS, config.SLIPPAGE = 0.0, 0.0
    try:
        timeline = [b[0] for b in series["BTC"]]
        idx = {s: {b[0]: (b[1], b[2]) for b in bs} for s, bs in series.items()}
        debut = config.SMA_J
        if len(timeline) < debut + 14:
            raise ValueError("pas assez d'historique pour backtester")
        pf, courbe, hist = Portefeuille(), [], {s: [] for s in series}
        btc_depart, plus_haut, dd_max = None, config.CAPITAL_DEPART_EUR, 0.0
        for i, ts in enumerate(timeline[:-1]):
            for s in series:
                if ts in idx[s]:
                    hist[s].append(idx[s][ts][1])
            if i < debut:
                continue
            clot = {s: idx[s][ts][1] for s in series if ts in idx[s]}
            pf.financer(clot, 24)
            pf.maj_prix_et_stops(clot, iso(ts))
            v = pf.valeur(clot)
            btc_depart = btc_depart or clot["BTC"]
            plus_haut = max(plus_haut, v)
            dd_max = max(dd_max, 1 - v / plus_haut)
            courbe.append({"t": iso(ts), "v": round(v, 3),
                           "btc": round(config.CAPITAL_DEPART_EUR * clot["BTC"] / btc_depart, 3)})
            ts_suiv = timeline[i + 1]
            ouv = {s: idx[s][ts_suiv][0] for s in series if ts_suiv in idx[s]}
            fermer, ouvrir = strategy.decisions(pf.positions, strategy.signaux(hist))
            for s, r in fermer.items():
                if s in ouv:
                    pf.vendre(s, ouv[s], iso(ts_suiv), r)
            for s, sens, r in ouvrir:
                if s in ouv and s not in pf.positions:
                    pf.ouvrir(s, sens, ouv[s], pf.valeur(ouv) * config.POIDS_PAR_ACTIF, iso(ts_suiv), r)
        derniers = {s: hist[s][-1] for s in series if hist[s]}
        v_fin = pf.valeur(derniers)
        ventes = [t for t in pf.trades if t["sens"] in ("vente", "rachat")]
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
            "financement_paye": round(pf.financement_total, 2),
            "courbe": courbe[::3] + [courbe[-1]],
        }
    finally:
        config.FRAIS, config.SLIPPAGE = frais_orig, slip_orig


def rapport(series):
    avec = simuler(series, frais=True)
    sans = simuler(series, frais=False)
    mieux = avec["rendement_pct"] > avec["btc_rendement_pct"]
    verdict = (f"Code du bot rejoué sur {avec['debut'][:10]} → {avec['fin'][:10]} : "
               f"{avec['rendement_pct']:+.1f} % contre {avec['btc_rendement_pct']:+.1f} % pour le BTC conservé, "
               f"pire baisse {avec['drawdown_max_pct']:.0f} %. "
               + ("Il fait mieux que le BTC sur cette période." if mieux else "Il ne fait pas mieux que le BTC sur cette période."))
    return {"genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "strategie": ID_STRATEGIE,
            "avec_frais": avec, "sans_frais": {k: sans[k] for k in ("rendement_pct", "nb_trades")},
            "verdict": verdict,
            "avertissement": "Contrôle du code, pas une preuve : les paramètres ont été choisis par la recherche "
                             "sur une période qui recouvre celle-ci. La validation honnête est l'onglet Recherche."}
