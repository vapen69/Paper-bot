/* Tableau de bord Paper Bot : crypto et Polymarket dans une seule page.
   Utilisé tel quel par GitHub Pages (index.html, poly.html) et recopié dans l'appli de bureau (app/).
   Lecture seule : il lit les branches data / data-poly et les prix publics, il ne passe aucun ordre.
   window.PB_TRANSPORT (facultatif) remplace les accès réseau : {json(url), pollPrix, lienVue}. */
(() => {
"use strict";
const T = window.PB_TRANSPORT || {};
const surPages = location.hostname.endsWith("github.io");
const OWNER = surPages ? location.hostname.split(".")[0] : "vapen69";
const REPO = surPages ? (location.pathname.split("/")[1] || "Paper-bot") : "Paper-bot";
const RAW = b => `https://raw.githubusercontent.com/${OWNER}/${REPO}/${b}/`;
const API = `https://api.github.com/repos/${OWNER}/${REPO}/contents/`;
const WF = f => `https://github.com/${OWNER}/${REPO}/actions/workflows/${f}`;
const CLOB = "https://clob.polymarket.com";
const KRAKEN = "https://api.kraken.com/0/public/";
const calme = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- outils ---------- */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const n = v => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
const fr = (v, d = 2) => n(v).toLocaleString("fr-FR", {minimumFractionDigits: d, maximumFractionDigits: d});
const eur = (v, d = 2) => fr(v, d) + " €";
const usd = (v, d = 2) => fr(v, d) + " $";
const pct = (v, d = 2) => (n(v) >= 0 ? "+" : "") + fr(v, d) + " %";
const prixFmt = p => p >= 100 ? eur(p, 2) : p >= 1 ? eur(p, 4) : eur(p, 6);
const proba = p => fr(n(p) * 100, 1) + " %";
const borne = v => Math.max(0, Math.min(100, n(v) * 100));
const heure = t => { const d = new Date(t); return isNaN(d) ? "" : d.toLocaleString("fr-FR", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}); };
const hms = t => { const d = new Date(t); return isNaN(d) ? "" : d.toLocaleTimeString("fr-FR", {hour: "2-digit", minute: "2-digit"}); };
const lienPoly = u => /^https:\/\/polymarket\.com\/[\w\-./%]*$/.test(String(u || "")) ? String(u) : "";
const duree = s => { s = Math.max(0, Math.floor(s)); const j = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return j ? `${j} j ${h} h ${String(m).padStart(2, "0")}` : `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`; };

async function jsonUrl(url) {
  if (T.json) return T.json(url);
  try { const r = await fetch(url, {cache: "no-store"}); if (r.ok) return await r.json(); } catch (e) {}
  return null;
}
async function lireData(branche, nom) {
  if (T.json) return T.json(RAW(branche) + nom + "?t=" + Date.now());
  try { const r = await fetch(RAW(branche) + nom + "?t=" + Date.now(), {cache: "no-store"}); if (r.ok) return await r.json(); } catch (e) {}
  try { const r = await fetch(API + nom + "?ref=" + branche, {headers: {Accept: "application/vnd.github.raw+json"}, cache: "no-store"}); if (r.ok) return await r.json(); } catch (e) {}
  return null;
}

/* Nombre qui défile jusqu'à sa nouvelle valeur, avec un halo vert ou rouge. */
function compteur(el, cible, fmt, halo) {
  if (!el) return;
  const depart = el._v;
  el._v = cible;
  if (depart == null || calme || Math.abs(cible - depart) < 1e-9) { el.innerHTML = fmt(cible); return; }
  if (halo && Math.abs(cible - depart) > 1e-6) { el.classList.remove("monte", "baisse"); void el.offsetWidth; el.classList.add(cible > depart ? "monte" : "baisse"); clearTimeout(el._h); el._h = setTimeout(() => el.classList.remove("monte", "baisse"), 900); }
  const t0 = performance.now(), dur = 650;
  cancelAnimationFrame(el._raf);
  const pas = t => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.innerHTML = fmt(depart + (cible - depart) * e); if (k < 1) el._raf = requestAnimationFrame(pas); };
  el._raf = requestAnimationFrame(pas);
}
function ambiance(d) { document.documentElement.style.setProperty("--glow", d >= 0 ? "47,209,122" : "255,92,108"); }

/* Petite courbe sans axes. */
function sparkSvg(vals, couleur, h = 38) {
  const v = vals.filter(Number.isFinite);
  if (v.length < 2) return `<svg viewBox="0 0 100 ${h}" preserveAspectRatio="none"><line x1="0" x2="100" y1="${h / 2}" y2="${h / 2}" stroke="#253040" stroke-dasharray="2 3"/></svg>`;
  const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const pts = v.map((x, i) => [i / (v.length - 1) * 100, h - 3 - (x - lo) / r * (h - 6)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + "," + p[1].toFixed(2)).join("");
  const id = "g" + Math.random().toString(36).slice(2, 8), last = pts[pts.length - 1];
  return `<svg viewBox="0 0 100 ${h}" preserveAspectRatio="none"><defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${couleur}" stop-opacity=".35"/><stop offset="1" stop-color="${couleur}" stop-opacity="0"/></linearGradient></defs>
    <path d="${d}L100,${h}L0,${h}Z" fill="url(#${id})"/><path d="${d}" fill="none" stroke="${couleur}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.2" fill="${couleur}" vector-effect="non-scaling-stroke"/></svg>`;
}

/* Grande courbe : dégradé, tracé animé, point qui pulse au bout, curseur au doigt ou à la souris. */
function courbe(fig, pts, series, base, fmt, cle) {
  const svg = fig.querySelector("svg"), bulle = fig.querySelector(".bulle");
  const W = svg.clientWidth, H = svg.clientHeight;
  if (pts.length < 2 || !W) { svg.innerHTML = `<text x="12" y="24" fill="#8693a2" font-size="13">La courbe se remplit au fil des heures.</text>`; fig._pts = null; return; }
  const vals = pts.flatMap(p => series.map(s => p[s.k])).concat(base).filter(Number.isFinite);
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * .12 || 1;
  const y = v => H - 22 - (v - (lo - pad)) / (hi - lo + 2 * pad) * (H - 34), x = i => 46 + i / (pts.length - 1) * (W - 56);
  const chemin = k => pts.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(p[k]).toFixed(1)).join("");
  const ticks = [lo, (lo + hi) / 2, hi];
  const premier = fig._cle !== cle; fig._cle = cle;
  let out = `<defs>${series.map((s, i) => `<linearGradient id="aire${i}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${s.c}" stop-opacity="${i ? .10 : .30}"/><stop offset="1" stop-color="${s.c}" stop-opacity="0"/></linearGradient>`).join("")}</defs>`;
  out += ticks.map(t => `<line x1="46" x2="${W}" y1="${y(t)}" y2="${y(t)}" stroke="#253040"/><text x="0" y="${y(t) + 4}" fill="#8693a2" font-size="11" font-family="JetBrains Mono,monospace">${esc(fr(t, W < 520 ? 0 : 1))}</text>`).join("");
  out += `<line x1="46" x2="${W}" y1="${y(base)}" y2="${y(base)}" stroke="#8693a2" stroke-dasharray="3 4" opacity=".55"/>`;
  series.slice().reverse().forEach(s => { const i = series.indexOf(s), d = chemin(s.k);
    out += `<path d="${d}L${x(pts.length - 1).toFixed(1)},${H - 22}L46,${H - 22}Z" fill="url(#aire${i})"/>`;
    out += `<path class="trace${premier && !calme ? " dessine" : ""}" d="${d}" fill="none" stroke="${s.c}" stroke-width="${i ? 1.6 : 2.4}" stroke-linejoin="round" opacity="${i ? .85 : 1}"/>`; });
  const lx = x(pts.length - 1), ly = y(pts[pts.length - 1][series[0].k]);
  out += `<circle class="bout" cx="${lx}" cy="${ly}" r="4" fill="${series[0].c}"/><circle cx="${lx}" cy="${ly}" r="4" fill="${series[0].c}" stroke="#0b0f15" stroke-width="2"/>`;
  out += `<text x="46" y="${H - 4}" fill="#8693a2" font-size="11">${esc(heure(pts[0].t))}</text><text x="${W}" y="${H - 4}" fill="#8693a2" font-size="11" text-anchor="end">${esc(heure(pts[pts.length - 1].t))}</text>`;
  out += `<g id="${fig.id}Cur" visibility="hidden"><line y1="8" y2="${H - 22}" stroke="#e8edf2" stroke-opacity=".35"/>${series.map(s => `<circle r="4.5" fill="${s.c}" stroke="#0b0f15" stroke-width="2"/>`).join("")}</g>`;
  svg.innerHTML = out;
  svg.querySelectorAll(".trace").forEach(p => { try { p.style.setProperty("--len", Math.ceil(p.getTotalLength()) + ""); } catch (e) {} });
  fig._pts = {pts, series, x, y, W, fmt};
  if (!fig._ecoute) {
    fig._ecoute = true;
    const bouge = ev => { const o = fig._pts; if (!o) return; const r = svg.getBoundingClientRect(), px = ev.clientX - r.left;
      const i = Math.max(0, Math.min(o.pts.length - 1, Math.round((px - 46) / (o.W - 56) * (o.pts.length - 1)))), p = o.pts[i], cx = o.x(i);
      const g = $(fig.id + "Cur"); if (!g) return; g.setAttribute("visibility", "visible");
      g.querySelector("line").setAttribute("x1", cx); g.querySelector("line").setAttribute("x2", cx);
      g.querySelectorAll("circle").forEach((c, k) => { c.setAttribute("cx", cx); c.setAttribute("cy", o.y(p[o.series[k].k])); });
      bulle.hidden = false; bulle.style.left = Math.max(70, Math.min(o.W - 70, cx)) + "px";
      bulle.innerHTML = `<div class="r">${esc(heure(p.t))}</div>` + o.series.map(s => `<div><span style="color:${s.c}">●</span> ${esc(s.nom)} <b class="num">${esc(o.fmt(p[s.k]))}</b></div>`).join(""); };
    const sort = () => { bulle.hidden = true; const g = $(fig.id + "Cur"); if (g) g.setAttribute("visibility", "hidden"); };
    fig.addEventListener("pointermove", bouge); fig.addEventListener("pointerdown", bouge); fig.addEventListener("pointerleave", sort); fig.addEventListener("pointercancel", sort);
  }
}
function filtrePeriode(c, per) {
  if (per === "tout" || c.length < 3) return c;
  const ms = {"6h": 6 * 3600e3, "24h": 864e5, "7j": 7 * 864e5}[per] || 0, fin = new Date(c[c.length - 1].t).getTime();
  const f = c.filter(p => new Date(p.t).getTime() >= fin - ms);
  return f.length >= 2 ? f : c;
}
function segPeriode(id, onChange) {
  const el = $(id);
  el.addEventListener("click", ev => { const b = ev.target.closest("button"); if (!b) return; el.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); onChange(b.dataset.p); });
}

/* ---------- squelette des deux vues ---------- */
const COMMANDES = (fichier, cent) => `<div class="card entre"><h2>Commandes <span>depuis ton téléphone</span></h2>
  <div class="ctrl"><a href="${WF(fichier)}" target="_blank" rel="noopener">⏸ Pause</a><a href="${WF(fichier)}" target="_blank" rel="noopener">▶ Reprendre</a>
  <a class="warn" href="${WF(fichier)}" target="_blank" rel="noopener">Tout vendre</a><a class="warn" href="${WF(fichier)}" target="_blank" rel="noopener">Remettre à ${cent}</a></div>
  <p class="note">Ouvre la page GitHub « ${fichier === "commande.yml" ? "Commande" : "Commande Polymarket"} », touche « Run workflow », choisis l'action puis « Run workflow ». Le bot l'applique en moins d'une minute.</p></div>`;
const SEG = id => `<div class="seg" id="${id}"><button data-p="6h">6 h</button><button data-p="24h">24 h</button><button data-p="7j">7 j</button><button data-p="tout" class="on">Tout</button></div>`;

const VUE_CRYPTO = `
  <header><h1>Paper Bot · crypto</h1><span id="cStatut" class="pill">…</span></header>
  <div id="cErr" class="err" hidden></div>
  <section class="hero">
    <div class="lab">Valeur du portefeuille (argent fictif) <span class="live"><i id="cDot" class="dot"></i><span id="cLive">connexion…</span></span></div>
    <div><div class="big num" id="cValeur">-</div><div class="delta num" id="cDelta">-</div></div>
    <div class="heroSpark" id="cHeroSpark"></div>
  </section>
  <div class="cours">
    <div class="coin entre" id="coinBTC"></div><div class="coin entre" id="coinETH"></div>
    <div class="coin decis entre"><svg class="ring" viewBox="0 0 62 62"><circle cx="31" cy="31" r="26" fill="none" stroke="#253040" stroke-width="5"/><circle id="cRing" cx="31" cy="31" r="26" fill="none" stroke="#4da3ff" stroke-width="5" stroke-linecap="round" transform="rotate(-90 31 31)" stroke-dasharray="163.4" stroke-dashoffset="0"/></svg>
      <div><span>Prochaine décision</span><b class="num" id="cCompte">--:--:--</b><span>à minuit UTC (1 h du matin à Paris en hiver)</span></div></div>
  </div>
  <div class="kpis">
    <div class="kpi entre"><span>Si j'avais gardé du BTC</span><b class="num" id="kBtc">-</b></div>
    <div class="kpi entre"><span>Écart vs BTC</span><b class="num" id="kEcart">-</b></div>
    <div class="kpi entre"><span>Baisse depuis le plus haut</span><b class="num" id="kDd">-</b></div>
    <div class="kpi entre"><span>Frais et financement</span><b class="num" id="kFrais">-</b></div>
  </div>
  <div class="card entre"><h2>Courbe <span id="cPeriode"></span>${SEG("cSeg")}</h2>
    <div class="fig" id="cFig"><svg></svg><div class="bulle" hidden></div></div>
    <div class="legend"><span><i style="background:var(--acc)"></i>Bot</span><span><i style="background:var(--btc)"></i>Garder du BTC</span><span><i style="background:var(--mute)"></i>Départ (100 €)</span><span>Glisse le doigt sur la courbe</span></div></div>
  <div class="card entre"><h2>Positions ouvertes <span id="cCash"></span></h2><div id="cPositions"></div></div>
  ${COMMANDES("commande.yml", "100 €")}
  <div class="card entre"><h2>Derniers trades <span id="cNbTrades"></span></h2><div id="cTrades"></div></div>
  <div class="card entre"><h2>Ce que le bot voit <span id="cMarche"></span></h2><p class="note" id="cStrat" style="margin:0 0 8px"></p><div id="cSignaux"></div></div>
  <div class="card entre"><h2>Tests de stratégie</h2><div class="tabs" id="cTabs"><button class="on" data-t="rs">Recherche 5 ans</button><button data-t="bt">Contrôle du code 2 ans</button></div><div id="cTests"></div></div>
  <div class="card entre"><h2>Journal du bot</h2><div class="log" id="cJournal"></div></div>
  <p class="note" id="cMaj"></p>`;

const VUE_POLY = `
  <header><h1>Paper Bot · Polymarket</h1><span id="pStatut" class="pill">…</span></header>
  <div id="pErr" class="err" hidden></div>
  <section class="hero">
    <div class="lab">Valeur du portefeuille (argent fictif) <span class="live"><i id="pDot" class="dot"></i><span id="pLive">connexion…</span></span></div>
    <div><div class="big num" id="pValeur">-</div><div class="delta num" id="pDelta">-</div></div>
    <div class="heroSpark" id="pHeroSpark"></div>
  </section>
  <div class="card entre"><h2>Paris réglés <span id="pScoreTxt"></span></h2><div class="score" id="pScore"></div><p class="note" id="pScoreNote" style="margin-top:6px"></p></div>
  <div class="kpis">
    <div class="kpi entre"><span>Paris réglés gagnés</span><b class="num" id="kReussite">-</b></div>
    <div class="kpi entre"><span>Gain déjà encaissé</span><b class="num" id="kRealise">-</b></div>
    <div class="kpi entre"><span>Baisse depuis le plus haut</span><b class="num" id="kPDd">-</b></div>
    <div class="kpi entre"><span>Frais payés</span><b class="num" id="kPFrais">-</b></div>
  </div>
  <div class="card entre"><h2>Activité du bot <span id="pScanAge"></span></h2>
    <div class="pouls"><div class="radar"><svg viewBox="0 0 62 62"><circle cx="31" cy="31" r="28" fill="none" stroke="#253040"/><circle cx="31" cy="31" r="18" fill="none" stroke="#253040"/><circle cx="31" cy="31" r="8" fill="none" stroke="#253040"/>
      <defs><linearGradient id="bal" x1="0" x2="1"><stop offset="0" stop-color="#9d8cff" stop-opacity="0"/><stop offset="1" stop-color="#9d8cff" stop-opacity=".8"/></linearGradient></defs>
      <path class="bal" id="pRadar" d="M31 31 L31 3 A28 28 0 0 1 55.2 17 Z" fill="url(#bal)"/></svg></div>
      <div><b class="num" id="aScan">-</b><span>marchés scannés</span></div><div><b class="num" id="aFiltres">-</b><span>dans les filtres</span></div>
      <div><b class="num" id="aCand">-</b><span>candidats</span></div><div><b class="num" id="aCarnets">-</b><span>carnets lus</span></div></div>
    <div class="feed" id="pFlux"></div></div>
  <div class="card entre"><h2>Courbe <span id="pPeriode"></span>${SEG("pSeg")}</h2>
    <div class="fig" id="pFig"><svg></svg><div class="bulle" hidden></div></div>
    <div class="legend"><span><i style="background:var(--poly)"></i>Bot</span><span><i style="background:var(--mute)"></i>Départ (100 $)</span><span>Glisse le doigt sur la courbe</span></div></div>
  <div class="card entre"><h2>Positions ouvertes <span id="pCash"></span></h2><div id="pPositions"></div></div>
  ${COMMANDES("commande_poly.yml", "100 $")}
  <div class="card entre"><h2>Derniers trades <span id="pNbTrades"></span></h2><div id="pTrades"></div></div>
  <div class="card entre"><h2>Marchés surveillés <span id="pNbSurv"></span></h2><p class="note" id="pStrat" style="margin:0 0 8px"></p><div id="pSurveilles"></div></div>
  <div class="card entre"><h2>Recherche <span id="pRsDate"></span></h2><div id="pRecherche"></div></div>
  <div class="card entre"><h2>Journal du bot</h2><div class="log" id="pJournal"></div></div>
  <p class="note" id="pMaj"></p>
  <p class="note">Simulation uniquement : aucun ordre réel, aucun compte, aucun argent engagé. Les prix viennent des carnets publics de Polymarket.</p>`;

const app = document.getElementById("app");
app.innerHTML = `<div class="wrap">
  <div class="top"><nav class="switch" aria-label="Choix du bot"><span class="glis" id="glis"></span><a data-vue="crypto" href="${T.lienVue ? "#crypto" : "index.html"}"><i></i>Crypto</a><a data-vue="poly" href="${T.lienVue ? "#polymarket" : "poly.html"}"><i></i>Polymarket</a></nav><span class="horloge num" id="horloge"></span></div>
  <div id="vueCrypto">${VUE_CRYPTO}</div><div id="vuePoly" class="poly" hidden>${VUE_POLY}</div></div>`;

let vue = document.body.dataset.vue === "poly" || location.hash === "#polymarket" ? "poly" : "crypto";
function montreVue(v, pousse) {
  vue = v;
  $("vueCrypto").hidden = v !== "crypto"; $("vuePoly").hidden = v !== "poly";
  document.querySelectorAll(".switch a").forEach(a => { const on = a.dataset.vue === v; a.classList.toggle("on", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const a = document.querySelector(`.switch a[data-vue="${v}"]`), g = $("glis");
  g.style.left = a.offsetLeft + "px"; g.style.width = a.offsetWidth + "px";
  document.title = v === "poly" ? "Paper Bot · Polymarket" : "Paper Bot";
  if (pousse) { if (T.lienVue) history.replaceState(null, "", v === "poly" ? "#polymarket" : "#crypto"); else history.replaceState(null, "", v === "poly" ? "poly.html" : "index.html"); }
  document.querySelectorAll(`#${v === "poly" ? "vuePoly" : "vueCrypto"} .entre`).forEach((el, i) => { el.style.animationDelay = (i * 45) + "ms"; el.classList.remove("entre"); void el.offsetWidth; el.classList.add("entre"); });
  if (v === "crypto" && C.S) dessineC(); if (v === "poly" && P.S) dessineP();
}
document.querySelector(".switch").addEventListener("click", ev => { const a = ev.target.closest("a[data-vue]"); if (!a) return; ev.preventDefault(); montreVue(a.dataset.vue, true); });
addEventListener("hashchange", () => { if (T.lienVue) montreVue(location.hash === "#polymarket" ? "poly" : "crypto", false); });

/* ---------- crypto ---------- */
const C = {S: null, live: {}, hist: {BTC: [], ETH: []}, lastTick: 0, per: "tout", tab: "rs", BT: null, RS: null, ws: null, subs: "", vus: new Set(), premier: true};
const COULEUR = {BTC: "#f2a33a", ETH: "#8ea2ff"}, LETTRE = {BTC: "₿", ETH: "Ξ"};
const valPos = (p, px) => p.sens === "short" ? Math.max(0, p.qte * (2 * p.prix_entree - px) - (p.financement || 0)) : p.qte * px;
const prixC = s => C.live[s] ?? C.S?.prix?.[s];
function valeurC() { let v = n(C.S.cash); for (const [s, p] of Object.entries(C.S.positions || {})) v += valPos(p, prixC(s) ?? p.dernier_prix); return v; }

function coinHtml(s) {
  const px = prixC(s), sg = C.S?.signaux?.[s], ouv = sg?.cloture, pos = C.S?.positions?.[s];
  const ch = px && ouv ? (px / ouv - 1) * 100 : null;
  const vals = C.hist[s].map(h => h[1]);
  return `<div class="h"><span class="s"><i style="background:${COULEUR[s]}">${LETTRE[s]}</i>${s}</span>${pos ? `<span class="tag ${pos.sens === "short" ? "short" : "achat"}">${pos.sens === "short" ? "SHORT" : "LONG"}</span>` : ""}</div>
    <div class="px num" data-px="${s}">${px ? esc(prixFmt(px)) : "-"}</div>
    <div class="ch num ${ch == null ? "" : ch >= 0 ? "up" : "down"}">${ch == null ? "&nbsp;" : esc(pct(ch)) + ' <span class="sub">depuis minuit UTC</span>'}</div>
    ${sparkSvg(vals, COULEUR[s])}`;
}
function renderLiveC() {
  const S = C.S; if (!S) return;
  const v = valeurC(), dep = n(S.capital_depart) || 100, d = v - dep;
  compteur($("cValeur"), v, x => esc(fr(x)) + " <small>€</small>", true);
  $("cDelta").textContent = `${d >= 0 ? "+" : ""}${eur(d)}  (${pct(d / dep * 100)}) depuis le départ`;
  $("cDelta").className = "delta num " + (d >= 0 ? "up" : "down");
  if (vue === "crypto") ambiance(d);
  const btcNow = prixC("BTC");
  if (S.btc_prix_depart && btcNow) {
    const b = dep * btcNow / S.btc_prix_depart, e = (v - b) / b * 100;
    $("kBtc").textContent = eur(b);
    $("kEcart").textContent = pct(e); $("kEcart").className = "num " + (e >= 0 ? "up" : "down");
  }
  const ph = Math.max(n(S.plus_haut_portefeuille) || dep, v);
  $("kDd").textContent = pct(-(1 - v / ph) * 100);
  $("kFrais").textContent = eur(n(S.frais_total) + n(S.financement_total));
  $("cCash").textContent = "cash " + eur(S.cash);
  ["BTC", "ETH"].forEach(s => { const el = $("coin" + s); const old = el.querySelector("[data-px]")?.textContent; el.innerHTML = coinHtml(s);
    const nv = el.querySelector("[data-px]"); if (old && nv && old !== nv.textContent && el._p != null) { nv.classList.add(prixC(s) > el._p ? "flash-up" : "flash-down"); } el._p = prixC(s); });
  const pos = Object.entries(S.positions || {});
  $("cPositions").innerHTML = pos.length ? pos.map(([s, p]) => {
    const px = prixC(s) ?? p.dernier_prix, val = valPos(p, px), pnl = val - p.cout, sh = p.sens === "short", r = pnl / p.cout * 100;
    const w = Math.min(50, Math.abs(r) * 5);
    return `<div class="pos"><div><div class="sym">${esc(s)} <span class="tag ${sh ? "short" : "achat"}">${sh ? "SHORT" : "LONG"}</span></div><div class="sub">${sh ? "Vendu à découvert" : "Acheté"} à ${esc(prixFmt(p.prix_entree))} · ${esc(heure(p.depuis))}</div><div class="sub">${sh ? "Gagne si le prix baisse" : "Gagne si le prix monte"}${p.financement ? " · financement payé " + esc(eur(p.financement, 3)) : ""}</div></div>
    <div style="text-align:right"><div class="num">${esc(prixFmt(px))}</div><div class="num ${pnl >= 0 ? "up" : "down"}">${pnl >= 0 ? "+" : ""}${esc(eur(pnl))} (${esc(pct(r))})</div><div class="sub num">${esc(eur(val))}</div></div>
    <div class="jauge" title="Gain ou perte de la position (trait = prix d'entrée)"><i style="left:${r >= 0 ? 50 : 50 - w}%;width:${w}%;background:${r >= 0 ? "var(--up)" : "var(--down)"}"></i><em></em></div></div>`;
  }).join("") : `<div class="empty">Aucune position ouverte pour l'instant : elles s'ouvrent à l'analyse du jour.</div>`;
}
function dessineC() {
  const S = C.S; if (!S) return;
  const c = filtrePeriode((S.courbe || []).filter(p => Number.isFinite(Number(p.v))), C.per).map(p => ({t: p.t, v: n(p.v), btc: n(p.btc)}));
  courbe($("cFig"), c, [{k: "v", c: "#4da3ff", nom: "Bot"}, {k: "btc", c: "#f2a33a", nom: "Garder du BTC"}], n(S.capital_depart) || 100, x => eur(x), C.per + c.length);
  $("cHeroSpark").innerHTML = sparkSvg((S.courbe || []).slice(-180).map(p => n(p.v)), "#4da3ff", 56);
}
function renderStateC() {
  const S = C.S, st = String(S.statut || "");
  $("cStatut").textContent = {actif: "Actif", pause: "Pause", "coupe-circuit": "Coupe-circuit"}[st] || st;
  $("cStatut").className = "pill " + (["actif", "pause", "coupe-circuit"].includes(st) ? st : "");
  $("cPeriode").textContent = "depuis le " + new Date(S.demarre_le).toLocaleDateString("fr-FR");
  $("cMarche").textContent = "moyenne " + (S.parametres?.sma_j ?? 50) + " jours";
  $("cStrat").textContent = S.strategie?.resume || "";
  // historique du BTC tiré de la courbe « garder du BTC » si Kraken n'a pas répondu
  if (C.hist.BTC.length < 5 && S.btc_prix_depart) C.hist.BTC = (S.courbe || []).slice(-240).map(p => [new Date(p.t).getTime(), n(p.btc) / (n(S.capital_depart) || 100) * S.btc_prix_depart]);
  const tr = [...(S.trades || [])].reverse().slice(0, 25);
  $("cNbTrades").textContent = (S.trades || []).length + " au total";
  $("cTrades").innerHTML = tr.length ? tr.map(t => { const k = t.t + t.symbole + t.sens, neuf = !C.premier && !C.vus.has(k); C.vus.add(k);
    return `<div class="row${neuf ? " neuf" : ""}"><div><span class="tag ${esc(t.sens)}">${esc({achat: "ACHAT", vente: "VENTE", short: "SHORT", rachat: "RACHAT"}[t.sens] || t.sens)}</span><b>${esc(t.symbole)}</b><div class="r">${esc(t.raison)}</div></div>
    <div style="text-align:right" class="num"><div>${esc(eur(t.montant))}</div>${t.pnl != null ? `<div class="${t.pnl >= 0 ? "up" : "down"}">${t.pnl >= 0 ? "+" : ""}${esc(eur(t.pnl))}</div>` : ""}<div class="r">${esc(heure(t.t))}</div></div></div>`; }).join("") : `<div class="empty">Pas encore de trade.</div>`;
  if (!C.premier && tr.length && T.notifie) { const t = tr[0], k = t.t + t.symbole + t.sens; if (C._dernier && C._dernier !== k) T.notifie(`Crypto : ${t.sens} ${t.symbole} pour ${eur(t.montant)}`); C._dernier = k; } else if (tr.length) C._dernier = tr[0].t + tr[0].symbole + tr[0].sens;
  C.premier = false;
  const sg = Object.entries(S.signaux || {});
  $("cSignaux").innerHTML = sg.length ? sg.map(([s, x]) => { const px = prixC(s) ?? x.cloture, ec = (px / x.moyenne - 1) * 100, w = Math.min(50, Math.abs(ec) * 2.5);
    return `<div class="row"><div><b>${esc(s)}</b> <span class="r">signal du jour : ${x.sens === "long" ? "LONG" : x.sens === "short" ? "SHORT" : "neutre"} · moyenne ${esc(prixFmt(x.moyenne))}</span>
    <div class="bar" style="position:relative"><i style="position:absolute;top:0;bottom:0;left:${ec >= 0 ? 50 : 50 - w}%;width:${w}%;background:${ec >= 0 ? "var(--up)" : "var(--down)"}"></i></div></div>
    <div class="num ${ec >= 0 ? "up" : "down"}">${esc(pct(ec))} <span class="r">vs moy.</span></div></div>`; }).join("") + `<p class="note">Le bot ne décide qu'une fois par jour, sur la clôture de minuit UTC. L'écart en direct indique seulement de quel côté penche le prochain signal.</p>`
    : `<div class="empty">Signaux disponibles après la première analyse du jour.</div>`;
  $("cJournal").innerHTML = [...(S.journal || [])].reverse().map(l => `<div><time>${esc(heure(l.t))}</time>${esc(l.msg)}</div>`).join("");
  const retard = (Date.now() - new Date(S.maj).getTime()) / 60000;
  $("cMaj").textContent = "Dernière synchro du bot : " + new Date(S.maj).toLocaleString("fr-FR") + (retard > 15 ? " (le bot semble arrêté ou en cours de relance)." : ". Les prix et la valeur bougent en direct.");
  dessineC(); renderLiveC(); abonneC();
}
function metrics(m) {
  return `<div class="kpis" style="margin:8px 0"><div class="kpi"><span>Stratégie</span><b class="num ${m.r >= 0 ? "up" : "down"}">${esc(pct(m.r))}</b></div><div class="kpi"><span>Garder du BTC</span><b class="num">${esc(pct(m.b))}</b></div><div class="kpi"><span>Pire baisse</span><b class="num down">${esc(pct(-Math.abs(m.dd)))}</b></div><div class="kpi"><span>${esc(m.l4)}</span><b class="num">${esc(m.v4)}</b></div></div>`;
}
function renderTestsC() {
  document.querySelectorAll("#cTabs button").forEach(b => b.classList.toggle("on", b.dataset.t === C.tab));
  const BT = C.BT, RS = C.RS;
  if (C.tab === "bt") {
    if (!BT) { $("cTests").innerHTML = `<div class="empty">Le backtest se calcule au démarrage du bot.</div>`; return; }
    const a = BT.avec_frais || {};
    $("cTests").innerHTML = `<p class="note" style="margin-top:0">Code du bot rejoué du ${esc(new Date(a.debut).toLocaleDateString("fr-FR"))} au ${esc(new Date(a.fin).toLocaleDateString("fr-FR"))}, frais et slippage inclus.</p>`
      + metrics({r: n(a.rendement_pct), b: n(a.btc_rendement_pct), dd: n(a.drawdown_max_pct), l4: "Trades", v4: n(a.nb_trades)})
      + `<p class="verdict">${esc(BT.verdict)}</p><p class="note">Sans frais, elle aurait fait ${esc(pct(BT.sans_frais?.rendement_pct))}. Frais payés : ${esc(eur(a.frais_payes))}. ${esc(BT.avertissement)}</p>`;
  } else {
    if (!RS) { $("cTests").innerHTML = `<div class="empty">Recherche long terme pas encore chargée (plusieurs années de données, plusieurs stratégies, validation sur des périodes jamais vues).</div>`; return; }
    const ligne = (nom, desc, o) => { const r = n(o.rendement_total_pct ?? o.total_return_pct), dd = n(o.drawdown_max_pct ?? o.max_drawdown_pct), sh = n(o.sharpe);
      return `<div class="row"><div><b>${esc(nom)}</b><div class="r">${esc(desc)}</div></div><div class="num" style="text-align:right"><div class="${r >= 0 ? "up" : "down"}">${esc(pct(r))}</div><div class="r">Sharpe ${esc(sh.toFixed(2))} · baisse ${esc(pct(-Math.abs(dd)))}</div></div></div>`; };
    const rows = (RS.strategies || []).map(s => ligne(s.nom, s.description || "", s.oos || {})).join("");
    $("cTests").innerHTML = `<p class="note" style="margin-top:0">Du ${esc((RS.periode?.oos_debut ?? "").slice(0, 10))} au ${esc((RS.periode?.oos_fin ?? "").slice(0, 10))}, uniquement sur des périodes jamais vues par la stratégie, frais inclus. Choix : <b>${esc(RS.choix?.nom ?? "")}</b>.</p>${rows}${ligne("Garder du BTC", "référence", RS.btc_hold?.oos || {})}<p class="verdict">${esc(RS.verdict || "")}</p>`;
  }
}
$("cTabs").addEventListener("click", ev => { const b = ev.target.closest("button"); if (!b) return; C.tab = b.dataset.t; renderTestsC(); });
segPeriode("cSeg", p => { C.per = p; C._fig = null; dessineC(); });

function tickPrix(s, px) {
  if (!(px > 0)) return;
  C.live[s] = px; C.lastTick = Date.now();
  const h = C.hist[s] || (C.hist[s] = []), now = Date.now();
  if (!h.length || now - h[h.length - 1][0] > 20000) h.push([now, px]); else h[h.length - 1][1] = px;
  if (h.length > 300) h.splice(0, h.length - 300);
}
async function historiqueKraken() {
  for (const [s, paire] of [["BTC", "XBTEUR"], ["ETH", "ETHEUR"]]) {
    const r = await jsonUrl(`${KRAKEN}OHLC?pair=${paire}&interval=15`);
    const k = r && r.result && Object.keys(r.result).find(x => x !== "last");
    if (k && Array.isArray(r.result[k])) C.hist[s] = r.result[k].slice(-96).map(c => [c[0] * 1000, Number(c[4])]);
  }
}
async function pollKraken() {
  const r = await jsonUrl(`${KRAKEN}Ticker?pair=XBTEUR,ETHEUR`);
  if (!r || !r.result) return;
  for (const [k, v] of Object.entries(r.result)) tickPrix(/XBT/.test(k) ? "BTC" : /ETH/.test(k) ? "ETH" : k, Number(v.c?.[0]));
}
function abonneC() {
  if (T.pollPrix) return;
  const syms = [...new Set(["BTC", "ETH", ...Object.keys(C.S.positions || {})])].map(s => s + "/EUR"), key = syms.sort().join(",");
  if (C.ws && C.ws.readyState <= 1 && key === C.subs) return;
  if (C.ws) try { C.ws.onclose = null; C.ws.close(); } catch (e) {}
  C.subs = key;
  try { C.ws = new WebSocket("wss://ws.kraken.com/v2"); } catch (e) { if (!C.repli) { C.repli = setInterval(pollKraken, 5000); pollKraken(); } return; }
  C.ws.onopen = () => C.ws.send(JSON.stringify({method: "subscribe", params: {channel: "ticker", symbol: syms}}));
  C.ws.onmessage = ev => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.channel !== "ticker" || !Array.isArray(m.data)) return;
    for (const d of m.data) tickPrix(String(d.symbol).split("/")[0], Number(d.last)); };
  C.ws.onclose = () => setTimeout(() => { C.subs = ""; abonneC(); }, 3000);
}
function compteARebours() {
  const now = new Date(), minuit = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1), reste = (minuit - now) / 1000;
  $("cCompte").textContent = duree(reste);
  $("cRing").setAttribute("stroke-dashoffset", (163.4 * (1 - reste / 86400)).toFixed(1));
}
async function refreshC() {
  const s = await lireData("data", "state.json");
  if (!s || typeof s !== "object") { if (!C.S) { $("cErr").hidden = false; $("cErr").textContent = "Les données du bot crypto ne sont pas encore arrivées (premier démarrage ou connexion lente, réessai automatique)."; } return; }
  $("cErr").hidden = true; C.S = s;
  try { renderStateC(); } catch (e) { console.error(e); }
}
async function refreshTestsC() { C.BT = await lireData("data", "backtest.json"); C.RS = await lireData("data", "research.json"); try { renderTestsC(); } catch (e) { console.error(e); } }

/* ---------- Polymarket ---------- */
const P = {S: null, RS: null, live: {}, lastTick: 0, per: "tout", vus: new Set(), premier: true, occupe: false, nbScore: 0};
const posP = () => Object.entries(P.S?.positions || {});
const prixP = (j, p) => P.live[j] ?? n(p.dernier_prix);
function valeurP() { let v = n(P.S.cash); for (const [j, p] of posP()) v += n(p.parts) * prixP(j, p); return v; }
function echeance(t) {
  const d = new Date(t).getTime();
  if (!t || isNaN(d)) return {txt: "échéance inconnue", s: null};
  const s = (d - Date.now()) / 1000;
  return s <= 0 ? {txt: "échéance passée, en attente du résultat", s: 0} : {txt: "résultat dans " + duree(s), s};
}
function renderLiveP() {
  const S = P.S; if (!S) return;
  const v = valeurP(), dep = n(S.capital_depart) || 100, d = v - dep;
  compteur($("pValeur"), v, x => esc(fr(x)) + " <small>$</small>", true);
  $("pDelta").textContent = `${d >= 0 ? "+" : ""}${usd(d)}  (${pct(d / dep * 100)}) depuis le départ`;
  $("pDelta").className = "delta num " + (d >= 0 ? "up" : "down");
  if (vue === "poly") ambiance(d);
  const ph = Math.max(n(S.plus_haut_portefeuille) || dep, v);
  $("kPDd").textContent = pct(Math.min(0, -(1 - v / ph) * 100) || 0);
  const pos = posP(), engage = pos.reduce((a, [, p]) => a + n(p.cout), 0);
  $("pCash").textContent = `${pos.length} ouverte(s) · ${usd(engage)} engagés · cash ${usd(S.cash)}`;
  // tri : les résultats les plus proches d'abord
  pos.sort((a, b) => (new Date(a[1].echeance).getTime() || 9e15) - (new Date(b[1].echeance).getTime() || 9e15));
  $("pPositions").innerHTML = pos.length ? pos.map(([j, p]) => {
    const px = prixP(j, p), val = n(p.parts) * px, pnl = val - n(p.cout), u = lienPoly(p.url), exp = p.strategie === "baleines", e = echeance(p.echeance);
    const titre = u ? `<a class="q" href="${esc(u)}" target="_blank" rel="noopener">${esc(p.question)}</a>` : `<span class="q">${esc(p.question)}</span>`;
    return `<div class="ppos"><div class="haut"><div>${titre}<div class="sub">Pari sur « ${esc(p.issue)} » ${exp ? '<span class="tag exp">EXPÉRIMENTAL</span>' : ""}</div></div>
      <div style="text-align:right"><div class="num ${pnl >= 0 ? "up" : "down"}">${pnl >= 0 ? "+" : ""}${esc(usd(pnl))}</div><div class="sub num">${esc(pct(n(p.cout) ? pnl / n(p.cout) * 100 : 0))}</div></div></div>
      <div class="proba" role="img" aria-label="Probabilité actuelle ${esc(proba(px))}, achetée à ${esc(proba(p.prix_entree))}"><i style="width:${borne(px).toFixed(1)}%"></i><em style="left:${borne(p.prix_entree).toFixed(1)}%"></em><b>${esc(proba(px))}</b></div>
      <div class="echelle"><span>acheté à ${esc(proba(p.prix_entree))} (trait blanc)</span><span>${esc(n(p.parts).toFixed(1))} parts · ${esc(usd(val))}</span></div>
      <div class="sub"><span class="chrono${e.s != null && e.s < 6 * 3600 ? " bientot" : ""}">${esc(e.txt)}</span> · si « ${esc(p.issue)} » se réalise : +${esc(usd(n(p.parts) - n(p.cout)))}, sinon ${esc(usd(-n(p.cout)))}</div></div>`;
  }).join("") : `<div class="empty">Aucune position ouverte pour l'instant : le bot attend un marché qui passe tous ses filtres.</div>`;
  const a = S.activite || {};
  if (a.dernier_scan) { const s = Math.max(0, Math.round((Date.now() - new Date(a.dernier_scan).getTime()) / 1000)); $("pScanAge").textContent = s < 3600 ? `dernier scan il y a ${s < 90 ? s + " s" : Math.round(s / 60) + " min"}` : "scan ancien"; }
}
function dessineP() {
  const S = P.S; if (!S) return;
  const c = filtrePeriode((S.courbe || []).filter(p => Number.isFinite(Number(p.v))), P.per).map(p => ({t: p.t, v: n(p.v)}));
  courbe($("pFig"), c, [{k: "v", c: "#9d8cff", nom: "Bot"}], n(S.capital_depart) || 100, x => usd(x), P.per + c.length);
  $("pHeroSpark").innerHTML = sparkSvg((S.courbe || []).slice(-180).map(p => n(p.v)), "#9d8cff", 56);
}
const TAGS = {achat: ["pari", "ACHAT"], vente: ["vente", "VENTE"], reglement: ["neutre", "RÉSOLU"]};
const FLUX = {scan: ["neutre", "SCAN"], achat: ["pari", "ACHAT"], vente: ["vente", "VENTE"], reglement: ["gagne", "RÉSOLU"], baleine: ["exp", "BALEINE"], ecarte: ["neutre", "ÉCARTÉ"]};
function renderStateP() {
  const S = P.S, st = String(S.statut || "");
  $("pStatut").textContent = {actif: "Actif", pause: "Pause", "coupe-circuit": "Coupe-circuit"}[st] || st;
  $("pStatut").className = "pill " + (["actif", "pause", "coupe-circuit"].includes(st) ? st : "");
  $("pPeriode").textContent = "depuis le " + new Date(S.demarre_le).toLocaleDateString("fr-FR");
  const ps = Object.values(S.pnl_strategies || {});
  const clos = ps.reduce((a, x) => a + n(x.clotures), 0), gagn = ps.reduce((a, x) => a + n(x.gagnants), 0), real = ps.reduce((a, x) => a + n(x.pnl), 0);
  $("kReussite").textContent = clos ? `${gagn} / ${clos}` : "0";
  $("kRealise").textContent = (real >= 0 ? "+" : "") + usd(real); $("kRealise").className = "num " + (real >= 0 ? "up" : "down");
  $("kPFrais").textContent = usd(S.frais_total);
  // tableau des paris : un carré par pari réglé (vert gagné, rouge perdu), pointillé pour ceux en cours
  const regles = (S.trades || []).filter(t => t.sens === "reglement" || (t.sens === "vente" && t.pnl != null));
  const nbOuv = posP().length;
  $("pScore").innerHTML = regles.map((t, i) => `<i class="${n(t.pnl) > 0 ? "g" : n(t.pnl) < 0 ? "p" : ""}${i >= P.nbScore ? " pop" : ""}" style="animation-delay:${Math.max(0, i - P.nbScore) * 60}ms" title="${esc(t.question)} : ${esc((n(t.pnl) >= 0 ? "+" : "") + usd(t.pnl))}"></i>`).join("")
    + Array.from({length: nbOuv}, () => `<i class="o" title="pari en cours"></i>`).join("");
  P.nbScore = regles.length;
  const g = regles.filter(t => n(t.pnl) > 0).length, pnlR = regles.reduce((a, t) => a + n(t.pnl), 0);
  $("pScoreTxt").textContent = regles.length ? `${g} gagnés, ${regles.length - g} perdus · ${(pnlR >= 0 ? "+" : "") + usd(pnlR)}` : "";
  $("pScoreNote").textContent = `Un carré par pari réglé (vert = gagné, rouge = perdu), en pointillé les ${nbOuv} paris en cours. Premier vrai bilan après 100 à 200 paris réglés.`;
  const a = S.activite || {};
  compteur($("aScan"), n(a.marches_scannes), x => esc(Math.round(x).toLocaleString("fr-FR")));
  compteur($("aFiltres"), n(a.dans_filtres), x => esc(Math.round(x).toLocaleString("fr-FR")));
  compteur($("aCand"), n(a.candidats), x => esc(Math.round(x).toLocaleString("fr-FR")));
  compteur($("aCarnets"), n(a.carnets_lus), x => esc(Math.round(x).toLocaleString("fr-FR")));
  const flux = [...(a.flux || [])].reverse().slice(0, 40);
  $("pFlux").innerHTML = flux.length ? flux.map(f => { const k = f.t + "|" + f.txt, nouveau = !P.premier && !P.vus.has(k); P.vus.add(k); const u = lienPoly(f.url), tg = FLUX[f.type] || ["neutre", "INFO"];
    return `<div class="${nouveau ? "new" : ""}"><time class="num">${esc(hms(f.t))}</time><span><span class="tag ${tg[0]}">${tg[1]}</span>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(f.txt)}</a>` : esc(f.txt)}</span></div>`; }).join("")
    : `<div class="empty">Le premier scan arrive dans la minute.</div>`;
  const tr = [...(S.trades || [])].reverse().slice(0, 30);
  $("pNbTrades").textContent = n(S.nb_trades) + " au total";
  $("pTrades").innerHTML = tr.length ? tr.map(t => {
    let [cls, lab] = TAGS[t.sens] || ["neutre", "?"];
    if (t.sens === "reglement") [cls, lab] = n(t.pnl) > 0 ? ["gagne", "GAGNÉ"] : n(t.pnl) < 0 ? ["perdu", "PERDU"] : ["neutre", "RÉSOLU"];
    const k = t.t + "|" + t.question + "|" + t.sens, neuf = !P.premier && !P.vus.has(k); P.vus.add(k);
    return `<div class="row${neuf ? " neuf" : ""}"><div><span class="tag ${cls}">${lab}</span>${t.strategie === "baleines" ? '<span class="tag exp">EXP.</span>' : ""}<b>${esc(t.issue)}</b> à ${esc(proba(t.prix))}<div>${esc(t.question)}</div><div class="r">${esc(t.raison)}</div></div>
    <div style="text-align:right" class="num"><div>${esc(usd(t.montant))}</div>${t.pnl != null ? `<div class="${n(t.pnl) >= 0 ? "up" : "down"}">${n(t.pnl) >= 0 ? "+" : ""}${esc(usd(t.pnl))}</div>` : ""}<div class="r">${esc(heure(t.t))}</div></div></div>`; }).join("") : `<div class="empty">Pas encore de trade.</div>`;
  if (T.notifie && tr.length) { const t = tr[0], k = t.t + "|" + t.question + "|" + t.sens; if (P._dernier && P._dernier !== k) T.notifie(`Polymarket : ${t.sens === "reglement" ? (n(t.pnl) > 0 ? "pari gagné" : "pari perdu") : t.sens} « ${String(t.question).slice(0, 80)} »`); P._dernier = k; }
  P.premier = false;
  const sg = S.strategie || {}, ex = S.experimentale || {}, pm = S.parametres || {};
  $("pStrat").innerHTML = `<b>${esc(sg.nom)}</b> (${sg.validee ? "validée par la recherche" : "non validée : mode observation, mises réduites"}). ${esc(sg.resume)} Mise : ${esc((n(sg.part_par_marche) * 100).toFixed(0))} % de la valeur par marché, ${esc(n(pm.positions_max))} positions au plus, écart achat/vente de ${esc((n(pm.spread_max) * 100).toFixed(0))} centimes maximum. ${esc(ex.nom)} : ${esc(ex.etat)}, budget plafonné à ${esc((n(ex.budget) * 100).toFixed(0))} %.`;
  const sv = S.surveilles || [];
  $("pNbSurv").textContent = sv.length ? sv.length + " candidat(s)" : "";
  $("pSurveilles").innerHTML = sv.length ? sv.map(x => { const u = lienPoly(x.url), enPos = String(x.etat) === "en position";
    return `<div class="row"><div>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener" style="color:inherit;font-weight:700">${esc(x.question)}</a>` : `<b>${esc(x.question)}</b>`}
      <div class="r">« ${esc(x.issue)} » · ${esc(echeance(x.echeance).txt)} · ${esc(n(x.volume24h).toLocaleString("fr-FR"))} $ échangés en 24 h</div>
      <div class="mini"><i style="width:${borne(x.prix).toFixed(1)}%"></i></div><div class="r" style="color:${enPos ? "var(--up)" : "var(--mute)"}">${esc(x.etat)}</div></div>
      <div class="num">${esc(proba(x.prix))}</div></div>`; }).join("")
    : `<div class="empty">Aucun marché ne correspond à la stratégie en ce moment. Le bot rescanne chaque minute.</div>`;
  $("pJournal").innerHTML = [...(S.journal || [])].reverse().map(l => `<div><time>${esc(heure(l.t))}</time>${esc(l.msg)}</div>`).join("");
  const retard = (Date.now() - new Date(S.maj).getTime()) / 60000;
  $("pMaj").textContent = "Dernière synchro du bot : " + new Date(S.maj).toLocaleString("fr-FR") + (retard > 15 ? " (le bot semble arrêté ou en cours de relance)." : ". Les prix des positions bougent en direct.");
  dessineP(); renderLiveP();
}
function renderRechercheP() {
  const RS = P.RS;
  if (!RS) { $("pRecherche").innerHTML = `<div class="empty">Recherche pas encore chargée. Elle rejoue plusieurs stratégies sur des milliers de marchés déjà résolus, coûts inclus, et ne valide que ce qui tient sur une période jamais vue.</div>`; return; }
  const c = RS.choix || {}, per = RS.periode || {};
  $("pRsDate").textContent = (RS.genere_le || "").slice(0, 10);
  const rows = (RS.strategies || []).map(s => { const o = s.oos || {}, pf = s.portefeuille || {}, r = n(o.rend_moyen_pct);
    return `<div class="row"><div><b>${esc(s.nom)}</b> <span class="tag ${s.eligible ? "gagne" : "neutre"}">${s.eligible ? "VALIDÉE" : s.nom === RS.reference ? "RÉFÉRENCE" : "NON VALIDÉE"}</span><div class="r">${esc(s.description)}</div>
      <div class="r">${esc(n(o.nb_trades))} trades · ${esc(n(o.gagnants_pct).toFixed(0))} % gagnants pour un prix moyen payé de ${esc(proba(o.prix_moyen))} · ${esc(n(o.jours_moyens).toFixed(1))} j bloqués · pire série : ${esc(n(o.pire_serie_pertes))} pertes</div>
      ${(s.refus || []).length ? `<div class="r">Refus : ${esc(s.refus.join(" ; "))}</div>` : ""}</div>
      <div class="num" style="text-align:right"><div class="${r >= 0 ? "up" : "down"}">${esc(pct(r))}</div><div class="r">par trade · t ${esc(n(o.t_stat).toFixed(2))}</div><div class="r">100 $ : ${esc(pct(pf.rendement_pct, 1))}</div><div class="r">baisse ${esc(pct(-Math.abs(n(pf.drawdown_max_pct)), 0))}</div></div></div>`; }).join("");
  $("pRecherche").innerHTML = `<div class="bandeau ${c.valide ? "ok" : ""}">${c.valide ? "Stratégie validée par la règle fixée à l'avance" : "Aucune stratégie validée : aucun avantage prouvé, le bot observe à mises réduites"}</div>
    <p class="verdict">${esc(RS.verdict)}</p>
    <p class="note">${esc(n(RS.nb_marches).toLocaleString("fr-FR"))} marchés résolus du ${esc((per.debut || "").slice(0, 10))} au ${esc((per.fin || "").slice(0, 10))}. Résultats ci-dessous : uniquement après le ${esc((per.coupure || "").slice(0, 10))}, période jamais vue pendant le réglage, coûts déduits.${RS.source === "synthetique" ? " DONNÉES FICTIVES." : ""}</p>
    ${rows}<details class="note"><summary>Règle de sélection et limites</summary><p>${esc(RS.regle_selection)}</p>${(RS.avertissements || []).map(a => `<p>· ${esc(a)}</p>`).join("")}</details>`;
}
segPeriode("pSeg", p => { P.per = p; dessineP(); });

async function milieu(jeton) {
  const m = await jsonUrl(`${CLOB}/midpoint?token_id=${encodeURIComponent(jeton)}`);
  const x = Number(m?.mid); if (x > 0 && x < 1) return x;
  const b = await jsonUrl(`${CLOB}/book?token_id=${encodeURIComponent(jeton)}`); if (!b) return null;
  const px = l => (Array.isArray(l) ? l : []).map(z => Number(z.price)).filter(z => z > 0 && z < 1);
  const bids = px(b.bids), asks = px(b.asks);
  if (bids.length && asks.length) { const bb = Math.max(...bids), ba = Math.min(...asks); return ba - bb <= 0.1 ? (bb + ba) / 2 : bb; }
  return bids.length ? Math.max(...bids) : null;
}
async function tickP() {
  if (!P.S || P.occupe || document.hidden) return;
  const jetons = Object.keys(P.S.positions || {}).filter(j => /^\d+$/.test(j)).slice(0, 20);
  if (!jetons.length) return;
  P.occupe = true;
  try { const res = await Promise.all(jetons.map(milieu));
    res.forEach((m, i) => { if (m != null) { P.live[jetons[i]] = m; P.lastTick = Date.now(); } });
    for (const j of Object.keys(P.live)) if (!P.S.positions[j]) delete P.live[j];
  } catch (e) {} finally { P.occupe = false; }
  renderLiveP();
}
async function refreshP() {
  const s = await lireData("data-poly", "state_poly.json");
  if (!s || typeof s !== "object") { if (!P.S) { $("pErr").hidden = false; $("pErr").textContent = "Les données du bot Polymarket ne sont pas encore arrivées (premier démarrage ou connexion lente, réessai automatique)."; } return; }
  $("pErr").hidden = true; P.S = s;
  try { renderStateP(); } catch (e) { console.error(e); }
  tickP();
}
async function refreshRechercheP() { P.RS = await lireData("data-poly", "research_poly.json"); try { renderRechercheP(); } catch (e) { console.error(e); } }

/* ---------- horloge commune ---------- */
setInterval(() => {
  $("horloge").textContent = new Date().toLocaleTimeString("fr-FR");
  compteARebours();
  if (C.S) { const ok = Date.now() - C.lastTick < 20000; $("cDot").className = "dot" + (ok ? " on" : ""); $("cLive").textContent = ok ? "prix en direct" : "connexion…"; if (vue === "crypto") renderLiveC(); }
  if (P.S) { const direct = Date.now() - P.lastTick < 40000, frais = Date.now() - new Date(P.S.maj).getTime() < 180000;
    $("pDot").className = "dot" + (direct || frais ? " on" : ""); $("pLive").textContent = direct ? "prix en direct" : frais ? "bot actif" : "en attente du bot";
    const actif = frais && P.S.statut === "actif"; $("pRadar").style.animationPlayState = actif ? "running" : "paused";
    if (vue === "poly") renderLiveP(); }
  if (T.parSeconde) T.parSeconde(vue === "poly" ? (P.S ? valeurP() : null) : (C.S ? valeurC() : null), vue);
}, 1000);

const ro = new ResizeObserver(es => es.forEach(e => { const w = Math.round(e.contentRect.width); if (e.target._w === w) return; e.target._w = w; if (e.target.id === "cFig" && vue === "crypto") dessineC(); if (e.target.id === "pFig" && vue === "poly") dessineP(); }));
ro.observe($("cFig")); ro.observe($("pFig"));
montreVue(vue, false);
compteARebours();
refreshC(); refreshP(); refreshTestsC(); refreshRechercheP(); historiqueKraken();
setInterval(refreshC, 60000); setInterval(refreshP, 30000); setInterval(tickP, T.pollPrix ? 15000 : 8000);
setInterval(refreshTestsC, 600000); setInterval(refreshRechercheP, 600000);
if (T.pollPrix) { pollKraken(); setInterval(pollKraken, 5000); }
window.PB = {C, P, valeurC, valeurP};
})();
