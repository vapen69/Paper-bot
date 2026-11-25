"""Logique de décision, partagée par le bot en direct et par le backtest."""
from . import config


def sma(valeurs, n):
    if len(valeurs) < n:
        return None
    return sum(valeurs[-n:]) / n


def marche_favorable(clotures_btc):
    """Filtre de marché : on n'achète que si le BTC est au-dessus de sa moyenne 200 h."""
    m = sma(clotures_btc, config.SMA_BTC_H)
    return m is not None and clotures_btc[-1] > m


def classement(clotures):
    """clotures : {symbole: [clôtures horaires terminées]}.
    Retourne la liste triée [{symbole, perf, eligible}] du plus fort au plus faible."""
    out = []
    for sym, c in clotures.items():
        if len(c) < max(config.LOOKBACK_H + 1, config.SMA_ACTIF_H):
            continue
        perf = c[-1] / c[-1 - config.LOOKBACK_H] - 1
        m = sma(c, config.SMA_ACTIF_H)
        eligible = perf > 0 and c[-1] > m
        out.append({"symbole": sym, "perf": perf, "eligible": eligible})
    out.sort(key=lambda x: x["perf"], reverse=True)
    for i, x in enumerate(out):
        x["rang"] = i + 1
    return out


def decisions(detenus, rang, marche_ok):
    """Retourne (a_vendre, a_acheter) avec la raison de chaque décision.
    detenus : symboles en portefeuille. rang : sortie de classement()."""
    par_sym = {x["symbole"]: x for x in rang}
    a_vendre = {}
    if not marche_ok:
        for s in detenus:
            a_vendre[s] = "BTC sous sa moyenne 200 h : passage en cash"
        return a_vendre, []
    for s in detenus:
        x = par_sym.get(s)
        if x is None:
            a_vendre[s] = "sorti de l'univers"
        elif x["rang"] > config.RANG_MAX_CONSERVE:
            a_vendre[s] = f"tombé au rang {x['rang']} (max {config.RANG_MAX_CONSERVE})"
        elif not x["eligible"]:
            a_vendre[s] = "momentum perdu (perf 24 h négative ou sous la moyenne 48 h)"
    restants = [s for s in detenus if s not in a_vendre]
    places = config.NB_POSITIONS - len(restants)
    a_acheter = []
    for x in rang:
        if places <= 0:
            break
        if x["eligible"] and x["symbole"] not in detenus:
            a_acheter.append((x["symbole"], f"rang {x['rang']}, +{x['perf']*100:.1f} % sur 24 h"))
            places -= 1
    return a_vendre, a_acheter
