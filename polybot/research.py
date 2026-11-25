"""Recherche honnête sur les marchés Polymarket déjà résolus.

    python -m polybot.research                # données réelles (internet requis, plusieurs dizaines de minutes)
    python -m polybot.research --synthetic    # marchés fictifs, hors ligne (vérifie seulement que tout tourne)

Méthode
- Marchés binaires fermés et résolus des derniers mois (Gamma), historique horaire de la première issue (CLOB).
- Décision à l'instant t avec les seuls prix connus jusqu'à t ; exécution au point SUIVANT de l'historique.
  Le résultat du marché ne sert qu'au règlement final.
- Coûts : l'historique ne contient pas le carnet, donc on paie un demi-écart supposé à chaque achat et à chaque
  vente : 1 centime, ou 2 % de la distance au bord le plus proche (min(prix, 1 - prix)), le plus grand des deux.
  Frais taker : (takerBaseFee / 10000) x min(prix, 1 - prix) par part, avec le takerBaseFee du marché s'il est
  connu, sinon l'hypothèse de polybot/config.py. Aucun frais au règlement.
- Le capital reste bloqué jusqu'à la résolution : on mesure donc le rendement par dollar et par jour immobilisé,
  et on rejoue un portefeuille de 100 dollars avec les mêmes limites que le bot (taille, nombre de positions).
- Découpage dans le temps : les 2 premiers tiers servent à choisir les paramètres (petite grille), le dernier
  tiers n'est regardé qu'une fois, avec les paramètres déjà figés. Les trades à cheval sur la coupure sont jetés.

RÈGLE DE SÉLECTION, écrite avant de voir le moindre résultat (fonction choisir) :
1. une stratégie est éligible si, sur le dernier tiers (jamais vu), coûts déduits :
   au moins 50 trades sur au moins 30 événements différents ; rendement moyen par trade positif avec un t de
   Student par événement >= 2,5 (seuil relevé car 4 stratégies sont testées) ; rendement sur capital immobilisé
   supérieur à celui de la référence « hasard » ; pire baisse du portefeuille simulé <= 25 % ; et rendement moyen
   encore positif avec les frais taker actuels (1000 points de base) appliqués à tous les marchés ;
2. parmi les éligibles, on retient le meilleur rendement annualisé du portefeuille simulé ;
3. si aucune n'est éligible, on le dit : aucune stratégie n'est validée. Le bot tourne alors en mode observation
   (favori proche de l'échéance, mises réduites), sans prétendre à un avantage.
"""
import argparse
import heapq
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import api, config
from .strategies import H, JOUR, REFERENCE, STRATEGIES

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "polybot_out"
CACHE = Path(__file__).resolve().parent / "cache"

# ---------- périmètre des données ----------
MOIS = 15                       # profondeur de l'historique
PAR_MOIS = 300                  # marchés retenus par mois d'échéance (les plus gros volumes)
PAGES_PAR_MOIS = 12
VOLUME_MIN = 10000.0            # dollars échangés sur la vie du marché
DUREE_MIN_J = 2.0               # écarte les marchés éclair (crypto 15 minutes, etc.)
POINTS_MIN = 24                 # historique trop court = inutilisable
BUDGET_TELECHARGEMENT_S = 100 * 60

# ---------- protocole ----------
PART_APPRENTISSAGE = 2 / 3
TRADES_MIN_GRILLE = 30
TRADES_MIN, EVENEMENTS_MIN, T_MIN, DD_MAX = 50, 30, 2.5, 25.0
FRAIS_ACTUELS_BPS = 1000.0
ECART_MAX_EXECUTION_S = 24 * H  # si le point suivant est à plus de 24 h, on ne peut pas prétendre exécuter

REGLE = ("Éligible si, sur le dernier tiers jamais vu et coûts déduits : au moins 50 trades sur 30 événements, "
         "rendement moyen positif avec t par événement >= 2,5, rendement sur capital immobilisé supérieur à la "
         "référence hasard, pire baisse du portefeuille simulé <= 25 %, et rendement moyen encore positif avec "
         "1000 points de base de frais taker partout. Parmi les éligibles : meilleur rendement annualisé du "
         "portefeuille simulé. Sinon : aucune stratégie validée, mode observation à mises réduites.")

SCENARIOS = {
    "base": {"spread_mult": 1.0, "frais_bps_min": None},
    "frais_actuels": {"spread_mult": 1.0, "frais_bps_min": FRAIS_ACTUELS_BPS},
    "spread_double": {"spread_mult": 2.0, "frais_bps_min": FRAIS_ACTUELS_BPS},
}


def demi_spread(prix):
    """Demi-écart supposé entre le prix de l'historique et le prix réellement payé ou reçu."""
    return max(0.01, 0.02 * min(prix, 1.0 - prix))


def _frais_part(prix, marche, couts):
    bps = marche.get("frais_bps")
    bps = config.FRAIS_BPS_SI_ABSENT if bps is None else bps
    if couts.get("frais_bps_min") is not None:
        bps = max(bps, couts["frais_bps_min"])
    return bps / 10000.0 * min(prix, 1.0 - prix)


# ---------- simulation d'un marché ----------
def simuler_marche(m, nom, params, couts=None):
    """Trades de la stratégie sur un marché. Le résultat m["issue0"] n'est lu qu'au règlement."""
    couts = couts or SCENARIOS["base"]
    strat = STRATEGIES[nom]
    t, p = m["t"], m["p"]
    n = len(t)
    if n < 2:
        return []
    cote = strat["fn"](t, p, m.get("fin"), {"id": m["id"], "oui_non": m.get("oui_non")}, **params)
    limite, sortie_h = params.get("prix_max"), params.get("sortie_h")
    trades, libre_a = [], -math.inf
    for i in np.nonzero(cote >= 0)[0]:
        if i + 1 >= n:
            break
        if t[i] < libre_a or t[i + 1] - t[i] > ECART_MAX_EXECUTION_S:
            continue
        c = int(cote[i])
        x = float(p[i + 1]) if c == 0 else 1.0 - float(p[i + 1])       # prix au point suivant : pas de triche
        if x < 0.02 or (limite is not None and x > limite):
            continue
        achat = x + demi_spread(x) * couts["spread_mult"]
        if achat > config.PRIX_ENTREE_MAX:
            continue
        cout = achat + _frais_part(achat, m, couts)
        t_in = float(t[i + 1])
        revenu = t_out = None
        if sortie_h:
            k = int(np.searchsorted(t, t_in + sortie_h * H, side="left"))
            if k < n:
                y = float(p[k]) if c == 0 else 1.0 - float(p[k])
                vente = max(0.0, y - demi_spread(y) * couts["spread_mult"])
                revenu, t_out, motif = max(0.0, vente - _frais_part(vente, m, couts)), float(t[k]), "temps"
        if revenu is None:                                             # règlement à la résolution, sans frais
            revenu = m["issue0"] if c == 0 else 1.0 - m["issue0"]
            t_out, motif = max(float(m["cloture"]), t_in + H), "resolution"
        trades.append({"marche": m["id"], "evenement": m.get("evenement") or m["id"],
                       "categorie": m.get("categorie", "autre"), "cote": c, "t_in": t_in, "t_out": t_out,
                       "cout": cout, "revenu": revenu, "rend": revenu / cout - 1.0,
                       "jours": max((t_out - t_in) / JOUR, 1 / 24), "motif": motif})
        libre_a = t_out
        if len(trades) >= strat["max_entrees"]:
            break
    return trades


def tous_les_trades(marches, nom, params, couts=None):
    out = []
    for m in marches:
        out.extend(simuler_marche(m, nom, params, couts))
    out.sort(key=lambda x: x["t_in"])
    return out


# ---------- mesures ----------
def t_par_evenement(trades):
    """t de Student du rendement moyen, un seul point par événement (les marchés d'un même événement sont liés)."""
    par_evt = {}
    for x in trades:
        par_evt.setdefault(x["evenement"], []).append(x["rend"])
    r = np.array([np.mean(v) for v in par_evt.values()])
    if len(r) < 3 or r.std(ddof=1) == 0:
        return 0.0, len(r)
    return float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))), len(r)


def metriques(trades):
    if not trades:
        return {"nb_trades": 0, "nb_evenements": 0, "gagnants_pct": 0.0, "prix_moyen": 0.0, "avantage_cts": 0.0,
                "rend_moyen_pct": 0.0, "t_stat": 0.0, "jours_moyens": 0.0, "rend_capital_temps_an_pct": 0.0,
                "pire_serie_pertes": 0}
    cout = np.array([x["cout"] for x in trades])
    revenu = np.array([x["revenu"] for x in trades])
    jours = np.array([x["jours"] for x in trades])
    t_stat, nb_evt = t_par_evenement(trades)
    serie = pire = 0
    for x in sorted(trades, key=lambda x: x["t_out"]):
        serie = serie + 1 if x["revenu"] < x["cout"] else 0
        pire = max(pire, serie)
    return {
        "nb_trades": len(trades), "nb_evenements": nb_evt,
        "gagnants_pct": round(100 * float((revenu > cout).mean()), 1),
        "prix_moyen": round(float(cout.mean()), 4),
        "avantage_cts": round(100 * float((revenu - cout).mean()), 2),           # gain moyen par part, en centimes
        "rend_moyen_pct": round(100 * float((revenu / cout - 1).mean()), 2),
        "t_stat": round(t_stat, 2),
        "jours_moyens": round(float(jours.mean()), 1),
        # gain total rapporté aux dollars-jours immobilisés (1 part par trade), ramené à l'année
        "rend_capital_temps_an_pct": round(100 * 365 * float((revenu - cout).sum() / (cout * jours).sum()), 1),
        "pire_serie_pertes": pire,
    }


def portefeuille_simule(trades, par_id, capital=config.CAPITAL_DEPART, part=config.PART_PAR_MARCHE):
    """Rejoue 100 dollars avec les limites du bot. Valorisation quotidienne au prix du jour (pas au coût)."""
    cash, ouverts, prises, ignores, seq = capital, [], [], 0, 0
    for x in sorted(trades, key=lambda x: x["t_in"]):
        while ouverts and ouverts[0][0] <= x["t_in"]:
            cash += heapq.heappop(ouverts)[2]["retour"]
        valeur = cash + sum(o[2]["mise"] for o in ouverts)
        mise = min(part * valeur, cash - config.RESERVE_CASH * valeur)
        meme_evt = sum(1 for o in ouverts if o[2]["evenement"] == x["evenement"])
        meme_cat = sum(o[2]["mise"] for o in ouverts if o[2]["categorie"] == x["categorie"])
        if (mise < config.ORDRE_MIN or len(ouverts) >= config.POSITIONS_MAX
                or any(o[2]["marche"] == x["marche"] for o in ouverts)
                or meme_evt >= config.POSITIONS_MAX_PAR_EVENEMENT
                or meme_cat + mise > config.PART_MAX_CATEGORIE * valeur):
            ignores += 1
            continue
        parts = mise / x["cout"]
        pos = {**x, "mise": mise, "parts": parts, "retour": parts * x["revenu"]}
        cash -= mise
        seq += 1
        heapq.heappush(ouverts, (x["t_out"], seq, pos))
        prises.append(pos)
    if not prises:
        return {"nb_trades": 0, "ignores": ignores, "rendement_pct": 0.0, "rendement_an_pct": 0.0,
                "drawdown_max_pct": 0.0, "exposition_moyenne_pct": 0.0, "valeur_finale": capital, "courbe": []}
    debut, fin = prises[0]["t_in"], max(x["t_out"] for x in prises)
    jours = np.arange(debut, fin + JOUR, JOUR)
    courbe, realise, k, actifs, expo = [], 0.0, 0, [], []
    for d in jours:
        while k < len(prises) and prises[k]["t_in"] <= d:
            actifs.append(prises[k])
            k += 1
        encore, latent, engage = [], 0.0, 0.0
        for x in actifs:
            if x["t_out"] <= d:
                realise += x["retour"] - x["mise"]
                continue
            m = par_id[x["marche"]]
            j = int(np.searchsorted(m["t"], d, side="right")) - 1
            prix = float(m["p"][max(j, 0)])
            latent += x["parts"] * (prix if x["cote"] == 0 else 1.0 - prix) - x["mise"]
            engage += x["mise"]
            encore.append(x)
        actifs = encore
        v = capital + realise + latent
        courbe.append((float(d), v))
        expo.append(engage / v if v > 0 else 0.0)
    final = capital + sum(x["retour"] - x["mise"] for x in prises)
    courbe.append((float(fin), final))
    vals = np.array([v for _, v in courbe])
    dd = float(((np.maximum.accumulate(vals) - vals) / np.maximum.accumulate(vals)).max())
    duree_j = max((fin - debut) / JOUR, 1.0)
    an = (final / capital) ** (365 / duree_j) - 1 if final > 0 and duree_j >= 30 else None
    pas = max(1, len(courbe) // 150)
    return {"nb_trades": len(prises), "ignores": ignores,
            "rendement_pct": round(100 * (final / capital - 1), 2),
            "rendement_an_pct": round(100 * an, 1) if an is not None else round(100 * (final / capital - 1), 2),
            "drawdown_max_pct": round(100 * dd, 1), "exposition_moyenne_pct": round(100 * float(np.mean(expo)), 0),
            "duree_jours": round(duree_j, 0), "valeur_finale": round(final, 2),
            "courbe": [{"t": api.iso(t), "v": round(v, 2)} for t, v in courbe[::pas]]}


# ---------- protocole apprentissage / test ----------
def coupure(marches):
    debut = min(float(m["t"][0]) for m in marches)
    fin = max(float(m["cloture"]) for m in marches)
    return debut, fin, debut + PART_APPRENTISSAGE * (fin - debut)


def choisir_parametres(marches, nom, t_coupe):
    """Meilleure combinaison de la grille sur la période d'apprentissage seulement (trades réglés avant la coupure)."""
    meilleur, meilleur_score, essais = None, -math.inf, []
    for params in STRATEGIES[nom]["grille"]:
        tr = [x for x in tous_les_trades(marches, nom, params) if x["t_out"] < t_coupe]
        t_stat, _ = t_par_evenement(tr)
        score = t_stat if len(tr) >= TRADES_MIN_GRILLE else -math.inf
        essais.append({"parametres": params, "nb_trades": len(tr), "t_stat": round(t_stat, 2)})
        if score > meilleur_score:
            meilleur, meilleur_score = params, score
    return meilleur or STRATEGIES[nom]["grille"][0], essais


def choisir(resultats):
    """Applique la règle de sélection. Retourne (nom ou None, raison). Remplit eligible / refus de chaque stratégie."""
    ref = next((s for s in resultats if s["nom"] == REFERENCE), None)
    ref_rend = ref["oos"]["rend_capital_temps_an_pct"] if ref else 0.0
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
        if o["rend_capital_temps_an_pct"] <= max(0.0, ref_rend):
            refus.append("ne bat pas la référence hasard sur le capital immobilisé")
        if s["portefeuille"]["drawdown_max_pct"] > DD_MAX:
            refus.append(f"pire baisse trop forte ({s['portefeuille']['drawdown_max_pct']:.0f} %)")
        if s["scenarios"]["frais_actuels"]["rend_moyen_pct"] <= 0:
            refus.append("ne survit pas aux frais taker actuels")
        s["eligible"], s["refus"] = not refus, refus
        if not refus:
            eligibles.append(s)
    if not eligibles:
        return None, "Aucune stratégie ne remplit la règle de sélection sur la période jamais vue."
    s = max(eligibles, key=lambda x: x["portefeuille"]["rendement_an_pct"])
    return s["nom"], (f"Meilleur rendement annualisé du portefeuille simulé ({s['portefeuille']['rendement_an_pct']:+.1f} %) "
                      f"parmi les {len(eligibles)} stratégie(s) éligible(s).")


def analyser(marches, infos, journal=print):
    par_id = {m["id"]: m for m in marches}
    debut, fin, t_coupe = coupure(marches)
    resultats = []
    for nom, strat in STRATEGIES.items():
        journal(f"Test de {nom} ({len(strat['grille'])} combinaisons) ...")
        params, essais = choisir_parametres(marches, nom, t_coupe)
        base = tous_les_trades(marches, nom, params)
        train = [x for x in base if x["t_out"] < t_coupe]
        oos = [x for x in base if x["t_in"] >= t_coupe]
        scen = {}
        for cle in ("frais_actuels", "spread_double"):
            m = metriques([x for x in tous_les_trades(marches, nom, params, SCENARIOS[cle]) if x["t_in"] >= t_coupe])
            scen[cle] = {k: m[k] for k in ("nb_trades", "rend_moyen_pct", "t_stat", "rend_capital_temps_an_pct")}
        pf = portefeuille_simule(oos, par_id)
        resultats.append({"nom": nom, "description": strat["description"], "parametres_retenus": params,
                          "nb_combos": len(strat["grille"]), "essais_apprentissage": essais,
                          "apprentissage": metriques(train), "oos": metriques(oos), "scenarios": scen,
                          "portefeuille": {k: v for k, v in pf.items() if k != "courbe"}, "courbe": pf["courbe"]})
    nom, raison = choisir(resultats)
    valide = nom is not None
    defaut = next(s for s in resultats if s["nom"] == config.STRATEGIE_DEFAUT)
    elu = next(s for s in resultats if s["nom"] == nom) if valide else defaut
    ref = next(s for s in resultats if s["nom"] == REFERENCE)
    prefixe = "DONNÉES FICTIVES (test technique, aucune conclusion à en tirer). " if infos["source"] == "synthetique" else ""
    o, pf = elu["oos"], elu["portefeuille"]
    if valide:
        verdict = (f"{prefixe}Sur la période jamais vue et coûts déduits, {nom} passe la règle fixée à l'avance : "
                   f"{o['nb_trades']} trades, {o['gagnants_pct']:.0f} % de gagnants pour un prix moyen payé de "
                   f"{o['prix_moyen']:.3f}, soit {o['avantage_cts']:+.2f} centime(s) par part (t = {o['t_stat']:.2f}). "
                   f"Portefeuille simulé de 100 dollars : {pf['rendement_pct']:+.1f} % en {pf.get('duree_jours', 0):.0f} jours, "
                   f"pire baisse {pf['drawdown_max_pct']:.0f} %. Cela reste un test sur le passé avec un écart de prix "
                   "supposé : le paper trading sur le vrai carnet dira si l'avantage existe encore.")
    else:
        if o["rend_moyen_pct"] > 0:
            etat = (f"gagne un peu sur la période jamais vue ({o['rend_moyen_pct']:+.2f} % par trade, "
                    f"t = {o['t_stat']:.2f}) mais sans preuve suffisante")
        else:
            etat = (f"perd de l'argent sur la période jamais vue ({o['rend_moyen_pct']:+.2f} % par trade, "
                    f"{o['gagnants_pct']:.0f} % de gagnants pour un prix moyen payé de {o['prix_moyen']:.3f})")
        verdict = (f"{prefixe}Aucune des {len(resultats) - 1} stratégies testées ne passe la règle fixée à l'avance : "
                   "aucun avantage prouvé une fois les coûts déduits. Le bot tourne donc en MODE OBSERVATION, à "
                   f"mises réduites, avec {elu['nom']}, qui {etat}. Il ne faut pas en attendre de gain : "
                   f"la référence au hasard fait {ref['oos']['rend_moyen_pct']:+.2f} % par trade.")
    ecarts = np.concatenate([np.diff(m["t"]) for m in marches[:500]])
    nb_combos = sum(s["nb_combos"] for s in resultats)
    avertissements = [
        "L'historique ne contient pas le carnet d'ordres : le prix payé est le prix de l'historique plus un demi-écart "
        "supposé (1 centime au minimum). Sur un marché peu liquide, l'écart réel peut être bien plus large.",
        "Frais taker : champ takerBaseFee du marché s'il existe, sinon l'hypothèse de la configuration. Le scénario "
        "« frais actuels » applique 1000 points de base à tous les marchés.",
        "Les marchés sont choisis d'après leur volume final, connu seulement après coup : léger biais favorable.",
        "L'échéance utilisée est celle affichée par Gamma aujourd'hui ; elle a pu être modifiée pendant la vie du marché.",
        "Près de l'échéance, un prix de 95 % peut refléter un résultat déjà connu mais pas encore réglé (risque de "
        "litige) : le rendement paraît facile mais le capital reste bloqué jusqu'au règlement.",
        "Le rendement « sur capital immobilisé » suppose que chaque dollar libéré est replacé aussitôt : le portefeuille "
        "simulé, lui, respecte les limites réelles du bot.",
        f"{nb_combos} combinaisons de paramètres essayées, toutes sur la période d'apprentissage ; la période de test "
        "n'a servi qu'une fois par stratégie.",
        "Les performances passées, même sur une période jamais vue, ne garantissent rien pour la suite.",
    ]
    return {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": infos["source"], "nb_marches": len(marches),
        "nb_evenements": len({m.get("evenement") or m["id"] for m in marches}),
        "periode": {"debut": api.iso(debut), "fin": api.iso(fin), "coupure": api.iso(t_coupe)},
        "pas_median_min": round(float(np.median(ecarts)) / 60, 0) if len(ecarts) else None,
        "couts": {"demi_spread": "max(1 centime, 2 % x min(prix, 1 - prix))",
                  "frais": "takerBaseFee / 10000 x min(prix, 1 - prix) par part",
                  "frais_bps_si_absent": config.FRAIS_BPS_SI_ABSENT, "frais_actuels_bps": FRAIS_ACTUELS_BPS},
        "limites_portefeuille": {"part_par_marche": config.PART_PAR_MARCHE, "positions_max": config.POSITIONS_MAX,
                                 "reserve_cash": config.RESERVE_CASH},
        "regle_selection": REGLE, "nb_combos_total": nb_combos, "reference": REFERENCE,
        "strategies": resultats,
        "choix": {"nom": elu["nom"], "parametres": elu["parametres_retenus"], "valide": valide, "raison": raison},
        "verdict": verdict, "avertissements": avertissements,
    }


# ---------- sorties ----------
def _p(v):
    return f"{v:+.2f} %".replace(".", ",")


def ecrire(resultat, dossier=SORTIE):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "research_poly.json").write_text(json.dumps(resultat, ensure_ascii=False, separators=(",", ":")))
    r = resultat
    lignes = [
        "# Recherche Polymarket : quelles stratégies résistent aux coûts ?", "",
        f"Généré le {r['genere_le']} · source : {r['source']} · {r['nb_marches']} marchés résolus "
        f"({r['nb_evenements']} événements) du {r['periode']['debut'][:10]} au {r['periode']['fin'][:10]}.",
        f"Période jamais vue (test) : à partir du {r['periode']['coupure'][:10]}. "
        f"Pas médian de l'historique : {r['pas_median_min']} min.", "",
        "## Verdict", "", r["verdict"], "",
        f"Choix pour le bot : **{r['choix']['nom']}** {json.dumps(r['choix']['parametres'], ensure_ascii=False)} "
        f"({'validée' if r['choix']['valide'] else 'NON validée, mode observation'}). {r['choix']['raison']}", "",
        "## Règle de sélection (fixée avant les résultats)", "", r["regle_selection"], "",
        "## Résultats sur la période jamais vue, coûts déduits", "",
        "| Stratégie | Trades | Gagnants | Prix moyen payé | Gain par part | Rendement par trade | t | Jours bloqués | "
        "Capital immobilisé (par an) | Pire série | Portefeuille 100 $ | Pire baisse | Avec frais actuels | Éligible |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in r["strategies"]:
        o, pf = s["oos"], s["portefeuille"]
        lignes.append(
            f"| {s['nom']} | {o['nb_trades']} | {o['gagnants_pct']:.0f} % | {o['prix_moyen']:.3f} | "
            f"{o['avantage_cts']:+.2f} c | {_p(o['rend_moyen_pct'])} | {o['t_stat']:.2f} | {o['jours_moyens']:.1f} | "
            f"{o['rend_capital_temps_an_pct']:+.0f} % | {o['pire_serie_pertes']} | {_p(pf['rendement_pct'])} "
            f"({pf['nb_trades']} trades) | {pf['drawdown_max_pct']:.0f} % | "
            f"{_p(s['scenarios']['frais_actuels']['rend_moyen_pct'])} | {'oui' if s['eligible'] else 'non'} |")
    lignes += ["", "## Détail par stratégie", ""]
    for s in r["strategies"]:
        a = s["apprentissage"]
        lignes += [f"### {s['nom']}", "", s["description"], "",
                   f"- Paramètres retenus sur l'apprentissage : `{json.dumps(s['parametres_retenus'], ensure_ascii=False)}` "
                   f"({s['nb_combos']} combinaison(s) essayée(s))",
                   f"- Apprentissage : {a['nb_trades']} trades, {_p(a['rend_moyen_pct'])} par trade, t = {a['t_stat']:.2f}",
                   f"- Test avec écart de prix doublé et frais actuels : "
                   f"{_p(s['scenarios']['spread_double']['rend_moyen_pct'])} par trade",
                   "- Refus : " + ("aucun, stratégie éligible" if s["eligible"] else " ; ".join(s["refus"])), ""]
    lignes += ["## Limites à garder en tête", ""] + [f"- {a}" for a in r["avertissements"]] + [""]
    (dossier / "research_poly.md").write_text("\n".join(lignes))


# ---------- données réelles ----------
def _historique_marche(m, journal):
    """Historique horaire de la première issue, avec replis si l'API ne renvoie rien pour un marché fermé."""
    jeton = m["jetons"][0]
    essais = [{"interval": "max", "fidelity": 60}]
    fin = m.get("ferme_le") or m.get("echeance")
    if fin:
        debut = max(m.get("debut") or (fin - 120 * JOUR), fin - 120 * JOUR)
        essais.append("fenetres")
    essais.append({"interval": "max", "fidelity": 720})
    meilleur = []
    for e in essais:
        try:
            if e == "fenetres":
                pts, a = [], debut
                while a < fin + JOUR:
                    b = min(a + 14 * JOUR, fin + JOUR)
                    pts.extend(api.historique(jeton, startTs=int(a), endTs=int(b), fidelity=60))
                    a = b
                pts = sorted(dict(pts).items())
            else:
                pts = api.historique(jeton, **e)
        except Exception as exc:
            journal(f"  historique indisponible pour {m['id']} : {exc}")
            pts = []
        if len(pts) > len(meilleur):
            meilleur = pts
        if len(meilleur) >= 5 * POINTS_MIN:
            break
    return meilleur


def _construire(m, pts):
    """Marché Gamma résolu + historique -> enregistrement de recherche, ou None si inutilisable."""
    final = api.issue_finale(m)
    if final is None:
        return None
    cloture = m.get("ferme_le") or max(pts[-1][0] if pts else 0, m.get("echeance") or 0)
    pts = [(t, p) for t, p in pts if t <= cloture]
    if len(pts) < POINTS_MIN:
        return None
    return {"id": m["id"], "question": m["question"], "evenement": m["evenement"], "categorie": m["categorie"],
            "oui_non": m["issues"][0].strip().lower() == "yes", "fin": m.get("echeance"), "cloture": float(cloture),
            "issue0": final[0], "frais_bps": m.get("frais_bps"), "volume": m.get("volume"),
            "t": np.array([t for t, _ in pts], dtype=float), "p": np.array([p for _, p in pts], dtype=float)}


def telecharger(mois=MOIS, par_mois=PAR_MOIS, journal=print, maintenant=None):
    """Marchés binaires résolus des derniers mois, avec historique. Cache : polybot/cache/hist/<id>.json."""
    hist_dir = CACHE / "hist"
    hist_dir.mkdir(parents=True, exist_ok=True)
    maintenant = maintenant or time.time()
    depart = time.time()
    retenus = {}
    for k in range(mois):
        a, b = maintenant - (k + 1) * 30 * JOUR, maintenant - k * 30 * JOUR
        base = {"closed": "true", "end_date_min": api.iso(a), "end_date_max": api.iso(b)}
        lot = api.marches({**base, "order": "volumeNum", "ascending": "false", "volume_num_min": int(VOLUME_MIN)},
                          pages=PAGES_PAR_MOIS)
        if not lot:     # repli si le tri ou le filtre de volume n'est pas accepté
            lot = api.marches(base, pages=PAGES_PAR_MOIS * 3)
        ok = []
        for m in sorted(lot, key=lambda x: -(x["volume"] or 0)):
            duree = (m["echeance"] - m["debut"]) / JOUR if m.get("echeance") and m.get("debut") else None
            if (m["volume"] or 0) < VOLUME_MIN or api.issue_finale(m) is None or m["id"] in retenus:
                continue
            if duree is not None and duree < DUREE_MIN_J:
                continue
            ok.append(m)
        for m in ok[:par_mois]:
            retenus[m["id"]] = m
        journal(f"Mois -{k + 1} : {len(lot)} marchés lus, {min(len(ok), par_mois)} retenus")
    marches, lus, vides = [], 0, 0
    for m in retenus.values():
        f = hist_dir / f"{m['id']}.json"
        pts = None
        if f.exists():
            try:
                pts = [tuple(x) for x in json.loads(f.read_text())]
            except Exception:
                pts = None
        if pts is None:
            if time.time() - depart > BUDGET_TELECHARGEMENT_S:
                continue        # budget de temps épuisé : on fera le reste au prochain lancement (cache)
            pts = _historique_marche(m, journal)
            f.write_text(json.dumps(pts))
            lus += 1
            if lus % 200 == 0:
                journal(f"  {lus} historiques téléchargés ...")
        r = _construire(m, pts)
        if r:
            marches.append(r)
        else:
            vides += 1
    journal(f"{len(marches)} marchés utilisables, {vides} écartés (historique trop court ou non résolu), "
            f"{lus} historiques téléchargés, {api.COMPTEUR['requetes']} requêtes")
    return marches


# ---------- données fictives ----------
def synthetique(nb=600, graine=7, biais=0.0, jours=420):
    """Marchés fictifs dont le prix est une vraie probabilité (martingale) : par construction, aucune stratégie n'a
    d'avantage et toutes doivent perdre à peu près les coûts. `biais` > 0 rend les favoris sous-cotés (sert aux
    tests : la recherche doit alors le détecter)."""
    rnd = np.random.default_rng(graine)
    base = 1_750_000_000
    marches = []
    for i in range(nb):
        duree_h = int(rnd.integers(72, 24 * 40))
        debut = base + float(rnd.uniform(0, jours * JOUR - duree_h * H))
        p = np.empty(duree_h)
        p[0] = rnd.uniform(0.08, 0.92)
        bruit = rnd.normal(0, 0.035, duree_h)
        saut = rnd.random(duree_h) < 0.01
        for j in range(1, duree_h):
            pas = bruit[j] * math.sqrt(p[j - 1] * (1 - p[j - 1])) * (4 if saut[j] else 1)
            p[j] = min(0.995, max(0.005, p[j - 1] + pas))
        vrai = min(1.0, max(0.0, p[-1] + biais * (1 if p[-1] > 0.5 else -1) * (1 - abs(2 * p[-1] - 1))))
        t = debut + H * np.arange(duree_h)
        marches.append({"id": f"s{i}", "question": f"Marché fictif {i}", "evenement": f"e{i // 2}",
                        "categorie": ["sport", "crypto", "politique", "autre"][i % 4], "oui_non": i % 3 != 0,
                        "fin": float(t[-1] + H), "cloture": float(t[-1] + 3 * H),
                        "issue0": 1.0 if rnd.random() < vrai else 0.0, "frais_bps": 0.0 if i % 2 else None,
                        "volume": 50000.0, "t": t, "p": np.round(p, 3)})
    return marches


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recherche de stratégie Polymarket (marchés résolus)")
    ap.add_argument("--synthetic", action="store_true", help="marchés fictifs, hors ligne")
    ap.add_argument("--mois", type=int, default=MOIS)
    ap.add_argument("--par-mois", type=int, default=PAR_MOIS)
    ap.add_argument("--sortie", default=str(SORTIE))
    args = ap.parse_args(argv)
    if args.synthetic:
        marches, infos = synthetique(), {"source": "synthetique"}
    else:
        marches, infos = telecharger(args.mois, args.par_mois), {"source": "polymarket"}
        if len(marches) < 100:
            raise SystemExit(f"Trop peu de marchés utilisables ({len(marches)}) : pas de conclusion possible, "
                             "aucun fichier écrit.")
    resultat = analyser(marches, infos)
    ecrire(resultat, Path(args.sortie))
    print(resultat["verdict"])
    print("Choix :", resultat["choix"]["nom"], resultat["choix"]["parametres"],
          "(validée)" if resultat["choix"]["valide"] else "(non validée)")
    return resultat


if __name__ == "__main__":
    main()
