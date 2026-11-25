"""Exécutions simulées sur le carnet d'ordres réel (aucun ordre n'est envoyé nulle part).

Un achat consomme les vendeurs (asks) du moins cher au plus cher, une vente consomme les acheteurs (bids) du plus
offrant au moins offrant, exactement comme le ferait un ordre au marché. Si le carnet est trop mince, l'exécution
est partielle : c'est à l'appelant de décider s'il l'accepte.
"""
from . import config


def frais_taker(parts, prix, frais_bps):
    """Frais taker prudents : (bps / 10000) x min(prix, 1 - prix) x parts. bps None = hypothèse de la config."""
    bps = config.FRAIS_BPS_SI_ABSENT if frais_bps is None else frais_bps
    if bps <= 0 or parts <= 0:
        return 0.0
    return bps / 10000.0 * min(prix, 1.0 - prix) * parts


def acheter_carnet(asks, budget, prix_limite=None, frais_bps=0.0):
    """Achète pour `budget` dollars au plus (frais compris) en remontant les asks triés par prix croissant.
    Retourne {"parts", "cout", "frais", "prix_moyen", "complet", "meilleur"} ou None si rien n'est exécutable."""
    if not asks or budget <= 0:
        return None
    meilleur = asks[0][0]
    limite = meilleur + config.GLISSEMENT_MAX
    if prix_limite is not None:
        limite = min(limite, prix_limite)
    reste, parts, cout, frais = budget, 0.0, 0.0, 0.0
    for prix, taille in asks:
        if prix > limite + 1e-9 or reste <= 1e-9:
            break
        cout_unitaire = prix + frais_taker(1.0, prix, frais_bps)
        q = min(taille, reste / cout_unitaire)
        parts += q
        cout += q * prix
        frais += frais_taker(q, prix, frais_bps)
        reste -= q * cout_unitaire
    if parts <= 0:
        return None
    return {"parts": parts, "cout": cout, "frais": frais, "prix_moyen": cout / parts,
            "complet": reste <= budget * 0.01, "meilleur": meilleur}


def vendre_carnet(bids, parts, prix_min=0.0, frais_bps=0.0):
    """Vend `parts` parts en descendant les bids triés par prix décroissant.
    Retourne {"parts", "brut", "frais", "prix_moyen", "complet"} ou None si aucun acheteur."""
    if not bids or parts <= 0:
        return None
    reste, brut, frais = parts, 0.0, 0.0
    for prix, taille in bids:
        if prix < prix_min - 1e-9 or reste <= 1e-9:
            break
        q = min(taille, reste)
        brut += q * prix
        frais += frais_taker(q, prix, frais_bps)
        reste -= q
    vendues = parts - reste
    if vendues <= 0:
        return None
    return {"parts": vendues, "brut": brut, "frais": frais, "prix_moyen": brut / vendues,
            "complet": reste <= parts * 1e-6}


def milieu(carnet):
    """Prix de référence d'une issue : milieu du carnet si les deux côtés existent et sont proches, sinon le bid
    (valorisation prudente), sinon None."""
    bids, asks = carnet.get("bids") or [], carnet.get("asks") or []
    if bids and asks:
        if asks[0][0] - bids[0][0] <= 0.10:
            return (bids[0][0] + asks[0][0]) / 2
        return bids[0][0]
    if bids:
        return bids[0][0]
    return None
