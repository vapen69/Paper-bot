/* Appli de bureau Paper Bot (artefact Claude installé comme application).
   Dans la fenêtre de l'appli, la page n'a pas le droit d'appeler Internet directement :
   elle lit donc les données publiques avec curl (présent sur Windows 10 et 11), en lecture seule.
   Ailleurs (navigateur, panneau Claude), elle propose d'installer l'appli ou d'ouvrir le tableau en ligne. */
(async () => {
"use strict";
const ACCUEIL = document.getElementById("accueil");
const EN_LIGNE = "https://vapen69.github.io/Paper-bot/";
const URL_OK = /^https:\/\/(raw\.githubusercontent\.com|api\.kraken\.com|clob\.polymarket\.com|api\.github\.com)\/[\w\-./?=&,%]*$/;

function accueil(html) { ACCUEIL.hidden = false; ACCUEIL.innerHTML = html; }
function icone() {
  const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
  const r = 56; g.fillStyle = "#0b0f15"; g.beginPath(); g.moveTo(r, 0); g.arcTo(256, 0, 256, 256, r); g.arcTo(256, 256, 0, 256, r); g.arcTo(0, 256, 0, 0, r); g.arcTo(0, 0, 256, 0, r); g.fill();
  const grad = g.createLinearGradient(0, 0, 256, 0); grad.addColorStop(0, "#4da3ff"); grad.addColorStop(1, "#9d8cff");
  g.strokeStyle = grad; g.lineWidth = 18; g.lineCap = g.lineJoin = "round";
  g.beginPath(); [[40, 180], [92, 128], [130, 156], [214, 70]].forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.stroke();
  g.fillStyle = "#2fd17a"; g.beginPath(); g.arc(214, 70, 16, 0, 7); g.fill();
  return c.toDataURL("image/png");
}

let desktop = null;
try { desktop = await window.claude?.use?.("desktop"); } catch (e) {}

if (!desktop?.childProcess) {
  let etat = "unavailable";
  try { etat = await desktop?.install?.state() ?? "unavailable"; } catch (e) {}
  accueil(`<h1>Paper Bot</h1>
    <p>Ce tableau de bord devient une vraie appli sur ton PC : une icône sur le bureau, un clic, et tes deux bots s'affichent avec les prix en direct.</p>
    <p>${etat === "installed" ? "L'appli est déjà installée sur cet ordinateur : ouvre-la depuis le menu Démarrer ou ton bureau." : etat === "available" ? "Clique sur le bouton pour l'installer." : "Pour l'installer, ouvre cette page dans l'appli Claude pour ordinateur, puis menu de l'artefact &gt; « Install as app »."}</p>
    ${etat === "available" ? '<button class="bouton" id="installer">Installer l\'appli</button>' : ""}
    <a class="bouton sec" href="${EN_LIGNE}" target="_blank" rel="noopener">Ouvrir le tableau en ligne</a>
    <p class="note">Ici, la page n'a pas le droit de lire Internet : les chiffres ne s'affichent que dans l'appli installée ou sur le lien en ligne.</p>`);
  const b = document.getElementById("installer");
  if (b) b.onclick = async () => { b.disabled = true; try { const r = await desktop.install.request(); if (r === "installed") b.textContent = "Installation lancée"; else b.disabled = false; } catch (e) { b.disabled = false; } };
  return;
}

/* --- dans la fenêtre de l'appli --- */
desktop.app.dock.setIcon(icone()).catch(() => {});
desktop.window.setOptions({width: 1040, height: 900, minWidth: 380, minHeight: 500, backgroundColor: "#0b0f15"}).catch(() => {});

let plateforme = "win32";
try { plateforme = await desktop.os.platform(); } catch (e) {}
const CURL = plateforme === "win32" ? "curl.exe" : "curl";

// file d'attente : 4 appels curl à la fois au plus
let enCours = 0; const attente = [];
const libere = () => { enCours--; const f = attente.shift(); if (f) f(); };
const place = () => enCours < 4 ? (enCours++, Promise.resolve()) : new Promise(r => attente.push(() => { enCours++; r(); }));
let dossier = null;
async function json(url) {
  if (!URL_OK.test(url)) return null;
  await place();
  try {
    const r = await desktop.childProcess.exec(`${CURL} -s -L --compressed --max-time 20 "${url}"`, {timeout: 25000});
    if (r.code === 0 && !r.truncated && r.stdout) return JSON.parse(r.stdout);
    if (r.code === 0 && r.truncated) {
      // gros fichier (la recherche) : on passe par un fichier temporaire
      if (!dossier) dossier = (await desktop.os.tmpdir()).replace(/[\\/]+$/, "");
      const f = `${dossier}${plateforme === "win32" ? "\\" : "/"}paper-bot-${Math.random().toString(36).slice(2)}.json`;
      const r2 = await desktop.childProcess.exec(`${CURL} -s -L --compressed --max-time 30 -o "${f}" "${url}"`, {timeout: 35000});
      if (r2.code !== 0) return null;
      const txt = await desktop.fs.readFile(f, "utf8");
      desktop.fs.rm(f, {force: true}).catch(() => {});
      return JSON.parse(txt);
    }
  } catch (e) { console.warn("lecture impossible", url, e?.message); }
  finally { libere(); }
  return null;
}

async function lance() {
  ACCUEIL.hidden = true;
  let notif = false;
  try { notif = (await desktop.permissions.state("notifications")) === "granted"; } catch (e) {}
  window.PB_TRANSPORT = {
    json, pollPrix: true, lienVue: true,
    notifie: notif ? txt => desktop.notification.show({body: String(txt).slice(0, 300)}).catch(() => {}) : null,
    parSeconde: (v, vue) => { if (v != null) document.title = (vue === "poly" ? v.toLocaleString("fr-FR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " $" : v.toLocaleString("fr-FR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " €") + " · Paper Bot"; }
  };
  window.lancerTableau();
}

let acces = "prompt";
try { acces = await desktop.permissions.state("full-access"); } catch (e) {}
if (acces === "granted") { lance(); return; }
if (acces === "unavailable") {
  accueil(`<h1>Paper Bot</h1><p>Claude n'autorise pas encore cette appli à lire Internet sur cet ordinateur. Rouvre l'appli dans quelques secondes ; si ça persiste, utilise le tableau en ligne.</p>
    <a class="bouton sec" href="${EN_LIGNE}" target="_blank" rel="noopener">Ouvrir le tableau en ligne</a>`);
  return;
}
accueil(`<h1>Paper Bot</h1>
  <p>Pour afficher tes bots, l'appli doit lire les données publiques sur Internet (GitHub, Kraken, Polymarket) avec l'outil curl de Windows. Elle ne fait que lire : aucun ordre, aucun fichier modifié.</p>
  <p>Claude va te demander une autorisation « accès complet » (c'est le seul moyen pour une appli de lancer curl). Tu peux aussi accepter les notifications pour être prévenu à chaque trade.</p>
  <button class="bouton" id="autoriser">Autoriser et démarrer</button>
  <button class="bouton sec" id="reglages" hidden>Ouvrir les autorisations</button>
  <a class="bouton sec" href="${EN_LIGNE}" target="_blank" rel="noopener">Tableau en ligne</a>`);
document.getElementById("autoriser").onclick = async () => {
  let m = {};
  try { m = await desktop.permissions.request(["full-access", "notifications"]); } catch (e) {}
  if (m["full-access"] === "granted") return lance();
  document.getElementById("reglages").hidden = false;
};
document.getElementById("reglages").onclick = () => desktop.permissions.manage().then(async () => { if ((await desktop.permissions.state("full-access")) === "granted") lance(); }).catch(() => {});
})();
