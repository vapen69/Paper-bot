"""Arène Polymarket : plusieurs stratégies en argent FICTIF, côte à côte, chacune avec son propre capital.

L'arène sert à REPÉRER des pistes, pas à les prouver : avec 14 courbes, il y en aura toujours une qui monte par
chance. Aucune stratégie ne passe dans le bot en direct (polybot/) sans réussir la règle de recherche fixée à
l'avance (polybot/research.py). Le bot en direct, son état et sa stratégie ne sont jamais touchés par l'arène.

Même simulation que le bot en direct : achat en remontant le vrai carnet d'ordres, frais taker prudents, positions
gardées jusqu'à la résolution (sauf sortie programmée). Chaque stratégie simule seule sur le carnet, comme si elle
était le seul acheteur (les mises de 4 $ sont trop petites pour que cela change grand-chose).
"""

CAPITAL_DEPART = 100.0          # USDC fictifs par stratégie
REQUETES_PAR_S = 3.0            # un peu sous le bot en direct, qui tourne sur une autre machine

# ---------- rythme ----------
TICK_S = 10
PRIX_S = 30                     # valorisation des positions (carnets, en rotation)
PRIX_PAR_TICK = 40              # carnets lus au plus par valorisation
SCAN_S = 60
MOUVEMENT_S = 300
MARCHES_MOUVEMENT = 40          # marchés dont on lit l'historique horaire à chaque passage
RESOLUTION_S = 180
RESOLUTIONS_LOINTAINES = 15     # marchés dont l'échéance n'est pas passée, vérifiés à chaque passage (rotation)
CLASSEMENT_S = 600
PUBLI_S = 120
POINT_COURBE_S = 900            # un point de courbe toutes les 15 min
CARNETS_PAR_SCAN = 30           # nouveaux carnets lus au plus par scan (cache commun à toutes les stratégies)
CARNET_CACHE_S = 20
JOURS_SCAN_ECHEANCE = 7         # marchés qui se terminent dans les 7 jours, en plus des plus actifs

# ---------- portefeuille de chaque stratégie ----------
PART_PAR_MARCHE = 0.04
POSITIONS_MAX = 20
RESERVE_CASH = 0.10
POSITIONS_MAX_PAR_EVENEMENT = 2
REFROIDISSEMENT_S = 86400       # pas de retour sur un marché quitté depuis moins de 24 h

# ---------- copie du classement (expérimental) ----------
CLASSEMENT_TOP = 10             # meilleurs portefeuilles du mois (gain) suivis
CLASSEMENT_AGE_MAX_S = 1800     # on ne copie que les achats de moins de 30 min
CLASSEMENT_ECART_PRIX = 0.02    # ni à plus de 2 centimes au-dessus de leur prix
CLASSEMENT_PRIX_MIN, CLASSEMENT_PRIX_MAX = 0.05, 0.95
CLASSEMENT_ECHECS_MAX = 3       # après 3 échecs d'affilée : en veille, un essai par heure
CLASSEMENT_RECHERCHES_MARCHE = 5   # marchés hors scan recherchés au plus par passage

# ---------- historique publié ----------
MAX_POINTS_COURBE = 2000        # environ 3 semaines à un point par 15 min, puis éclaircissement
MAX_TRADES_PAR_STRATEGIE = 60
MAX_JOURNAL = 150

# Une couleur par stratégie (lisible sur fond sombre). "regle" désigne une fonction de polybot/strategies.py
# (ou arene/runner.py pour achat_outsider). famille : fourchette (prix au scan), mouvement (historique horaire),
# hasard (référence), classement (copie des meilleurs, expérimental).
CONCURRENTS = [
    {"id": "favori_3j", "nom": "Favori 88-97 %, 3 jours", "famille": "fourchette", "regle": "favori_echeance",
     "params": {"prix_min": 0.88, "prix_max": 0.97, "jours_max": 3}, "couleur": "#f2a33a",
     "desc": "Ancienne stratégie du bot : le favori dans les 3 derniers jours. Perdante en recherche (-8,4 %/pari)."},
    {"id": "favori_7j", "nom": "Favori 80-97 %, 7 jours", "famille": "fourchette", "regle": "favori_echeance",
     "params": {"prix_min": 0.80, "prix_max": 0.97, "jours_max": 7}, "couleur": "#ffd166",
     "desc": "Favori un peu moins sûr, jusqu'à 7 jours avant l'échéance."},
    {"id": "favori_modere", "nom": "Favori modéré 65-85 %", "famille": "fourchette", "regle": "favori_echeance",
     "params": {"prix_min": 0.65, "prix_max": 0.85, "jours_max": 7}, "couleur": "#e9c46a",
     "desc": "Favori net mais pas écrasant : on gagne plus par pari, on perd plus souvent."},
    {"id": "contre_outsider_10", "nom": "Contre les outsiders 10 %", "famille": "fourchette", "regle": "longshot_fade",
     "params": {"seuil_oui": 0.10, "prix_max": 0.97, "jours_max": 30}, "couleur": "#4da3ff",
     "desc": "Acheter Non quand le Oui est coté 10 % ou moins (-4,5 %/pari en recherche)."},
    {"id": "contre_outsider_05", "nom": "Contre les outsiders 5 %", "famille": "fourchette", "regle": "longshot_fade",
     "params": {"seuil_oui": 0.05, "prix_max": 0.97, "jours_max": 60}, "couleur": "#7cc4ff",
     "desc": "Pareil, seulement les Oui à 5 % ou moins."},
    {"id": "achat_outsider", "nom": "Achat d'outsiders 3-15 %", "famille": "fourchette", "regle": "achat_outsider",
     "params": {"prix_min": 0.03, "prix_max": 0.15, "jours_max": 30}, "couleur": "#ff8fab",
     "desc": "L'inverse : acheter le Oui des outsiders. Gagne rarement mais beaucoup."},
    {"id": "contre_mvt_15_3h", "nom": "Contre mouvement 15 pts / 3 h", "famille": "mouvement",
     "regle": "contre_mouvement", "params": {"ecart": 0.15, "fenetre_h": 3, "sortie_h": None}, "couleur": "#2fd17a",
     "desc": "Comme le bot en direct : parier sur le retour après une chute de 15 points en 3 h, jusqu'à la résolution."},
    {"id": "contre_mvt_10_6h", "nom": "Contre mouvement 10 pts / 6 h", "famille": "mouvement",
     "regle": "contre_mouvement", "params": {"ecart": 0.10, "fenetre_h": 6, "sortie_h": None}, "couleur": "#8be9b0",
     "desc": "Même idée, mouvements plus petits sur 6 h."},
    {"id": "contre_mvt_08_12h", "nom": "Contre mouvement 8 pts / 12 h", "famille": "mouvement",
     "regle": "contre_mouvement", "params": {"ecart": 0.08, "fenetre_h": 12, "sortie_h": None}, "couleur": "#1fa67a",
     "desc": "Même idée, mouvements lents sur 12 h."},
    {"id": "contre_mvt_15_3h_24h", "nom": "Contre mouvement, sortie 24 h", "famille": "mouvement",
     "regle": "contre_mouvement", "params": {"ecart": 0.15, "fenetre_h": 3, "sortie_h": 24}, "couleur": "#b7f171",
     "desc": "Comme le bot en direct, mais revente après 24 h au lieu d'attendre la résolution."},
    {"id": "suivi_mvt_10_6h", "nom": "Suivi mouvement 10 pts / 6 h", "famille": "mouvement",
     "regle": "suivi_mouvement", "params": {"ecart": 0.10, "fenetre_h": 6, "sortie_h": None}, "couleur": "#c77dff",
     "desc": "L'inverse : suivre la tendance après un gros mouvement (-12,2 %/pari en recherche)."},
    {"id": "suivi_mvt_15_3h_24h", "nom": "Suivi mouvement, sortie 24 h", "famille": "mouvement",
     "regle": "suivi_mouvement", "params": {"ecart": 0.15, "fenetre_h": 3, "sortie_h": 24}, "couleur": "#9d8cff",
     "desc": "Suivre la tendance, revente après 24 h."},
    {"id": "hasard", "nom": "Hasard (référence)", "famille": "hasard", "regle": "hasard",
     "params": {"proba": 0.002}, "couleur": "#8693a2", "reference": True,
     "desc": "Une issue au hasard, gardée jusqu'à la résolution. Une stratégie qui ne bat pas celle-ci n'apporte rien."},
    {"id": "classement", "nom": "Copie du classement", "famille": "classement", "regle": "classement",
     "params": {"top": CLASSEMENT_TOP, "age_max_min": CLASSEMENT_AGE_MAX_S // 60}, "couleur": "#ff5c6c",
     "experimental": True,
     "desc": "Copier les achats récents des 10 meilleurs portefeuilles du mois sur Polymarket. Expérimental : "
             "se met en veille si le classement n'est pas lisible depuis GitHub."},
]
