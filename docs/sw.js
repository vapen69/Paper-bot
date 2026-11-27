/* Service worker de l'appli Paper Bot (téléphone).
   Seul rôle : garder une copie de la coquille (pages, style, code, icônes) pour que l'appli s'ouvre même sans réseau.
   Toujours le réseau d'abord : une nouvelle version du tableau arrive dès qu'on rouvre l'appli.
   Les données des bots et les prix (GitHub raw, API GitHub, Kraken, Polymarket) ne passent jamais par ce cache :
   on ne les intercepte pas, donc on n'affiche jamais une valeur périmée en la faisant passer pour fraîche. */
const CACHE = "paperbot-coquille-v1";
const COQUILLE = ["./", "accueil.html", "index.html", "poly.html", "tableau.css", "tableau.js", "manifest.webmanifest", "icones/icone-192.png", "icones/apple-touch-icon.png"];

self.addEventListener("install", ev => {
  ev.waitUntil(caches.open(CACHE).then(c => c.addAll(COQUILLE)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", ev => {
  ev.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", ev => {
  const req = ev.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  ev.respondWith(fetch(req).then(r => {
    if (r.ok) { const copie = r.clone(); caches.open(CACHE).then(c => c.put(req, copie)).catch(() => {}); }
    return r;
  }).catch(() => caches.match(req, {ignoreSearch: true}).then(r => r || (req.mode === "navigate" ? caches.match("accueil.html") : Response.error()))));
});
