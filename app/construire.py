"""Fabrique app/paper-bot-app.html (l'artefact Claude installable comme appli de bureau)
à partir du tableau de bord en ligne (docs/tableau.css et docs/tableau.js) : un seul code pour les deux.
Usage : python3 app/construire.py"""
from pathlib import Path

ICI = Path(__file__).resolve().parent
DOCS = ICI.parent / "docs"


def construire() -> str:
    css = (DOCS / "tableau.css").read_text(encoding="utf-8")
    js = (DOCS / "tableau.js").read_text(encoding="utf-8")
    boot = (ICI / "demarrage.js").read_text(encoding="utf-8")
    for bloc in (css, js, boot):
        assert "</script" not in bloc.lower() and "</style" not in bloc.lower()
    return f"""<title>Paper Bot</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<script type="application/json" id="claude-artifacts-manifest">{{"permissions": ["full-access", "notifications"]}}</script>
<style>
{css}
</style>
<div class="wrap"><div class="accueil" id="accueil"><p class="note">Chargement…</p></div></div>
<div id="app"></div>
<script>
window.lancerTableau = () => {{
{js}
}};
</script>
<script>
{boot}
</script>
"""


if __name__ == "__main__":
    sortie = ICI / "paper-bot-app.html"
    sortie.write_text(construire(), encoding="utf-8")
    print(sortie)
