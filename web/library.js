// Biblioteca (proyectos y carpetas) y hoja de «Nuevo proyecto».
"use strict";

const isRec = (p) => isBusy(p) && !!p.source && !!p.source.live && p.source.live.mode === "next" && !p.source.file;
const stopRec = guard(async (p) => { if (await ask({ title: "¿Detener la grabación?", text: "Se buscan los clips con lo que se grabó hasta ahora.", ok: "Detener y usar lo grabado" })) { await api(`/api/projects/${p.id}/detener`, { method: "POST" }); toast("Se detiene en unos segundos."); } });

// espera a que acabe un directo de Kick para bajarlo
const isWait = (p) => isBusy(p) && !!p.source && !!p.source.live && p.source.live.mode === "after" && !p.source.file;
const stopWait = guard(async (p) => { if (await ask({ title: "¿Bajarlo sin esperar más?", text: "Se baja lo que el directo lleva hasta ahora. Lo que falte no entra en este proyecto.", ok: "Bajar ahora" })) { await api(`/api/projects/${p.id}/detener`, { method: "POST" }); toast("Empieza a bajar en unos segundos."); } });
const waitHtml = (p) => `<div class="mut small">${esc(p.message || "Esperando a que termine el directo")}</div>`;

function library(cur = "") {
  mount("tpl-library");
  let pSig = "", fSig = "", lSig = "", lives = [], all = [];
  async function newFolder() {
    const r = await ask({ title: "Nueva carpeta", ok: "Crear carpeta", fields: [{ name: "n", label: "Nombre", placeholder: "Kick, Twitch, Podcast…", max: 40 }] });
    if (!r || !r.n.trim()) return;
    const f = await api("/api/folders", { method: "POST", json: { name: r.n } }); location.hash = `#/f/${f.id}`;
  }
  const folderMenu = (btn, f) => menu(btn, [
    { label: "Renombrar carpeta", icon: "pen", run: async () => { const r = await ask({ title: "Renombrar carpeta", ok: "Renombrar", fields: [{ name: "n", label: "Nombre", value: f.name, max: 40 }] }); if (r && r.n.trim()) { await api(`/api/folders/${f.id}`, { method: "PUT", json: { name: r.n } }); refresh(); } } },
    { label: "Usar predeterminados de otra carpeta…", icon: "pin", run: guard(() => copyDefs({ to: f.id })) },
    { label: "Borrar carpeta", icon: "trash", bad: true, run: async () => { if (await ask({ title: `¿Borrar la carpeta «${f.name}»?`, text: "Sus proyectos no se borran: pasan a «Sin carpeta». Los predeterminados de la carpeta sí se borran.", ok: "Borrar carpeta", danger: true })) { await api(`/api/folders/${f.id}`, { method: "DELETE" }); if (cur === f.id) location.hash = "#/"; else refresh(); } } }]);
  async function loadFolders(force = false) {
    const r = await api("/api/folders"); FOLDERS = r.folders;
    const sig = JSON.stringify(r); if (!force && sig === fSig) return; fSig = sig;
    const box = $("#tree"); if (!box) return;
    const row = (id, name, color, n) => `<button class="fc ${cur === id ? "on" : ""}" data-f="${id}">${color ? `<i style="background:${esc(color)}"></i>` : icon("library", 15)}<span class="t">${esc(name)}</span><span class="n">${n}</span></button>`;
    box.innerHTML = row("", "Todo", null, r.total) + r.folders.map(f => `<div class="fcw">${row(f.id, f.name, f.color, f.n)}<button class="btn gh sq sm" data-fm="${f.id}" title="Opciones de la carpeta" aria-label="Opciones de «${esc(f.name)}»">${icon("more", 16)}</button></div>`).join("") +
      (r.folders.length && (r.loose || cur === "sin") ? row("sin", "Sin carpeta", "var(--faint)", r.loose) : "") + `<button class="fc add" id="fadd">${icon("plus", 15)}<span class="t">Nueva carpeta</span></button>`;
    $$(".fc[data-f]", box).forEach(b => {
      b.onclick = () => location.hash = b.dataset.f ? `#/f/${b.dataset.f}` : "#/";
      if (!b.dataset.f) return;
      b.ondragover = (e) => { if (e.dataTransfer.types.includes("text/x-proyecto")) { e.preventDefault(); b.classList.add("drop"); } };
      b.ondragleave = () => b.classList.remove("drop");
      b.ondrop = guard(async (e) => { b.classList.remove("drop"); const pid = e.dataTransfer.getData("text/x-proyecto"); if (pid) { e.preventDefault(); await moveProject(pid, b.dataset.f === "sin" ? null : b.dataset.f); refresh(); } });
    });
    $$("[data-fm]", box).forEach(b => b.onclick = () => folderMenu(b, folderOf(b.dataset.fm)));
    $("#fadd").onclick = guard(newFolder);
    const cf = folderOf(cur), head = $("#lhead");
    head.innerHTML = cf ? `<h1 class="pname">${esc(cf.name)}</h1><input type="color" class="colorpick" value="${esc(cf.color)}" title="Color de la carpeta" aria-label="Color de la carpeta"><button class="btn sm" data-d>Usar predeterminados de…</button><button class="btn gh sq sm" data-m aria-label="Opciones de la carpeta">${icon("more")}</button>`
      : `<h1>${cur === "sin" ? "Sin carpeta" : "Biblioteca"}</h1>`;
    if (cf) {
      $(".colorpick", head).onchange = guard(async (e) => { await api(`/api/folders/${cf.id}`, { method: "PUT", json: { color: e.target.value } }); refresh(); });
      $("[data-d]", head).onclick = guard(() => copyDefs({ to: cf.id }));
      $("[data-m]", head).onclick = (e) => folderMenu(e.currentTarget, cf);
    }
  }
  const refresh = async () => { pSig = ""; await loadFolders(true); await loadProjects(); };
  function draw() {
    const box = $("#rows"); if (!box) return;
    const q = $("#lsearch").value.trim().toLowerCase();
    let list = cur === "sin" ? all.filter(p => !folderOf(p.folder)) : cur ? all.filter(p => p.folder === cur) : all;
    if (q) list = list.filter(p => p.name.toLowerCase().includes(q));
    const sig = JSON.stringify(list.map(p => [p.id, p.name, p.status, Math.round(p.progress), p.message, p.folder, p.n_clips, p.n_exports, p.marks.map(m => [m.id, m.v, m.s])])) + JSON.stringify(FOLDERS) + q + JSON.stringify(lives);
    if (sig === pSig) return; pSig = sig;
    box.innerHTML = "";
    if (!list.length) {
      const wait = lives.find(s => s.status === "activo" && !s.n && (!cur || s.folder === cur || (cur === "sin" && !folderOf(s.folder))));
      box.innerHTML = q ? `<div class="empty"><h2>Nada con «${esc(q)}»</h2><p>Prueba con otra parte del nombre.</p></div>`
        : `<div class="empty">${icon("film", 34)}<h2>${wait ? "Esperando la primera hora del directo" : cur ? "Esta carpeta está vacía" : "Aún no hay videos"}</h2><p>${wait ? `El primer proyecto aparece aquí a las ${liveAt(wait)}. Si quieres algo que ya pasó, crea un proyecto con «Lo que ya pasó».` : cur ? "Arrastra aquí un proyecto o crea uno nuevo." : "Trae un directo, una entrevista o cualquier video largo: se transcribe, se buscan los momentos que funcionan solos y salen en vertical, listos para retocar."}</p><button class="btn pri lg">${icon("plus")}Nuevo proyecto</button></div>`;
      const b = $(".btn", box); if (b) b.onclick = () => newSheet({ folder: cur });
      return;
    }
    for (const p of list) {
      const el = document.createElement("article"); el.className = "prow"; el.draggable = true; el.tabIndex = 0;
      const f = folderOf(p.folder), busy = isBusy(p), dur = p.media ? p.media.duration : 0, top = [...p.marks].sort((a, b) => b.score - a.score).slice(0, 4);
      el.innerHTML = `${top.length ? `<div class="strip">${top.map(m => `<i style="background-image:url('/api/projects/${p.id}/thumb/${m.id}?v=${m.v}')"></i>`).join("")}</div>` : `<div class="strip none">${icon("film", 26)}</div>`}
        <div style="min-width:0"><div class="nm" title="${esc(p.name)}">${esc(p.name)}</div>
          <div class="facts"><span class="num">${dur ? fmtLong(dur) : "Duración por conocer"}</span><span>${fmtDate(p.created)}</span>${f ? `<span class="fol"><i style="background:${esc(f.color)}"></i>${esc(f.name)}</span>` : ""}${p.n_exports ? `<span>${plural(p.n_exports, "exportado", "exportados")}</span>` : ""}</div>
          ${isWait(p) ? waitHtml(p) : busy ? stagesHtml(p) : p.status === "error" ? `<div class="err">${esc((p.error || "Error").slice(0, 160))}</div>` : dur ? `<div class="mini" title="Dónde cae cada clip en el video">${p.marks.map(m => `<i style="left:${m.s / dur * 100}%;width:${(m.e - m.s) / dur * 100}%"></i>`).join("")}</div>` : ""}</div>
        <div class="rt">${isWait(p) ? `<span class="mut small">En espera</span>` : busy ? `<span class="num">${Math.round(p.progress || 0)}%</span>` : `<div class="cnt">${p.n_clips}<small> ${p.n_clips === 1 ? "clip" : "clips"}</small></div>`}<button class="btn gh sq sm" data-m aria-label="Opciones del proyecto">${icon("more")}</button></div>`;
      const open = () => location.hash = `#/p/${p.id}`;
      el.onclick = open; el.onkeydown = (e) => { if (e.key === "Enter" && e.target === el) open(); };
      el.ondragstart = (e) => { e.dataTransfer.setData("text/x-proyecto", p.id); el.classList.add("dragging"); }; el.ondragend = () => el.classList.remove("dragging");
      $("[data-m]", el).onclick = (e) => { e.stopPropagation(); menu(e.currentTarget, [
        ...(isRec(p) ? [{ label: "Detener y usar lo grabado", icon: "check", run: () => stopRec(p) }] : []),
        ...(isWait(p) ? [{ label: "Bajar ahora, sin esperar", icon: "download", run: () => stopWait(p) }] : []),
        { label: "Renombrar", icon: "pen", run: async () => { const r = await ask({ title: "Renombrar proyecto", ok: "Renombrar", fields: [{ name: "n", label: "Nombre", value: p.name }] }); if (r && r.n.trim()) { await api(`/api/projects/${p.id}`, { method: "PUT", json: { name: r.n } }); refresh(); } } },
        { head: "Mover a" }, ...FOLDERS.filter(x => x.id !== p.folder).map(x => ({ label: x.name, dot: x.color, run: async () => { await moveProject(p.id, x.id); refresh(); } })),
        ...(f ? [{ label: "Sin carpeta", dot: "var(--faint)", run: async () => { await moveProject(p.id, null); refresh(); } }] : []),
        { label: "Nueva carpeta…", icon: "plus", run: newFolder }, "-",
        { label: "Borrar proyecto", icon: "trash", bad: true, run: async () => { if (await ask({ title: "¿Borrar este proyecto?", text: `Se borran «${p.name}», sus clips y todos sus archivos. No se puede deshacer.`, ok: "Borrar proyecto", danger: true })) { spDeleted(await api(`/api/projects/${p.id}`, { method: "DELETE" })); refresh(); spNotice($("#lspace")); } } }]); };
      box.appendChild(el);
    }
  }
  async function loadProjects() { all = await api("/api/projects"); draw(); }
  $("#lsearch").oninput = draw;
  $("#lnew").onclick = () => newSheet({ folder: cur });
  if (!cur) equipoNotice($("#lnotice"));
  spNotice($("#lspace")); every(10000, () => spNotice($("#lspace")));
  async function loadLive() {
    const box = $("#llive"); if (!box) return;
    const l = await api("/api/directos"), sig = JSON.stringify([l, l.map(liveText)]); if (sig === lSig) return; lSig = sig;
    const on = liveOn; lives = l;
    box.innerHTML = l.map(s => `<section class="liveb ${s.status}" data-s="${s.id}" aria-label="Directo que sigues"><i></i><div><b>${esc(s.base)}</b><span>${esc(liveText(s))}</span></div>
      ${on(s) ? `<button class="btn sm" data-a="lim">Cambiar límites</button><button class="btn sm" data-a="stop">Detener</button>` : `<button class="btn gh sq sm" data-a="del" aria-label="Quitar este aviso">${icon("close", 16)}</button>`}</section>`).join("");
    $$("[data-a]", box).forEach(b => b.onclick = guard(async () => {
      const s = l.find(x => x.id === b.closest("section").dataset.s), u = `/api/directos/${s.id}`;
      if (b.dataset.a === "del") await api(u, { method: "DELETE" });
      else if (b.dataset.a === "stop") { if (!(await ask({ title: "¿Dejar de seguir este directo?", text: `«${s.base}». Los proyectos que ya se crearon se quedan. La hora en curso no se guarda.`, ok: "Dejar de seguir" }))) return; await api(u + "/detener", { method: "POST" }); }
      else { const r = await ask({ title: "Límites del directo", ok: "Guardar", fields: [{ name: "h", label: "Cuántas horas, como máximo (1 a 48)", value: String(s.hours) }, { name: "g", label: "Espacio en disco, como máximo (GB)", value: String(s.gb) }] }); if (!r) return; if (!(+r.h >= 1 && +r.g >= 2)) throw new Error("Escribe al menos 1 hora y 2 GB."); await api(u, { method: "PUT", json: { hours: +r.h, gb: +r.g } }); }
      loadLive();
    }));
  }
  every(4000, async () => { try { await loadLive(); } catch (e) {} });
  every(2000, async () => { try { await loadFolders(); await loadProjects(); } catch (e) {} });
}

// ------------------------------------------------------------ directos que se siguen
const liveOn = (s) => s.status === "activo" || s.status === "lleno";
// cada hora se baja unos segundos después de cumplirse
const liveAt = (s, d = 60) => new Date((s.due + d) * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });
function liveText(s) {
  if (!liveOn(s)) return s.note || "Terminó.";
  const n = `${s.n} de ${plural(s.hours, "hora", "horas")}. `;
  return n + (s.note || (s.due * 1000 > Date.now() ? `Espera a que se cumpla la hora (de ${liveAt(s, -3600)} a ${liveAt(s, 0)}). Se baja a las ${liveAt(s)}.` : "Ya toca bajar la siguiente."));
}

// ------------------------------------------------------------ nuevo proyecto
function newSheet({ folder = "", file: startFile = null } = {}) {
  if ($("#sheet[open]")) return;
  const d = document.createElement("dialog"); d.id = "sheet"; d.className = "sheet"; d.setAttribute("aria-label", "Nuevo proyecto");
  d.appendChild($("#tpl-new").content.cloneNode(true)); paintIcons(d);
  $$("[data-frame]", d).forEach(b => b.insertAdjacentHTML("afterbegin", frameSvg(b.dataset.frame)));
  document.body.appendChild(d); d.showModal();
  const q = (s) => $(s, d);
  let file = null, busy = false, xhr = null, folderTouched = false;
  const close = async () => {
    if (busy && !(await ask({ title: "¿Cancelar la subida?", text: "El video todavía se está copiando.", ok: "Cancelar subida", danger: true }))) return;
    if (xhr) xhr.abort(); d.close();
  };
  d.oncancel = (e) => { e.preventDefault(); close(); };
  d.onclose = () => d.remove();
  q("#nclose").onclick = close;

  // ---------- origen: un solo campo para enlace, ruta o archivo
  const src = q("#src"), info = q("#srcinfo");
  const SITES = [["kick", "Kick"], ["twitch", "Twitch"], ["youtu", "YouTube"], ["tiktok", "TikTok"], ["drive.google", "Google Drive"], ["zoom", "Zoom"], ["instagram", "Instagram"], ["facebook", "Facebook"]];
  function parse() {
    if (file) return { kind: "file" };
    const v = src.value.trim().replace(/^"|"$/g, "");
    if (!v) return { kind: "" };
    if (/^([a-z]:[\\/]|\\\\|\/)/i.test(v)) return { kind: "path", v };
    return { kind: "url", v: /^https?:/i.test(v) ? v : "https://" + v, site: (SITES.find(([k]) => v.toLowerCase().includes(k)) || [])[1] };
  }
  function showSrc() {
    const p = parse(); info.classList.toggle("set", !!p.kind);
    info.innerHTML = p.kind === "file" ? `${icon("film", 16)}<span>${esc(file.name)} (${fmtSize(file.size)})</span><button type="button" class="btn gh sm" id="nofile">Quitar</button>`
      : p.kind === "path" ? `${icon("film", 16)}<span>Archivo de este PC. Se usa donde está, sin copiarlo.</span>`
      : p.kind === "url" ? `${icon("link", 16)}<span>${live && p.v === liveUrl ? `Directo: ${esc(live.title)}` : vod && p.v === liveUrl ? `${esc(vod.title)}, ${fmtLong(vod.duration)}. Se descarga a este PC.` : `${p.site ? `Enlace de ${p.site}` : "Enlace"}. Se descarga a este PC.`}</span>` : "<span>También puedes soltar un video en cualquier parte de la ventana.</span>";
    src.disabled = p.kind === "file"; const x = $("#nofile", info); if (x) x.onclick = () => { file = null; q("#file").value = ""; showSrc(); };
    q("#dlbox").hidden = p.kind !== "url"; chatBox(); checkLive(p);
    if (p.kind === "url" && !folderTouched) {
      const low = p.v.toLowerCase(), site = ["kick", "twitch", "youtube", "tiktok"].find(s => low.includes(s)), f = site && FOLDERS.find(x => x.name.toLowerCase().includes(site));
      if (f && q("#o-folder").value !== f.id) { q("#o-folder").value = f.id; applyDefs(); }
    }
  }
  // ---------- directo en vivo de YouTube o Kick
  let live = null, liveUrl = "", liveT = 0, checking = null;
  const lmode = choice(q("#l-mode"), () => drawLive()), lspan = choice(q("#l-span"), () => drawLive()), lmin = choice(q("#l-min"), () => drawLive());
  const local = (t) => { const x = new Date(t * 1000); return new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
  const hm = (t) => new Date(t * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });
  const day = (t) => new Date(t * 1000).toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long" });
  function setLive(v) {
    live = v; q("#livebox").hidden = !v; q("#go").textContent = "Crear clips"; if (!v) return;
    const kick = v.site === "kick"; $$("#l-mode button", d).forEach(b => b.hidden = ["after", "sofar"].includes(b.dataset.v) !== kick);
    q("#l-namelb").textContent = kick ? "Nombre del proyecto" : "Nombre de los proyectos";
    q("#l-name").value = v.title; lmode.value = kick ? "after" : "past"; lspan.value = "1"; lmin.value = "60";
    if (kick) return drawLive();
    const n = Date.now() / 1000, h = Math.floor(n / 3600) * 3600;
    for (const s of ["#l-from", "#l-to"]) { q(s).min = local(n - v.back); q(s).max = local(n + 60); }
    q("#l-from").value = local(h - 3600); q("#l-to").value = local(h); drawLive();
  }
  function checkLive(p) {
    const u = p.kind === "url" && (p.site === "YouTube" && /[?&]v=|youtu\.be\/.|\/(live|watch|shorts|@|c\/|channel)/.test(p.v) || /^https?:\/\/(www\.)?kick\.com\/[\w-]+(\/videos(\/[0-9a-f-]{36})?)?\/?([?#].*)?$/i.test(p.v)) ? p.v : "";
    if (u === liveUrl) { if (checking) info.insertAdjacentHTML("beforeend", `<span class="mut">Revisando si está en vivo…</span>`); return; }
    liveUrl = u; clearTimeout(liveT); checking = null; setLive(null); setVod(null); if (!u) return;
    checking = new Promise(done => { liveT = setTimeout(async () => {
      let r = {}; try { r = await api("/api/directo?url=" + encodeURIComponent(u)); } catch (e) {}
      if (u === liveUrl && d.isConnected) { checking = null; setLive(r.live ? r : null); setVod(r.vod || null); showSrc(); } done();
    }, 500); });
    info.insertAdjacentHTML("beforeend", `<span class="mut">Revisando si está en vivo…</span>`);
  }
  function liveAsk() {
    const n = Date.now() / 1000, name = q("#l-name").value.trim() || live.title, m = lmode.value;
    if (m === "after" || m === "sofar") return { mode: m, name };
    if (m === "next") return { mode: m, name, minutes: +lmin.value };
    if (m === "follow") return { mode: m, name, hours: +q("#l-hours").value, gb: +q("#l-gb").value };
    const [a, b] = lspan.value === "x" ? [q("#l-from"), q("#l-to")].map(x => new Date(x.value).getTime() / 1000) : [n - lspan.value * 3600, n];
    return { mode: m, name, from: a, to: Math.min(b, n) };
  }
  function drawLive() {
    if (!live) return;
    const m = lmode.value; $$(".lv", d).forEach(x => x.hidden = x.dataset.l !== m); q("#l-range").hidden = lspan.value !== "x";
    const a = liveAsk(), r = { auto: "720", 480: "480", 720: "720", 1080: "1080" }[q("#o-download").value] || "720", gb = (h, w = "Pesa") => `${w} cerca de ${h * live.gb_h[r] < 1 ? Math.max(1, Math.round(h * live.gb_h[r] * 100)) * 10 + " MB" : (h * live.gb_h[r]).toFixed(1) + " GB"} en ${r}p.`;
    let t = "";
    if (m === "past") {
      const len = a.to - a.from, parts = [], when = day(a.from) === day(Date.now() / 1000) ? "" : `, ${day(a.from)}`; for (let s = a.from; s < a.to;) { let e = Math.min(s + 3600, a.to); if (a.to - e < 600) e = a.to; parts.push([s, e]); s = e; }
      t = !(len >= 60) ? "El horario debe durar al menos 1 minuto y empezar antes de ahora." : len > live.max_span + 60 ? "Como máximo 12 horas por pedido."
        : `${parts.length === 1 ? `Se crea 1 proyecto${when}, de ${hm(a.from)} a ${hm(a.to)}.` : `Se crean ${parts.length} proyectos de cerca de 1 hora${when}, de ${hm(a.from)} a ${hm(a.to)}, que comparten 30 segundos para no partir un momento.`} ${gb(len / 3600)}`;
      if (lspan.value === "x") t += ` Puedes ir hasta el ${day(Date.now() / 1000 - live.back)}, ${hm(Date.now() / 1000 - live.back)}.`;
    } else if (m === "next") { const n = Date.now() / 1000; t = `Graba desde ahora hasta las ${hm(n + a.minutes * 60)}, se detiene solo y busca los clips. Puedes detenerlo antes. ${gb(a.minutes / 60)}`; }
    else if (m === "after" || m === "sofar") {
      const h = live.started ? (Date.now() / 1000 - live.started) / 3600 : 0, since = live.started ? `Empezó a las ${hm(live.started)} y lleva ${fmtLong(h * 3600)}. ` : "";
      t = m === "after" ? `${since}Revisa cada minuto y, cuando termine, baja el directo completo y busca los clips. ${window.APP_NAME || "La app"} debe quedar abierto y el equipo encendido, sin suspenderse. ${gb(1, "Cada hora pesa")}`
        : `${since}Se baja solo lo que va hasta este momento; lo que sigue no entra. ${h ? gb(h) : ""}`;
    } else t = `Cada hora crea un proyecto con la hora anterior y saca sus clips. El primero, a las ${hm(Date.now() / 1000 + 3600)}. ${window.APP_NAME || "La app"} debe quedar abierto: si lo cierras, al volver baja las horas que faltaron. Si se llena el espacio, se pausa y te avisa; no borra nada. ${gb(1, "Cada hora pesa")}`;
    q("#l-info").textContent = t;
    q("#go").textContent = m === "next" ? "Empezar a grabar" : m === "follow" ? "Seguir el directo" : m === "after" ? "Esperar a que termine" : "Crear clips";
  }
  for (const s of ["#l-from", "#l-to", "#l-hours", "#l-gb", "#o-download"]) q(s).addEventListener("input", drawLive);

  // ---------- periodos de un video de Kick: se baja solo lo elegido
  let vod = null, pers = [], drag = null;
  const vmode = choice(q("#v-mode"), () => drawVod(true));
  const hms = (s) => { s = Math.round(s); return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
  // «1:20:00», «20:00» (minutos y segundos) o «20» (minutos)
  const unhms = (v) => { const m = v.trim().match(/^(?:(\d{1,2}):)?(\d{1,3})(?::(\d{1,2}))?$/); if (!m) return null; if (m[3] === undefined && m[1] === undefined) return +m[2] * 60; return m[3] === undefined ? +m[1] * 60 + +m[2] : (+m[1] || 0) * 3600 + +m[2] * 60 + +m[3]; };
  const shot = (t) => `/api/kick/cuadro?t=${Math.max(0, Math.round(t))}&url=${encodeURIComponent(liveUrl)}`;
  function setVod(v) {
    vod = v; q("#vodbox").hidden = !v; if (!v) return;
    pers = [[0, v.duration]]; vmode.value = "all"; q("#v-strip").innerHTML = ""; drawVod(true);
  }
  const union = () => { const o = []; for (const [a, b] of [...pers].sort((x, y) => x[0] - y[0])) { const l = o[o.length - 1]; if (l && a <= l[1]) l[1] = Math.max(l[1], b); else o.push([a, b]); } return o; };
  function vodInfo() {
    const some = vmode.value === "some", len = (some ? union() : [[0, vod.duration]]).reduce((t, [a, b]) => t + b - a, 0);
    const weigh = (sec) => { const r = { 480: 480, 720: 720, 1080: 1080 }[q("#o-download").value] || (sec > vod.long ? 720 : 1080), f = vod.q.filter(x => x.h <= r).pop() || vod.q[0]; return [f.h, f.gb_h * sec / 3600]; };
    const gb = (x) => x < 1 ? Math.max(1, Math.round(x * 100)) * 10 + " MB" : x.toFixed(1) + " GB", [h, x] = weigh(len);
    let t = `${some ? `${plural(pers.length, "periodo", "periodos")}, ${fmtLong(len)} de ${fmtLong(vod.duration)}. Pesa` : "Pesa"} cerca de ${gb(x)} en ${h}p${some && len < vod.duration - 2 ? `; todo pesaría ${gb(weigh(vod.duration)[1])}` : ""}.`;
    if (some && len >= vod.duration - 2) t = "Arrastra los bordes o escribe las horas para dejar solo lo que quieres. " + t.replace(/^[^.]*\. /, "");
    else if (some) t += ` Cada periodo puede empezar o terminar hasta 12 segundos antes o después.${pers.length > 1 ? " Se unen en un solo proyecto." : ""}`;
    if (vod.free_gb - x * 1.8 < vod.keep_gb) t += ` No cabe: quedan ${vod.free_gb.toFixed(0)} GB libres.`;
    q("#v-info").textContent = t; q("#v-add").disabled = !gapFor();
  }
  const bars = () => { $$(".vbar", d).forEach((el, n) => { const [a, b] = pers[n]; el.style.left = a / vod.duration * 100 + "%"; el.style.width = (b - a) / vod.duration * 100 + "%"; }); };
  function rowText(n, only) {
    const r = $$(".vrow", d)[n]; if (!r) return; const [a, b] = pers[n], [i, j] = $$("input", r);
    if (only !== i) i.value = hms(a); if (only !== j) j.value = hms(b);
    $(".len", r).textContent = fmtLong(b - a); clearTimeout(r._t);
    r._t = setTimeout(() => { if (!d.isConnected) return; const [x, y] = $$("img", r), put = (im, t) => { const s = shot(t); if (im.dataset.s !== s) { im.dataset.s = s; im.classList.remove("got"); im.src = s; } }; put(x, a); put(y, b - 2); }, 250);
  }
  // mueve un borde (o el periodo entero) sin encimarse con los vecinos
  function moveTo(n, side, t) {
    const [a, b] = pers[n], lo = Math.max(0, ...pers.filter((x, k) => k !== n && x[1] <= a + .5).map(x => x[1])), hi = Math.min(vod.duration, ...pers.filter((x, k) => k !== n && x[0] >= b - .5).map(x => x[0]));
    if (side === "a") pers[n][0] = Math.max(lo, Math.min(b - vod.min, t)); else if (side === "b") pers[n][1] = Math.min(hi, Math.max(a + vod.min, t));
    else { const s = Math.max(lo, Math.min(hi - (b - a), t)); pers[n] = [s, s + b - a]; }
  }
  function drawVod(all) {
    if (!vod) return; const some = vmode.value === "some"; q("#v-some").hidden = !some; vodInfo(); if (!some || !all) return;
    if (!q("#v-strip").children.length) q("#v-strip").innerHTML = Array.from({ length: 8 }, (_, k) => `<img alt="" loading="lazy" src="${esc(shot(vod.duration * (k + .5) / 8))}">`).join("");
    $$("#v-strip img", d).forEach(im => im.onerror = () => im.classList.add("no"));
    q("#v-scale").innerHTML = [0, .25, .5, .75, 1].map(k => `<span>${hms(vod.duration * k)}</span>`).join("");
    pers.sort((x, y) => x[0] - y[0]);
    q("#v-bars").innerHTML = pers.map((_, n) => `<div class="vbar" data-n="${n}"><i data-s="a"></i><i data-s="b"></i></div>`).join(""); bars();
    q("#v-rows").innerHTML = pers.map((_, n) => `<div class="vrow" data-n="${n}"><figure><img alt="Cómo empieza"></figure><label><span class="lb">Desde</span><input type="text" inputmode="numeric" autocomplete="off" aria-label="Periodo ${n + 1}, desde"></label><label><span class="lb">Hasta</span><input type="text" inputmode="numeric" autocomplete="off" aria-label="Periodo ${n + 1}, hasta"></label><figure><img alt="Cómo termina"></figure><span class="len mut small"></span><button type="button" class="btn gh sq sm" aria-label="Quitar el periodo ${n + 1}"${pers.length < 2 ? " hidden" : ""}>${icon("close", 14)}</button></div>`).join("");
    $$(".vrow", d).forEach((r, n) => {
      $$("img", r).forEach(im => { im.onload = () => im.classList.add("got"); im.onerror = () => im.classList.remove("got"); });
      $$("input", r).forEach((el, k) => {
        const side = "ab"[k], set = (t) => { moveTo(n, side, t); bars(); rowText(n); vodInfo(); };
        el.onchange = () => { const t = unhms(el.value); set(t === null ? pers[n][k] : t); };
        el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); el.onchange(); } const s = { ArrowUp: 1, ArrowDown: -1 }[e.key]; if (s) { e.preventDefault(); set(pers[n][k] + s * (e.shiftKey ? 60 : 10)); } };
      });
      $("button", r).onclick = () => { pers.splice(n, 1); drawVod(true); }; rowText(n);
    });
  }
  function gapFor() {          // el hueco más grande que queda libre
    const u = union(); let best = null, at = 0; for (const [a, b] of [...u, [vod.duration, vod.duration]]) { if (a - at >= 60 && (!best || a - at > best[1] - best[0])) best = [at, a]; at = b; }
    return pers.length < vod.max_n ? best : null;
  }
  q("#v-add").onclick = () => { const g = gapFor(); if (!g) return; const len = Math.min(600, (g[1] - g[0]) / 2), m = (g[0] + g[1]) / 2; pers.push([Math.round(m - len / 2), Math.round(m + len / 2)]); drawVod(true); };
  q("#v-track").onpointerdown = (e) => {
    const bar = e.target.closest(".vbar"); if (!bar || e.button) return; e.preventDefault();
    const n = +bar.dataset.n, w = q("#v-track").getBoundingClientRect(), at = (x) => (x.clientX - w.left) / w.width * vod.duration, side = e.target.dataset.s || "m"; drag = { n, side, off: at(e) - pers[n][side === "b" ? 1 : 0] };
    q("#v-track").setPointerCapture(e.pointerId); bar.classList.add("on");
    q("#v-track").onpointermove = (x) => { if (!drag) return; moveTo(drag.n, drag.side, Math.round(at(x) - drag.off)); bars(); rowText(drag.n); vodInfo(); };
    q("#v-track").onpointerup = q("#v-track").onpointercancel = () => { drag = null; bar.classList.remove("on"); q("#v-track").onpointermove = null; };
  };
  q("#o-download").addEventListener("input", () => drawVod());

  const setFile = (f) => { if (f) { file = f; src.value = ""; showSrc(); } };
  d._setFile = setFile;
  src.oninput = showSrc; q("#pick").onclick = () => q("#file").click(); q("#file").onchange = () => setFile(q("#file").files[0]);

  // ---------- opciones (salen de los predeterminados de la carpeta; lo que tocas a mano no se pisa)
  const touched = new Set();
  function chatBox() { q("#o-chatbox").hidden = parse().site !== "Kick" || q("#o-whole").dataset.value === "1"; }
  q("#o-chat").checked = pref.get("chat-guia", "si") === "si";
  const whole = choice(q("#o-whole"), (v) => { $$(".whole-hide", d).forEach(el => el.hidden = v === "1"); chatBox(); });
  const mode = choice(q("#o-mode"), () => touched.add("mode")), style = choice(q("#o-style"), (v) => { touched.add("style"); if (v === "dinamico") { q("#o-silence").checked = true; touched.add("remove_silence"); } });
  const ids = { language: "#o-lang", min_len: "#o-min", max_len: "#o-max", max_clips: "#o-n", remove_silence: "#o-silence", download: "#o-download" };
  for (const [k, s] of Object.entries(ids)) for (const ev of ["input", "change"]) q(s).addEventListener(ev, () => touched.add(k));
  const opts = () => ({ mode: mode.value, style: style.value, language: q("#o-lang").value, min_len: +q("#o-min").value, max_len: +q("#o-max").value, max_clips: +q("#o-n").value, remove_silence: q("#o-silence").checked, download: q("#o-download").value });
  let seq = 0;
  async function applyDefs() {
    const fol = folderOf(q("#o-folder").value), my = ++seq;
    let r = {}; try { r = await api(`/api/defaults/resolved?folder=${fol ? fol.id : ""}`); } catch (e) { return; }
    if (my !== seq || !d.isConnected) return;
    const v = { mode: "auto", style: "karaoke", language: "auto", min_len: 20, max_len: 60, max_clips: 10, remove_silence: false, download: "auto", ...(r.opciones || {}) };
    if (r.encuadre) v.mode = r.encuadre.mode;
    for (const k of ["style", "remove_silence"]) if (r.estilo && r.estilo[k] !== undefined) v[k] = r.estilo[k];
    if (!touched.has("mode")) mode.value = v.mode; if (!touched.has("style")) style.value = v.style;
    for (const [k, s] of Object.entries(ids)) if (!touched.has(k)) { if (k === "remove_silence") q(s).checked = !!v[k]; else q(s).value = v[k]; }
    const has = DEF_LABELS.filter(([g]) => r[g]).map(([, l]) => l.toLowerCase());
    q("#o-definfo").textContent = has.length ? `Con tus predeterminados${fol ? ` de «${fol.name}»` : ""}: ${andList(has)}.` : "";
    q("#o-savedef").textContent = fol ? `Guardar como predeterminado de «${fol.name}»` : "Guardar como predeterminado";
  }
  q("#o-folder").onchange = () => { folderTouched = true; applyDefs(); };
  q("#o-savedef").onclick = guard(async () => {
    const fol = folderOf(q("#o-folder").value);
    await api("/api/defaults", { method: "POST", json: { folder: fol ? fol.id : null, options: opts() } });
    touched.clear(); await applyDefs(); toast(`Guardado: así saldrán los proyectos nuevos${fol ? ` de «${fol.name}»` : ""}.`);
  });
  api("/api/folders").then(r => { FOLDERS = r.folders; folderOptions(q("#o-folder"), folderOf(folder) ? folder : ""); showSrc(); applyDefs(); });

  // ---------- crear
  q("#go").onclick = async () => {
    const err = q("#newerr"), p = parse(); err.textContent = "";
    if (!p.kind) { err.textContent = "Pega un enlace, escribe una ruta o elige un video."; src.focus(); return; }
    const options = { whole: whole.value === "1", ...opts() };
    if (!q("#o-chatbox").hidden) { options.chat_guide = q("#o-chat").checked; pref.set("chat-guia", q("#o-chat").checked ? "si" : "no"); }
    if (!options.whole && !(options.min_len >= 5 && options.max_len > options.min_len && options.max_len <= 180)) { err.textContent = "Revisa la duración: el mínimo debe ser menor que el máximo (5 a 180 s)."; return; }
    if (p.kind === "path") options.local_path = p.v;
    if (q("#o-folder").value) options.folder = q("#o-folder").value;
    if (checking) { const b = q("#go"), l = b.textContent; b.disabled = true; b.textContent = "Revisando si está en vivo…"; await checking; if (!d.isConnected) return; b.disabled = false; b.textContent = live ? b.textContent : l; if (vod) { q("#vodbox").scrollIntoView({ block: "nearest" }); return; } if (live) { q("#livebox").scrollIntoView({ block: "nearest" }); return; } }
    if (live) {
      const a = options.live = liveAsk();
      if (a.mode === "past" && !(a.to - a.from >= 60)) { err.textContent = "Revisa el horario: debe empezar antes de ahora y durar al menos 1 minuto."; return; }
    }
    if (vod && p.kind === "url" && vmode.value === "some") { if (document.activeElement && document.activeElement.closest(".vrow")) document.activeElement.blur(); options.periods = union(); }
    const fd = new FormData(); if (file) fd.append("file", file); fd.append("url", p.kind === "url" ? p.v : ""); fd.append("options", JSON.stringify(options));
    const btn = q("#go"), label = btn.textContent; btn.disabled = true; busy = true;
    try {
      const r = await new Promise((res, rej) => {
        const x = xhr = new XMLHttpRequest(); x.open("POST", "/api/projects");
        x.upload.onprogress = (e) => { if (file && e.lengthComputable) btn.textContent = `Copiando el video, ${Math.round(e.loaded / e.total * 100)}%`; };
        x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {} x.status < 300 ? res(j) : rej(new Error(j.detail || x.statusText)); };
        x.onerror = () => rej(new Error("No hay conexión con la app. ¿Sigue abierta?")); x.onabort = () => rej(new Error("")); x.send(fd);
      });
      busy = false; xhr = null; d.close();
      if (r.serie || r.n > 1) { location.hash = options.folder ? `#/f/${options.folder}` : "#/"; toast(r.serie ? `Siguiendo el directo. El primer proyecto aparece a las ${liveAt({ due: Date.now() / 1000 + 3600 })}; mientras, lo ves en la Cola.` : `Se crearon ${r.n} proyectos. Se bajan y se analizan uno por uno.`); }
      else location.hash = `#/p/${r.id}`;
    } catch (e) { busy = false; xhr = null; if (d.isConnected) { err.textContent = e.message; btn.disabled = false; btn.textContent = label; } }
  };
  if (startFile) setFile(startFile); else src.focus();
}

// soltar un video en cualquier parte abre la hoja con ese archivo
(() => {
  let veil = null; const has = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files"), off = () => { veil && veil.remove(); veil = null; };
  addEventListener("dragover", (e) => { if (!has(e)) return; e.preventDefault(); if (!veil) { veil = document.createElement("div"); veil.id = "dropveil"; veil.textContent = "Suelta el video para crear clips"; ($("dialog[open]") || document.body).appendChild(veil); } });
  addEventListener("dragleave", (e) => { if (!e.relatedTarget) off(); });
  addEventListener("drop", (e) => { if (!has(e)) return; e.preventDefault(); off(); const f = e.dataTransfer.files[0]; if (!f) return; if (!/^video\//.test(f.type) && !/\.(mp4|mov|mkv|webm|avi|m4v|ts)$/i.test(f.name)) return toast("Ese archivo no parece un video.", true); const s = $("#sheet[open]"); if (s) s._setFile(f); else if (!$("dialog[open]")) newSheet({ file: f }); });
})();
