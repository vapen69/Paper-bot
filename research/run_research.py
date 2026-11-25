"""Recherche de stratégie : télécharge l'historique, teste toutes les candidates en marche avant,
écrit data_out/research.json (pour le tableau de bord) et data_out/research.md (résumé lisible).

    python -m research.run_research                 # données réelles Coinbase (internet requis)
    python -m research.run_research --synthetic     # données fictives, hors ligne (vérifie que tout tourne)

RÈGLE DE SÉLECTION, écrite avant de voir le moindre résultat (fonction choisir) :
1. sont éligibles les stratégies dont le Sharpe hors échantillon, frais déduits, dépasse celui du BTC conservé,
   avec un rendement annuel positif et un Sharpe non suspect (<= 3) ;
2. parmi elles, on retient le meilleur Calmar (rendement annuel / pire baisse) ;
3. si aucune n'est éligible, on le dit, et on recommande par défaut la plus robuste : la plus faible baisse
   maximale parmi celles qui gagnent de l'argent en étant investies au moins 10 % du temps ; à défaut, la
   tendance BTC + ETH (tendance_sma).
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bot import config
from . import data, walkforward as wf
from .strategies import STRATEGIES

RACINE = Path(__file__).resolve().parent.parent
DEFAUT = "tendance_sma"
PROBA_SOLIDE = 0.90

REGLE = ("Éligible si Sharpe hors échantillon net de frais > Sharpe du BTC conservé, rendement annuel > 0 et "
         "Sharpe <= 3. Parmi les éligibles : meilleur Calmar. Sinon : plus faible baisse maximale parmi les "
         "stratégies gagnantes investies au moins 10 % du temps, à défaut tendance_sma.")


def choisir(strategies, btc):
    """Applique la règle de sélection. Retourne (nom, raison, bat_btc)."""
    eligibles = [s for s in strategies if s["oos"]["sharpe"] > btc["sharpe"]
                 and s["oos"]["cagr_pct"] > 0 and not s["oos"]["sharpe_suspect"]]
    if eligibles:
        s = max(eligibles, key=lambda x: x["oos"]["calmar"])
        return s["nom"], (f"Meilleur Calmar ({s['oos']['calmar']:.2f}) parmi les {len(eligibles)} stratégie(s) dont le "
                          f"Sharpe hors échantillon ({s['oos']['sharpe']:.2f}) dépasse celui du BTC conservé "
                          f"({btc['sharpe']:.2f}), frais déduits."), True
    robustes = [s for s in strategies if s["oos"]["cagr_pct"] > 0 and s["oos"]["temps_investi_pct"] >= 10]
    if robustes:
        s = min(robustes, key=lambda x: x["oos"]["drawdown_max_pct"])
        return s["nom"], ("Aucune stratégie ne bat le BTC conservé en Sharpe hors échantillon. Choix par défaut : la plus "
                          f"robuste (baisse maximale la plus faible, {s['oos']['drawdown_max_pct']:.1f} %) parmi celles "
                          "qui restent gagnantes."), False
    return DEFAUT, ("Aucune stratégie ne bat le BTC conservé et aucune n'est gagnante hors échantillon. "
                    "Choix par défaut : suivi de tendance BTC + ETH, le plus simple et le moins coûteux en frais."), False


def analyser(ouv, clo, infos, journal=print):
    resultats, btc_df = [], None
    for strat in STRATEGIES:
        journal(f"Test de {strat['nom']} ...")
        r = wf.marche_avant(ouv, clo, strat)
        oos = r["oos"]
        if btc_df is None:
            btc_df = wf.btc_hold(ouv, clo, oos.index)
        m = wf.metriques(oos)
        m["proba_sharpe_sup_btc"] = wf.proba_sharpe_superieur(oos["rend"], btc_df["rend"])
        freq = Counter(json.dumps(s["parametres"], sort_keys=True) for s in r["segments"])
        resultats.append({
            "nom": strat["nom"], "description": strat["description"],
            "parametres_retenus": r["parametres_live"],          # choisis sur les 12 derniers mois : à utiliser en direct
            "oos": m, "courbe": wf.courbe_journaliere(oos),
            "nb_combos": r["nb_combos"], "grille": strat["grille"],
            "stabilite_parametres_pct": round(100 * freq.most_common(1)[0][1] / len(r["segments"]), 0),
            "segments": r["segments"],
        })
    btc = wf.metriques(btc_df)
    nb_total = sum(s["nb_combos"] for s in resultats)
    seuil = wf.sharpe_du_hasard(nb_total, btc["duree_ans"])
    for s in resultats:
        s["oos"]["bat_btc_sharpe"] = bool(s["oos"]["sharpe"] > btc["sharpe"])
        s["oos"]["depasse_seuil_hasard"] = bool(s["oos"]["sharpe"] > seuil)
    nom, raison, bat = choisir(resultats, btc)
    elu = next(s for s in resultats if s["nom"] == nom)
    classement = [s["nom"] for s in sorted(resultats, key=lambda x: x["oos"]["calmar"], reverse=True)]
    oos_debut, oos_fin = elu["courbe"][0]["t"], elu["courbe"][-1]["t"]
    proba = elu["oos"]["proba_sharpe_sup_btc"]
    if infos["source"] == "synthetique":
        prefixe = "DONNÉES FICTIVES (test technique, aucune conclusion à en tirer). "
    else:
        prefixe = ""
    if bat:
        solide = proba >= PROBA_SOLIDE and elu["oos"]["depasse_seuil_hasard"]
        verdict = (f"{prefixe}Hors échantillon et frais déduits, {nom} fait mieux que garder du BTC à risque égal : "
                   f"Sharpe {elu['oos']['sharpe']:.2f} contre {btc['sharpe']:.2f}, rendement annuel "
                   f"{elu['oos']['cagr_pct']:+.1f} % contre {btc['cagr_pct']:+.1f} %, pire baisse "
                   f"{elu['oos']['drawdown_max_pct']:.0f} % contre {btc['drawdown_max_pct']:.0f} %. "
                   + ("L'avantage résiste aux tests de hasard." if solide else
                      f"Mais l'avantage n'est PAS prouvé statistiquement (probabilité de {proba * 100:.0f} % que le Sharpe soit "
                      f"réellement supérieur, seuil de chance {seuil:.2f}) : à confirmer en paper trading avant d'y croire."))
    else:
        if elu["oos"]["cagr_pct"] > 0:
            suite = (f"Par défaut, le bot peut utiliser {nom}, qui limite surtout les baisses "
                     f"({elu['oos']['drawdown_max_pct']:.0f} % contre {btc['drawdown_max_pct']:.0f} % pour le BTC), "
                     "sans promesse de gain supérieur.")
        else:
            suite = (f"Le choix par défaut, {nom}, perd lui aussi de l'argent sur la période "
                     f"({elu['oos']['cagr_pct']:+.1f} % par an) : rien ici ne justifie de trader plutôt que de ne rien faire.")
        verdict = (f"{prefixe}Aucune des {len(resultats)} stratégies testées ne bat le simple fait de garder du BTC à risque "
                   f"égal, hors échantillon et frais déduits (Sharpe du BTC : {btc['sharpe']:.2f}). {suite}")
    avertissements = [
        "Biais de survie : l'univers est composé d'actifs encore liquides aujourd'hui, ce qui avantage les rotations.",
        "Les performances passées, même hors échantillon, ne garantissent rien pour la suite.",
        f"{nb_total} combinaisons de paramètres essayées au total : en gardant la meilleure par pure chance, on "
        f"s'attendrait déjà à un Sharpe d'environ {seuil:.2f}.",
        "Ordre minimum de 5 EUR ignoré ; exécution supposée à l'ouverture de l'heure suivante avec 0,10 % de slippage.",
    ]
    if infos["devise"] == "EUR" and infos["source"] == "coinbase":
        avertissements.append("Paires USD converties en EUR avec le taux implicite BTC-USD / BTC-EUR.")
    suspects = [s["nom"] for s in resultats if s["oos"]["sharpe_suspect"]]
    if suspects:
        avertissements.append("Sharpe > 3 jugé suspect (erreur ou surajustement probable), exclu du choix : " + ", ".join(suspects))
    return {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": infos["source"], "devise": infos["devise"], "actifs": infos["actifs"],
        "periode": {"donnees_debut": wf._iso(clo.index[0]), "donnees_fin": wf._iso(clo.index[-1]),
                    "oos_debut": oos_debut, "oos_fin": oos_fin, "oos_ans": btc["duree_ans"],
                    "apprentissage_jours": wf.TRAIN_H // 24, "test_jours": wf.TEST_H // 24},
        "couts": {"frais": config.FRAIS, "slippage": config.SLIPPAGE},
        "regle_selection": REGLE,
        "nb_combos_total": nb_total, "sharpe_seuil_hasard": seuil,
        "strategies": resultats,
        "btc_hold": {"nom": "btc_hold", "description": "Acheter du BTC au début et ne plus y toucher.",
                     "oos": btc, "courbe": wf.courbe_journaliere(btc_df)},
        "classement": classement,
        "choix": {"nom": nom, "parametres": elu["parametres_retenus"], "raison": raison, "bat_btc": bat},
        "verdict": verdict,
        "avertissements": avertissements,
    }


def en_markdown(r):
    p, btc = r["periode"], r["btc_hold"]["oos"]

    def ligne(nom, m, proba="", stab=""):
        return (f"| {nom} | {m['rendement_total_pct']:+.1f} % | {m['cagr_pct']:+.1f} % | {m['drawdown_max_pct']:.1f} % | "
                f"{m['sharpe']:.2f} | {m['sortino']:.2f} | {m['calmar']:.2f} | {m['turnover_annuel']:.1f} x | "
                f"{m['frais_eur_pour_100']:.2f} | {m['temps_investi_pct']:.0f} % | {proba} | {stab} |")

    par_nom = {s["nom"]: s for s in r["strategies"]}
    L = ["# Recherche de stratégie", ""]
    if r["source"] == "synthetique":
        L += ["**ATTENTION : résultats calculés sur des DONNÉES FICTIVES (test technique). Ne rien en conclure.**", ""]
    L += [f"Généré le {r['genere_le']}. Données : {r['source']}, {len(r['actifs'])} actifs, en {r['devise']}.",
          f"Période hors échantillon : du {p['oos_debut'][:10]} au {p['oos_fin'][:10]} ({p['oos_ans']} ans). "
          f"Paramètres choisis sur {p['apprentissage_jours']} jours, puis testés sur les {p['test_jours']} jours suivants, "
          "jamais vus au moment du choix.",
          f"Coûts : {r['couts']['frais'] * 100:.2f} % de frais + {r['couts']['slippage'] * 100:.2f} % de slippage par ordre.",
          "", "## Verdict", "", r["verdict"], "",
          f"**Stratégie retenue : {r['choix']['nom']}** avec les paramètres `{json.dumps(r['choix']['parametres'])}`.",
          "", r["choix"]["raison"], "",
          "## Classement hors échantillon (par Calmar, frais déduits)", "",
          "| Stratégie | Rendement | Par an | Pire baisse | Sharpe | Sortino | Calmar | Turnover/an | Frais (EUR pour 100) "
          "| Temps investi | Proba Sharpe > BTC | Stabilité des paramètres |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for nom in r["classement"]:
        s = par_nom[nom]
        marque = " (suspect)" if s["oos"]["sharpe_suspect"] else ""
        L.append(ligne(f"{nom}{marque}", s["oos"], f"{s['oos']['proba_sharpe_sup_btc'] * 100:.0f} %",
                       f"{s['stabilite_parametres_pct']:.0f} %"))
    L += [ligne("**BTC conservé**", btc, "-", "-"), "",
          "Lecture : Sharpe et Sortino = rendement par unité de risque (plus haut = mieux). Calmar = rendement annuel "
          "divisé par la pire baisse. Proba Sharpe > BTC : autour de 50 % = aucune différence démontrée, au-dessus de "
          "90 % = avantage crédible. Stabilité : part des trimestres où les mêmes paramètres ont été choisis.",
          "", "## Paramètres à utiliser en direct (choisis sur les 12 derniers mois)", ""]
    for s in r["strategies"]:
        L.append(f"- **{s['nom']}** : `{json.dumps(s['parametres_retenus'])}` ({s['nb_combos']} combinaison(s) testée(s)). "
                 f"{s['description']}")
    L += ["", "## Règle de sélection (fixée avant de voir les résultats)", "", r["regle_selection"], "",
          "## Limites à garder en tête", ""] + [f"- {a}" for a in r["avertissements"]] + [""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recherche de stratégie en marche avant.")
    ap.add_argument("--synthetic", action="store_true", help="données fictives, sans internet")
    ap.add_argument("--annees", type=float, default=5.0, help="années d'historique horaire (défaut 5)")
    ap.add_argument("--sortie", default=None, help="dossier de sortie")
    a = ap.parse_args(argv)
    if a.synthetic:
        ouv, clo, infos = data.synthetique(min(a.annees, 4.0))
        sortie = Path(a.sortie) if a.sortie else RACINE / "research" / "sortie_synthetique"
    else:
        print("Téléchargement de l'historique Coinbase ...", flush=True)
        ouv, clo, infos = data.panneau(a.annees)
        sortie = Path(a.sortie) if a.sortie else RACINE / "data_out"
    r = analyser(ouv, clo, infos, journal=lambda m: print(m, flush=True))
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "research.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (sortie / "research.md").write_text(en_markdown(r), encoding="utf-8")
    print(f"\n{r['verdict']}\nChoix : {r['choix']['nom']} {r['choix']['parametres']}\nFichiers écrits dans {sortie}")
    return r


if __name__ == "__main__":
    main()
