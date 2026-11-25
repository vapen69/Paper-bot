"""Portefeuille simulé pour les marchés de prédiction.

Une position = des parts d'une issue (Oui ou Non) d'un marché. Chaque part vaut 1 dollar si l'issue se réalise,
0 sinon. Les positions sont indexées par l'identifiant du jeton (token) de l'issue.
"""
from . import config


class Portefeuille:
    def __init__(self, etat=None):
        etat = etat or {}
        self.cash = float(etat.get("cash", config.CAPITAL_DEPART))
        self.positions = etat.get("positions", {}) or {}
        self.trades = etat.get("trades", []) or []
        self.frais_total = float(etat.get("frais_total", 0.0))
        self.plus_haut = float(etat.get("plus_haut_portefeuille", config.CAPITAL_DEPART))
        self.nb_trades = int(etat.get("nb_trades", len(self.trades)))
        self.pnl_strategies = etat.get("pnl_strategies", {}) or {}

    # ---------- valeur ----------
    def valeur(self):
        return self.cash + sum(p["parts"] * p["dernier_prix"] for p in self.positions.values())

    def engage(self, filtre=None):
        """Somme des coûts d'entrée des positions (éventuellement filtrées)."""
        return sum(p["cout"] for p in self.positions.values() if filtre is None or filtre(p))

    def _noter(self, trade, strategie, pnl=None):
        self.trades.append(trade)
        self.trades = self.trades[-config.MAX_TRADES:]
        self.nb_trades += 1
        s = self.pnl_strategies.setdefault(strategie, {"pnl": 0.0, "clotures": 0, "gagnants": 0, "entrees": 0})
        if pnl is None:
            s["entrees"] += 1
        else:
            s["pnl"] = round(s["pnl"] + pnl, 6)
            s["clotures"] += 1
            s["gagnants"] += 1 if pnl > 0 else 0

    # ---------- mouvements ----------
    def acheter(self, jeton, execu, infos, t, raison):
        """Enregistre un achat déjà simulé sur le carnet (execu vient de execution.acheter_carnet)."""
        total = execu["cout"] + execu["frais"]
        if jeton in self.positions or total > self.cash + 1e-9 or execu["parts"] <= 0:
            return False
        self.cash -= total
        self.frais_total += execu["frais"]
        self.positions[jeton] = {
            **infos, "parts": execu["parts"], "prix_entree": execu["prix_moyen"], "cout": total,
            "dernier_prix": execu["prix_moyen"], "bid": None, "depuis": t,
        }
        self._noter({"t": t, "sens": "achat", "question": infos["question"], "issue": infos["issue"],
                     "prix": round(execu["prix_moyen"], 4), "parts": round(execu["parts"], 3),
                     "montant": round(total, 4), "frais": round(execu["frais"], 4), "raison": raison,
                     "strategie": infos["strategie"], "url": infos.get("url", "")}, infos["strategie"])
        return True

    def _cloturer(self, jeton, parts, net, frais, prix, t, raison, sens):
        p = self.positions[jeton]
        fraction = min(1.0, parts / p["parts"])
        cout = p["cout"] * fraction
        self.cash += net
        self.frais_total += frais
        pnl = net - cout
        self._noter({"t": t, "sens": sens, "question": p["question"], "issue": p["issue"],
                     "prix": round(prix, 4), "parts": round(parts, 3), "montant": round(net, 4),
                     "frais": round(frais, 4), "pnl": round(pnl, 4),
                     "pnl_pct": round((net / cout - 1) * 100, 2) if cout > 0 else 0.0, "raison": raison,
                     "strategie": p["strategie"], "url": p.get("url", "")}, p["strategie"], pnl)
        if fraction >= 1.0 - 1e-9:
            del self.positions[jeton]
        else:
            p["parts"] -= parts
            p["cout"] -= cout
        return pnl

    def vendre(self, jeton, execu, t, raison):
        """Enregistre une vente déjà simulée sur le carnet (execu vient de execution.vendre_carnet)."""
        return self._cloturer(jeton, execu["parts"], execu["brut"] - execu["frais"], execu["frais"],
                              execu["prix_moyen"], t, raison, "vente")

    def regler(self, jeton, prix_final, t, raison):
        """Marché résolu : chaque part est payée prix_final (1, 0 ou 0,5), sans frais."""
        p = self.positions[jeton]
        return self._cloturer(jeton, p["parts"], p["parts"] * prix_final, 0.0, prix_final, t, raison, "reglement")

    def etat(self):
        return {"cash": self.cash, "positions": self.positions, "trades": self.trades,
                "frais_total": self.frais_total, "plus_haut_portefeuille": self.plus_haut,
                "nb_trades": self.nb_trades, "pnl_strategies": self.pnl_strategies}
