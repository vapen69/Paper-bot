"""Moteur de simulation honnête + validation "walk-forward" (marche avant).

Règles du moteur :
- le poids décidé à la clôture de l'heure t est exécuté à l'OUVERTURE de l'heure t+1 ;
- chaque euro échangé coûte frais + slippage (0,40 % + 0,10 %) ;
- on ne passe des ordres que lorsque la cible change ; entre deux, les positions dérivent avec les prix ;
- un poids négatif est une vente à découvert (perpétuel simulé) : gain si le prix baisse, perte non plafonnée
  s'il monte, plus un coût de financement horaire ; exposition brute cible limitée à 100 % (pas de levier) ;
- l'ordre minimum de 5 EUR est ignoré (recherche).

Marche avant : on choisit les paramètres sur 12 mois (petite grille), on les applique aux 3 mois suivants,
on avance de 3 mois et on recommence. Seuls les morceaux "jamais vus" sont mis bout à bout et mesurés.
"""
import itertools

import numpy as np
import pandas as pd

from bot import config
from .strategies import CHAUFFE_J

COUT = config.FRAIS + config.SLIPPAGE     # par euro échangé
H_AN = 24 * 365
TRAIN_H = 365 * 24
TEST_H = 91 * 24
SHARPE_SUSPECT = 3.0
# Coût de financement payé par les positions short : 0,01 % toutes les 8 h (environ 11 % par an).
# HYPOTHÈSE prudente et moyenne : en réalité le financement varie d'une heure à l'autre, et quand il est
# positif ce sont les longs qui paient les shorts. Ici le short paie toujours. Les longs (spot) ne paient rien.
FUNDING_SHORT_8H = 0.0001


def simuler(ouv, clo, poids, cout=COUT, financement_8h=FUNDING_SHORT_8H):
    """Retourne (df, poids_reels). df : rend (rendement net close à close), turnover, frais, financement,
    expo (brute) et short, par heure, en fraction du capital courant.
    poids_reels[t] : poids effectivement détenus à la clôture t (négatif = short).
    Comptabilité du short : vendre X à découvert ajoute X au cash et crée une position de valeur -X,
    qui devient -X * (prix / prix d'entrée). Le capital est toujours cash + somme des positions."""
    C = clo.to_numpy(float)
    O = ouv.reindex(columns=clo.columns).to_numpy(float)
    W = poids.reindex(index=clo.index, columns=clo.columns).fillna(0.0).to_numpy(float)
    W = np.where(np.isnan(C), 0.0, W)                    # impossible de détenir un actif pas encore coté
    W = W / np.maximum(np.abs(W).sum(axis=1, keepdims=True), 1.0)     # exposition brute cible <= 100 %
    T, N = C.shape
    nuit = np.nan_to_num(O[1:] / C[:-1], nan=1.0)        # clôture t-1 -> ouverture t
    jour = np.nan_to_num(C[1:] / O[1:], nan=1.0)         # ouverture t -> clôture t
    change = np.ones(T, bool)
    change[1:] = np.abs(W[1:] - W[:-1]).sum(axis=1) > 1e-9
    change[0] = W[0].any()
    rend, tour, frais, expo, fin, short = (np.zeros(T) for _ in range(6))
    f_h = financement_8h / 8.0
    reels = np.zeros((T, N))
    pos, cash, avant = np.zeros(N), 1.0, 1.0
    for t in range(1, T):
        pos = pos * nuit[t - 1]
        if change[t - 1]:                                # décision prise à la clôture t-1, exécutée à l'ouverture t
            total = cash + pos.sum()
            c = 0.0
            for _ in range(6):                           # le coût est payé sur le capital : petit point fixe
                cible = W[t - 1] * (total - c)
                c = cout * np.abs(cible - pos).sum()
            tour[t], frais[t] = np.abs(cible - pos).sum() / avant, c / avant
            cash, pos = total - c - cible.sum(), cible
        pos = pos * jour[t - 1]
        a_decouvert = -np.minimum(pos, 0.0).sum()
        if a_decouvert > 0:                              # financement de l'heure, sur la valeur du short
            cash -= f_h * a_decouvert
            fin[t] = f_h * a_decouvert / avant
        total = cash + pos.sum()
        if total <= 1e-12:                               # short emporté par une hausse : capital perdu, fin
            rend[t] = -1.0
            break
        rend[t], expo[t], short[t], reels[t] = total / avant - 1, np.abs(pos).sum() / total, a_decouvert / total, pos / total
        avant = total
    return pd.DataFrame({"rend": rend, "turnover": tour, "frais": frais, "financement": fin,
                         "expo": expo, "short": short}, index=clo.index), reels


def sharpe(r):
    r = np.asarray(r, float)
    s = r.std()
    return float(r.mean() / s * np.sqrt(H_AN)) if s > 0 else 0.0


def metriques(df):
    """Mesures sur une série horaire nette (colonnes rend, turnover, frais, expo). Taux sans risque = 0."""
    r = df["rend"].to_numpy(float)
    ans = len(r) / H_AN
    courbe = np.cumprod(1 + r)
    total = courbe[-1] - 1
    cagr = (1 + total) ** (1 / ans) - 1 if total > -1 else -1.0
    dd = float((1 - courbe / np.maximum.accumulate(np.maximum(courbe, 1.0))).max())
    baisse = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    sh = sharpe(r)
    capital_avant = np.concatenate([[1.0], courbe[:-1]])
    return {
        "rendement_total_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "drawdown_max_pct": round(dd * 100, 2),
        "sharpe": round(sh, 3),
        "sortino": round(float(r.mean() / baisse * np.sqrt(H_AN)) if baisse > 0 else 0.0, 3),
        "calmar": round(cagr / dd, 3) if dd > 0 else 0.0,
        "turnover_annuel": round(float(df["turnover"].sum() / ans), 2),      # 1.0 = 100 % du capital échangé par an
        "frais_eur_pour_100": round(float((df["frais"].to_numpy() * capital_avant).sum() * 100), 2),
        "financement_eur_pour_100": round(float((df["financement"].to_numpy() * capital_avant).sum() * 100), 2),
        "temps_investi_pct": round(float((df["expo"] > 0.01).mean() * 100), 1),
        "temps_short_pct": round(float((df["short"] > 0.01).mean() * 100), 1),
        "duree_ans": round(ans, 2),
        "sharpe_suspect": bool(sh > SHARPE_SUSPECT),
    }


def fenetres(n, debut=CHAUFFE_J * 24, train=TRAIN_H, test=TEST_H):
    """Découpage (a, b, c) : apprentissage sur [a, b), test sur [b, c). Les tests ne se chevauchent pas."""
    out, a = [], debut
    while a + train + 24 <= n:
        out.append((a, a + train, min(a + train + test, n)))
        a += test
    return out


def combinaisons(grille):
    cles = list(grille)
    return [dict(zip(cles, v)) for v in itertools.product(*(grille[k] for k in cles))]


def marche_avant(ouv, clo, strat, train=TRAIN_H, test=TEST_H, debut=CHAUFFE_J * 24, cout=COUT,
                 financement_8h=FUNDING_SHORT_8H):
    """Validation marche avant d'une stratégie. Critère de choix des paramètres : meilleur Sharpe net
    sur la fenêtre d'apprentissage (en cas d'égalité, la première combinaison de la grille)."""
    combos = combinaisons(strat["grille"])
    sims = [simuler(ouv, clo, strat["fonction"](clo, **p), cout, financement_8h) for p in combos]

    def meilleur(a, b):
        return int(np.argmax([sharpe(df["rend"].to_numpy()[a:b]) for df, _ in sims]))

    morceaux, detenus, segments, precedent = [], [], [], None
    for a, b, c in fenetres(len(clo), debut, train, test):
        i = meilleur(a, b)                               # n'utilise QUE [a, b)
        m = sims[i][0].iloc[b:c].copy()
        if precedent is not None and precedent != i:
            # changement de paramètres : on paie la bascule d'un portefeuille à l'autre
            ecart = float(np.abs(sims[i][1][b - 1] - sims[precedent][1][b - 1]).sum())
            m.iloc[0, m.columns.get_loc("rend")] -= cout * ecart
            m.iloc[0, m.columns.get_loc("frais")] += cout * ecart
            m.iloc[0, m.columns.get_loc("turnover")] += ecart
        precedent = i
        morceaux.append(m)
        detenus.append(sims[i][1][b:c])
        segments.append({"apprentissage": [_iso(clo.index[a]), _iso(clo.index[b - 1])],
                         "test": [_iso(clo.index[b]), _iso(clo.index[c - 1])], "parametres": combos[i]})
    if not morceaux:
        raise ValueError("historique trop court pour une validation marche avant")
    n = len(clo)
    oos = pd.concat(morceaux)
    return {"oos": oos, "segments": segments, "nb_combos": len(combos),
            "poids_oos": pd.DataFrame(np.vstack(detenus), index=oos.index, columns=clo.columns),
            "parametres_live": combos[meilleur(max(0, n - train), n)]}     # choisis sur les 12 derniers mois


def btc_hold(ouv, clo, index_oos, cout=COUT):
    """Acheter du BTC au début de la période hors échantillon et ne plus y toucher (frais d'entrée payés)."""
    df, _ = simuler(ouv[["BTC"]], clo[["BTC"]], pd.DataFrame({"BTC": 1.0}, index=clo.index), cout=0.0)
    df = df.loc[index_oos].copy()
    df.iloc[0, df.columns.get_loc("rend")] -= cout
    df.iloc[0, df.columns.get_loc("frais")] = cout
    df.iloc[0, df.columns.get_loc("turnover")] = 1.0
    df["expo"] = 1.0
    return df


def pires_hausses_short(clo, poids_oos):
    """Pire hausse de prix subie pendant qu'un actif était vendu à découvert, hors échantillon :
    sur une heure, et sur 24 h de short ininterrompu. Aucun stop n'est simulé : c'est le risque brut."""
    en_short = (poids_oos < 0).shift(1, fill_value=False)        # short détenu pendant l'heure t
    if not en_short.to_numpy().any():
        return {"pire_hausse_horaire_short_pct": None, "pire_hausse_journaliere_short_pct": None}
    c = clo.reindex(columns=poids_oos.columns)
    h = c.pct_change(fill_method=None).reindex(poids_oos.index)[en_short]
    j = c.pct_change(24, fill_method=None).reindex(poids_oos.index)[en_short.rolling(24).min() == 1]
    arrondi = lambda x: None if pd.isna(x) else round(float(x) * 100, 2)
    return {"pire_hausse_horaire_short_pct": arrondi(h.max().max()),
            "pire_hausse_journaliere_short_pct": arrondi(j.max().max())}


def proba_sharpe_superieur(r, r_ref, blocs_h=168, tirages=500, graine=0):
    """Bootstrap par blocs d'une semaine, tirages appariés : part des tirages où le Sharpe de la stratégie
    dépasse celui de la référence. Autour de 0,5 = aucune différence démontrée."""
    r, r_ref = np.asarray(r, float), np.asarray(r_ref, float)
    n, rng = len(r), np.random.default_rng(graine)
    nb = n // blocs_h + 1
    gagne = 0
    for _ in range(tirages):
        idx = (rng.integers(0, n, nb)[:, None] + np.arange(blocs_h)[None, :]).ravel()[:n] % n
        gagne += sharpe(r[idx]) > sharpe(r_ref[idx])
    return round(gagne / tirages, 3)


def sharpe_du_hasard(nb_essais, ans):
    """Garde-fou "deflated Sharpe" simplifié : Sharpe annualisé qu'on s'attend à voir par pure chance
    en gardant le meilleur de nb_essais essais sans aucun talent, sur `ans` années."""
    return round(float(np.sqrt(2 * np.log(max(nb_essais, 2))) / np.sqrt(max(ans, 1e-9))), 2)


def courbe_journaliere(df, base=100.0):
    v = base * (1 + df["rend"]).cumprod()
    j = v[v.index.hour == 23]
    if j.empty or j.index[-1] != v.index[-1]:
        j = pd.concat([j, v.iloc[[-1]]])
    return [{"t": _iso(t), "v": round(float(x), 2)} for t, x in j.items()]


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%MZ")
