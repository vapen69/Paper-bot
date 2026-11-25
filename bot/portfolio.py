"""Portefeuille simulé : frais, slippage, stop suiveur, coupe-circuit."""
from . import config


class Portefeuille:
    def __init__(self, etat=None):
        etat = etat or {}
        self.cash = etat.get("cash", config.CAPITAL_DEPART_EUR)
        self.positions = etat.get("positions", {})
        self.trades = etat.get("trades", [])
        self.frais_total = etat.get("frais_total", 0.0)
        self.plus_haut = etat.get("plus_haut_portefeuille", config.CAPITAL_DEPART_EUR)

    def valeur(self, prix):
        return self.cash + sum(p["qte"] * prix.get(s, p["dernier_prix"]) for s, p in self.positions.items())

    def acheter(self, sym, prix, montant_eur, t, raison):
        montant_eur = min(montant_eur, self.cash)
        if montant_eur < config.ORDRE_MIN_EUR:
            return False
        prix_exec = prix * (1 + config.SLIPPAGE)
        frais = montant_eur * config.FRAIS
        qte = (montant_eur - frais) / prix_exec
        self.cash -= montant_eur
        self.frais_total += frais
        self.positions[sym] = {"qte": qte, "prix_entree": prix_exec, "cout": montant_eur,
                               "plus_haut": prix, "dernier_prix": prix, "depuis": t}
        self.trades.append({"t": t, "sens": "achat", "symbole": sym, "prix": prix_exec,
                            "montant": round(montant_eur, 4), "frais": round(frais, 4), "raison": raison})
        return True

    def vendre(self, sym, prix, t, raison):
        p = self.positions.pop(sym)
        prix_exec = prix * (1 - config.SLIPPAGE)
        brut = p["qte"] * prix_exec
        frais = brut * config.FRAIS
        net = brut - frais
        self.cash += net
        self.frais_total += frais
        self.trades.append({"t": t, "sens": "vente", "symbole": sym, "prix": prix_exec,
                            "montant": round(net, 4), "frais": round(frais, 4),
                            "pnl": round(net - p["cout"], 4),
                            "pnl_pct": round((net / p["cout"] - 1) * 100, 2), "raison": raison})

    def maj_prix_et_stops(self, prix, t):
        """Met à jour les plus hauts et déclenche les stops suiveurs. Retourne les ventes faites."""
        ventes = []
        for sym in list(self.positions):
            if sym not in prix:
                continue
            p = self.positions[sym]
            p["dernier_prix"] = prix[sym]
            p["plus_haut"] = max(p["plus_haut"], prix[sym])
            if prix[sym] <= p["plus_haut"] * (1 - config.STOP_SUIVEUR):
                self.vendre(sym, prix[sym], t, f"stop suiveur (-{config.STOP_SUIVEUR*100:.0f} % depuis le plus haut)")
                ventes.append(sym)
        return ventes

    def tout_vendre(self, prix, t, raison):
        for sym in list(self.positions):
            self.vendre(sym, prix.get(sym, self.positions[sym]["dernier_prix"]), t, raison)

    def etat(self):
        return {"cash": self.cash, "positions": self.positions,
                "trades": self.trades[-config.MAX_TRADES:], "frais_total": self.frais_total,
                "plus_haut_portefeuille": self.plus_haut}
