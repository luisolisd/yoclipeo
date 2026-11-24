// Cola, descargas y ajustes.
"use strict";

// ------------------------------------------------------------ cola
function cola() {
  mount("tpl-cola");
  let sig = "";
  every(1000, async () => {
    let js, ps, lv, yt; try { [js, ps, lv, yt] = await Promise.all([api("/api/jobs"), api("/api/projects"), api("/api/directos"), api("/api/publicaciones")]); } catch (e) { return; }
    yt = yt.filter(p => !p.hidden);
    lv = lv.filter(liveOn); const box = $("#qbox"); if (!box) return;
    const s = JSON.stringify([js, ytSig(yt), lv.map(liveText), ps.map(p => [p.id, p.status, p.progress, p.message])]); if (s === sig) return; sig = s;
    const P = Object.fromEntries(ps.map(p => [p.id, p])), running = js.filter(j => ["en cola", "renderizando", "descargando"].includes(j.status)).sort((a, b) => a.created - b.created), bad = js.filter(j => j.status === "error"), done = js.filter(j => j.status === "listo"), waits = ps.filter(isWait), busy = ps.filter(p => isBusy(p) && !isWait(p));
    const clipOf = (j) => ((P[j.pid] || {}).marks || []).find(m => m.id === j.cid), what = (j) => j.kind === "download" ? (j.title || j.url) : (clipOf(j) || {}).t || "Clip borrado", from = (j) => j.kind === "export" && P[j.pid] ? `, ${P[j.pid].name}` : "";
    const th = (j) => j.kind === "export" ? `<i style="flex:none;width:27px;height:48px;border-radius:2px;background:var(--well) url('/api/projects/${j.pid}/thumb/${j.cid}') center/cover"></i>` : `<span style="width:27px;display:grid;place-items:center;color:var(--mut)">${icon("download", 18)}</span>`;
    const tag = (j) => j.kind === "download" ? (j.format === "mp3" ? "Descarga MP3" : "Descarga de video") : `Exportación ${j.quality}`;
    box.innerHTML =
      (busy.length ? `<section class="block"><h2>Analizando</h2>${busy.map(p => `<a class="proc" style="display:block;color:inherit;text-decoration:none" href="#/p/${p.id}"><div class="ms">${esc(p.name)}<span>${Math.round(p.progress || 0)}%</span></div>${stagesHtml(p)}<div class="mut small" style="margin-top:10px">${esc(p.message || "")}</div></a>`).join("")}</section>` : "") +
      (lv.length || waits.length ? `<section class="block"><h2>Directos que sigues</h2>${waits.map(p => `<a class="liveb activo" style="color:inherit;text-decoration:none" href="#/p/${p.id}"><i></i><div><b>${esc(p.name)}</b><span>${esc(p.message || "")}</span></div></a>`).join("")}${lv.map(s => `<a class="liveb ${s.status}" style="color:inherit;text-decoration:none" href="#/"><i></i><div><b>${esc(s.base)}</b><span>${esc(liveText(s))}</span></div></a>`).join("")}</section>` : "") +
      (running.length ? `<section class="block"><h2>En marcha</h2><div class="files">${running.map(j => `<div class="file">${th(j)}<span class="n">${esc(what(j))}<small>${tag(j)}${j.status === "en cola" ? ", en espera" : j.fps ? `, ${j.fps} fps` : ""}${esc(from(j))}</small><div class="line" style="margin-top:6px"><i style="width:${j.progress}%"></i></div></span><span class="num">${Math.round(j.progress)}%</span></div>`).join("")}</div></section>` : "") +
      (yt.length ? `<section class="block"><h2>YouTube</h2><div class="files" id="qyt">${ytRows(yt)}</div></section>` : "") +
      (bad.length ? `<section class="block"><h2>Con error</h2><div class="files">${bad.map(j => `<div class="file">${th(j)}<span class="n" style="white-space:normal">${esc(what(j))}<small>${tag(j)}</small><span class="err">${esc((j.error || "").slice(0, 400))}</span></span></div>`).join("")}</div></section>` : "") +
      (done.length ? `<section class="block"><h2>Terminado en esta sesión</h2><div class="files">${done.map(j => `<div class="file">${th(j)}<span class="n">${esc(j.file)}<small>${tag(j)}${esc(from(j))}</small></span><a class="btn sm" href="${j.kind === "download" ? `/api/downloads/file/${encodeURIComponent(j.file)}` : `/api/projects/${j.pid}/files/${encodeURIComponent(j.file)}`}" download>${icon("download", 15)}Guardar</a></div>`).join("")}</div></section>` : "") ||
      `<div class="empty">${icon("queue", 34)}<h2>No hay nada en marcha</h2><p>Aquí verás los análisis, las exportaciones y las descargas mientras trabajan. Puedes seguir editando: no se detienen.</p></div>`;
    if ($("#qyt")) ytBind($("#qyt"), () => { sig = ""; });
  });
}

// ------------------------------------------------------------ descargas
function descargas() {
  mount("tpl-descargas");
  const f = choice($("#dfmt")); f.value = "video"; let sig = "";
  $("#dform").onsubmit = async (e) => {
    e.preventDefault(); $("#derr").textContent = "";
    try { await api("/api/downloads", { method: "POST", json: { url: $("#durl").value, format: f.value } }); $("#durl").value = ""; toast("En la cola de descargas"); } catch (err) { $("#derr").textContent = err.message; }
  };
  every(1200, async () => {
    let js, done; try { [js, done] = await Promise.all([api("/api/jobs"), api("/api/downloads")]); } catch (e) { return; }
    const box = $("#dlist"); if (!box) return; const run = js.filter(j => j.kind === "download" && j.status !== "listo"), s = JSON.stringify([run, done]); if (s === sig) return; sig = s;
    box.innerHTML = run.map(j => `<div class="file"><span class="n">${esc(j.url)}${j.status === "error" ? `<span class="err" style="white-space:normal">${esc(j.error)}</span>` : `<small>${esc(j.status)}</small><div class="line" style="margin-top:6px"><i style="width:${j.progress}%"></i></div>`}</span><span class="num">${j.status === "error" ? "" : Math.round(j.progress) + "%"}</span></div>`).join("") +
      done.map(d => `<div class="file">${icon(d.format === "mp3" ? "rhythm" : "film", 18)}<span class="n">${esc(d.file)}<small>${d.format === "mp3" ? "MP3" : "Video"}, ${fmtLong(d.duration)}, ${fmtSize(d.size || 0)}</small></span><a class="btn sm" href="/api/downloads/file/${encodeURIComponent(d.file)}" download>${icon("download", 15)}Guardar</a></div>`).join("");
    $("#dnone").hidden = !!(run.length || done.length);
  });
}

// ------------------------------------------------------------ ajustes
const FIT = { gpu: "entero en tu GPU", auto: "Ollama decide si usa la GPU", mixto: "entre la GPU y el procesador: lento", cpu: "en el procesador: lento", no: "demasiado grande para este PC" };
function modelManager(changed) {
  const btn = $("#s-omore"), box = $("#s-omgr"); let sig = "", pulling = false, typed = "", note = "";
  const start = async (name) => {
    const m = await api("/api/ollama/lookup", { method: "POST", json: { model: name } });
    if (m.installed) throw new Error(`${m.name} ya está en este equipo.`);
    const extra = [m.fit === "no" ? "Es demasiado grande para este PC: puede no arrancar." : `Aquí iría ${FIT[m.fit]}.`, m.odd ? "Por su nombre parece hecho para otra cosa." : ""].filter(Boolean).join(" ");
    if (!(await ask({ title: `¿Descargar ${m.name}?`, text: `Son ${gbTxt(m.size)} desde ${m.name.startsWith("hf.co/") ? "Hugging Face" : "ollama.com"}, a ${m.dir}${m.free ? ` (${gbTxt(m.free)} libres)` : ""}. ${extra}`, ok: "Descargar" }))) return;
    await api("/api/ollama/pull", { method: "POST", json: { model: m.name } }); typed = ""; note = ""; sig = ""; draw();
  };
  const draw = async () => {
    if (box.hidden || !box.isConnected) return;
    let o; try { o = await api("/api/ollama"); } catch (e) { return; }
    if (!box.isConnected || box.hidden) return;
    if (pulling && !o.pull.on) changed(); pulling = o.pull.on;
    const k = JSON.stringify([o.installed, o.all, o.suggest, o.pull, o.use]); if (k === sig) return; sig = k;
    const inp = $("#s-oname"); if (inp) typed = inp.value; const foc = inp && document.activeElement === inp;
    const row = (m, act) => `<div class="mdl"><div><b>${esc(m.name)}</b><div class="mut small">${gbTxt(m.size)}, ${FIT[m.fit]}</div></div>${act}</div>`;
    if (!o.installed) { box.innerHTML = `<p class="mut">Primero instala Ollama: es gratis. <a href="https://ollama.com/download" target="_blank" rel="noopener">Descargar Ollama</a></p>`; return; }
    const p = o.pull;
    box.innerHTML = (p.on ? `<div class="mdls"><div class="mdl"><div><b>${esc(p.msg)} ${esc(p.model)}</b><div class="line" style="margin:6px 0 5px"><i style="width:${p.total ? p.done / p.total * 100 : 0}%"></i></div><div class="mut small">${gbTxt(p.done)} de ${gbTxt(p.total)}</div></div><button type="button" class="btn sm gh" data-stop>Detener</button></div></div>` : p.error ? `<p class="mdlh" style="color:var(--bad)">${esc(p.error)}</p>` : "")
      + (o.all.length ? `<p class="mdlh">En este equipo</p><div class="mdls">${o.all.map(m => row(m, `<button type="button" class="btn sm gh bad" data-del="${esc(m.name)}" data-size="${m.size}" aria-label="Borrar ${esc(m.name)}">Borrar</button>`)).join("")}</div>` : "")
      + (o.suggest.length ? `<p class="mdlh">Sugeridos</p><div class="mdls">${o.suggest.map(m => row(m, `<button type="button" class="btn sm" data-get="${esc(m.name)}" ${p.on ? "disabled" : ""} aria-label="Descargar ${esc(m.name)}">Descargar</button>`)).join("")}</div>` : "")
      + `<p class="mdlh">Otro modelo de Ollama o de Hugging Face</p><div class="addm"><input id="s-oname" type="text" placeholder="llama3.1:8b, hf.co/usuario/modelo-GGUF" autocomplete="off" spellcheck="false" aria-label="Nombre del modelo"><button type="button" class="btn" id="s-oget" ${p.on ? "disabled" : ""}>Revisar</button></div><p class="mut small" id="s-onote" role="status">${esc(note || "Antes de descargar te digo cuánto pesa y cómo iría en este PC.")}</p>`;
    const i = $("#s-oname"); i.value = typed; if (foc) i.focus(); i.oninput = (e) => e.stopPropagation();
    const go = guard(async () => { if (!i.value.trim()) return; const n = $("#s-onote"); n.textContent = "Consultando…"; try { await start(i.value); } catch (e) { note = e.message; $("#s-onote").textContent = e.message; $("#s-onote").style.color = "var(--bad)"; return; } const z = $("#s-onote"); if (z) z.textContent = ""; });
    $("#s-oget").onclick = go; i.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); if (!p.on) go(); } };
    $$("[data-get]", box).forEach(b => b.onclick = guard(() => start(b.dataset.get)));
    $$("[data-del]", box).forEach(b => b.onclick = guard(async () => {
      if (!(await ask({ title: `¿Borrar ${b.dataset.del}?`, text: `Libera hasta ${gbTxt(+b.dataset.size)}. Para volver a usarlo habría que descargarlo otra vez.`, ok: "Borrar", danger: true }))) return;
      await api("/api/ollama/delete", { method: "POST", json: { model: b.dataset.del } }); sig = ""; draw(); changed();
    }));
    const st = $("[data-stop]", box); if (st) st.onclick = guard(async () => { await api("/api/ollama/pull", { method: "DELETE" }); sig = ""; draw(); });
  };
  btn.onclick = () => { box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); sig = ""; draw(); };
  every(2000, draw);
}

function serverForm(s, dirty) {
  const url = $("#s-lurl"), mod = $("#s-lmodel"), key = $("#s-lkey"), ok = $("#s-lok"), box = $("#s-lfound"); let saved = s, clear = false;
  const short = (m) => /^([a-z]:)?[\\/]|\.gguf$/i.test(m) ? m.split(/[\\/]/).pop().replace(/\.gguf$/i, "").replace(/^(sha256-.{8}).*/, "$1") : m;
  const say = (t, cls = "") => { ok.textContent = t; ok.className = "small " + (cls || "mut"); };
  const fill = (ms, want) => { mod.innerHTML = `<option value="auto">Automático: el que esté cargado</option>` + [...new Set([...ms, ...(want === "auto" ? [] : [want])])].map(m => `<option value="${esc(m)}">${esc(short(m))}</option>`).join(""); mod.value = want; };
  const hint = () => { $("#s-lkeyhint").innerHTML = saved.has_local_key && !clear && url.value.trim() === saved.local_url ? `Guardada. <button type="button" class="lnk">Quitar</button>` : ""; const b = $("#s-lkeyhint button"); if (b) b.onclick = () => { clear = true; hint(); dirty(); }; };
  url.value = s.local_url; fill([], s.local_model); hint();
  // Fuera de este PC y de la red de casa: se confirma antes de mandar nada
  const allow = async () => {
    const u = url.value.trim(); if (!u) return { confirm: false };
    const c = await api("/api/servidor/check", { method: "POST", json: { url: u } });
    if (c.allowed) return { confirm: false };
    return await ask({ title: `¿Mandar el guion a ${c.host}?`, text: `Está fuera de este PC y de tu red. Ahí llegará la transcripción de cada video que analices.${c.secure ? "" : " Además, la dirección no usa https: iría sin cifrar."}`, ok: "Sí, usarlo" }) ? { confirm: true } : null;
  };
  url.addEventListener("input", () => { fill([], "auto"); say(""); hint(); });
  if (s.local_url) api("/api/equipo").then(e => { const v = e.server; if (url.value.trim() !== s.local_url || !url.isConnected) return; fill(v.models, s.local_model); say(v.on && v.use ? `Encendido: ${v.label}.` : v.error, v.on && v.use ? "ok" : "bad"); }).catch(() => {});
  $("#s-lscan").onclick = guard(async () => {
    say("Buscando…"); const { found } = await api("/api/servidor/scan", { method: "POST" }); if (!box.isConnected) return; box.hidden = !found.length;
    say(found.length ? "" : "No encontré ninguno encendido. ¿Activaste su servidor?");
    box.innerHTML = found.map((f, i) => `<button type="button" data-i="${i}"><b>${esc(f.name)}</b><span>${esc(f.url)}, ${f.locked ? "pide clave" : esc(plural(f.models.length, "modelo", "modelos"))}</span></button>`).join("");
    $$("button", box).forEach(b => b.onclick = () => { const f = found[+b.dataset.i]; url.value = f.url; fill(f.models, "auto"); box.hidden = true; hint(); dirty(); say("Pulsa «Probar» para comprobarlo."); });
  });
  $("#s-ltest").onclick = guard(async () => {
    if (!url.value.trim()) return say("Escribe la dirección o pulsa «Buscar en este PC».", "bad");
    const a = await allow(); if (!a) return;
    const want = mod.value; say("Probando…"); $("#s-ltest").disabled = true;
    try { const r = await api("/api/servidor/test", { method: "POST", json: { url: url.value.trim(), model: want, key: key.value.trim(), confirm: a.confirm } }); if (!ok.isConnected) return;
      if (r.models.length) fill(r.models, want); say(r.ok ? `Funciona: ${r.label} contestó en ${String(r.secs).replace(".", ",")} s.` : r.error, r.ok ? "ok" : "bad");
    } finally { $("#s-ltest") && ($("#s-ltest").disabled = false); }
  });
  return {
    body: async () => {
      const u = url.value.trim(), out = { local_url: u, local_model: mod.value || "auto", local_key: key.value.trim(), local_key_clear: clear && !key.value.trim() };
      if (u && u !== saved.local_url) { const a = await allow(); if (!a) return null; out.local_confirm = a.confirm; }
      return out;
    },
    saved: (r) => { saved = r; clear = false; key.value = ""; hint(); },
  };
}

async function ajustes() {
  const s = await api("/api/settings");
  if (!location.hash.startsWith("#/ajustes")) return;
  mount("tpl-ajustes");
  if (window.APP_VERSION) { $("#s-about").hidden = false; $("#s-ver").textContent = `${window.APP_NAME}, versión ${window.APP_VERSION}`; $("#s-author").textContent = window.APP_AUTHOR; $("#s-notice").textContent = window.APP_NOTICE; }
  updPanel($("#s-upd")); ytPanel($("#s-yt"));
  if (location.hash.endsWith("/youtube")) setTimeout(() => $("#s-ytsec") && $("#s-ytsec").scrollIntoView(), 350);
  if (window.APP_DONATE) { $("#s-cafe").hidden = false; $("#s-cafe a").href = window.APP_DONATE; }
  const dirty = () => { $("#s-ok").textContent = "Cambios sin guardar"; $("#s-ok").style.color = "var(--mut)"; };
  const engine = choice($("#s-engine"), dirty); engine.value = s.engine;
  $("#s-encoder").innerHTML = `<option value="auto">Automático</option>`; $("#s-encoder").value = "auto";
  let encSig = "";
  equipoPanel($("#s-equipo"), $("#s-eqfoot"), (e) => {
    const el = $("#s-encoder"), ks = Object.keys(e.encoder_names).filter(k => k === "cpu" || (e.encoders[k] || {}).ok || k === s.encoder), sig = ks.join(); if (!el || sig === encSig || document.activeElement === el) return;
    const cur = encSig ? el.value : s.encoder; encSig = sig;
    el.innerHTML = `<option value="auto">Automático</option>` + ks.map(k => `<option value="${k}">${esc(e.encoder_names[k])}</option>`).join(""); el.value = cur;
  });
  $("#s-model").value = s.model; $("#s-whisper").value = s.whisper_model; $("#s-odir").value = s.ollama_dir;
  const keyHint = (r) => $("#s-keyhint").textContent = r.has_key ? `Guardada: ${r.key_hint}` : "No hay ninguna guardada."; keyHint(s);
  $$("#sform input, #sform select").forEach(el => el.addEventListener("input", dirty));
  const sel = $("#s-omodel"), autoOpt = (n) => `<option value="auto">Automático${n ? `: ${esc(n)}` : ""}</option>`; sel.innerHTML = autoOpt("") + (s.ollama_model === "auto" ? "" : `<option value="${esc(s.ollama_model)}">${esc(s.ollama_model)}</option>`); sel.value = s.ollama_model;
  const loadOllama = (keep) => api("/api/ollama").then(o => {
    const el = $("#s-ollama-status"); if (!el) return; const was = keep ? sel.value : s.ollama_model;
    if (!o.installed) { el.textContent = s.ollama_dir ? `No encuentro Ollama en ${s.ollama_dir} ni en los lugares habituales.` : "No encuentro Ollama en este equipo."; return; }
    el.innerHTML = `<span style="color:var(--ok)">${o.running ? "Encendida" : "Instalada"}</span>${o.exe ? ` en ${esc(o.exe)}` : ""}, con ${plural(o.models.length, "modelo", "modelos")}.`;
    const all = [...o.models, ...o.others];
    sel.innerHTML = autoOpt(o.auto) + [...new Set([...o.models, ...(s.ollama_model === "auto" || all.includes(s.ollama_model) ? [] : [s.ollama_model])])].map(m => `<option value="${esc(m)}">${esc(m)}${all.includes(m) ? "" : " (no descargado)"}</option>`).join("")
      + (o.others.length ? `<optgroup label="Otros: quizá no sirvan para esto">${o.others.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join("")}</optgroup>` : ""); sel.value = was; if (!sel.value) { sel.value = "auto"; dirty(); }
  }).catch(() => {});
  loadOllama(); modelManager(() => loadOllama(true));
  const srv = serverForm(s, dirty);
  const fl = (k) => s.fonts[k] || k;
  const DEF_TEXT = {
    titulo: (v) => v.title_on === false ? "sin titular" : `${s.title_styles[v.title_style] || v.title_style}, letra ${fl(v.title_font)}, color ${v.title_color}, tamaño ${v.title_size}, altura ${Math.round(v.title_y / 19.2)} %`,
    subtitulos: (v) => v.subs_on === false ? "sin subtítulos" : `letra ${fl(v.font)}, color ${v.color}, tamaño ${v.sub_size}, altura ${Math.round(v.sub_y / 19.2)} %`,
    marca: (v) => v.brand && v.brand.length ? plural(v.brand.length, "sticker", "stickers") : "sin stickers", encuadre: (v) => modeText(v),
    estilo: (v) => [v.style === "dinamico" ? "dinámico" : "karaoke", v.remove_silence ? "quitar silencios" : "", v.filter && v.filter !== "ninguno" ? `filtro ${v.filter}` : ""].filter(Boolean).join(", "),
    opciones: (v) => `hasta ${v.max_clips} clips de ${v.min_len} a ${v.max_len} s, idioma ${v.language === "auto" ? "automático" : v.language}, descarga ${!v.download || v.download === "auto" ? "automática" : v.download + "p"}`,
  };
  const showDefs = async () => {
    const [d, fr] = await Promise.all([api("/api/defaults"), api("/api/folders")]); FOLDERS = fr.folders; const el = $("#s-defs"); if (!el) return;
    const scopes = [["", "Generales", d.general], ...FOLDERS.filter(f => d.carpetas[f.id]).map(f => [f.id, f.name, d.carpetas[f.id], f.color])];
    el.innerHTML = scopes.map(([id, name, g, color]) => { const n = Object.keys(g).length; return `<div class="defscope"><div class="defhead">${color ? `<i style="background:${esc(color)}"></i>` : ""}<b>${esc(name)}</b>${n ? `<button class="btn sm gh bad" data-f="${id}" data-g="" data-n="${esc(name)}">Quitar todos</button>` : ""}</div>
      ${n ? DEF_LABELS.filter(([k]) => g[k]).map(([k, l]) => `<div class="defrow"><span class="k">${l}</span><span>${esc(DEF_TEXT[k](g[k]))}</span><button class="btn sm gh sq" data-f="${id}" data-g="${k}" data-n="${esc(name)}" title="Quitar" aria-label="Quitar ${l}">${icon("close", 14)}</button></div>`).join("") : `<p class="mut small" style="margin-top:4px">Ninguno: se usan los de fábrica.</p>`}</div>`; }).join("");
    $$("button[data-f]", el).forEach(b => b.onclick = guard(async () => {
      const what = b.dataset.g ? `«${DEF_LABELS.find(([k]) => k === b.dataset.g)[1]}»` : "todos los predeterminados";
      if (!(await ask({ title: `¿Quitar ${what}?`, text: `De ${b.dataset.f ? `la carpeta «${b.dataset.n}»` : "los generales"}. Los clips que ya existen no cambian.`, ok: "Quitar", danger: true }))) return;
      await api(`/api/defaults?folder=${b.dataset.f}&group=${b.dataset.g}`, { method: "DELETE" }); showDefs();
    }));
  };
  showDefs();
  $("#sform").onsubmit = async (e) => {
    e.preventDefault();
    const body = { model: $("#s-model").value, whisper_model: $("#s-whisper").value, engine: engine.value, ollama_model: $("#s-omodel").value, ollama_dir: $("#s-odir").value.trim(), encoder: $("#s-encoder").value };
    const sb = await guard(srv.body)(); if (!sb) return; Object.assign(body, sb);
    if ($("#s-key").value.trim()) body.api_key = $("#s-key").value.trim();
    try { const r = await api("/api/settings", { method: "POST", json: body }); $("#s-ok").textContent = "Guardado"; $("#s-ok").style.color = ""; $("#s-key").value = ""; keyHint(r); srv.saved(r); sysBadge(); } catch (err) { toast(err.message, true); }
  };
}
