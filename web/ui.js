// Base de la interfaz: utilidades, iconos propios, ventanas, menús y avisos.
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $("#view");
let timers = [];
let cleanup = [];

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || j); } catch (e) {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const p2 = (n) => String(n).padStart(2, "0");
// 0:42 · 12:05 · 5:34:32
const fmt = (s) => {
  s = Math.max(0, s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = Math.floor(s % 60);
  return h ? `${h}:${p2(m)}:${p2(x)}` : `${m}:${p2(x)}`;
};
const fmtLong = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60; return h ? `${h} h ${m} min` : m ? `${m} min ${s % 60} s` : `${s} s`; };
const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
const fmtDate = (t) => new Date(t * 1000).toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
const toSecs = (v) => { v = String(v).trim().replace(",", "."); return v.includes(":") ? v.split(":").reduce((a, b) => a * 60 + +b, 0) : +v; };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const andList = (a) => a.length > 1 ? a.slice(0, -1).join(", ") + " y " + a[a.length - 1] : a[0] || "";
const isTyping = () => { const a = document.activeElement; return a && (["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) && a.type !== "range" && a.type !== "checkbox" || a.isContentEditable); };
const pref = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
function every(ms, fn) { fn(); const id = setInterval(fn, ms); timers.push(id); return id; }
function mount(tpl, work = false) {
  view.innerHTML = ""; view.className = work ? "work" : ""; view.scrollTop = 0;
  view.appendChild($(`#${tpl}`).content.cloneNode(true)); paintIcons(view);
}

// ------------------------------------------------------------ iconos
const ICONS = {
  library: '<rect x="3.5" y="4" width="5" height="16"/><rect x="11.5" y="4" width="5" height="16"/><path d="M20 5.5v13"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  queue: '<path d="M4 6h16M4 12h8M4 18h8"/><path class="f" d="M15 11.5v9l7-4.5z"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M4 20h16"/>',
  upload: '<path d="M12 15V4M7 8.5l5-5 5 5M4 20h16"/>',
  settings: '<path d="M4 7h8M18 7h2M4 17h2M12 17h8"/><rect x="12.5" y="4.5" width="5" height="5"/><rect x="6.5" y="14.5" width="5" height="5"/>',
  coffee: '<path d="M4 9.5h12v5.5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z"/><path d="M16 11h1.8a2.4 2.4 0 0 1 0 4.8H16M8 3.5V6M12 3.5V6"/>',
  update: '<circle cx="12" cy="12" r="8.5"/><path d="M12 16.500V8M8.500 11.200L12 7.700l3.500 3.500"/>',
  theme: '<circle cx="12" cy="12" r="8"/><path class="f" d="M12 4a8 8 0 0 1 0 16z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
  folder: '<path d="M3.5 6h6l2 2.5h9V19h-17z"/>',
  left: '<path d="M14.5 5.5L8 12l6.5 6.5"/>', right: '<path d="M9.5 5.5L16 12l-6.5 6.5"/>',
  more: '<circle class="f" cx="5.5" cy="12" r="1.7"/><circle class="f" cx="12" cy="12" r="1.7"/><circle class="f" cx="18.5" cy="12" r="1.7"/>',
  play: '<path class="f" d="M7 4.5v15L19.5 12z"/>', pause: '<path class="f" d="M6.5 5h4v14h-4zM13.5 5h4v14h-4z"/>',
  back1: '<path d="M11 6l-6 6 6 6M19 6l-6 6 6 6"/>', fwd1: '<path d="M13 6l6 6-6 6M5 6l6 6-6 6"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11"/><path d="M5 15.5h-.5v-11h11V5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', close: '<path d="M6 6l12 12M18 6L6 18"/>',
  grid: '<rect x="4.5" y="4.5" width="5.5" height="15"/><rect x="14" y="4.5" width="5.5" height="15"/>', list: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  title: '<path d="M4.5 8V5h15v3M12 5v14M8.5 19h7"/>',
  cut: '<path d="M8.5 4.5H5v15h3.5M15.5 4.5H19v15h-3.5M12 8.5v7"/>',
  frame: '<path d="M2.5 7.5h3M2.5 16.5h3M18.5 7.5h3M18.5 16.5h3M2.5 7.5v9M21.5 7.5v9"/><rect x="8.5" y="3.5" width="7" height="17"/>',
  captions: '<rect x="3.5" y="5.5" width="17" height="13"/><path d="M7 14.5h6M15.5 14.5H17M7 11h3M12.5 11H17"/>',
  rhythm: '<path d="M4 10v4M8 6v12M12 9v6M16 4v16M20 10v4"/>',
  brand: '<path d="M4.5 4.5h15v9l-6 6h-9z"/><path d="M19.5 13.5h-6v6"/>',
  out: '<path d="M11 5H4.5v14.5H19V13"/><path d="M14 4.5h5.5V10M19.5 4.5L11.5 12.5"/>',
  film: '<rect x="3.5" y="5.5" width="17" height="13"/><path d="M8 5.5v13M16 5.5v13"/>', link: '<path d="M9.5 14.5l5-5M8 11l-2.5 2.5a3.5 3.5 0 0 0 5 5L13 16M16 13l2.5-2.5a3.5 3.5 0 0 0-5-5L11 8"/>',
  redo: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L20 9.2M20 4v5.2h-5.2"/>',
  star: '<path class="f" d="M12 3.5l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9L6.700 20l1.100-6-4.400-4.200 6-.8z"/>',
  layers: '<path d="M12 4l8.500 4.500L12 13 3.500 8.500zM4 13.500l8 4.200 8-4.200"/>', pin: '<path d="M6 4.500h12M8 4.500l1 7-3 3h12l-3-3 1-7M12 14.500v6"/>',
  zoomin: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.500h5M10.500 8v5"/>', zoomout: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.500h5"/>', fit: '<path d="M4 9V4.500h4.500M20 9V4.500h-4.500M4 15v4.500h4.500M20 15v4.500h-4.500"/>', pen: '<path d="M4.500 19.500l1-4.500L16 4.500l3.500 3.500L9 18.500z"/>',
};
const icon = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;
function paintIcons(root = document) { $$("[data-ic]", root).forEach(e => { if (!e.firstElementChild) e.innerHTML = icon(e.dataset.ic, +e.dataset.s || 18); }); }
// marca: un corte vertical dentro de un cuadro horizontal (lo que hace la app)
const MARK = (s = 30) => `<svg width="${s * 1.2}" height="${s}" viewBox="0 0 36 30" aria-hidden="true"><path d="M14 8H2.500v14H14M29 8h4.500v14H29" fill="none" stroke="currentColor" stroke-width="2.600"/><rect x="16.500" y="1.500" width="10" height="27" fill="var(--acc)"/></svg>`;

// dibujos de cada encuadre
const person = (x, y, k) => `<circle class="p" cx="${x}" cy="${y}" r="${4 * k}"/><path class="p" d="M${x - 8 * k} ${y + 14 * k}c0-5 3-8 ${8 * k}-8s${8 * k} 3 ${8 * k} 8z"/>`;
const FRAME_SVG = {
  auto: `<rect class="d" x="3" y="17" width="68" height="38"/><rect class="g" x="26" y="4" width="22" height="56"/>${person(37, 30, 1)}<rect class="o" x="26" y="4" width="22" height="56"/>`,
  streamer: `<rect class="g" x="22" y="3" width="30" height="58"/>${person(37, 11, .72)}<path class="w" d="M22 24h30v37H22z"/><path class="p" d="M27 50l7-9 5 5 4-4 5 8z"/><rect class="o" x="22" y="3" width="30" height="58"/><path class="o" d="M22 24h30"/>`,
  apilado: `<rect class="g" x="22" y="3" width="30" height="58"/>${person(37, 17, 1)}<path class="w" d="M22 44h30v17H22z"/>${person(44, 49, .6)}<rect class="o" x="22" y="3" width="30" height="58"/><path class="o" d="M22 44h30"/>`,
  full: `<rect class="g" x="22" y="3" width="30" height="58"/><rect class="w" x="22" y="23" width="30" height="18"/>${person(37, 28, .72)}<rect class="o" x="22" y="3" width="30" height="58"/><path class="o" d="M22 23h30M22 41h30"/>`,
  split: `<rect class="g" x="22" y="3" width="30" height="58"/>${person(37, 11, .8)}${person(37, 40, .8)}<rect class="o" x="22" y="3" width="30" height="58"/><path class="o" d="M22 32h30"/>`,
};
const frameSvg = (k) => `<svg viewBox="0 0 74 64" aria-hidden="true">${FRAME_SVG[k]}</svg>`;

// control de opciones con valor: los botones llevan data-v
function choice(el, onchange) {
  const bs = $$("button[data-v]", el);
  const c = {
    el, get value() { return el.dataset.value ?? ""; },
    set value(v) { el.dataset.value = v; bs.forEach(b => { const on = b.dataset.v === String(v); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); }); },
  };
  bs.forEach(b => { b.type = "button"; b.onclick = () => { c.value = b.dataset.v; onchange && onchange(b.dataset.v); }; });
  c.value = el.dataset.value ?? (bs[0] ? bs[0].dataset.v : "");
  return c;
}

// ------------------------------------------------------------ avisos, ventanas y menús
function toast(txt, bad = false) {
  const t = document.createElement("div"); t.className = "toast" + (bad ? " bad" : ""); t.textContent = txt; t.setAttribute("role", "status");
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), bad ? 6000 : 3200);
}
const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

// ask({title, text, ok, danger, fields:[{name,label,value,placeholder}]}) → null si se cancela, {valores} si se acepta
function ask({ title, text = "", ok = "Aceptar", no = "Cancelar", danger = false, fields = [] }) {
  return new Promise(res => {
    const d = document.createElement("dialog"); d.className = "dlg";
    d.innerHTML = `<form method="dialog"><div class="in"><h2>${esc(title)}</h2>${text ? `<p class="mut">${esc(text)}</p>` : ""}
      ${fields.map(f => `<label class="fld" style="margin-top:14px"><span class="lb">${esc(f.label)}</span><input type="text" name="${f.name}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder ?? "")}" maxlength="${f.max || 120}" autocomplete="off"></label>`).join("")}</div>
      <div class="acts"><button type="button" class="btn gh" data-no>${esc(no)}</button><button type="submit" class="btn pri" data-yes>${esc(ok)}</button></div></form>`;
    if (danger) { const y = $("[data-yes]", d); y.style.background = y.style.borderColor = "var(--bad)"; y.style.color = "#fff"; }
    let out = null;
    $("form", d).onsubmit = () => { out = Object.fromEntries(fields.map(f => [f.name, $(`[name="${f.name}"]`, d).value])); };
    $("[data-no]", d).onclick = () => d.close();
    d.onclose = () => { d.remove(); res(out); };
    document.body.appendChild(d); d.showModal();
    const first = $("input", d); if (first) { first.focus(); first.select(); } else $(danger ? "[data-no]" : "[data-yes]", d).focus();
  });
}

let openMenu = null;
function closeMenu() { if (openMenu) { openMenu.el.remove(); document.removeEventListener("pointerdown", openMenu.out, true); document.removeEventListener("keydown", openMenu.key, true); const b = openMenu.btn; openMenu = null; b.setAttribute("aria-expanded", "false"); } }
// items: {label, icon, hint, bad, dot, run} · "-" separador · {head}
function menu(btn, items) {
  const same = openMenu && openMenu.btn === btn; closeMenu(); if (same) return;
  const el = document.createElement("div"); el.className = "menu"; el.setAttribute("role", "menu");
  for (const it of items) {
    if (it === "-") { el.appendChild(document.createElement("hr")); continue; }
    if (it.head) { const h = document.createElement("div"); h.className = "hd"; h.textContent = it.head; el.appendChild(h); continue; }
    const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitem"); if (it.bad) b.className = "bad";
    b.innerHTML = `${it.dot ? `<i class="dot" style="background:${it.dot}"></i>` : it.icon ? icon(it.icon, 17) : ""}<span>${esc(it.label)}${it.hint ? `<small>${esc(it.hint)}</small>` : ""}</span>`;
    b.onclick = (e) => { e.stopPropagation(); closeMenu(); guard(it.run)(); };
    el.appendChild(b);
  }
  (btn.closest("dialog") || document.body).appendChild(el);
  const r = btn.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
  el.style.top = (r.bottom + h + 8 > innerHeight && r.top - h - 4 > 0 ? r.top - h - 4 : Math.min(r.bottom + 4, innerHeight - h - 8)) + "px";
  const out = (e) => { if (!el.contains(e.target) && !btn.contains(e.target)) closeMenu(); };
  const key = (e) => {
    const bs = $$("button", el), i = bs.indexOf(document.activeElement);
    if (e.key === "Escape") { e.stopPropagation(); closeMenu(); btn.focus(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); bs[(i + (e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length].focus(); }
  };
  document.addEventListener("pointerdown", out, true); document.addEventListener("keydown", key, true);
  openMenu = { el, btn, out, key }; btn.setAttribute("aria-expanded", "true");
  const b0 = $("button", el); b0 && b0.focus({ preventScroll: true });
}

const noOpen = (msg) => `<div class="page"><div class="empty"><h2>No se pudo abrir</h2><p>${esc(msg)}</p><a class="btn" href="#/">Ir a la biblioteca</a></div></div>`;

// ------------------------------------------------------------ tema
function setTheme(t) { document.documentElement.dataset.theme = t; pref.set("tema", t); window.dispatchEvent(new Event("tema")); }
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ------------------------------------------------------------ etapas del análisis (mismos tramos que cliper/jobs.py)
const STAGES = [["Descarga", 0, 12], ["Copia de trabajo", 12, 25], ["Voz", 25, 65], ["Imagen", 65, 85], ["Momentos", 85, 96], ["Portadas", 96, 100]];
const isBusy = (p) => p.status !== "listo" && p.status !== "error";
function stagesHtml(p, labels = true) {
  const v = p.progress || 0, list = p.source && p.source.url ? STAGES : STAGES.slice(1);
  return `<div class="stages">${list.map(([n, a, b]) => {
    const f = Math.max(0, Math.min(1, (v - a) / (b - a)));
    return `<span style="--w:${Math.max(12, b - a)}" class="${f >= 1 ? "done" : v >= a && p.status === "procesando" ? "now" : ""}"><i><b style="width:${f * 100}%"></b></i>${labels ? `<small>${n}</small>` : ""}</span>`;
  }).join("")}</div>`;
}

// ------------------------------------------------------------ carpetas y predeterminados (compartido)
let FOLDERS = [];
const folderOf = (id) => FOLDERS.find(f => f.id === id);
const moveProject = (pid, fid) => api(`/api/projects/${pid}`, { method: "PUT", json: { folder: fid || null } });
function folderOptions(sel, current, emptyLabel = "Sin carpeta") {
  sel.innerHTML = `<option value="">${emptyLabel}</option>` + FOLDERS.map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join("");
  sel.value = current || "";
}
const DEF_LABELS = [["titulo", "Titular"], ["subtitulos", "Subtítulos"], ["marca", "Marca"], ["encuadre", "Encuadre"],
  ["estilo", "Estilo y efectos"], ["opciones", "Cantidad, duración, idioma y descarga"]];
const MODE_LABELS = { auto: "vertical siguiendo a quien habla", streamer: "streamer: cámara arriba, juego abajo",
  apilado: "vertical arriba, horizontal completo abajo", full: "video entero con fondo desenfocado" };
const modeText = (v) => v.mode === "apilado" && v.swap ? "horizontal completo arriba, vertical abajo" : MODE_LABELS[v.mode] || v.mode;
