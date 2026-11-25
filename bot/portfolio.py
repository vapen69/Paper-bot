"""Portefeuille simulé : achats (long) et ventes à découvert (short, comme un contrat perpétuel), frais, slippage,
financement des shorts, coupe-circuit.

Short : on bloque une garantie C en euros. Après frais, on vend à découvert N = C - frais euros d'actif au prix p0.
Valeur de la position = N + qte * (p0 - prix) - financement cumulé (gain si le prix baisse, perte si il monte).
Si cette valeur tombe à 0, la position est liquidée (perte de toute la garantie).
"""
from . import config


def valeur_position(p, prix):
    if p.get("sens", "long") == "long":
        return p["qte"] * prix
    return max(0.0, p["qte"] * (2 * p["prix_entree"] - prix) - p.get("financement", 0.0))


class Portefeuille:
    def __init__(self, etat=None):
        etat = etat or {}
        self.cash = etat.get("cash", config.CAPITAL_DEPART_EUR)
        self.positions = etat.get("positions", {})
        self.trades = etat.get("trades", [])
        self.frais_total = etat.get("frais_total", 0.0)
        self.financement_total = etat.get("financement_total", 0.0)
        self.plus_haut = etat.get("plus_haut_portefeuille", config.CAPITAL_DEPART_EUR)

    def valeur(self, prix):
        return self.cash + sum(valeur_position(p, prix.get(s, p["dernier_prix"])) for s, p in self.positions.items())

    def ouvrir(self, sym, sens, prix, montant_eur, t, raison):
        montant_eur = min(montant_eur, self.cash)
        if montant_eur < config.ORDRE_MIN_EUR:
            return False
        frais = montant_eur * config.FRAIS
        if sens == "long":
            prix_exec = prix * (1 + config.SLIPPAGE)
        else:
            prix_exec = prix * (1 - config.SLIPPAGE)  # vente à découvert : légèrement sous le prix affiché
        qte = (montant_eur - frais) / prix_exec
        self.cash -= montant_eur
        self.frais_total += frais
        self.positions[sym] = {"sens": sens, "qte": qte, "prix_entree": prix_exec, "cout": montant_eur,
                               "plus_haut": prix, "dernier_prix": prix, "depuis": t, "financement": 0.0}
        self.trades.append({"t": t, "sens": "achat" if sens == "long" else "short", "symbole": sym,
                            "prix": prix_exec, "montant": round(montant_eur, 4), "frais": round(frais, 4),
                            "raison": raison})
        return True

    def acheter(self, sym, prix, montant_eur, t, raison):
        return self.ouvrir(sym, "long", prix, montant_eur, t, raison)

    def vendre(self, sym, prix, t, raison):
        """Clôture la position, qu'elle soit longue (vente) ou courte (rachat)."""
        p = self.positions.pop(sym)
        if p.get("sens", "long") == "long":
            prix_exec = prix * (1 - config.SLIPPAGE)
            brut = p["qte"] * prix_exec
            frais = brut * config.FRAIS
            sens_trade = "vente"
        else:
            prix_exec = prix * (1 + config.SLIPPAGE)  # rachat : légèrement au-dessus du prix affiché
            brut = max(0.0, p["qte"] * (2 * p["prix_entree"] - prix_exec) - p.get("financement", 0.0))
            frais = min(brut, p["qte"] * prix_exec * config.FRAIS)
            sens_trade = "rachat"
        net = brut - frais
        self.cash += net
        self.frais_total += frais
        self.trades.append({"t": t, "sens": sens_trade, "symbole": sym, "prix": prix_exec,
                            "montant": round(net, 4), "frais": round(frais, 4),
                            "pnl": round(net - p["cout"], 4),
                            "pnl_pct": round((net / p["cout"] - 1) * 100, 2), "raison": raison})

    def financer(self, prix, heures):
        """Coût de financement des shorts, payé en continu comme sur un contrat perpétuel."""
        if heures <= 0:
            return
        for s, p in self.positions.items():
            if p.get("sens") == "short":
                cout = p["qte"] * prix.get(s, p["dernier_prix"]) * config.FINANCEMENT_SHORT_8H * heures / 8
                p["financement"] = p.get("financement", 0.0) + cout
                self.financement_total += cout

    def maj_prix_et_stops(self, prix, t):
        """Met à jour les prix, liquide les shorts ruinés, déclenche les stops éventuels. Retourne les clôtures."""
        ventes = []
        for sym in list(self.positions):
            if sym not in prix:
                continue
            p = self.positions[sym]
            p["dernier_prix"] = prix[sym]
            p["plus_haut"] = max(p["plus_haut"], prix[sym])
            if p.get("sens") == "short" and valeur_position(p, prix[sym]) <= 0:
                self.vendre(sym, prix[sym], t, "liquidation : la hausse a absorbé toute la garantie")
                ventes.append(sym)
            elif p.get("sens", "long") == "long" and config.STOP_SUIVEUR and \
                    prix[sym] <= p["plus_haut"] * (1 - config.STOP_SUIVEUR):
                self.vendre(sym, prix[sym], t, f"stop suiveur (-{config.STOP_SUIVEUR*100:.0f} % depuis le plus haut)")
                ventes.append(sym)
        return ventes

    def tout_vendre(self, prix, t, raison):
        for sym in list(self.positions):
            self.vendre(sym, prix.get(sym, self.positions[sym]["dernier_prix"]), t, raison)

    def etat(self):
        return {"cash": self.cash, "positions": self.positions,
                "trades": self.trades[-config.MAX_TRADES:], "frais_total": self.frais_total,
                "financement_total": self.financement_total, "plus_haut_portefeuille": self.plus_haut}
