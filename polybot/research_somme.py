"""Recherche : la somme des probabilités d'un événement à plusieurs issues s'écarte-t-elle de 100 % de façon exploitable ?

    python -m polybot.research_somme                # données réelles (internet requis)
    python -m polybot.research_somme --synthetic    # événements fictifs, hors ligne

Idée reprise de l'ancien bot local (« arbitrage corrélé », avril 2026) qui n'avait jamais été testée proprement.
Sur un événement « negRisk » (une seule issue gagne parmi N, par exemple « qui gagnera l'élection »), la somme des
prix du Oui de chaque issue devrait valoir 1. Si elle vaut plus, les Oui sont trop chers dans leur ensemble ; moins,
trop bon marché.

Méthode (mêmes principes que polybot/research.py)
- Événements negRisk fermés, de 3 à 30 issues, toutes résolues, avec exactement un Oui gagnant.
- Grille horaire. À l'heure g, on ne connaît que le dernier prix de chaque issue au plus tard à g (âge <= 3 h,
  sinon pas de décision). La somme S(g) décide ; l'exécution se fait aux prix de g + 1 h.
- Coûts à chaque jambe : demi-écart max(1 centime, 2 % x min(p, 1 - p)) et frais taker. Le règlement final est
  gratuit. Une seule entrée par événement, gardée jusqu'à la résolution.

Stratégies (petite grille de seuil : 3, 5 ou 10 points)
- panier : si S >= 1 + seuil, acheter le Non de toutes les issues (rapporte N - 1) ; si S <= 1 - seuil, acheter le
  Oui de toutes les issues (rapporte 1). C'est l'arbitrage « parfait » : il ne perd qu'à cause des coûts.
- jambe_favori : même signal, mais une seule jambe : le Non (ou le Oui) de l'issue la plus chère.
- hasard (référence) : une issue au hasard, un côté au hasard, un instant au hasard.

RÈGLE DE SÉLECTION, écrite avant de voir le moindre résultat : identique à polybot/research.py (dernier tiers
jamais vu, au moins 50 trades sur 30 événements, rendement moyen positif avec t >= 2,5, mieux que le hasard sur le
capital immobilisé, rendement encore positif avec 1000 points de base de frais taker partout) ; la pire baisse est
mesurée sur une suite de mises de 4 % d'un capital de 100 dollars, dans l'ordre des règlements, et doit rester
<= 25 %. Si rien ne passe : aucune stratégie validée, rien ne change dans le bot en direct.
"""
import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import api, config
from .research import (CACHE, DD_MAX, EVENEMENTS_MIN, FRAIS_ACTUELS_BPS, PART_APPRENTISSAGE, SORTIE, T_MIN,
                       TRADES_MIN, TRADES_MIN_GRILLE, _historique_marche, demi_spread, metriques, t_par_evenement)
from .strategies import H, JOUR

MOIS = 15
EVENEMENTS_PAR_MOIS = 40
ISSUES_MIN, ISSUES_MAX = 3, 30
VOLUME_EVT_MIN = 50000.0
AGE_MAX_S = 3 * H
MARGE_FIN_S = 6 * H
BUDGET_TELECHARGEMENT_S = 80 * 60
SEUILS = [0.03, 0.05, 0.10]
MISE = 0.04

SCENARIOS = {"base": {"frais_bps_min": None}, "frais_actuels": {"frais_bps_min": FRAIS_ACTUELS_BPS}}

STRATEGIES = {
    "panier": "Si la somme des Oui dépasse 1 + seuil, acheter le Non de toutes les issues ; sous 1 - seuil, acheter "
              "le Oui de toutes les issues. Gardé jusqu'à la résolution.",
    "jambe_favori": "Même signal, mais une seule jambe : le Non (somme trop haute) ou le Oui (somme trop basse) de "
                    "l'issue la plus chère. Gardé jusqu'à la résolution.",
    "hasard": "Référence : une issue au hasard, un côté au hasard, un instant au hasard. Doit perdre les coûts.",
}
REFERENCE = "hasard"

REGLE = ("Éligible si, sur le dernier tiers jamais vu et coûts déduits : au moins 50 trades sur 30 événements, "
         "rendement moyen positif avec t par événement >= 2,5, rendement sur capital immobilisé supérieur à la "
         "référence hasard, pire baisse (mises de 4 %) <= 25 %, et rendement moyen encore positif avec 1000 points "
         "de base de frais taker partout. Sinon : aucune stratégie validée, le bot en direct ne change pas.")


# ---------- panneau de prix ----------
def panneau(evt):
    """Grille horaire et prix connus de chaque issue (NaN si inconnu ou trop ancien). Ne lit jamais le résultat."""
    debut = max(float(j["t"][0]) for j in evt["jambes"])
    fin = evt["cloture"] - MARGE_FIN_S
    if fin <= debut + 2 * H:
        return np.array([]), np.zeros((0, len(evt["jambes"])))
    g = np.arange(debut, fin, H)
    P = np.full((len(g), len(evt["jambes"])), np.nan)
    for k, j in enumerate(evt["jambes"]):
        i = np.searchsorted(j["t"], g, side="right") - 1
        ok = (i >= 0) & ((g - j["t"][np.clip(i, 0, None)]) <= AGE_MAX_S)
        P[ok, k] = j["p"][i[ok]]
    return g, P


def _frais(prix, frais_bps, couts):
    bps = config.FRAIS_BPS_SI_ABSENT if frais_bps is None else frais_bps
    if couts.get("frais_bps_min") is not None:
        bps = max(bps, couts["frais_bps_min"])
    return bps / 10000.0 * min(prix, 1.0 - prix)


def _achat(prix, frais_bps, couts):
    a = prix + demi_spread(prix)
    return a + _frais(a, frais_bps, couts)


def _tirage(cle):
    return int.from_bytes(hashlib.sha256(cle.encode()).digest()[:8], "big") / 2 ** 64


def simuler_evenement(evt, nom, seuil, couts=None, grille=None):
    """Au plus un trade par événement. Le résultat (evt["gagnant"]) n'est lu qu'au règlement."""
    couts = couts or SCENARIOS["base"]
    g, P = grille if grille is not None else panneau(evt)
    if len(g) < 3:
        return []
    complet = ~np.isnan(P).any(axis=1)
    S = np.where(complet, np.nansum(P, axis=1), np.nan)
    n = P.shape[1]
    frais = [j.get("frais_bps") for j in evt["jambes"]]
    if nom == "hasard":
        cand = [i for i in range(len(g) - 1) if complet[i] and complet[i + 1]]
        if not cand:
            return []
        i = cand[int(_tirage(evt["id"] + ":t") * len(cand))]
        k = int(_tirage(evt["id"] + ":k") * n)
        oui = _tirage(evt["id"] + ":c") < 0.5
        signal = None
    else:
        i, signal = None, None
        for x in range(len(g) - 1):
            if not (complet[x] and complet[x + 1]):
                continue
            if S[x] >= 1 + seuil:
                i, signal = x, "haut"
                break
            if S[x] <= 1 - seuil:
                i, signal = x, "bas"
                break
        if i is None:
            return []
    px = P[i + 1]                                                       # exécution au point suivant
    if nom == "panier":
        if signal == "haut":
            cout = sum(_achat(1.0 - float(p), frais[k], couts) for k, p in enumerate(px))
            revenu = float(n - 1)
        else:
            cout = sum(_achat(float(p), frais[k], couts) for k, p in enumerate(px))
            revenu = 1.0
    else:
        if nom == "jambe_favori":
            k = int(np.argmax(P[i]))
            oui = signal == "bas"
        x = float(px[k]) if oui else 1.0 - float(px[k])
        if x < 0.02 or x > config.PRIX_ENTREE_MAX:
            return []
        cout = _achat(x, frais[k], couts)
        gagne = evt["gagnant"] == k
        revenu = 1.0 if gagne == oui else 0.0
    t_in, t_out = float(g[i + 1]), max(float(evt["cloture"]), float(g[i + 1]) + H)
    return [{"marche": evt["id"], "evenement": evt["id"], "categorie": evt.get("categorie", "autre"),
             "t_in": t_in, "t_out": t_out, "cout": cout, "revenu": revenu, "rend": revenu / cout - 1.0,
             "jours": max((t_out - t_in) / JOUR, 1 / 24), "somme": round(float(S[i]), 4), "issues": n}]


def tous_les_trades(evts, nom, seuil, couts=None, grilles=None):
    out = []
    for e in evts:
        out.extend(simuler_evenement(e, nom, seuil, couts, grilles.get(e["id"]) if grilles else None))
    return sorted(out, key=lambda x: x["t_in"])


def pire_baisse(trades, capital=config.CAPITAL_DEPART):
    """Mises de 4 % de la valeur courante, réglées dans l'ordre des règlements : pire baisse en %."""
    v, pic, dd = capital, capital, 0.0
    for x in sorted(trades, key=lambda x: x["t_out"]):
        v += MISE * v * x["rend"]
        pic = max(pic, v)
        dd = max(dd, (pic - v) / pic)
    return round(100 * dd, 1), round(100 * (v / capital - 1), 2)


# ---------- protocole ----------
def analyser(evts, infos, journal=print):
    grilles = {e["id"]: panneau(e) for e in evts}
    debut = min(float(g[0]) for g, _ in grilles.values() if len(g))
    fin = max(e["cloture"] for e in evts)
    t_coupe = debut + PART_APPRENTISSAGE * (fin - debut)
    resultats = []
    for nom, desc in STRATEGIES.items():
        seuils = [0.0] if nom == REFERENCE else SEUILS
        meilleur, score, essais = seuils[0], -math.inf, []
        for s in seuils:
            tr = [x for x in tous_les_trades(evts, nom, s, grilles=grilles) if x["t_out"] < t_coupe]
            t_stat, _ = t_par_evenement(tr)
            essais.append({"seuil": s, "nb_trades": len(tr), "t_stat": round(t_stat, 2)})
            if len(tr) >= TRADES_MIN_GRILLE and t_stat > score:
                meilleur, score = s, t_stat
        base = tous_les_trades(evts, nom, meilleur, grilles=grilles)
        oos = [x for x in base if x["t_in"] >= t_coupe]
        frais = [x for x in tous_les_trades(evts, nom, meilleur, SCENARIOS["frais_actuels"], grilles)
                 if x["t_in"] >= t_coupe]
        dd, rend = pire_baisse(oos)
        sommes = [x["somme"] for x in oos]
        resultats.append({"nom": nom, "description": desc, "seuil_retenu": meilleur, "essais_apprentissage": essais,
                          "apprentissage": metriques([x for x in base if x["t_out"] < t_coupe]),
                          "oos": metriques(oos), "frais_actuels": metriques(frais),
                          "mises_4pct": {"drawdown_max_pct": dd, "rendement_pct": rend},
                          "somme_mediane_au_signal": round(float(np.median(sommes)), 3) if sommes else None})
    ref = next(s for s in resultats if s["nom"] == REFERENCE)["oos"]["rend_capital_temps_an_pct"]
    eligibles = []
    for s in resultats:
        o, refus = s["oos"], []
        if s["nom"] == REFERENCE:
            refus.append("référence, jamais sélectionnable")
        if o["nb_trades"] < TRADES_MIN or o["nb_evenements"] < EVENEMENTS_MIN:
            refus.append(f"trop peu de données ({o['nb_trades']} trades, {o['nb_evenements']} événements)")
        if o["rend_moyen_pct"] <= 0:
            refus.append(f"rendement moyen négatif ou nul ({o['rend_moyen_pct']:+.2f} % par trade)")
        elif o["t_stat"] < T_MIN:
            refus.append(f"avantage non prouvé (t = {o['t_stat']:.2f}, il faut {T_MIN})")
        if o["rend_capital_temps_an_pct"] <= max(0.0, ref):
            refus.append("ne bat pas la référence hasard sur le capital immobilisé")
        if s["mises_4pct"]["drawdown_max_pct"] > DD_MAX:
            refus.append(f"pire baisse trop forte ({s['mises_4pct']['drawdown_max_pct']:.0f} %)")
        if s["frais_actuels"]["rend_moyen_pct"] <= 0:
            refus.append("ne survit pas aux frais taker actuels")
        s["eligible"], s["refus"] = not refus, refus
        if not refus:
            eligibles.append(s)
    prefixe = "DONNÉES FICTIVES (test technique, aucune conclusion à en tirer). " if infos["source"] == "synthetique" else ""
    if eligibles:
        elu = max(eligibles, key=lambda x: x["oos"]["rend_capital_temps_an_pct"])
        o = elu["oos"]
        verdict = (f"{prefixe}{elu['nom']} (seuil {elu['seuil_retenu']}) passe la règle fixée à l'avance sur la "
                   f"période jamais vue : {o['nb_trades']} trades, {o['rend_moyen_pct']:+.2f} % par trade, "
                   f"t = {o['t_stat']:.2f}. À confirmer en paper trading sur le vrai carnet avant tout usage.")
    else:
        elu = None
        detail = " ; ".join(f"{s['nom']} {s['oos']['rend_moyen_pct']:+.2f} % par trade ({s['oos']['nb_trades']} trades)"
                            for s in resultats)
        verdict = (f"{prefixe}Aucune stratégie « somme des probabilités » ne passe la règle fixée à l'avance. "
                   f"Résultats sur la période jamais vue, coûts déduits : {detail}. Rien ne change dans le bot.")
    return {"genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": infos["source"],
            "nb_evenements": len(evts), "nb_issues": sum(len(e["jambes"]) for e in evts),
            "periode": {"debut": api.iso(debut), "fin": api.iso(fin), "coupure": api.iso(t_coupe)},
            "regle_selection": REGLE, "strategies": resultats,
            "choix": {"nom": elu["nom"] if elu else None, "seuil": elu["seuil_retenu"] if elu else None,
                      "valide": elu is not None},
            "verdict": verdict}


def ecrire(r, dossier=SORTIE):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "research_somme.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
    p = lambda v: f"{v:+.2f} %".replace(".", ",")
    L = ["# Recherche Polymarket : somme des probabilités d'un événement", "",
         f"Généré le {r['genere_le']} · source : {r['source']} · {r['nb_evenements']} événements "
         f"({r['nb_issues']} issues) du {r['periode']['debut'][:10]} au {r['periode']['fin'][:10]}. "
         f"Période jamais vue : à partir du {r['periode']['coupure'][:10]}.", "",
         "## Verdict", "", r["verdict"], "",
         "## Règle de sélection (fixée avant les résultats)", "", r["regle_selection"], "",
         "## Période jamais vue, coûts déduits", "",
         "| Stratégie | Seuil | Trades | Gagnants | Rendement par trade | t | Somme médiane au signal | "
         "Mises de 4 % | Pire baisse | Avec frais actuels | Éligible |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in r["strategies"]:
        o = s["oos"]
        L.append(f"| {s['nom']} | {s['seuil_retenu']} | {o['nb_trades']} | {o['gagnants_pct']:.0f} % | "
                 f"{p(o['rend_moyen_pct'])} | {o['t_stat']:.2f} | {s['somme_mediane_au_signal']} | "
                 f"{p(s['mises_4pct']['rendement_pct'])} | {s['mises_4pct']['drawdown_max_pct']:.0f} % | "
                 f"{p(s['frais_actuels']['rend_moyen_pct'])} | {'oui' if s['eligible'] else 'non'} |")
    L += ["", "## Détail", ""]
    for s in r["strategies"]:
        L += [f"### {s['nom']}", "", s["description"], "",
              f"- Essais sur l'apprentissage : {json.dumps(s['essais_apprentissage'], ensure_ascii=False)}",
              "- Refus : " + ("aucun, stratégie éligible" if s["eligible"] else " ; ".join(s["refus"])), ""]
    L += ["## Limites", "",
          "- L'historique donne un prix par issue, pas le carnet : une somme qui s'écarte de 1 peut venir d'issues peu "
          "échangées dont le dernier prix est ancien. Le demi-écart d'au moins 1 centime par jambe en tient compte.",
          "- Les événements sont choisis d'après leur volume final, connu après coup.",
          "- Les performances passées ne garantissent rien.", ""]
    (dossier / "research_somme.md").write_text("\n".join(L))


# ---------- données réelles ----------
def _evenements_gamma(params, pages):
    out, decalage = [], 0
    for _ in range(pages):
        try:
            lot = api._get(config.GAMMA + "/events", {**params, "limit": 100, "offset": decalage})
        except Exception:
            break
        if isinstance(lot, dict):
            lot = lot.get("data") or lot.get("events") or []
        if not isinstance(lot, list) or not lot:
            break
        decalage += len(lot)
        out.extend(e for e in lot if isinstance(e, dict))
    return out


def construire_evenement(brut, jambes_hist):
    """Événement Gamma + historiques -> enregistrement de recherche, ou None s'il ne convient pas."""
    marches = [api.parse_marche(m) for m in brut.get("markets") or []]
    if not marches or any(m is None for m in marches) or not (ISSUES_MIN <= len(marches) <= ISSUES_MAX):
        return None
    finales = [api.issue_finale(m) for m in marches]
    if any(f is None for f in finales) or sum(f[0] for f in finales) != 1.0:
        return None
    jambes = []
    for m in marches:
        pts = jambes_hist.get(m["id"]) or []
        if len(pts) < 24:
            return None
        jambes.append({"id": m["id"], "frais_bps": m.get("frais_bps"),
                       "t": np.array([t for t, _ in pts], dtype=float), "p": np.array([x for _, x in pts], dtype=float)})
    cloture = max(m.get("ferme_le") or m.get("echeance") or 0 for m in marches)
    if not cloture:
        return None
    return {"id": str(brut.get("id")), "titre": str(brut.get("title") or "")[:200],
            "categorie": marches[0]["categorie"], "cloture": float(cloture),
            "gagnant": next(k for k, f in enumerate(finales) if f[0] == 1.0), "jambes": jambes}


def telecharger(mois=MOIS, par_mois=EVENEMENTS_PAR_MOIS, journal=print):
    hist_dir = CACHE / "hist"
    hist_dir.mkdir(parents=True, exist_ok=True)
    depart, maintenant, evts, lus = time.time(), time.time(), [], 0
    for k in range(mois):
        a, b = maintenant - (k + 1) * 30 * JOUR, maintenant - k * 30 * JOUR
        lot = _evenements_gamma({"closed": "true", "end_date_min": api.iso(a), "end_date_max": api.iso(b),
                                 "order": "volume", "ascending": "false"}, pages=5)
        lot = [e for e in lot if e.get("negRisk") and (api.nombre(e.get("volume"), 0) or 0) >= VOLUME_EVT_MIN
               and ISSUES_MIN <= len(e.get("markets") or []) <= ISSUES_MAX]
        lot.sort(key=lambda e: -(api.nombre(e.get("volume"), 0) or 0))
        retenus = 0
        for brut in lot:
            if retenus >= par_mois:
                break
            hist = {}
            for m in (api.parse_marche(x) for x in brut.get("markets") or []):
                if m is None:
                    break
                f = hist_dir / f"{m['id']}.json"
                pts = None
                if f.exists():
                    try:
                        pts = [tuple(x) for x in json.loads(f.read_text())]
                    except Exception:
                        pts = None
                if pts is None:
                    if time.time() - depart > BUDGET_TELECHARGEMENT_S:
                        break
                    pts = _historique_marche(m, journal)
                    f.write_text(json.dumps(pts))
                    lus += 1
                hist[m["id"]] = pts
            e = construire_evenement(brut, hist)
            if e:
                evts.append(e)
                retenus += 1
        journal(f"Mois -{k + 1} : {len(lot)} événements negRisk candidats, {retenus} retenus")
    journal(f"{len(evts)} événements utilisables, {lus} historiques téléchargés, {api.COMPTEUR['requetes']} requêtes")
    return evts


# ---------- données fictives ----------
def synthetique(nb=400, graine=5, biais=0.0, jours=420):
    """Événements fictifs. biais = 0 : les prix sont de vraies probabilités qui somment à 1 (plus un petit bruit),
    aucune stratégie ne doit gagner. biais > 0 : tous les Oui sont surcotés d'un facteur (1 + biais)."""
    rnd = np.random.default_rng(graine)
    base, evts = 1_750_000_000, []
    for e in range(nb):
        n = int(rnd.integers(3, 8))
        duree_h = int(rnd.integers(96, 24 * 30))
        debut = base + float(rnd.uniform(0, jours * JOUR - duree_h * H))
        x = rnd.normal(0, 1, n)
        vrais = np.empty((duree_h, n))
        for j in range(duree_h):
            x = x + rnd.normal(0, 0.05, n)
            v = np.exp(x)
            vrais[j] = v / v.sum()
        gagnant = int(rnd.choice(n, p=vrais[-1]))
        t = debut + H * np.arange(duree_h)
        jambes = []
        for k in range(n):
            p = np.clip(vrais[:, k] * (1 + biais) + rnd.normal(0, 0.004, duree_h), 0.001, 0.999)
            jambes.append({"id": f"e{e}m{k}", "frais_bps": 0.0, "t": t, "p": np.round(p, 3)})
        evts.append({"id": f"e{e}", "titre": f"Événement fictif {e}", "categorie": "autre",
                     "cloture": float(t[-1] + MARGE_FIN_S + 2 * H), "gagnant": gagnant, "jambes": jambes})
    return evts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recherche : somme des probabilités des événements Polymarket")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--mois", type=int, default=MOIS)
    ap.add_argument("--sortie", default=str(SORTIE))
    args = ap.parse_args(argv)
    if args.synthetic:
        evts, infos = synthetique(), {"source": "synthetique"}
    else:
        evts, infos = telecharger(args.mois), {"source": "polymarket"}
        if len(evts) < 60:
            raise SystemExit(f"Trop peu d'événements utilisables ({len(evts)}) : aucun fichier écrit.")
    r = analyser(evts, infos)
    ecrire(r, Path(args.sortie))
    print(r["verdict"])
    return r


if __name__ == "__main__":
    main()
