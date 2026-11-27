"""L'appli du téléphone (PWA sur GitHub Pages) : manifeste valide, icônes présentes, pages reliées."""
import json
import struct
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


def taille_png(chemin: Path):
    tete = chemin.read_bytes()[:24]
    assert tete[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", tete[16:24])


def test_manifeste_et_icones():
    m = json.loads((DOCS / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["display"] == "standalone"
    assert (DOCS / m["start_url"]).exists()
    tailles = set()
    for ic in m["icons"]:
        w, h = taille_png(DOCS / ic["src"])
        assert f"{w}x{h}" == ic["sizes"]
        tailles.add((w, ic.get("purpose", "any")))
    assert (192, "any") in tailles and (512, "any") in tailles and (512, "maskable") in tailles
    assert taille_png(DOCS / "icones/apple-touch-icon.png") == (180, 180)


def test_pages_reliees_a_l_appli():
    for page in ("accueil.html", "index.html", "poly.html"):
        html = (DOCS / page).read_text(encoding="utf-8")
        assert 'rel="manifest"' in html and 'rel="apple-touch-icon"' in html
        assert "apple-mobile-web-app-capable" in html and "viewport-fit=cover" in html
    assert 'data-vue="accueil"' in (DOCS / "accueil.html").read_text(encoding="utf-8")


def test_service_worker_ne_garde_pas_les_donnees():
    sw = (DOCS / "sw.js").read_text(encoding="utf-8")
    # les données et les prix sont sur d'autres domaines : le service worker ne doit jamais les intercepter
    assert "url.origin !== self.location.origin" in sw
    for f in ("accueil.html", "tableau.js", "tableau.css"):
        assert f'"{f}"' in sw
