"""Règles de décision, communes à la recherche (historique) et au bot en direct.

Chaque règle reçoit uniquement ce qui est connu à l'instant de la décision : les horodatages t et les prix p de
la première issue du marché (prix de la seconde = 1 - p), l'échéance annoncée `fin` et des informations fixes du
marché. Elle ne reçoit JAMAIS le résultat du marché. Elle renvoie, pour chaque indice i, de quel côté elle
voudrait acheter : -1 (rien), 0 (première issue) ou 1 (seconde issue). La décision à l'indice i ne dépend que
de t[:i+1] et p[:i+1] (vérifié par les tests en tronquant l'historique).

En direct, le bot appelle les mêmes fonctions avec l'historique disponible et regarde le dernier indice.
"""
import hashlib

import numpy as np

H = 3600.0
JOUR = 86400.0
MARGE_FIN_S = 2 * H     # jamais d'entrée à moins de 2 h de l'échéance annoncée


def _restant(t, fin):
    return (fin - t) if fin is not None else np.full(len(t), np.inf)


def favori_echeance(t, p, fin, infos, prix_min, prix_max, jours_max):
    """Acheter l'issue favorite (prix entre prix_min et prix_max) dans les jours_max jours avant l'échéance."""
    r = _restant(t, fin)
    fenetre = (r >= MARGE_FIN_S) & (r <= jours_max * JOUR)
    cote = np.full(len(t), -1)
    cote[fenetre & (p >= prix_min) & (p <= prix_max)] = 0
    cote[fenetre & (1 - p >= prix_min) & (1 - p <= prix_max)] = 1
    return cote


def longshot_fade(t, p, fin, infos, seuil_oui, prix_max, jours_max):
    """Marchés Oui/Non seulement : acheter Non quand le Oui est un outsider (prix du Oui <= seuil_oui)."""
    cote = np.full(len(t), -1)
    if not infos.get("oui_non"):
        return cote
    r = _restant(t, fin)
    ok = (r >= MARGE_FIN_S) & (r <= jours_max * JOUR) & (p <= seuil_oui) & (1 - p <= prix_max)
    cote[ok] = 1
    return cote


def _mouvement(t, p, fin, ecart, fenetre_h):
    """Variation du prix sur fenetre_h heures, mesurée uniquement avec des points passés."""
    t = np.asarray(t, dtype=float)
    j = np.searchsorted(t, t - fenetre_h * H, side="right") - 1      # dernier point au plus tard à t - fenêtre
    valide = (j >= 0)
    jj = np.clip(j, 0, None)
    valide &= (t - t[jj]) <= 2 * fenetre_h * H                        # référence pas trop ancienne
    delta = np.where(valide, p - p[jj], 0.0)
    r = _restant(t, fin)
    ok = valide & (np.abs(delta) >= ecart) & (p >= 0.08) & (p <= 0.92) & (r >= 6 * H)
    return ok, delta


def suivi_mouvement(t, p, fin, infos, ecart, fenetre_h, sortie_h):
    """Suivre un gros mouvement : acheter l'issue qui vient de monter d'au moins `ecart` en fenetre_h heures."""
    ok, delta = _mouvement(t, p, fin, ecart, fenetre_h)
    cote = np.full(len(t), -1)
    cote[ok & (delta > 0)] = 0
    cote[ok & (delta < 0)] = 1
    return cote


def contre_mouvement(t, p, fin, infos, ecart, fenetre_h, sortie_h):
    """Parier sur un excès : acheter l'issue qui vient de baisser d'au moins `ecart` en fenetre_h heures."""
    ok, delta = _mouvement(t, p, fin, ecart, fenetre_h)
    cote = np.full(len(t), -1)
    cote[ok & (delta > 0)] = 1
    cote[ok & (delta < 0)] = 0
    return cote


def _tirage(identifiant, ts):
    """Nombre pseudo-aléatoire stable dans [0, 1) qui ne dépend que du marché et de l'instant."""
    h = hashlib.sha256(f"{identifiant}:{int(ts)}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def hasard(t, p, fin, infos, proba):
    """Référence naïve : acheter une issue au hasard, à un instant au hasard, et attendre la résolution."""
    r = _restant(t, fin)
    cote = np.full(len(t), -1)
    for i in np.nonzero((r >= MARGE_FIN_S) & (p >= 0.05) & (p <= 0.95))[0]:
        u = _tirage(infos.get("id", ""), t[i])
        if u < proba:
            cote[i] = 0 if u < proba / 2 else 1
    return cote


def _grille(**axes):
    combos = [{}]
    for nom, valeurs in axes.items():
        combos = [{**c, nom: v} for c in combos for v in valeurs]
    return combos


# Grilles volontairement petites : chaque combinaison essayée augmente le risque de trouver un gagnant par chance.
STRATEGIES = {
    "favori_echeance": {
        "fn": favori_echeance, "max_entrees": 1,
        "description": "Acheter le favori (issue cotée entre 80-90 % et 97 %) dans les derniers jours avant "
                       "l'échéance et attendre la résolution.",
        "grille": _grille(prix_min=[0.80, 0.85, 0.90], prix_max=[0.97], jours_max=[1, 3, 7]),
    },
    "longshot_fade": {
        "fn": longshot_fade, "max_entrees": 1,
        "description": "Marchés Oui/Non : acheter Non quand le Oui est un outsider (5 à 15 %), jusqu'à 60 jours "
                       "avant l'échéance, et attendre la résolution.",
        "grille": _grille(seuil_oui=[0.05, 0.10, 0.15], prix_max=[0.97], jours_max=[14, 60]),
    },
    "suivi_mouvement": {
        "fn": suivi_mouvement, "max_entrees": 3,
        "description": "Suivre un gros mouvement de prix (8 à 15 points en quelques heures), sortie après 24 h "
                       "ou à la résolution.",
        "grille": _grille(ecart=[0.08, 0.15], fenetre_h=[3, 12], sortie_h=[24, None]),
    },
    "contre_mouvement": {
        "fn": contre_mouvement, "max_entrees": 3,
        "description": "Parier contre un gros mouvement de prix (retour après excès), sortie après 24 h ou à la "
                       "résolution.",
        "grille": _grille(ecart=[0.08, 0.15], fenetre_h=[3, 12], sortie_h=[24, None]),
    },
    "hasard": {
        "fn": hasard, "max_entrees": 1,
        "description": "Référence naïve : une issue au hasard, à un moment au hasard, gardée jusqu'à la résolution. "
                       "Doit perdre à peu près les coûts.",
        "grille": [{"proba": 0.005}],
    },
}
REFERENCE = "hasard"


def limite_prix(nom, params):
    """Prix maximal accepté à l'exécution pour l'issue achetée (None = pas de limite propre à la stratégie)."""
    return params.get("prix_max")


def signal_direct(nom, params, t, p, fin, infos):
    """Décision en direct : côté voulu (-1, 0 ou 1) au dernier point connu."""
    if nom not in STRATEGIES or len(t) == 0:
        return -1
    t, p = np.asarray(t, dtype=float), np.asarray(p, dtype=float)
    return int(STRATEGIES[nom]["fn"](t, p, fin, infos, **params)[-1])
