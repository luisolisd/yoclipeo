// Proyecto: mapa del video, clips, selección múltiple y rehacer.
"use strict";

const QUALS = [["1080p", "La mejor"], ["720p", "Más ligero"], ["480p", "Borrador"], ["mp3", "Solo el audio"]];
const exportClip = (pid, cid, q) => api(`/api/projects/${pid}/clips/${cid}/export`, { method: "POST", json: { quality: q } });
const potBars = (s) => `<span class="pot" title="Potencial según la IA: ${s} de 100">${[40, 60, 75, 90].map(k => `<i class="${s >= k ? "on" : ""}"></i>`).join("")}</span>`;

function project(pid) {
  mount("tpl-project");
  let P = null, sig = "", map = null, cat = "", sel = new Set(), jobs = {}, jobSig = "", foldersOk = false;
  const sort = choice($("#sort"), (v) => { pref.set("orden", v); sig = ""; draw(); }); sort.value = pref.get("orden", "video");
  const look = choice($("#look"), (v) => { pref.set("vista", v); sig = ""; draw(); }); look.value = pref.get("vista", "grid");
  api("/api/folders").then(r => { FOLDERS = r.folders; foldersOk = true; folderBtn(); });
  cleanup.push(() => map && map.destroy());

  const name = $("#pname");
  name.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); name.blur(); } if (e.key === "Escape") { name.textContent = P.name; name.blur(); } };
  name.onblur = guard(async () => { const v = name.textContent.trim(); if (P && v && v !== P.name) { await api(`/api/projects/${pid}`, { method: "PUT", json: { name: v } }); toast("Nombre guardado"); } else if (P) name.textContent = P.name; });
  function folderBtn() {
    if (!P || !foldersOk) return; const f = folderOf(P.folder), b = $("#pfolder");
    b.innerHTML = `${f ? `<i style="width:9px;height:9px;border-radius:50%;background:${esc(f.color)}"></i>` : icon("folder", 16)}${esc(f ? f.name : "Sin carpeta")}`;
    b.onclick = () => menu(b, [{ head: "Carpeta del proyecto" }, ...FOLDERS.map(x => ({ label: x.name, dot: x.color, run: () => mv(x.id) })), { label: "Sin carpeta", dot: "var(--faint)", run: () => mv(null) }]);
  }
  const mv = async (id) => { await moveProject(pid, id); P.folder = id; folderBtn(); };

  function head(p) {
    if (document.activeElement !== name) name.textContent = p.name;
    const s = p.selection || {};
    $("#pmeta").textContent = [p.media ? `${fmtLong(p.media.duration)}, ${p.media.width}×${p.media.height}` : "", p.language ? `idioma ${p.language}` : "", p.transcriber ? `voz: ${p.transcriber}` : "",
      s.engine ? `momentos: ${s.engine === "claude" ? "Claude, " + s.model : ["ollama", "servidor"].includes(s.engine) ? "IA local, " + (s.model || "") : s.engine}` : ""].filter(Boolean).join("  ·  ");
    const warn = p.status === "listo" && /sin IA|vista previa/.test(p.message || "");
    $("#pstatus").innerHTML = isBusy(p) ? `<div class="proc"><div class="ms">${esc(p.message || p.status)}<span>${isWait(p) ? "" : Math.round(p.progress || 0) + "%"}</span></div>${isWait(p) ? `<button class="btn sm" id="waitstop" style="margin-top:14px">Bajar ahora, sin esperar</button>` : stagesHtml(p)}${isRec(p) ? `<button class="btn sm" id="recstop" style="margin-top:14px">Detener y usar lo grabado</button>` : ""}</div>`
      : p.status === "error" ? `<div class="proc bad">${esc(p.error || "Error")}</div>` : warn ? `<div class="proc">${esc(p.message)}</div>` : "";
    const ws = $("#waitstop"); if (ws) { ws.disabled = !!p.source.live.stop; ws.onclick = () => stopWait(p); }
    const rs = $("#recstop"); if (rs) { rs.disabled = !!p.source.live.stop; if (rs.disabled) rs.textContent = "Deteniendo…"; rs.onclick = () => stopRec(p); }
    if (!map && p.media && p.status === "listo") map = new VideoMap($("#vmap"), pid, p.media.duration, {
      open: (c) => location.hash = `#/p/${pid}/c/${c.id}`, create: guard((a, b) => createClip(a, b)),
      hover: (id) => $$(".clip").forEach(el => el.classList.toggle("hot", el.dataset.id === id)) });
    $("#vmap").hidden = !map;
  }
  function numbered() { return [...P.clips].sort((a, b) => a.start - b.start).map((c, i) => ({ ...c, no: i + 1 })); }
  function draw() {
    if (!P) return;
    const s = JSON.stringify(P.clips.map(c => [c.id, c.title, c.score, c.thumb_v, c.start, c.end, (c.exports || []).length])); if (s === sig) return; sig = s;
    let list = numbered(); map && map.setClips(list);
    const cats = {}; list.forEach(c => { const k = c.category || "Sin tema"; cats[k] = (cats[k] || 0) + 1; }); if (cat && !cats[cat]) cat = "";
    const ks = Object.keys(cats).sort((a, b) => cats[b] - cats[a]);
    $("#cats").innerHTML = ks.length > 1 ? `<button class="${cat ? "" : "on"}" data-c="">Todos<small>${list.length}</small></button>` + ks.map(k => `<button class="${cat === k ? "on" : ""}" data-c="${esc(k)}">${esc(k)}<small>${cats[k]}</small></button>`).join("") : "";
    $$("#cats button").forEach(b => b.onclick = () => { cat = b.dataset.c; sig = ""; draw(); });
    $("#cbar").hidden = !list.length;
    if (cat) list = list.filter(c => (c.category || "Sin tema") === cat);
    if (sort.value === "pot") list.sort((a, b) => b.score - a.score || a.start - b.start); else if (sort.value === "len") list.sort((a, b) => (a.end - a.start) - (b.end - b.start));
    const box = $("#clips"); box.className = "clips" + (look.value === "list" ? " list" : "") + (sel.size ? " picking" : ""); box.innerHTML = "";
    [...sel].forEach(id => { if (!P.clips.some(c => c.id === id)) sel.delete(id); });
    if (!list.length && !isBusy(P) && P.status === "listo") box.innerHTML = `<div class="empty" style="grid-column:1/-1"><h2>Sin clips</h2><p>Marca un tramo en el mapa para hacer uno a mano, o vuelve a elegir momentos desde el menú.</p></div>`;
    for (const c of list) {
      const el = document.createElement("article"); el.className = "clip" + (sel.has(c.id) ? " sel" : ""); el.dataset.id = c.id;
      el.innerHTML = `<button class="th" style="background-image:url('/api/projects/${pid}/thumb/${c.id}?v=${c.thumb_v || 0}')" aria-label="Editar «${esc(c.title)}»">${(c.exports || []).length ? `<span class="done">${icon("check", 12)}Exportado</span>` : ""}</button>
        <button class="pick" aria-label="Seleccionar" aria-pressed="${sel.has(c.id)}">${icon("check", 15)}</button>
        <div class="cap"><span class="no">${c.no}</span><div class="tt" title="${esc(c.title)}">${esc(c.title)}</div><div class="mt">${potBars(c.score)}<span class="at">${fmt(c.start)}</span><span>${esc(c.category || "")}</span></div><div class="why">${esc(c.reason || "")}</div></div>
        <div class="rgt"><span class="len">${fmt(c.end - c.start)}</span><button class="more" aria-label="Opciones del clip">${icon("more", 17)}</button></div>`;
      const go = () => location.hash = `#/p/${pid}/c/${c.id}`;
      $(".th", el).onclick = (e) => { if (e.ctrlKey || e.shiftKey || e.metaKey) pick(c.id); else go(); };
      $(".pick", el).onclick = () => pick(c.id);
      el.onmouseenter = () => map && map.hot(c.id); el.onmouseleave = () => map && map.hot(null);
      const lenEl = $(".len", el); if (look.value !== "list") $(".th", el).appendChild(lenEl);
      $(".more", el).onclick = (e) => menu(e.currentTarget, [
        { label: "Editar", icon: "pen", run: go }, { head: "Exportar" }, ...QUALS.map(([k, h]) => ({ label: k === "mp3" ? "MP3" : k, hint: h, icon: "out", run: async () => { await exportClip(pid, c.id, k); toast("En la cola de exportación"); jobTick(); } })), "-",
        { label: "Duplicar", icon: "copy", run: async () => { await api(`/api/projects/${pid}/clips/${c.id}/duplicate`, { method: "POST" }); tick(); } },
        { label: "Quitar clip", icon: "trash", bad: true, run: () => removeClips([c.id]) }]);
      box.appendChild(el);
    }
    jobSig = ""; jobDraw(); bulk();
  }
  async function removeClips(ids) {
    const one = ids.length === 1 && P.clips.find(c => c.id === ids[0]);
    if (!(await ask({ title: one ? "¿Quitar este clip?" : `¿Quitar ${ids.length} clips?`, text: (one ? `«${one.title}». ` : "") + "Se pierden sus ediciones. Los archivos ya exportados se quedan en su carpeta.", ok: "Quitar", danger: true }))) return;
    for (const id of ids) await api(`/api/projects/${pid}/clips/${id}`, { method: "DELETE" });
    ids.forEach(i => sel.delete(i)); tick();
  }
  function pick(id) { sel.has(id) ? sel.delete(id) : sel.add(id); $$(".clip").forEach(el => { const on = sel.has(el.dataset.id); el.classList.toggle("sel", on); $(".pick", el).setAttribute("aria-pressed", on); }); $("#clips").classList.toggle("picking", sel.size > 0); bulk(); }
  function bulk() {
    const b = $("#bulk"); b.hidden = !sel.size; if (!sel.size) return;
    b.innerHTML = `<b>${plural(sel.size, "clip", "clips")}</b><button class="btn sm pri" data-x>${icon("out", 15)}Exportar</button><button class="btn sm gh" data-all>Seleccionar todos</button><button class="btn sm gh bad" data-del>${icon("trash", 15)}Quitar</button><button class="btn sm gh sq" data-none aria-label="Quitar la selección">${icon("close", 16)}</button>`;
    const ids = () => numbered().filter(c => sel.has(c.id)).map(c => c.id);
    $("[data-x]", b).onclick = (e) => menu(e.currentTarget, [{ head: `Exportar ${plural(sel.size, "clip", "clips")}` }, ...QUALS.map(([k, h]) => ({ label: k === "mp3" ? "MP3" : k, hint: h, icon: "out", run: async () => { const l = ids(); for (const id of l) await exportClip(pid, id, k); toast(`${plural(l.length, "clip", "clips")} en la cola de exportación`); sel.clear(); sig = ""; draw(); jobTick(); } }))]);
    $("[data-all]", b).onclick = () => { $$(".clip").forEach(el => sel.add(el.dataset.id)); sig = ""; draw(); };
    $("[data-none]", b).onclick = () => { sel.clear(); sig = ""; draw(); };
    $("[data-del]", b).onclick = guard(() => removeClips(ids()));
  }
  // progreso de exportación sobre cada clip
  function jobDraw() {
    const s = JSON.stringify(jobs); if (s === jobSig) return; jobSig = s;
    $$(".clip").forEach(el => {
      const j = jobs[el.dataset.id]; let pr = $(".prog", el);
      if (!j) { pr && pr.remove(); return; }
      if (!pr) { pr = document.createElement("div"); pr.className = "prog"; $(".th", el).appendChild(pr); }
      pr.innerHTML = `${j.status === "renderizando" ? `Exportando, ${Math.round(j.progress)}%` : "En cola"}<div class="line"><i style="width:${j.progress}%"></i></div>`;
    });
  }
  const jobTick = async () => { try { const js = await api("/api/jobs"); jobs = {}; js.filter(j => j.kind === "export" && j.pid === pid && (j.status === "en cola" || j.status === "renderizando")).forEach(j => jobs[j.cid] = j); jobDraw(); } catch (e) {} };
  const tick = async () => { try { P = await api(`/api/projects/${pid}`); if (!$("#pname")) return; head(P); folderBtn(); draw(); } catch (e) { if (!$("#pstatus")) return; if (!P) { timers.forEach(clearInterval); view.innerHTML = noOpen(e.message); } else $("#pstatus").innerHTML = `<div class="proc bad">No hay conexión con la app: ${esc(e.message)}</div>`; } };
  every(1500, tick); every(1200, jobTick);

  async function createClip(a, b) { const c = await api(`/api/projects/${pid}/clips`, { method: "POST", json: { start: +a.toFixed(2), end: +b.toFixed(2) } }); location.hash = `#/p/${pid}/c/${c.id}`; }
  $("#newclip").onclick = guard(async () => {
    const r = await ask({ title: "Clip a mano", text: "Escribe los tiempos del video original, o marca un tramo en el mapa.", ok: "Crear clip", fields: [{ name: "a", label: "Inicio (12:05, 1:12:05 o segundos)", value: "0:00" }, { name: "b", label: "Fin", value: "0:30" }] });
    if (!r) return; const a = toSecs(r.a), b = toSecs(r.b);
    if (!(a >= 0 && b > a)) throw new Error("Revisa los tiempos: el fin debe ir después del inicio."); await createClip(a, b);
  });
  $("#openfolder").onclick = guard(() => api(`/api/projects/${pid}/open-folder`, { method: "POST" }));

  // ---------- rehacer
  const rMode = choice($("#r-mode")), rStyle = choice($("#r-style"), (v) => { if (v === "dinamico") $("#r-silence").checked = true; });
  $$("[data-frame]", $("#redo")).forEach(b => b.insertAdjacentHTML("afterbegin", frameSvg(b.dataset.frame)));
  const openRedo = async (onlySelect) => {
    const p = await api(`/api/projects/${pid}`), o = p.options || {};
    $("#redo-title").textContent = onlySelect ? "Volver a elegir momentos" : "Analizar de cero";
    $("#redo-hint").textContent = onlySelect ? "Usa la transcripción que ya existe y el motor de Ajustes. Los clips actuales y sus ediciones se reemplazan." : "Repite todo: transcripción, imagen y momentos. Los clips actuales y sus ediciones se reemplazan.";
    if (isBusy(P)) $("#redo-hint").textContent += " Este video ya se está procesando: lo nuevo reemplaza lo que esté en marcha.";
    $("#redo-def").textContent = "";
    api(`/api/defaults/resolved?folder=${p.folder || ""}`).then(d => {
      const has = DEF_LABELS.filter(([g]) => ["titulo", "subtitulos", "marca"].includes(g) && d[g]).map(([, l]) => l.toLowerCase()), el = $("#redo-def"), f = folderOf(p.folder);
      if (el) el.textContent = has.length ? `Los clips nuevos saldrán con tus predeterminados${f ? ` de «${f.name}»` : ""}: ${andList(has)}.` : "No hay titular, subtítulos ni marca predeterminados: saldrán los de fábrica.";
    }).catch(() => {});
    rMode.value = o.mode || "auto"; rStyle.value = o.style || "karaoke"; $("#r-n").value = o.max_clips || 10; $("#r-min").value = o.min_len || 20; $("#r-max").value = o.max_len || 60; $("#r-silence").checked = !!o.remove_silence; $("#r-err").textContent = "";
    $("#r-cancel").onclick = () => $("#redo").close();
    $("#r-go").onclick = async () => {
      const mn = +$("#r-min").value, mx = +$("#r-max").value, n = +$("#r-n").value, err = $("#r-err");
      if (!(n >= 1 && n <= 40)) return err.textContent = "La cantidad de clips va de 1 a 40.";
      if (!(mn >= 5 && mx > mn && mx <= 180)) return err.textContent = "Revisa la duración: el mínimo debe ser menor que el máximo (5 a 180 s).";
      try { await api(`/api/projects/${pid}/reanalyze`, { method: "POST", json: { only_select: onlySelect, mode: rMode.value, style: rStyle.value, max_clips: n, min_len: mn, max_len: mx, remove_silence: $("#r-silence").checked } }); $("#redo").close(); sig = ""; tick(); }
      catch (e) { err.textContent = e.message; }
    };
    $("#redo").showModal();
  };
  $("#pmore").onclick = (e) => menu(e.currentTarget, [
    { label: "Volver a elegir momentos", hint: "Con la transcripción que ya existe", icon: "redo", run: () => openRedo(true) },
    { label: "Analizar de cero", hint: "Transcripción, imagen y momentos", icon: "layers", run: () => openRedo(false) }, "-",
    { label: "Borrar proyecto", icon: "trash", bad: true, run: async () => { if (await ask({ title: "¿Borrar este proyecto?", text: `Se borran «${P.name}», sus clips y todos sus archivos. No se puede deshacer.`, ok: "Borrar proyecto", danger: true })) { await api(`/api/projects/${pid}`, { method: "DELETE" }); location.hash = "#/"; } } }]);
}
