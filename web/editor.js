// Editor de un clip: secciones, guion, monitor y línea de tiempo.
"use strict";

const TRANS = {};  // transcripciones ya cargadas, por proyecto
const loadTrans = (pid) => TRANS[pid] || (TRANS[pid] = api(`/api/projects/${pid}/transcript`).then(t => t.segments.flatMap(s => s.words.map((w, i) => ({ ...w, first: i === 0, ts: s.s })))).catch(() => { delete TRANS[pid]; return []; }));

async function editor(pid, cid) {
  const hash = location.hash;
  const [proj, settings, clip0] = await Promise.all([api(`/api/projects/${pid}`), api("/api/settings"), api(`/api/projects/${pid}/clips/${cid}`)]);
  if (location.hash !== hash) return;
  mount("tpl-editor", true);
  let clip = clip0, ctxWords = [];
  const E = clip.edit;
  let dead = false; cleanup.push(() => { dead = true; });

  // ---------- cabecera: volver, anterior / siguiente
  $("#eback").onclick = () => location.hash = `#/p/${pid}`;
  const order = [...proj.clips].sort((a, b) => a.start - b.start), idx = order.findIndex(c => c.id === cid);
  $("#enum").textContent = `${idx + 1} de ${order.length}`;
  const goClip = (k) => { const c = order[idx + k]; if (c) location.hash = `#/p/${pid}/c/${c.id}`; };
  $("#eprev").onclick = () => goClip(-1); $("#enext").onclick = () => goClip(1);
  $("#eprev").disabled = idx <= 0; $("#enext").disabled = idx >= order.length - 1;

  $("#edel").onclick = guard(async () => {
    $("#edel").disabled = true;
    try {
      const up = (await api(`/api/publicaciones?pid=${pid}&cid=${cid}`)).filter(p => ["en cola", "exportando", "subiendo", "pausada"].includes(p.status));
      if (up.some(p => p.status === "subiendo" || p.status === "exportando")) return toast("Este clip se está subiendo a YouTube. Espera a que termine o cancela la subida.", true);
      if (!(await ask({ title: "¿Quitar este clip?", text: `«${clip.title}». Se pierden sus ediciones. Los archivos ya exportados se quedan en su carpeta.${up.length ? " Está en la cola de YouTube y ya no se va a subir." : ""}`, ok: "Quitar", danger: true })) || dead) return;
      clearTimeout(saveTimer); pending = {};
      await api(`/api/projects/${pid}/clips/${cid}`, { method: "DELETE" }); pending = {};
      for (const p of up) await api(`/api/publicaciones/${p.id}/cancelar`, { method: "POST" }).catch(() => {});
      const c = order[idx + 1] || order[idx - 1]; toast("Clip quitado"); location.replace(c ? `#/p/${pid}/c/${c.id}` : `#/p/${pid}`);
    } finally { const b = $("#edel"); if (b && !dead) b.disabled = false; }
  });

  // ---------- monitor
  const tl = new Timeline($("#tl"), {
    playing: () => pv.playing,
    seek: (src) => pv.plan && pv.seek(pv.tmap.toOut(src)),
    trimming: (s, e) => { $("#e-start").value = s.toFixed(2); $("#e-end").value = e.toFixed(2); durUpd(); },
    trim: (s, e) => { $("#e-start").value = s.toFixed(2); $("#e-end").value = e.toFixed(2); durUpd(); save({ start: s, end: e }, true); renderCtx(); },
  });
  cleanup.push(() => tl.destroy());
  const pv = new CliperPreview.Preview($("#cv"), (t) => {
    const el = $("#tcode"); if (!el) return;
    el.textContent = `${fmt(t)} / ${fmt(pv.duration)}`;
    if (pv.tmap) tl.head(pv.tmap.toSrc(t), t);
    highlightWord(t);
  });
  window.__pv = pv;
  cleanup.push(() => { pv.destroy(); window.__pv = null; });
  $("#play").onclick = () => pv.toggle(); $("#b5").onclick = () => pv.seek(pv.t - 5); $("#f5").onclick = () => pv.seek(pv.t + 5);
  let wasPlaying = null;
  timers.push(setInterval(() => { if (pv.playing !== wasPlaying && $("#play")) { wasPlaying = pv.playing; $("#play").innerHTML = icon(pv.playing ? "pause" : "play", 19); $("#play").setAttribute("aria-label", pv.playing ? "Pausar" : "Reproducir"); } }, 120));
  const onKey = (e) => {
    if (isTyping() || $("dialog[open]") || openMenu || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === "Space") { if (document.activeElement.tagName === "BUTTON") document.activeElement.blur(); e.preventDefault(); pv.toggle(); }
    else if (document.activeElement.type === "range") return;
    else if (e.code === "ArrowLeft") { e.preventDefault(); pv.seek(pv.t - (e.shiftKey ? 0.1 : 1)); }
    else if (e.code === "ArrowRight") { e.preventDefault(); pv.seek(pv.t + (e.shiftKey ? 0.1 : 1)); }
    else if (e.code === "Home") pv.seek(0);
    else if (e.code === "End") pv.seek(pv.duration - 0.05);
  };
  document.addEventListener("keydown", onKey); cleanup.push(() => document.removeEventListener("keydown", onKey));

  // ---------- secciones
  const goTab = (id) => {
    $$("#secs button").forEach(x => { const on = x.dataset.tab === id; x.classList.toggle("on", on); x.setAttribute("aria-selected", on); });
    $$(".tab").forEach(t => t.classList.toggle("on", t.id === id)); $(".panel").scrollTop = 0; pref.set("seccion", id);
    if (id === "t-corte") renderCtx();
    if (id === "t-subs" && pv.plan) { syncTrack(pv.t); syncShow(); }
    if (id === "t-encuadre") drawSrc();
    pv.selBrand = id === "t-marca" ? selB : -1;
  };
  $$("#secs button").forEach(b => b.onclick = () => goTab(b.dataset.tab));

  // ---------- guardar + replanificar
  let saveTimer = null, pending = {}, planSeq = 0;
  const saved = (txt) => { const el = $("#savestate"); if (el && !dead) el.textContent = txt; };
  async function refreshPlan() {
    const seq = ++planSeq, plan = await api(`/api/projects/${pid}/clips/${cid}/plan`, { method: "POST", json: {} });
    if (seq !== planSeq || dead) return;
    pv.setPlan(plan); pushTl(); chatUI(); syncShow();
  }
  // lo que se adelanta (−) o atrasa (+) cada palabra, y cuándo sale en el clip
  const shiftOf = (w) => Math.max(-10, Math.min(10, (+E.sub_shift || 0) + (+w.d || 0)));
  let outs = [];
  function pushTl() {
    const p = pv.plan; if (!p || dead) return;
    outs = clip.words.map(w => { const k = shiftOf(w); return { s: pv.tmap.toOut(w.s) + k, e: pv.tmap.toOut(w.e) + k }; });
    phr().forEach((ix, k, all) => { const nx = all[k + 1] && phStart(all[k + 1]); if (nx) ix.slice(1).forEach(n => { outs[n].s = Math.min(outs[n].s, nx - 0.001); }); });
    const inClip = (t) => pv.tmap.toSrc(Math.min(pv.duration, Math.max(0, t)));
    const words = clip.words.map((w, i) => { if (!shiftOf(w)) return w; const s = inClip(outs[i].s), e = inClip(outs[i].e); return e > s ? { ...w, s, e } : null; }).filter(Boolean);
    tl.set({ start: clip.start, end: clip.end, segs: p.segments, words, ctx: ctxWords, title: p.title.on ? Math.min(p.title.until, p.duration) : 0,
      brand: p.brand || [], stickers: p.stickers || [], media: proj.media.duration, toSrc: (t) => pv.tmap.toSrc(t) });
    tl.head(pv.tmap.toSrc(pv.t));
  }
  let waveKey = "";
  async function loadAround() {
    const a = Math.max(0, clip.start - 62), b = Math.min(proj.media.duration, clip.end + 62), key = `${Math.round(clip.start / 20)}-${Math.round(clip.end / 20)}`;
    const all = await loadTrans(pid); if (dead) return;
    ctxWords = all.filter(w => w.e > a && w.s < b); pushTl();
    if (key === waveKey) return; waveKey = key;
    try { const r = await api(`/api/projects/${pid}/wave?a=${a.toFixed(2)}&b=${b.toFixed(2)}&n=${Math.min(4000, Math.round((b - a) * 20))}`); if (!dead) tl.setWave(r.peaks, a, b); } catch (e) {}
  }
  async function put(body) {
    const c = await api(`/api/projects/${pid}/clips/${cid}`, { method: "PUT", json: body });
    if (body.start !== undefined || body.end !== undefined) { clip.words = c.words; if (!dead) { renderWords(); loadAround(); } }
    clip.start = c.start; clip.end = c.end;
  }
  function save(patch, immediate = false) {
    for (const [k, v] of Object.entries(patch)) { if (k === "edit") pending.edit = { ...(pending.edit || {}), ...v }; else pending[k] = v; }
    saved("Guardando…"); clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const body = pending; pending = {};
      try { await put(body); if (!dead) { await refreshPlan(); saved("Guardado"); } } catch (e) { saved(""); toast("No se guardó: " + e.message, true); }
    }, immediate ? 0 : 350);
  }
  async function flushSave() { clearTimeout(saveTimer); if (Object.keys(pending).length) { const body = pending; pending = {}; await put(body); } }
  cleanup.push(() => { flushSave().catch(() => {}); });  // al salir a media espera, guardar lo pendiente
  const setEdit = (k, v) => { E[k] = v; save({ edit: { [k]: v } }); syncUI(); };
  const slider = (id, key, def, txt = (v) => v) => {
    const el = $(id), out = el.closest(".fld").querySelector("output"); el.value = E[key] ?? def; const show = () => { if (out) out.textContent = txt(+el.value); }; show();
    el.oninput = () => { show(); setEdit(key, +el.value); };
  };
  const bindCheck = (sel, key) => { $(sel).checked = !!E[key]; $(sel).onchange = () => setEdit(key, $(sel).checked); };
  const fillBtns = (sel, entries, key, paint) => { for (const [k, label] of entries) { const b = document.createElement("button"); b.type = "button"; b.dataset.v = k; paint(b, k, label); b.onclick = () => setEdit(key, k); $(sel).appendChild(b); } };
  const asFont = (b, k, label) => { b.textContent = label; b.style.fontFamily = CliperPreview.FONT_CSS[k]; if (k === "clasica") b.style.fontWeight = 900; };
  const asColor = (b, k, col) => { b.title = k; b.setAttribute("aria-label", "Color " + k); b.style.background = col; };

  // ---------- predeterminados (generales o de una carpeta) y aplicar a todo
  const scopeHint = () => { const f = folderOf($("#defscope").value); $("#defscopehint").textContent = f ? `Solo para los proyectos de la carpeta «${f.name}».` : FOLDERS.length ? "Para todos los proyectos, salvo las carpetas que tengan los suyos." : "Para todos los proyectos."; };
  const openDef = guard(async () => {
    $("#deferr").textContent = ""; FOLDERS = (await api("/api/folders")).folders;
    const cur = (await api(`/api/projects/${pid}`)).folder;
    folderOptions($("#defscope"), folderOf(cur) ? cur : "", "Todos los proyectos (general)");
    $$("#defscope option").forEach(o => { if (o.value) o.textContent = `Carpeta «${folderOf(o.value).name}»`; });
    $("#defscope").onchange = scopeHint; scopeHint();
    const n = (E.brand || []).length, box = $('#defdlg [data-g="encuadre"]');
    $("#defmarca").textContent = n ? `${n} en este clip, con su posición, tamaño y opacidad` : "Este clip no tiene: los nuevos saldrán sin stickers";
    $('#defdlg [data-g="marca"]').checked = n > 0;
    const mode = E.layout === "split" ? null : E.layout === "streamer" ? ((E.streamer || {}).mode === "apilado" ? "apilado" : "streamer") : E.layout === "full" ? "full" : "auto";
    box.disabled = !mode; box.checked = !!mode;
    const t = modeText({ mode, swap: (E.streamer || {}).swap });
    $("#defenc").textContent = !mode ? "«Dos videos» no se puede dejar como predeterminado" : t[0].toUpperCase() + t.slice(1) + (mode === "streamer" ? " (los recuadros se detectan en cada video)" : "");
    $("#defdlg").showModal();
  });
  $("#defcancel").onclick = () => $("#defdlg").close();
  $("#defgo").onclick = async () => {
    const groups = $$("#defdlg [data-g]").filter(c => c.checked && !c.disabled).map(c => c.dataset.g);
    if (!groups.length) return $("#deferr").textContent = "Marca al menos una opción.";
    $("#defgo").disabled = true;
    try {
      await flushSave(); const f = folderOf($("#defscope").value);
      await api("/api/defaults", { method: "POST", json: { pid, cid, groups, folder: f ? f.id : null } });
      $("#defdlg").close(); toast(`Guardado. Los clips nuevos${f ? ` de «${f.name}»` : ""} saldrán así; los que ya existen no cambian.`);
    } catch (e) { $("#deferr").textContent = e.message; }
    $("#defgo").disabled = false;
  };
  $("#applycancel").onclick = () => $("#applydlg").close();
  $("#applygo").onclick = async () => {
    const groups = $$("#applydlg [data-g]").filter(c => c.checked).map(c => c.dataset.g);
    if (!groups.length) return $("#applyerr").textContent = "Marca al menos una opción.";
    $("#applygo").disabled = true;
    try { await flushSave(); const r = await api(`/api/projects/${pid}/clips/${cid}/apply-all`, { method: "POST", json: { groups } }); $("#applydlg").close(); toast(`Aplicado a ${plural(r.n, "clip", "clips")}`); }
    catch (e) { $("#applyerr").textContent = e.message; }
    $("#applygo").disabled = false;
  };
  $("#elook").onclick = (e) => menu(e.currentTarget, [
    { label: "Aplicar a todo el proyecto…", hint: "Copia el estilo de este clip a los demás", icon: "layers", run: () => { $("#applyerr").textContent = ""; $("#applydlg").showModal(); } },
    { label: "Guardar como predeterminado…", hint: "Para los clips nuevos, en general o por carpeta", icon: "pin", run: openDef },
    { label: "Usar mis predeterminados aquí", hint: "Reemplaza el estilo de este clip", icon: "redo", run: async () => { await flushSave(); await api(`/api/projects/${pid}/clips/${cid}/use-defaults`, { method: "POST" }); toast("Predeterminados aplicados a este clip"); route(); } },
    { label: "Usar predeterminados de otra carpeta…", hint: "En este clip o en todos los del proyecto", icon: "folder", run: guard(async () => { if (await useDefs({ pid, cid, folder: proj.folder, n: proj.clips.length, before: flushSave }) && !dead) route(); }) }]);

  // ---------- titular
  $("#etitle").textContent = clip.title; $("#e-title").value = clip.title;
  $("#e-title").oninput = () => { clip.title = $("#e-title").value; $("#etitle").textContent = clip.title; save({ title: clip.title }); };
  bindCheck("#e-title-on", "title_on"); bindCheck("#e-subs-on", "subs_on"); bindCheck("#e-upper", "upper");
  const secs = choice($("#e-title-secs"), (v) => setEdit("title_secs", +v)); secs.value = String(E.title_secs || 0);
  fillBtns("#e-tstyle", Object.entries(settings.title_styles), "title_style", (b, k, l) => b.textContent = l);
  fillBtns("#e-tfont", Object.entries(settings.fonts), "title_font", asFont);
  fillBtns("#e-tcolor", Object.entries(settings.title_colors), "title_color", asColor);
  slider("#e-tsize", "title_size", 62); slider("#e-ty", "title_y", 250, (v) => Math.round(v / 19.2) + " %");

  // ---------- vista en un teléfono
  phoneView(pv, (key, d) => {
    const el = $(key === "title_y" ? "#e-ty" : "#e-suby"); if (!el) return;
    el.value = (E[key] ?? +el.value) + d; el.oninput(); goTab(key === "title_y" ? "t-titulo" : "t-subs");
  });

  // ---------- guion
  function renderWords() {
    const box = $("#words"); if (!box) return; box.innerHTML = ""; lastHi = -1;
    if (!clip.words.length) box.innerHTML = `<p class="mut small">No hay voz en este tramo.</p>`;
    clip.words.forEach((w) => {
      const el = document.createElement("span"); el.className = "word" + (w.key ? " key" : "") + (w.w ? "" : " gone") + (w.d ? " mv" : ""); if (w.d) el.title = `Movida ${shTxt(w.d)}`;
      el.innerHTML = `<span contenteditable="plaintext-only" spellcheck="false" role="textbox">${esc(w.w)}</span><b>${icon("star", 13)}<u style="text-decoration:none"></u></b>`;
      const sp = el.firstChild, b = $("b", el), lab = () => $("u", b).textContent = w.key ? "Quitar clave" : "Palabra clave"; lab();
      sp.onfocus = () => { if (pv.plan) { pv.pause(); pv.seek(Math.max(0, pv.tmap.toOut(w.s) + shiftOf(w))); } };
      sp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); sp.blur(); } if (e.key === "Escape") { sp.textContent = w.w; sp.blur(); } };
      sp.onblur = () => { const v = sp.textContent.trim(), was = w.w; if (v !== was) { w.w = v; el.classList.toggle("gone", !v); save({ words: clip.words }); if (v && was) repHint(was, v, w); } };
      b.onpointerdown = (e) => { e.preventDefault(); w.key = !w.key; el.classList.toggle("key", w.key); lab(); save({ words: clip.words }); };
      box.append(el, " ");
    });
  }
  let lastHi = -1;
  function highlightWord(t) {
    if (!pv.plan) return;
    let i = -1;
    for (let k = 0; k < outs.length; k++) if (outs[k].s <= t + 0.02 && (i < 0 || outs[k].s >= outs[i].s)) i = k;
    if (i >= 0 && t > outs[i].e + 0.6) i = -1;
    syncTrack(t);
    if (i === lastHi) return;
    const box = $("#words"), ws = box ? box.querySelectorAll(".word") : []; if (!ws.length) return;
    if (lastHi >= 0 && ws[lastHi]) ws[lastHi].classList.remove("now");
    if (i >= 0 && ws[i]) { ws[i].classList.add("now"); if (pv.playing) { const r = ws[i].offsetTop - box.offsetTop; if (r < box.scrollTop || r > box.scrollTop + box.clientHeight - 60) box.scrollTop = r - box.clientHeight / 3; } }
    lastHi = i;
  }

  // ---------- reemplazar palabras iguales
  const rep = { seq: 0, timer: null, done: null, n: null, auto: false };
  const repWhere = choice($("#repwhere"), () => repUI());
  const core = (x) => x.normalize("NFC").replace(/^[^\p{L}\p{N}_]+|[^\p{L}\p{N}_]+$/gu, "");
  const repHits = (idx) => $$("#words .word").forEach((el, k) => el.classList.toggle("hit", idx.includes(k)));
  function repUI() {
    const box = $("#repbox"); if (!box || dead) return;
    const find = $("#repfind").value.trim(), to = $("#repto").value.trim(), n = rep.n, all = repWhere.value === "all", k = n ? (all ? n.all : n.clip) : 0;
    $("#repinfo").textContent = !find || !n ? "" : all ? (n.all ? `${plural(n.all, "vez", "veces")} en ${plural(n.clips, "clip", "clips")}.${to ? " También se corrige en los clips que hagas después." : ""}` : `No sale en ningún clip.${to ? " Se corrige en los que hagas después." : ""}`)
      : n.clip ? `${plural(n.clip, "vez", "veces")} en este clip${n.all > n.clip ? `; ${n.all} en todo el proyecto` : ""}.` : n.all ? `En este clip no. En los otros sale ${plural(n.all, "vez", "veces")}.` : "No sale en ningún clip.";
    $("#repgo").textContent = find && n && !to ? "Quitar del subtítulo" : "Reemplazar";
    $("#repgo").disabled = !find || !n || (!k && !(all && to)) || find === to;
    $("#repundo").hidden = !rep.done;
  }
  async function repLook() {
    const seq = ++rep.seq, find = $("#repfind").value.trim();
    if (!find) { rep.n = null; repHits([]); return repUI(); }
    try {
      await flushSave(); const n = await api(`/api/projects/${pid}/clips/${cid}/palabras`, { method: "POST", json: { find } });
      if (dead || seq !== rep.seq) return; rep.n = n; repHits($("#repbox").hidden ? [] : n.idx); repUI();
    } catch (e) { if (!dead && seq === rep.seq) { rep.n = null; repUI(); $("#repinfo").textContent = e.message; } }
  }
  const repSoon = () => { rep.n = null; clearTimeout(rep.timer); rep.timer = setTimeout(repLook, 220); repUI(); };
  const repShow = (on) => { $("#repbox").hidden = !on; $("#repopen").setAttribute("aria-expanded", on); $("#repopen").classList.toggle("on", on); if (on) repLook(); else { rep.seq++; repHits([]); } };
  // al corregir una a mano: si hay más iguales en el clip, queda listo para cambiarlas todas
  function repHint(was, now, self) {
    const a = core(was).toLowerCase(); if (!a || /\s/.test(was) || a === core(now).toLowerCase() && core(was) === core(now)) return;
    if (!clip.words.some(w => w !== self && core(w.w).toLowerCase() === a && core(w.w) !== core(now))) return;
    if (!$("#repbox").hidden && $("#repfind").value.trim() && !rep.auto) return;
    setTimeout(() => { if (dead) return; $("#repfind").value = core(was); $("#repto").value = core(now) || now; rep.done = null; rep.auto = true; repWhere.value = "clip"; repShow(true); }, 250);
  }
  $("#repopen").onclick = () => { const on = $("#repbox").hidden; if (on) { const s = String(getSelection()).trim(); if (s && s.length <= 80 && $("#words").contains(getSelection().anchorNode)) $("#repfind").value = core(s); } rep.auto = false; repShow(on); if (on) $("#repfind").focus(); };
  $("#repclose").onclick = () => repShow(false);
  $("#repbox").onkeydown = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); repShow(false); $("#repopen").focus(); } };
  $("#repfind").oninput = () => { rep.auto = false; repSoon(); }; $("#repto").oninput = repUI;
  async function repReload() {
    const c = await api(`/api/projects/${pid}/clips/${cid}`); if (dead) return;
    clip.words = c.words; clip.emojis = c.emojis; delete TRANS[pid]; renderWords(); renderEmojis(); loadAround(); await refreshPlan(); saved("Guardado");
  }
  $("#repbox").onsubmit = guard(async (e) => {
    e.preventDefault(); const find = $("#repfind").value.trim(), to = $("#repto").value.trim(), all = repWhere.value === "all";
    if (!find || $("#repgo").disabled) return;
    $("#repgo").disabled = true;
    try {
      await flushSave();
      const r = await api(`/api/projects/${pid}/clips/${cid}/palabras`, { method: "PUT", json: { find, to, all } }); if (dead) return;
      rep.done = r.clips || r.tr ? r.done : null; await repReload(); if (dead) return;
      toast(r.n ? `${to ? "Cambiada" : "Quitada"} ${plural(r.n, "vez", "veces")}${all && r.clips > 1 ? ` en ${r.clips} clips` : ""}` : r.tr ? "Corregida para los clips que hagas después" : "Ya estaba escrita así");
      await repLook();
    } finally { if (!dead) repUI(); }
  });
  $("#repundo").onclick = guard(async () => {
    $("#repundo").disabled = true;
    try { await flushSave(); await api(`/api/projects/${pid}/palabras/deshacer`, { method: "PUT", json: { done: rep.done } }); rep.done = null; if (dead) return; await repReload(); toast("Deshecho"); await repLook(); }
    finally { const b = $("#repundo"); if (b) b.disabled = false; if (!dead) repUI(); }
  });
  cleanup.push(() => clearTimeout(rep.timer));

  // ---------- sincronía de los subtítulos
  const shTxt = (v) => `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v).toFixed(Math.round(Math.abs(v) * 100) % 10 ? 2 : 1).replace(".", ",")} s`;
  const what = choice($("#e-syncwhat"), () => { syncAt = -1; pv.plan && syncTrack(pv.t); syncShow(); });
  let syncAt = -1, syncHold = 0, syncSaid = -9e9;       // frase elegida; un momento fija tras moverla, aunque ya no esté bajo el cabezal
  const phr = () => (pv.plan && pv.plan.phrases || []).filter(ix => ix.every(k => clip.words[k]));
  const phStart = (ix) => outs[ix[0]] ? outs[ix[0]].s : 0;
  function syncTrack(t) {
    if (what.value === "all" || performance.now() < syncHold || !$("#t-subs.on")) return;
    const all = phr(); let at = all.length ? 0 : -1;
    for (let k = 0; k < all.length; k++) if (phStart(all[k]) <= t + 0.04) at = k;
    if (at !== syncAt) { syncAt = at; syncShow(); }
  }
  function syncShow() {
    if (dead || !$("#syncbox")) return;
    const all = phr(), one = what.value !== "all", ix = one ? all[syncAt] : null;
    if (one && !ix && all.length) { syncAt = -1; if (pv.plan) syncTrack(pv.t); }
    const cur = one ? all[syncAt] : null;
    $("#syncphrase").hidden = $("#synchint").hidden = !one;
    if (one) {
      $("#synctext").textContent = cur ? `${cur.map(k => clip.words[k].w).join(" ")}` : "No hay frases en este clip";
      $("#syncprev").disabled = !cur || syncAt <= 0; $("#syncnext").disabled = !cur || syncAt >= all.length - 1;
    }
    $("#syncval").textContent = shTxt(one ? (cur ? +clip.words[cur[0]].d || 0 : 0) : +E.sub_shift || 0);
    const off = !E.subs_on || (one ? !cur : !clip.words.length);
    $$("#syncn button").forEach(b => b.disabled = off);
    $("#syncreset").hidden = !(+E.sub_shift) && !clip.words.some(w => w.d);
  }
  const syncGo = (at) => { const ix = phr()[at]; if (!ix) return; pv.pause(); syncAt = at; syncHold = performance.now() + 400; pv.seek(Math.min(Math.max(0, phStart(ix)) + 0.03, Math.max(0, pv.duration - 0.05))); syncShow(); };
  $("#syncprev").onclick = () => syncGo(syncAt - 1); $("#syncnext").onclick = () => syncGo(syncAt + 1);
  const lim = (v) => +Math.max(-10, Math.min(10, v)).toFixed(2);
  const syncMarks = () => $$("#words .word").forEach((el, k) => { const w = clip.words[k]; if (!w) return; el.classList.toggle("mv", !!w.d); el.title = w.d ? `Movida ${shTxt(w.d)}` : ""; });
  $$("#syncn button").forEach(b => b.onclick = () => {
    const d = +b.dataset.sh;
    if (what.value === "all") { E.sub_shift = lim((+E.sub_shift || 0) + d); save({ edit: { sub_shift: E.sub_shift } }); pushTl(); return syncShow(); }
    const all = phr(), ix = all[syncAt]; if (!ix) return;
    const to = what.value === "one" ? ix : all.slice(syncAt).flat(), base = +clip.words[ix[0]].d || 0, at = phStart(ix), prev = all[syncAt - 1], next = what.value === "one" && all[syncAt + 1];
    // una frase no puede rebasar a la de al lado
    const lo = prev ? phStart(prev) + 0.1 - at : -99, hi = next ? phStart(next) - 0.1 - at : 99, k = +Math.min(Math.max(lim(base + d) - base, Math.min(0, lo)), Math.max(0, hi)).toFixed(2);
    if (Math.abs(k) < 0.01) { if (performance.now() - syncSaid < 2500) return; syncSaid = performance.now(); return toast(Math.abs(base + d) > 10 ? "Más de 10 segundos no se puede." : `Ya toca la frase ${d < 0 ? "anterior" : "siguiente"}.`); }
    for (const n of to) { const w = clip.words[n], v = lim((+w.d || 0) + k); if (v) w.d = v; else delete w.d; }
    pushTl(); syncMarks(); save({ words: clip.words }); syncGo(syncAt);
    syncHold = performance.now() + 1500;
  });
  $("#syncreset").onclick = () => { E.sub_shift = 0; clip.words.forEach(w => delete w.d); pushTl(); syncMarks(); save({ words: clip.words, edit: { sub_shift: 0 } }); syncShow(); toast("Los subtítulos volvieron a su tiempo"); };

  // ---------- corte
  const durUpd = () => { const el = $("#e-dur"); if (el) el.textContent = `${(+$("#e-end").value - +$("#e-start").value).toFixed(1)} s`; };
  const setTimes = () => { $("#e-start").value = clip.start.toFixed(2); $("#e-end").value = clip.end.toFixed(2); durUpd(); };
  setTimes();
  const applyTimes = () => {
    const s = +$("#e-start").value, e = +$("#e-end").value;
    if (!(s >= 0 && e > s)) { toast("El fin debe ir después del inicio.", true); return setTimes(); }
    clip.start = s; clip.end = e; save({ start: s, end: e }); renderCtx();
  };
  $("#e-start").onchange = applyTimes; $("#e-end").onchange = applyTimes;
  $$("[data-n]").forEach(b => b.onclick = () => { const [k, d] = b.dataset.n.split(":"), el = $(`#e-${k}`); el.value = Math.max(0, +el.value + +d).toFixed(2); durUpd(); applyTimes(); });
  const pickmode = choice($("#pickmode"));
  async function renderCtx() {
    const all = await loadTrans(pid), box = $("#ctx"); if (!box || dead || !$("#t-corte").classList.contains("on")) return;
    const s = +$("#e-start").value, e = +$("#e-end").value; box.innerHTML = "";
    for (const w of all) {
      if (w.e < s - 30 || w.s > e + 30) continue;
      if (w.first || !box.firstChild) { if (box.firstChild) box.appendChild(document.createElement("br")); const ts = document.createElement("span"); ts.className = "ts"; ts.textContent = fmt(w.ts) + "  "; box.appendChild(ts); }
      const sp = document.createElement("span"); sp.textContent = w.w + " "; sp.title = `${w.s.toFixed(2)} a ${w.e.toFixed(2)}`;
      if (w.s >= s - 0.05 && w.e <= e + 0.05) sp.className = "in";
      if (Math.abs(w.s - s) < 0.12 || Math.abs(w.e - e) < 0.3) sp.classList.add("edge");
      sp.onclick = () => { if (pickmode.value === "start") $("#e-start").value = Math.max(0, w.s - 0.08).toFixed(2); else $("#e-end").value = (w.e + 0.25).toFixed(2); durUpd(); applyTimes(); };
      box.appendChild(sp);
    }
    const first = $(".in", box); if (first) box.scrollTop = first.offsetTop - box.offsetTop - 60;
  }
  bindCheck("#e-silence", "remove_silence");

  // ---------- encuadre
  $$("[data-frame]", $("#e-layout")).forEach(b => b.insertAdjacentHTML("afterbegin", frameSvg(b.dataset.frame)));
  const segBind = (sel, key, after) => $$(`${sel} button`).forEach(b => b.onclick = () => { setEdit(key, b.dataset.v); after && after(); });
  const autoBoxes = () => api(`/api/projects/${pid}/clips/${cid}/auto-streamer`, { method: "POST" });
  const saveStreamer = () => { save({ edit: { streamer: E.streamer } }); syncUI(); };
  // cada botón es un encuadre completo: «streamer» y «apilado» son el mismo layout con otro modo
  $$("#e-layout button").forEach(b => b.onclick = guard(async () => {
    const v = b.dataset.v, layout = v === "apilado" ? "streamer" : v;
    if (layout === "streamer") { if (!E.streamer) E.streamer = await autoBoxes(); E.streamer = { ...E.streamer, mode: v === "apilado" ? "apilado" : "recuadros" }; save({ edit: { streamer: E.streamer } }); }
    setEdit("layout", layout);
    // en «Dos videos» los subtítulos van en la unión de ambos
    if (layout === "split" && E.sub_y === 1250) { setEdit("sub_y", 960); $("#e-suby").value = 960; } else if (layout !== "split" && E.sub_y === 960) { setEdit("sub_y", 1250); $("#e-suby").value = 1250; }
    if (layout === "split") loadOthers();
    drawSrc();
  }));
  segBind("#e-framing", "framing"); segBind("#e-framing2", "framing");
  $("#e-mx").value = $("#e-mx2").value = E.manual_x ?? 0.5;
  $("#e-mx").oninput = () => { $("#e-mx2").value = $("#e-mx").value; setEdit("manual_x", +$("#e-mx").value); };
  $("#e-mx2").oninput = () => { $("#e-mx").value = $("#e-mx2").value; setEdit("manual_x", +$("#e-mx2").value); };
  $("#e-camh").value = (E.streamer && E.streamer.cam_h) || 640;
  $("#e-camh").oninput = () => { E.streamer = { ...(E.streamer || {}), cam_h: +$("#e-camh").value }; save({ edit: { streamer: E.streamer } }); };
  $("#autostream").onclick = guard(async () => { E.streamer = { ...(E.streamer || {}), ...(await autoBoxes()) }; saveStreamer(); drawSrc(); });
  $$("#e-sswap button").forEach(b => b.onclick = () => { E.streamer = { ...E.streamer, swap: b.dataset.v === "1" }; saveStreamer(); });

  // lienzo de recuadros del streamer
  const sc = $("#srccv"), sctx = sc.getContext("2d"); let drag = null;
  function drawSrc() {
    if (dead) return;
    const v = pv.vA, W = 480, H = Math.round(480 * (proj.media.height / proj.media.width)); if (sc.height !== H) sc.height = H;
    sctx.fillStyle = "#000"; sctx.fillRect(0, 0, W, H); if (v.videoWidth) sctx.drawImage(v, 0, 0, W, H);
    if (!E.streamer || !E.streamer.game) return;
    for (const [k, col] of [["game", "#2bd9ff"], ["cam", "#ffd400"]]) {
      const [x, y, w, h] = E.streamer[k]; sctx.strokeStyle = col; sctx.lineWidth = 3; sctx.strokeRect(x * W + 1.5, y * H + 1.5, w * W - 3, h * H - 3);
      sctx.fillStyle = col; sctx.fillRect((x + w) * W - 12, (y + h) * H - 12, 12, 12); sctx.font = "600 13px Bahnschrift, Segoe UI"; sctx.fillText(k === "cam" ? "Cámara" : "Juego", x * W + 8, y * H + 18);
    }
  }
  timers.push(setInterval(() => { if ($("#t-encuadre.on") && E.layout === "streamer") drawSrc(); }, 250));
  const scPos = (e) => { const r = sc.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  sc.onpointerdown = (e) => {
    if (!E.streamer || !E.streamer.game) return; const [px, py] = scPos(e);
    for (const k of ["cam", "game"]) {
      const [x, y, w, h] = E.streamer[k], corner = Math.abs(px - (x + w)) < 0.04 && Math.abs(py - (y + h)) < 0.06;
      if (corner || (px > x && px < x + w && py > y && py < y + h)) { drag = { k, mode: corner ? "size" : "move", px, py, orig: [x, y, w, h] }; sc.setPointerCapture(e.pointerId); return; }
    }
  };
  sc.onpointermove = (e) => {
    if (!drag) return; const [px, py] = scPos(e); let [x, y, w, h] = drag.orig;
    if (drag.mode === "move") { x = Math.min(Math.max(0, x + px - drag.px), 1 - w); y = Math.min(Math.max(0, y + py - drag.py), 1 - h); }
    else { w = Math.min(Math.max(0.05, w + px - drag.px), 1 - x); h = Math.min(Math.max(0.05, h + py - drag.py), 1 - y); }
    E.streamer[drag.k] = [x, y, w, h].map(v => +v.toFixed(4)); drawSrc();
  };
  sc.onpointerup = sc.onpointercancel = () => { if (drag) { drag = null; save({ edit: { streamer: E.streamer } }); } };

  async function loadOthers() {
    const list = (await api("/api/projects")).filter(p => p.id !== pid && p.status === "listo"), sel = $("#e-other"); if (!sel) return;
    sel.innerHTML = `<option value="">Elige un proyecto</option>` + list.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    if (E.split && E.split.pid) sel.value = E.split.pid; $("#e-offset").value = (E.split && E.split.offset) || 0;
  }
  $("#e-other").onchange = () => { E.split = { pid: $("#e-other").value, offset: +$("#e-offset").value || 0 }; save({ edit: { split: E.split } }); };
  $("#e-offset").oninput = () => { E.split = { ...(E.split || {}), offset: +$("#e-offset").value }; save({ edit: { split: E.split } }); };
  $("#dosync").onclick = async () => {
    const other = $("#e-other").value; if (!other) return toast("Elige primero el otro video.", true);
    $("#syncinfo").textContent = "Escuchando los dos audios…";
    try { const r = await api(`/api/projects/${pid}/sync/${other}`, { method: "POST" }); $("#e-offset").value = r.offset; E.split = { pid: other, offset: r.offset }; save({ edit: { split: E.split } }); $("#syncinfo").textContent = `Desfase ${r.offset.toFixed(2)} s (confianza ${(r.confidence * 100).toFixed(0)} %).`; }
    catch (e) { $("#syncinfo").textContent = e.message; }
  };

  // ---------- subtítulos
  segBind("#e-style", "style");
  fillBtns("#e-font", Object.entries(settings.fonts), "font", asFont); fillBtns("#e-color", Object.entries(settings.colors), "color", asColor);
  slider("#e-size", "sub_size", 96); slider("#e-suby", "sub_y", 1250, (v) => Math.round(v / 19.2) + " %");

  // ---------- ritmo
  segBind("#e-filter", "filter"); bindCheck("#e-zooms", "zooms"); bindCheck("#e-emojis", "emojis_on"); bindCheck("#e-logos", "logos_on");
  function renderEmojis() {
    const box = $("#emojis"); box.innerHTML = (clip.emojis || []).length ? "" : `<p class="mut small">Ninguno todavía.</p>`;
    (clip.emojis || []).forEach((p, i) => {
      const r = document.createElement("div"); r.className = "er";
      r.innerHTML = `<input type="text" value="${esc(p.word)}" placeholder="Al decir…" aria-label="Palabra"><input type="text" value="${esc(p.emoji)}" aria-label="Emoji"><button class="btn gh sq" aria-label="Quitar emoji">${icon("close", 15)}</button>`;
      const [iw, ie] = $$("input", r), upd = () => { clip.emojis[i] = { word: iw.value.trim(), emoji: ie.value.trim() }; save({ emojis: clip.emojis }); };
      iw.onchange = upd; ie.onchange = upd; $("button", r).onclick = () => { clip.emojis.splice(i, 1); save({ emojis: clip.emojis }); renderEmojis(); };
      box.appendChild(r);
    });
  }
  $("#addemoji").onclick = () => { clip.emojis = [...(clip.emojis || []), { word: "", emoji: "🔥" }]; renderEmojis(); const l = $$("#emojis input[placeholder]"); l[l.length - 1].focus(); };

  // ---------- stickers de marca
  E.brand = E.brand || [];
  let brandLib = [], selB = -1;
  const bHeight = (b) => { const l = brandLib.find(x => x.id === b.id); return l ? Math.round(l.h * b.w / l.w) : b.w; };
  const saveBrand = () => { save({ edit: { brand: E.brand } }); renderBList(); };
  const selectB = (i) => { selB = i; if ($("#t-marca.on")) pv.selBrand = i; $$("#blist .br").forEach((r, k) => r.classList.toggle("sel", k === i)); };
  async function loadBrand() { brandLib = await api("/api/brand"); if (!dead) { renderGallery(); renderBList(); } }
  function renderGallery() {
    const box = $("#bgallery"); box.innerHTML = brandLib.length ? "" : `<p class="mut small" style="grid-column:1/-1">Todavía no subes ninguno.</p>`;
    for (const it of brandLib) {
      const d = document.createElement("div"); d.className = "bi"; d.tabIndex = 0; d.setAttribute("role", "button"); d.title = `Poner «${it.name}» en el clip`;
      d.innerHTML = `<img src="/api/img/brand/${it.id}?w=160" alt="${esc(it.name)}"><b role="button" tabindex="0" title="Borrar de tus stickers" aria-label="Borrar de tus stickers">${icon("close", 13)}</b>`;
      const add = () => { const w = Math.min(420, Math.round(360 * Math.min(1, it.w / it.h * 1.2))); E.brand.push({ id: it.id, x: 540, y: Math.round(1920 - 90 - (it.h * w / it.w) / 2), w, opacity: 100, when: "todo" }); saveBrand(); selectB(E.brand.length - 1); };
      d.onclick = add; d.onkeydown = (e) => { if (e.key === "Enter" && e.target === d) add(); };
      $("b", d).onclick = guard(async (e) => {
        e.stopPropagation(); if (!(await ask({ title: `¿Borrar «${it.name}»?`, text: "Se quita de tus stickers y de los clips que lo usan.", ok: "Borrar sticker", danger: true }))) return;
        await api(`/api/brand/${it.id}`, { method: "DELETE" }); E.brand = E.brand.filter(b => b.id !== it.id); saveBrand(); loadBrand();
      });
      box.appendChild(d);
    }
  }
  const syncBY = (i) => { const inp = $$("#blist .br")[i]?.querySelector('[data-k="y"]'); if (inp && E.brand[i]) inp.value = E.brand[i].y; };
  const CELLS = ["tl", "tc", "tr", "cl", "cc", "cr", "bl", "bc", "br"], CELL_TXT = { t: "arriba", c: "centro", b: "abajo", l: "izquierda", r: "derecha" };
  function renderBList() {
    const box = $("#blist"); if (!box) return; box.innerHTML = E.brand.length ? "" : `<p class="mut small">Elige un sticker de arriba para ponerlo en este clip.</p>`;
    E.brand.forEach((b, i) => {
      const r = document.createElement("div"); r.className = "br" + (i === selB ? " sel" : "");
      r.innerHTML = `<div class="hd"><img src="/api/img/brand/${b.id}?w=120" alt=""><button class="btn gh sq sm bad" data-rm title="Quitar del clip" aria-label="Quitar del clip">${icon("trash", 16)}</button></div>
        <label class="fld"><span class="lb">Tamaño</span><input type="range" min="60" max="1080" step="10" value="${b.w}" data-k="w"></label>
        <label class="fld"><span class="lb">Altura</span><input type="range" min="0" max="1920" step="5" value="${b.y ?? 1700}" data-k="y"></label>
        <label class="fld"><span class="lb">Opacidad</span><input type="range" min="10" max="100" step="5" value="${b.opacity ?? 100}" data-k="opacity"></label>
        <div class="two"><label class="fld"><span class="lb">Se ve</span><select data-k="when"><option value="todo">Todo el clip</option><option value="inicio">Los primeros 5 s</option><option value="final">Los últimos 5 s</option></select></label>
          <div><span class="lb">Posición</span><div class="pos">${CELLS.map(k => `<button data-p="${k}" aria-label="Mover: ${CELL_TXT[k[0]]}, ${CELL_TXT[k[1]]}"></button>`).join("")}</div></div></div>`;
      $("select", r).value = b.when || "todo"; r.onclick = () => selectB(i);
      $$("[data-k]", r).forEach(inp => inp.oninput = () => {
        const k = inp.dataset.k; b[k] = k === "when" ? inp.value : +inp.value;
        const it = (pv.plan?.brand || []).find(x => x.i === i);  // mover al instante, sin esperar al guardado
        if (k === "y" && it) { it.y = b.y; pv.draw(pv.t); }
        save({ edit: { brand: E.brand } });
      });
      $$("[data-p]", r).forEach(btn => btn.onclick = (e) => {
        e.stopPropagation(); const h = bHeight(b), m = 50, p = btn.dataset.p;
        b.x = p[1] === "l" ? Math.round(b.w / 2 + m) : p[1] === "r" ? Math.round(1080 - b.w / 2 - m) : 540;
        b.y = p[0] === "t" ? Math.round(h / 2 + m + 40) : p[0] === "b" ? Math.round(1920 - h / 2 - m - 40) : 960;
        syncBY(i); save({ edit: { brand: E.brand } }); selectB(i);
      });
      $("[data-rm]", r).onclick = (e) => { e.stopPropagation(); E.brand.splice(i, 1); selB = -1; pv.selBrand = -1; saveBrand(); };
      box.appendChild(r);
    });
  }
  $("#bupload").onchange = async () => {
    const f = $("#bupload").files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
    try { const r = await fetch("/api/brand", { method: "POST", body: fd }); if (!r.ok) throw new Error((await r.json()).detail || r.statusText); } catch (e) { toast(e.message, true); }
    $("#bupload").value = ""; loadBrand();
  };
  $("#ball").onclick = guard(async () => {
    if (!(await ask({ title: "¿Poner estos stickers en todos los clips?", text: "Con esta posición y tamaño, en lugar de los que tengan.", ok: "Poner en todos" }))) return;
    await flushSave(); const r = await api(`/api/projects/${pid}/brand-all`, { method: "POST", json: { brand: E.brand } }); toast(`Puestos en ${plural(r.n, "clip", "clips")}`);
  });
  // arrastrar los stickers sobre el monitor
  const cvEl = $("#cv"); let bdrag = null;
  const cvPos = (e) => { const r = cvEl.getBoundingClientRect(); return [(e.clientX - r.left) * 1080 / r.width, (e.clientY - r.top) * 1920 / r.height]; };
  const hitB = (x, y) => [...((pv.plan || {}).brand || [])].reverse().find(b => pv.t >= b.s && pv.t <= b.e && Math.abs(x - b.x) <= b.w / 2 && Math.abs(y - b.y) <= b.h / 2);
  let downAt = null;
  cvEl.onpointerdown = (e) => {
    const [x, y] = cvPos(e), hit = hitB(x, y); downAt = [e.clientX, e.clientY];
    if (!hit) return; e.preventDefault(); cvEl.setPointerCapture(e.pointerId); bdrag = { item: hit, dx: x - hit.x, dy: y - hit.y, moved: false };
  };
  cvEl.onpointermove = (e) => {
    const [x, y] = cvPos(e); if (!bdrag) { cvEl.classList.toggle("brandmode", !!hitB(x, y)); return; }
    if (!bdrag.moved && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 4) return;
    if (!bdrag.moved) { bdrag.moved = true; if (!$("#t-marca.on")) goTab("t-marca"); selectB(bdrag.item.i); }
    const it = bdrag.item; it.x = Math.round(Math.min(1080, Math.max(0, x - bdrag.dx))); it.y = Math.round(Math.min(1920, Math.max(0, y - bdrag.dy)));
    if (E.brand[it.i]) { E.brand[it.i].x = it.x; E.brand[it.i].y = it.y; syncBY(it.i); } pv.draw(pv.t);
  };
  cvEl.onpointerup = () => { if (bdrag && bdrag.moved) save({ edit: { brand: E.brand } }); else if (downAt) pv.toggle(); bdrag = null; downAt = null; };
  cvEl.onpointercancel = () => { bdrag = null; downAt = null; };
  loadBrand();

  // ---------- chat de Kick (solo en videos de Kick)
  $("#tabchat").hidden = !proj.chat; $$(".onlychat").forEach(el => { el.hidden = !proj.chat; });
  E.chat_names ??= true; E.chat_count ??= true; E.chat_safe ??= true; bindCheck("#e-chat-safe", "chat_safe");
  bindCheck("#e-chat-names", "chat_names"); bindCheck("#e-chat-count", "chat_count");
  $("#e-chat-on").checked = !!E.chat_on; $("#e-chat-on").onchange = () => { chatTried = ""; setEdit("chat_on", $("#e-chat-on").checked); };
  segBind("#e-chat-mode", "chat_mode"); $$("#e-chat-side button").forEach(b => b.onclick = () => { setEdit("chat_x", null); setEdit("chat_side", b.dataset.v); });
  slider("#e-chat-size", "chat_size", 38); slider("#e-chat-lead", "chat_lead", 0, (v) => v ? `${v > 0 ? "" : "−"}${Math.abs(v)} s` : "0 s");
  let chatTried = "", chatSig = "", chatBusy = false;
  const chatSay = (t, bad) => { const el = $("#chatstate"); el.hidden = !t; el.textContent = t; el.style.color = bad ? "var(--bad)" : ""; };
  async function readChat() {
    if (chatBusy || dead) return; chatBusy = true; chatTried = `${clip.start}-${clip.end}`; chatSay("Leyendo el chat de Kick…");
    const tick = setInterval(async () => { try { const { wait } = await api("/api/chat/estado"); if (chatBusy && !dead) chatSay(wait ? `Kick pidió ir más despacio. Sigue solo en ${wait} s.` : "Leyendo el chat de Kick…"); } catch (e) {} if (!chatBusy || dead) clearInterval(tick); }, 2000);
    try { const r = await api(`/api/projects/${pid}/clips/${cid}/chat`, { method: "POST" }); chatBusy = false; if (dead) return; chatSay(r.n ? "" : "En este momento del directo nadie escribió."); await refreshPlan(); }
    catch (e) { chatBusy = false; if (dead) return; const el = $("#chatstate"); chatSay(e.message, true); const b = document.createElement("button"); b.className = "btn sm"; b.type = "button"; b.textContent = "Reintentar"; b.style.marginLeft = "8px"; b.onclick = readChat; el.append(b); }
  }
  function chatUI() {
    const ch = pv.plan && pv.plan.chat; if (!proj.chat || dead) return;
    $("#chatopts").hidden = !E.chat_on; $("#chatnames").hidden = E.chat_mode === "emotes"; if (!E.chat_on) { chatSay(""); return; }
    if (!ch) return;
    for (const [id, v, txt] of [["#e-chat-y", ch.y, Math.round(ch.y / 19.2) + " %"], ["#e-chat-x", ch.px, ch.px + " %"]]) if (document.activeElement !== $(id)) { $(id).value = v; $(id).closest(".fld").querySelector("output").textContent = txt; }
    if (ch.missing && chatTried !== `${clip.start}-${clip.end}`) readChat();
    const s = JSON.stringify([ch.mode, ch.missing, ch.items.map(i => [i.id, i.s]), E.chat_hide]); if (s === chatSig) return; chatSig = s;
    const box = $("#chatlist"); box.innerHTML = "";
    const n = (E.chat_hide || []).length;
    if (ch.mode === "emotes") box.innerHTML = `<p class="mut small">En este modo solo salen los emotes${ch.parts.length ? "" : ", y en este clip no hubo"}.</p>`;
    else if (!ch.items.length && !ch.missing) box.innerHTML = `<p class="mut small">Ningún mensaje con texto pasó los filtros.</p>`;
    for (const it of ch.items) {
      const r = document.createElement("div"); r.className = "cm";
      r.innerHTML = `<button class="lnk num" type="button">${fmt(it.s)}</button><span>${it.u ? `<b>${esc(it.u)}</b> ` : ""}${esc(it.x).replace(/\[e:(\d+)\]/g, (m, i) => `<i class="em" style="background-image:url(/api/img/emote/${i})"></i>`)}</span><button class="btn gh sq sm" type="button" title="Quitar de este clip" aria-label="Quitar este mensaje">${icon("close", 14)}</button>`;
      const [go, rm] = $$("button", r); go.onclick = () => { pv.pause(); pv.seek(Math.max(0, it.s) + .3); }; rm.onclick = () => setEdit("chat_hide", [...(E.chat_hide || []), it.id]);
      box.appendChild(r);
    }
    if (n) { const b = document.createElement("button"); b.className = "btn sm gh"; b.type = "button"; b.textContent = `Volver a poner ${plural(n, "mensaje quitado", "mensajes quitados")}`; b.onclick = () => setEdit("chat_hide", []); box.appendChild(b); }
  }
  $("#e-chat-y").oninput = () => { $("#e-chat-y").closest(".fld").querySelector("output").textContent = Math.round($("#e-chat-y").value / 19.2) + " %"; setEdit("chat_y", +$("#e-chat-y").value); };
  $("#e-chat-x").oninput = () => { $("#e-chat-x").closest(".fld").querySelector("output").textContent = $("#e-chat-x").value + " %"; setEdit("chat_x", +$("#e-chat-x").value); };
  if (proj.chat) api("/api/chat/palabras").then(ws => { if (!dead) $("#chatblock").value = ws.join("\n"); }).catch(() => {});
  $("#chatblock").onchange = guard(async () => { const ws = await api("/api/chat/palabras", { method: "PUT", json: { words: $("#chatblock").value.split("\n") } }); if (dead) return; $("#chatblock").value = ws.join("\n"); await refreshPlan(); });

  // ---------- salida: publicar y exportar
  $("#e-desc").value = clip.description || ""; $("#e-desc").oninput = () => save({ description: $("#e-desc").value });
  $("#e-tags").value = (clip.hashtags || []).join(" "); $("#e-tags").oninput = () => save({ hashtags: $("#e-tags").value.split(/\s+/).filter(Boolean) });
  $("#e-reason").innerHTML = clip.reason ? `${potBars(clip.score)} <b>${clip.score}</b> de 100, ${esc((clip.category || "").toLowerCase())}. ${esc(clip.reason)}${clip.chat_heat ? ` ${esc(heatTxt(clip.chat_heat))}` : ""}` : ""; $("#reasonbox").hidden = !clip.reason;
  $("#copypub").onclick = guard(async () => { await navigator.clipboard.writeText(`${clip.title}\n\n${$("#e-desc").value}\n\n${$("#e-tags").value}`); toast("Copiado: titular, descripción y hashtags"); });
  const doExport = async (q) => { await flushSave(); await exportClip(pid, cid, q); goTab("t-salida"); toast("En la cola de exportación"); pollJobs(); };
  $$(".quals button").forEach(b => b.onclick = guard(() => doExport(b.dataset.q)));
  $("#eexport").onclick = (e) => menu(e.currentTarget, [{ head: "Exportar este clip" }, ...QUALS.map(([k, h]) => ({ label: k === "mp3" ? "MP3" : k, hint: h, icon: "out", run: () => doExport(k) }))]);
  $("#eyt").onclick = guard(async () => { await flushSave(); if (await ytPublish(pid, [await api(`/api/projects/${pid}/clips/${cid}`)])) pollPubs(); });
  let pubSig = "";
  $("#emine").onclick = guard(async () => { if (await ytManual({ pid, cid, title: clip.title })) { pubSig = ""; pollPubs(); } });
  async function pollPubs() {
    let ps; try { ps = await api(`/api/publicaciones?pid=${pid}&cid=${cid}`); } catch (e) { return; }
    if ($("#emine")) $("#emine").hidden = ps.some(p => ytUploaded(p) || ["exportando", "subiendo"].includes(p.status) || !p.hidden && YT_ON.includes(p.status));
    ps = ps.filter(p => !p.hidden);
    const box = $("#epubs"), s = ytSig(ps); if (!box || s === pubSig) return; pubSig = s; box.innerHTML = ytRows(ps); ytBind(box, () => { pubSig = ""; pollPubs(); });
  }
  timers.push(setInterval(pollPubs, 2000));
  async function renderExports() {
    const c = await api(`/api/projects/${pid}/clips/${cid}`), box = $("#eexports"); if (!box) return;
    const l = [...(c.exports || [])].reverse(); $("#noexp").hidden = l.length > 0;
    box.innerHTML = l.map(x => `<div class="file"><span class="n" title="${esc(x.file)}">${esc(x.quality)}<small>${esc(x.file)} · ${fmtSize(x.size)}</small></span><a class="btn sm" href="/api/projects/${pid}/files/${encodeURIComponent(x.file)}" download>${icon("download", 15)}Guardar</a></div>`).join("");
  }
  $("#eopen").onclick = guard(() => api(`/api/projects/${pid}/open-folder`, { method: "POST" }));
  let jobsActive = false;
  async function pollJobs() {
    let js; try { js = (await api("/api/jobs")).filter(j => j.kind === "export" && j.pid === pid && j.cid === cid); } catch (e) { return; }
    const box = $("#ejobs"); if (!box) return;
    box.innerHTML = js.filter(j => j.status !== "listo").map(j => `<div class="job"><div class="hd"><b>${esc(j.quality)}</b><span class="num">${j.status === "renderizando" ? `${Math.round(j.progress)} %${j.fps ? `, ${j.fps} fps` : ""}` : esc(j.status)}</span></div>${j.status === "error" ? `<div class="err">${esc(j.error)}</div>` : `<div class="line"><i style="width:${j.progress}%"></i></div>`}</div>`).join("");
    const active = js.some(j => j.status === "en cola" || j.status === "renderizando"); if (jobsActive && !active) renderExports(); jobsActive = active;
  }
  timers.push(setInterval(pollJobs, 1000));

  // ---------- la interfaz sigue al estado
  function syncUI() {
    if (dead) return;
    const on = (sel, v) => $$(`${sel} button`).forEach(b => { const k = b.dataset.v === v; b.classList.toggle("on", k); b.setAttribute("aria-pressed", k); });
    const smode = (E.streamer && E.streamer.mode) || "recuadros", lay = E.layout || "vertical";
    on("#e-layout", lay === "streamer" && smode === "apilado" ? "apilado" : lay);
    on("#e-framing", E.framing || "auto"); on("#e-framing2", E.framing || "auto"); on("#e-style", E.style || "karaoke"); on("#e-filter", E.filter || "ninguno");
    on("#e-font", E.font); on("#e-color", E.color); on("#e-tstyle", E.title_style || "caja"); on("#e-tfont", E.title_font || "clasica"); on("#e-tcolor", E.title_color || "blanco");
    $$(".lay").forEach(l => l.classList.toggle("on", l.classList.contains(`lay-${lay}`))); $$(".manual-only").forEach(el => el.classList.toggle("on", E.framing === "manual"));
    $(".smode-recuadros").classList.toggle("on", smode === "recuadros"); $(".smode-apilado").classList.toggle("on", smode === "apilado"); on("#e-sswap", E.streamer && E.streamer.swap ? "1" : "0");
    on("#e-chat-mode", E.chat_mode || "mensajes"); on("#e-chat-side", E.chat_side || "izq");
    $("#tcolorhint").textContent = ["oscura", "contorno"].includes(E.title_style) ? "de la letra" : "de la caja"; $("#dynhint").hidden = E.style !== "dinamico"; syncShow();
  }
  syncUI(); renderWords(); renderEmojis(); renderExports(); pollJobs(); pollPubs(); if (E.layout === "split") loadOthers();
  const tab = pref.get("seccion", "t-titulo"); goTab(document.getElementById(tab) && (proj.chat || tab !== "t-chat") ? tab : "t-titulo");
  loadAround();
  await refreshPlan();
}
