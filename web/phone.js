// Cómo se verá el clip en un teléfono: silueta, botones de la app y aviso de lo que queda tapado.
// Son medidas aproximadas (en puntos de pantalla): ninguna app publica las suyas y cambian con cada versión.
"use strict";

const PHONES = {
  iphone: { name: "iPhone", w: 402, h: 874, top: 62, foot: 34, r: 56, cut: { x: 138, y: 14, w: 126, h: 37 }, clock: { x: 44, y: 21, w: 46, h: 22 }, bat: { x: 312, y: 21, w: 52, h: 22 }, what: "La isla dinámica" },
  android: { name: "Android", w: 412, h: 915, top: 50, foot: 24, r: 38, cut: { x: 194, y: 13, w: 24, h: 24 }, clock: { x: 20, y: 15, w: 44, h: 20 }, bat: { x: 344, y: 15, w: 48, h: 20 }, what: "La cámara" },
};
const PHONE_APPS = {
  youtube: { name: "YouTube", menu: (W) => ({ x: W - 100, w: 88 }), col: { w: 50, h: 384, n: 6 }, text: { w: 84, h: 98, n: 2 } },
  tiktok: { name: "TikTok", menu: (W) => ({ x: 60, w: W - 72 }), col: { w: 54, h: 424, n: 6 }, text: { w: 104, h: 92, n: 2 } },
  reels: { name: "Reels", menu: (W) => ({ x: 12, w: W - 24 }), col: { w: 48, h: 366, n: 5 }, text: { w: 92, h: 106, n: 3 } },
};
const PHONE_TOP = 290, PHONE_LOW = 1600;      // de aquí a aquí un texto centrado queda libre en las tres apps

function phoneMap(phone, app) {
  const P = PHONES[phone], A = PHONE_APPS[app], R = P.h - 49 - P.foot;             // alto que queda para el video, sobre la barra de abajo
  const k = Math.max(R / 1920, P.w / 1080), off = (P.w - 1080 * k) / 2, m = A.menu(P.w);
  const obs = [{ id: "cut", ...P.cut }, { id: "bar", ...P.clock }, { id: "bar", ...P.bat }, { id: "menu", x: m.x, y: P.top, w: m.w, h: 40 },
    { id: "col", x: P.w - A.col.w - 8, y: R - A.col.h - 8, w: A.col.w, h: A.col.h }, { id: "text", x: 12, y: R - A.text.h - 8, w: P.w - A.text.w - 12, h: A.text.h }];
  return { P, A, R, k, off, obs, box: (o) => ({ x: (o.x - off) / k, y: o.y / k, w: o.w / k, h: o.h / k }), left: -off / k, right: (P.w - off) / k };
}

const opaqueCache = new Map();
function opaqueBox(url) {                      // dónde hay tinta de verdad dentro de la imagen del titular
  if (opaqueCache.has(url)) return opaqueCache.get(url);
  const im = CliperPreview.cachedImg(url); if (!im) return null;
  const c = document.createElement("canvas"); c.width = im.naturalWidth; c.height = im.naturalHeight;
  const x = c.getContext("2d", { willReadFrequently: true }); x.drawImage(im, 0, 0);
  let a = 1e9, b = -1, t = 1e9, d = -1; const px = x.getImageData(0, 0, c.width, c.height).data;
  for (let j = 0; j < c.height; j += 2) for (let i = 0; i < c.width; i += 2) if (px[(j * c.width + i) * 4 + 3] > 40) { if (i < a) a = i; if (i > b) b = i; if (j < t) t = j; if (j > d) d = j; }
  if (a < 4 && b > c.width - 5) {              // una franja de lado a lado: lo que importa es su texto
    const m = (Math.round((t + d) / 4) * 2 * c.width + a) * 4; let l = 1e9, e = -1;
    for (let j = t; j <= d; j += 2) for (let i = a; i <= b; i += 2) { const q = (j * c.width + i) * 4; if (px[q + 3] > 200 && Math.abs(px[q] - px[m]) + Math.abs(px[q + 1] - px[m + 1]) + Math.abs(px[q + 2] - px[m + 2]) > 160) { if (i < l) l = i; if (i > e) e = i; } }
    if (e > l) { a = l; b = e; }
  }
  const r = b < 0 ? { x: 0, y: 0, w: 0, h: 0 } : { x: a, y: t, w: b - a, h: d - t };
  if (opaqueCache.size > 80) opaqueCache.clear(); opaqueCache.set(url, r); return r;
}

function phoneItems(pv) {                      // lo que el clip pone encima del video, en píxeles de 1080×1920
  const p = pv.plan, out = [];
  if (p.title.on && p.title.text) { const b = opaqueBox(CliperPreview.titleUrl(p.title)); if (b && b.w) out.push({ id: "title", x: b.x, y: p.title.y + b.y, w: b.w, h: b.h }); }
  if (p.subs.on) for (const g of p.subs.pages) { const b = pv.pageBox(g, p.subs); if (b.w) out.push({ id: "subs", ...b }); }
  for (const b of p.brand || []) out.push({ id: "brand", x: b.x - b.w / 2, y: b.y - b.h / 2, w: b.w, h: b.h });
  for (const s of p.stickers || []) out.push({ id: "stick", x: s.x - s.size / 2, y: s.y - s.size / 2, w: s.size, h: s.size });
  return out;
}

function phoneHits(items, phone, app) {
  const M = phoneMap(phone, app), hits = [];
  for (const it of items) {
    for (const o of M.obs) {
      const b = M.box(o), w = Math.min(it.x + it.w, b.x + b.w) - Math.max(it.x, b.x), h = Math.min(it.y + it.h, b.y + b.h) - Math.max(it.y, b.y);
      if (w > 8 && h > 8 && (w * h > 0.04 * it.w * it.h || w * h > 0.3 * b.w * b.h)) hits.push({ it: it.id, o: o.id, ref: o });
    }
    if (it.x < M.left - 8 || it.x + it.w > M.right + 8) hits.push({ it: it.id, o: "side" });
  }
  return hits;
}

const PHONE_SAY = { bar: ["La hora y la batería", "tapan"], menu: ["El menú de arriba", "tapa"], col: ["Los botones", "tapan parte de"], text: ["El nombre y la descripción", "tapan"] };
const PHONE_IT = { title: "el titular", subs: "los subtítulos", brand: "un sticker", stick: "un emoji o logo" };
function phoneText(hits, P) {
  const out = [];
  for (const it of Object.keys(PHONE_IT)) {
    const os = [...new Set(hits.filter(h => h.it === it).map(h => h.o))];
    for (const o of os) out.push(o === "side" ? `La pantalla recorta ${PHONE_IT[it]} por los lados.` : o === "cut" ? `${P.what} tapa ${PHONE_IT[it]}.` : `${PHONE_SAY[o][0]} ${PHONE_SAY[o][1]} ${PHONE_IT[it]}.`);
  }
  return out;
}

function phoneSvg(M, hits) {
  const { P, A, R, obs } = M, W = P.w, H = P.h, ink = "rgba(255,255,255,.9)", soft = "rgba(255,255,255,.55)";
  const rr = (x, y, w, h, r, f) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${f}"/>`, dot = (x, y, r, f) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}"/>`;
  const [, , , menu, col, text] = obs, cut = P.cut, my = menu.y + 20;
  let s = rr(0, R, W, H - R, 0, "#0b0d0e");
  for (let i = 0; i < 5; i++) s += i === 2 ? rr(W / 2 - 15, R + 13, 30, 22, 7, soft) : rr(W * (i + .5) / 5 - 9, R + 15, 18, 18, 6, soft);
  s += rr(W / 2 - 66, H - (P.foot > 30 ? 13 : 11), 132, 5, 2.5, ink);
  s += menu.w < 120 ? dot(menu.x + 20, my, 11, ink) + dot(menu.x + 66, my, 11, ink)
    : A === PHONE_APPS.tiktok ? rr(W / 2 - 92, my - 6, 80, 12, 6, soft) + rr(W / 2 + 12, my - 6, 80, 12, 6, ink) + dot(menu.x + menu.w - 14, my, 11, ink)
    : rr(menu.x + 4, my - 8, 84, 16, 8, ink) + dot(menu.x + menu.w - 16, my, 11, ink);
  const step = col.h / A.col.n, cx = col.x + col.w / 2;
  for (let i = 0; i < A.col.n; i++) { const y = col.y + step * (i + .5); s += dot(cx, y - 7, 16, ink) + rr(cx - 11, y + 14, 22, 6, 3, soft); }
  s += dot(text.x + 16, text.y + 18, 16, ink) + rr(text.x + 40, text.y + 11, 120, 12, 6, ink) + rr(text.x + 172, text.y + 5, 62, 26, 13, soft);
  for (let i = 0; i < A.text.n; i++) s += rr(text.x, text.y + 46 + i * 20, (i === A.text.n - 1 ? .6 : .9) * text.w, 11, 5.5, i ? soft : ink);
  s += `<text x="${P.clock.x + P.clock.w / 2}" y="${P.clock.y + 17}" fill="#fff" font-family="system-ui, sans-serif" font-size="17" font-weight="600" text-anchor="middle">9:41</text>`;
  s += `<rect x="${P.bat.x + P.bat.w - 28}" y="${P.bat.y + 5}" width="24" height="12" rx="4" fill="none" stroke="#fff" stroke-width="1.4"/>` + rr(P.bat.x + P.bat.w - 26, P.bat.y + 7, 16, 8, 2, "#fff") + dot(P.bat.x + 12, P.bat.y + 11, 5, "#fff");
  s += rr(cut.x, cut.y, cut.w, cut.h, cut.h / 2, "#000");
  for (const o of new Set(hits.map(h => h.ref).filter(Boolean))) s += `<rect x="${o.x - 3}" y="${o.y - 3}" width="${o.w + 6}" height="${o.h + 6}" rx="${Math.min(o.h / 2 + 3, 14)}" fill="${o.id === "cut" ? "none" : "rgba(255,107,71,.16)"}" stroke="#ff6b47" stroke-width="2.5" stroke-dasharray="7 5"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">${s}</svg>`;
}

// Une todo al monitor del editor. move(clave, píxeles) cambia la altura del titular o de los subtítulos.
function phoneView(pv, move) {
  const stage = $("#stage"), lay = $("#pvlay"), warn = $("#pvwarn"), apps = $("#pvapp");
  let sig = "";
  const phone = choice($("#pvphone"), (v) => { pref.set("pv-tel", v); sig = ""; tick(); }), app = choice(apps, (v) => { pref.set("pv-app", v); sig = ""; tick(); });
  phone.value = PHONES[pref.get("pv-tel", "")] ? pref.get("pv-tel", "") : ""; app.value = PHONE_APPS[pref.get("pv-app", "youtube")] ? pref.get("pv-app", "youtube") : "youtube";
  function tick() {
    const p = pv.plan, on = phone.value; if (!stage.isConnected) return;
    stage.classList.toggle("phone", !!on); apps.hidden = !on;
    if (!p) { lay.innerHTML = ""; return; }
    const items = phoneItems(pv), s = JSON.stringify([on, app.value, items.map(i => [i.id, Math.round(i.x), Math.round(i.y), Math.round(i.w), Math.round(i.h)])]);
    if (s === sig) return; sig = s;
    const bad = (a, b) => phoneHits(items, a, b).some(h => h.it === "title" || h.o !== "col");
    $$("button", phone.el).forEach(b => { const x = b.dataset.v; if (x) mark(b, Object.keys(PHONE_APPS).some(a => bad(x, a)), PHONES[x].name); });
    $$("button", app.el).forEach(b => mark(b, on ? bad(on, b.dataset.v) : false, PHONE_APPS[b.dataset.v].name));
    const cv = $("#cv");
    if (!on) { lay.innerHTML = ""; warn.hidden = true; cv.style.cssText = ""; stage.style.cssText = ""; return; }
    const M = phoneMap(on, app.value), hits = phoneHits(items, on, app.value), pc = (a, b) => (100 * a / b).toFixed(3) + "%";
    stage.style.setProperty("--ar", M.P.w / M.P.h); stage.style.setProperty("--r", pc(M.P.r, M.P.w) + " / " + pc(M.P.r, M.P.h));
    cv.style.cssText = `left:${pc(M.off, M.P.w)};width:${pc(1080 * M.k, M.P.w)};height:${pc(1920 * M.k, M.P.h)}`;
    lay.innerHTML = phoneSvg(M, hits);
    const ls = phoneText(hits, M.P), t = items.find(i => i.id === "title"), th = hits.filter(h => h.it === "title" && h.o !== "side" && h.o !== "col");
    const sub = items.filter(i => i.id === "subs"), sh = hits.some(h => h.it === "subs" && !["side", "col"].includes(h.o));
    const dt = t && th.length ? fix(t) : 0, ds = sh ? fix({ y: Math.min(...sub.map(i => i.y)), h: Math.max(...sub.map(i => i.y + i.h)) - Math.min(...sub.map(i => i.y)) }) : 0;
    warn.hidden = false; warn.classList.toggle("ok", !ls.length);
    warn.innerHTML = (ls.length ? ls.map(esc).join(" ") : `Nada queda tapado en ${esc(M.P.name)} con ${esc(M.A.name)}.`) +
      (dt ? ` <button type="button" class="lnk" data-mv="title_y">${dt > 0 ? "Bajar" : "Subir"} el titular</button>` : "") + (ds ? ` <button type="button" class="lnk" data-mv="sub_y">${ds > 0 ? "Bajar" : "Subir"} los subtítulos</button>` : "") +
      `<small>Medidas aproximadas: cada app cambia un poco.</small>`;
    $$("[data-mv]", warn).forEach(b => b.onclick = () => move(b.dataset.mv, b.dataset.mv === "title_y" ? dt : ds));
  }
  const fix = (b) => Math.round(b.y < PHONE_TOP ? PHONE_TOP - b.y : b.y + b.h > PHONE_LOW ? PHONE_LOW - b.y - b.h : 0);
  const mark = (b, bad, name) => { b.classList.toggle("alert", bad); b.title = bad ? `En ${name} algo queda tapado` : ""; };
  every(400, tick);
  return { tick };
}
