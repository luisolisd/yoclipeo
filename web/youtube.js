// YouTube: conectar en Ajustes, ventana para publicar y seguimiento de cada subida.
"use strict";

const YT_TERMS = "https://www.youtube.com/t/terms", G_PRIVACY = "https://policies.google.com/privacy", G_PERMS = "https://myaccount.google.com/permissions";
const YT_SEES = { private: "Privado", unlisted: "Oculto", public: "Público" };
const YT_ON = ["en cola", "exportando", "subiendo", "pausada"];
const ytExports = (ps, j) => j.kind === "export" && ps.some(p => p.status === "exportando" && p.pid === j.pid && p.cid === j.cid);   // esa exportación ya se cuenta como subida
const ext = (url, txt) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>`;
const ytDate = (d) => new Date(d).toLocaleString("es", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const ytLegal = () => `${ext(YT_TERMS, "Términos de YouTube")} y la ${ext(G_PRIVACY, "política de privacidad de Google")}`;

// ------------------------------------------------------------ Ajustes
const YT_STEPS = [
  `Entra al ${ext("https://console.cloud.google.com/auth/overview/personal", "modo personal de Google")} con la misma cuenta de tu canal. Crea un proyecto nuevo por ti.`,
  `En tipo de aplicación elige «App de escritorio», acepta los términos y pulsa «Continuar».`,
  `Pulsa «Descargar JSON» en ese momento: después Google ya no muestra la clave completa.`,
  `Con ese proyecto elegido arriba, abre ${ext("https://console.cloud.google.com/apis/library/youtube.googleapis.com", "YouTube Data API v3")} y pulsa «Habilitar».`,
  `Elige aquí el archivo y pulsa «Conectar con YouTube». Deja marcados los dos permisos.`];
const YT_NOTE = `No hace falta marca, dominio ni publicar la app. Solo funciona con la cuenta que la creó; si sale <b>client_user_mismatch</b>, entraste con otra.`;

// Abre Google para dar el permiso; con lists, también el de las listas de reproducción.
async function ytConnect(lists) {
  const w = window.open("about:blank", "_blank");          // se abre ya, para que el navegador no lo bloquee
  try { const { url } = await api("/api/youtube/connect", { method: "POST", json: { lists: !!lists } }); if (w) { w.opener = null; w.location.replace(url); } else location.assign(url); }
  catch (e) { if (w) w.close(); throw e; }
}
const YT_LISTS = "Para agregar tus videos a una lista de reproducción, Google pide un permiso más amplio: administrar tu cuenta de YouTube. Con él solo se leen tus listas y se agregan los videos que subas desde aquí.";

function ytPanel(el) {
  let sig = "", waiting = 0, open = false;
  const load = async () => { let s; try { s = await api("/api/youtube"); } catch (e) { return; } if (el.isConnected) draw(s); };
  const connect = guard(async (lists) => { await ytConnect(lists); waiting = Date.now(); sig = ""; load(); });
  const off = guard(async (full) => {
    if (full && !(await ask({ title: "¿Desconectar YouTube?", text: "Se quita el permiso en Google y se borra de este PC, junto con el archivo de tu app. Los videos que ya subiste se quedan en tu canal.", ok: "Desconectar", danger: true }))) return;
    const r = await api("/api/youtube/disconnect", { method: "POST" }); if (r.note) toast(r.note, true); waiting = 0; sig = ""; load();
  });
  const file = guard(async (inp) => {
    const f = inp.files[0]; if (!f) return;
    let j = null; try { if (f.size < 20000) j = JSON.parse(await f.text()); } catch (e) {} finally { inp.value = ""; }
    if (j && j.web) throw new Error("Ese archivo es de una app web. Crea un cliente de tipo «App de escritorio».");
    if (!j || !j.installed) throw new Error("Ese no es el archivo JSON de un cliente de Google.");
    await api("/api/youtube/client", { method: "POST", json: { id: j.installed.client_id, key: j.installed.client_secret } }); sig = ""; load();
  });
  function draw(s) {
    if (s.connected || s.error) waiting = 0;
    const k = JSON.stringify([s, !!waiting]); if (k === sig) return; sig = k;
    const d = $("details", el); if (d) open = d.open;
    const pick = (t, cls) => `<label class="btn ${cls}" tabindex="0" role="button">${t}<input type="file" accept=".json,application/json" hidden></label>`;
    const ch = s.channel;
    el.innerHTML = s.connected ? `<div class="ytch"><i class="on"></i><div><b>${esc(ch.title)}</b><span class="mut small">${esc(ch.handle || "Conectado")}</span></div><button type="button" class="btn sm gh bad" data-off>Desconectar</button></div>
        ${s.lists ? `<p class="mut small">Puedes elegir una lista de reproducción al publicar.</p>` : `<p class="mut small">${YT_LISTS}</p>${s.error ? `<p class="err">${esc(s.error)}</p>` : ""}<div class="eqfoot"><button type="button" class="btn sm" data-lists>Activar listas</button></div>`}
        <p class="mut small">También puedes quitar el permiso en ${ext(G_PERMS, "tu cuenta de Google")}.</p>`
      : s.configured ? `<div class="ytch"><i class="${s.expired ? "warn" : ""}"></i><div><b>${s.expired ? "El permiso caducó o se quitó" : "Falta conectar tu canal"}</b><span class="mut small">${waiting ? "Termina en la pestaña de Google…" : s.expired ? "Vuelve a conectar para seguir publicando." : "Tu app de Google ya está guardada."}</span></div></div>
        ${s.error ? `<p class="err" style="margin-bottom:10px">${esc(s.error)}</p>` : ""}<div class="eqfoot"><button type="button" class="btn pri" data-on>${s.expired ? "Volver a conectar" : "Conectar con YouTube"}</button>${s.expired ? `<button type="button" class="btn gh" data-off>Desconectar</button>` : `<button type="button" class="btn gh" data-clear>Usar otra app</button>`}</div>`
      : `<div class="eqfoot">${pick("Elegir el archivo de tu app", "pri")}</div>`;
    if (!s.connected) el.innerHTML += `<details class="ythow"${open || !s.configured ? " open" : ""}><summary>Cómo conseguir ese archivo</summary><ol>${YT_STEPS.map(x => `<li>${x}</li>`).join("")}</ol><p class="hint">${YT_NOTE}</p></details>
        <p class="mut small">Con esto, ${esc(window.APP_NAME)} podrá subir videos a tu canal y ver cómo quedaron. El permiso se guarda cifrado en este PC y no pasa por ningún otro servidor. Al conectar aceptas los ${ytLegal()}.</p>`;
    const on = $("[data-on]", el), o = $("[data-off]", el), c = $("[data-clear]", el), inp = $("input[type=file]", el);
    const li = $("[data-lists]", el); if (li) li.onclick = () => connect(true);
    if (on) on.onclick = () => connect(s.lists); if (o) o.onclick = () => off(true); if (c) c.onclick = () => off(false);
    if (inp) { inp.onchange = () => file(inp); inp.parentElement.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inp.click(); } }; }
  }
  every(2500, load);
}

// ------------------------------------------------------------ portada
// Pinta en `pic` el fotograma del segundo x.cover y deja escoger otro con la barra. Las imágenes se piden de una en una.
let coverLine = Promise.resolve();
const coverName = (t) => t ? `Segundo ${t.toFixed(1)}` : "Primer fotograma";
const coverBar = (x) => `<label class="fld"><span class="lb"><span>Portada</span><output data-cvn>${coverName(x.cover)}</output></span><input type="range" data-cv min="0" max="${Math.max(.1, x.dur).toFixed(1)}" step="0.1" value="${x.cover}" aria-label="Momento de la portada"></label>`;
function coverPick(box, pic, x, pid, cid, fail) {
  const r = $("[data-cv]", box), out = $("[data-cvn]", box); let want = 0, t;
  const show = () => {
    const me = ++want; pic.classList.add("wait");
    coverLine = coverLine.then(async () => {
      if (me !== want || !pic.isConnected) return;
      try {
        const q = await fetch(`/api/projects/${pid}/clips/${cid}/portada?t=${x.cover}`); if (!q.ok) throw new Error(((await q.json().catch(() => ({}))).detail) || "No se pudo leer el fotograma.");
        const dur = +q.headers.get("X-Duration"), u = URL.createObjectURL(await q.blob());
        if (dur > 0 && r) { r.max = Math.max(.1, dur - .1).toFixed(1); if (x.cover > +r.max) { x.cover = +r.max; out.textContent = coverName(x.cover); } }
        if (me === want && pic.isConnected) { if (x.url) URL.revokeObjectURL(x.url); x.url = u; pic.style.backgroundImage = `url('${u}')`; } else URL.revokeObjectURL(u);
      } catch (e) { if (me === want && fail) fail(e.message); }
      if (me === want) pic.classList.remove("wait");
    });
  };
  if (r) r.oninput = () => { x.cover = +r.value; out.textContent = coverName(x.cover); clearTimeout(t); t = setTimeout(show, 180); };
  if (x.url) pic.style.backgroundImage = `url('${x.url}')`; else show();
}

async function ytCover(p) {                    // poner o cambiar la portada de un video ya subido
  const pr = await api(`/api/projects/${p.pid}`), c = (pr.clips || []).find(y => y.id === p.cid); if (!c) throw new Error("Ese clip ya no existe en el proyecto.");
  const x = { cover: p.cover || 0, dur: c.end - c.start }, d = document.createElement("dialog"); d.className = "dlg cvd";
  d.innerHTML = `<div class="in"><h2>Portada en YouTube</h2><div class="cvbox"><i class="cvp" role="img" aria-label="Portada"></i><div><p class="mut small">${esc(p.title)}</p>${coverBar(x)}<p class="mut small">Se toma del clip como está ahora. Puede tardar un rato en verse en YouTube.</p><div class="err" role="alert"></div></div></div></div><div class="acts"><button type="button" class="btn gh" data-no>Cancelar</button><button type="button" class="btn pri" data-yes>Poner portada</button></div>`;
  return new Promise(res => {
    let ok = false; const err = $(".err", d);
    d.onclose = () => { if (x.url) URL.revokeObjectURL(x.url); d.remove(); res(ok); }; $("[data-no]", d).onclick = () => d.close();
    $("[data-yes]", d).onclick = async (e) => { const b = e.currentTarget; b.disabled = true; err.textContent = ""; try { await api(`/api/publicaciones/${p.id}/portada`, { method: "POST", json: { t: x.cover } }); ok = true; d.close(); toast("La portada va en camino"); } catch (e2) { err.textContent = e2.message; b.disabled = false; } };
    document.body.appendChild(d); d.showModal(); coverPick(d, $(".cvp", d), x, p.pid, p.cid, m => err.textContent = m);
  });
}

// ------------------------------------------------------------ publicar uno o varios clips
const toLocal = (d) => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

async function ytPublish(pid, clips) {
  const [yt, mine] = await Promise.all([api("/api/youtube"), api(`/api/publicaciones?pid=${pid}`)]);
  if (!yt.connected) {
    if (await ask({ title: yt.expired ? "El permiso de YouTube caducó" : "Conecta tu canal de YouTube", text: yt.expired ? "Vuelve a conectar en Ajustes para publicar." : "Se hace una sola vez, en Ajustes.", ok: "Ir a Ajustes" })) location.hash = "#/ajustes/youtube";
    return false;
  }
  if (clips.length > 50) throw new Error("Elige hasta 50 clips a la vez.");
  const before = (c) => mine.find(p => p.cid === c.id && (p.video || YT_ON.includes(p.status)));
  clips = [...clips].sort((a, b) => a.start - b.start);      // en lote, en el orden del video
  let list = clips.map(c => ({ c, title: (c.title || "").replace(/[<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 100), desc: (c.description || "").replace(/[<>]/g, ""), tags: (c.hashtags || []).map(t => t.startsWith("#") ? t : "#" + t).join(" "), old: before(c), cover: 0, dur: c.end - c.start }));
  const start = new Date(Date.now() + 3600e3); start.setMinutes(0, 0, 0); start.setHours(start.getHours() + 1);
  const d = document.createElement("dialog"); d.className = "sheet pub";
  d.innerHTML = `<header><h2>Publicar en YouTube</h2><button type="button" class="btn gh sq" data-x aria-label="Cerrar">${icon("close", 18)}</button></header>
    <div class="scroll"><div class="ytch"><i class="on"></i><div><b>${esc(yt.channel.title)}</b><span class="mut small">${esc(yt.channel.handle || "Tu canal")}</span></div></div>
      ${yt.first ? `<p class="pubnote">Es tu primera publicación. Sugerencia: sube un clip en privado y revisa cómo queda.</p>` : ""}
      ${clips.length > 1 ? `<p class="mut small">Se suben en el orden del video, del primero al último.</p>` : ""}
      <div data-list></div>
      <label class="chk"><input type="checkbox" data-cov> <span>Poner esta portada en YouTube</span></label><p class="mut small" style="margin:0 0 18px" data-covx></p>
      <div data-favs></div>
      <h3>Quién puede verlo</h3><div class="seg" data-see data-value="private"><button data-v="private">Privado</button><button data-v="unlisted">Oculto</button><button data-v="public">Público</button><button data-v="plan">Programado</button></div>
      <div data-plan hidden style="margin-top:14px"><div class="two"><label class="fld"><span class="lb" data-wl>Fecha y hora</span><input type="datetime-local" data-when></label><label class="fld" data-gapf><span class="lb">Uno cada (horas)</span><input type="number" data-gap min="1" max="336" step="1" value="24"></label></div></div>
      <p class="mut small" data-seetx style="margin:8px 0 18px"></p>
      <h3>¿Está hecho para niños?</h3><div class="seg" data-kids data-value=""><button data-v="no">No</button><button data-v="si">Sí</button></div><p class="mut small" style="margin:8px 0 14px">YouTube obliga a decirlo. Si es para niños, quita comentarios y otras funciones.</p>
      <label class="chk"><input type="checkbox" data-syn> <span>Muestra cosas realistas hechas o alteradas con IA</span></label>
      <label class="chk" data-notf><input type="checkbox" data-not checked> <span>Avisar a los suscriptores</span></label>
      <label class="fld" style="margin-top:12px"><span class="lb">Categoría</span><select data-cat>${Object.entries(yt.categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <div data-plists></div>
      <p class="mut small">Se sube en 1080p; si hace falta, primero se exporta. Al publicar aceptas los ${ytLegal()}.</p></div>
    <footer><div class="err" role="alert"></div><button type="button" class="btn pri lg" data-go></button></footer>`;
  const err = $(".err", d), see = choice($("[data-see]", d), () => { sync(); sure(); }), kids = choice($("[data-kids]", d), () => err.textContent = ""), when = $("[data-when]", d), gap = $("[data-gap]", d);
  see.value = pref.get("yt-ve", "private"); if (yt.first || !["private", "unlisted", "public", "plan"].includes(see.value)) see.value = "private";
  let knows = !yt.first;                     // la primera vez, antes de que lo vea cualquiera, se pregunta
  async function sure() {
    if (knows || !["public", "plan"].includes(see.value)) return;
    const plan = see.value === "plan", yes = await ask({ title: "¿Estás seguro?", text: `Es tu primera publicación y la podrá ver cualquiera${plan ? " cuando llegue la hora" : ""}. Te sugerimos subir primero un clip en privado.`, ok: plan ? "Sí, programar" : "Sí, en público", no: "Mejor en privado" });
    if (yes) knows = true; else { see.value = "private"; sync(); }
  }
  when.value = toLocal(start); when.min = toLocal(new Date()); gap.value = pref.get("yt-horas", "24"); $("[data-cat]", d).value = pref.get("yt-cat", "24"); if (!$("[data-cat]", d).value) $("[data-cat]", d).value = "24";
  const at = (i) => { const t = new Date(when.value); return isNaN(t) ? null : new Date(+t + i * Math.max(1, +gap.value || 24) * 3600e3); };
  const verb = () => { const n = list.length, o = n > 1 ? ` ${n} clips` : ""; return see.value === "plan" ? "Programar" + o : see.value === "public" ? "Publicar" + o : `Subir${o} ${see.value === "private" ? "en privado" : "como oculto"}`; };
  const pls = $("[data-plists]", d), prefList = `yt-lista-${yt.channel.id}`;
  let picked = { id: "", title: "" };
  function offerLists(msg) {
    pls.innerHTML = `<p class="lb" style="margin:12px 0 6px">Lista de reproducción</p><p class="mut small">${YT_LISTS}</p>${msg ? `<p class="err">${esc(msg)}</p>` : ""}<div class="eqfoot"><button type="button" class="btn sm" data-lists>Activar listas</button></div>`;
    $("[data-lists]", pls).onclick = async (e) => {
      const b = e.currentTarget;
      try {
        await ytConnect(true); b.textContent = "Termina en la pestaña de Google…"; b.disabled = true;
        const end = Date.now() + 900e3, look = async () => {
          if (!d.isConnected) return;
          let s = null; try { s = await api("/api/youtube"); } catch (e) {}
          if (s && s.lists) return showLists();
          if (s && s.error || Date.now() > end) return offerLists(s && s.error || "No se completó el permiso.");
          setTimeout(look, 2000);
        };
        setTimeout(look, 2000);
      } catch (e2) { offerLists(e2.message); }
    };
  }
  async function showLists() {
    pls.innerHTML = `<label class="fld" style="margin-top:12px"><span class="lb">Lista de reproducción</span><select data-pl><option value="">Ninguna</option></select></label><p class="mut small" data-plx></p>`;
    const sel = $("[data-pl]", pls), tx = $("[data-plx]", pls);
    const fill = async () => {
      sel.disabled = true; tx.textContent = "Buscando tus listas…";
      try {
        const ls = await api("/api/youtube/listas"), want = sel.value || pref.get(prefList, "");
        sel.innerHTML = `<option value="">Ninguna</option>` + ls.map(l => `<option value="${esc(l.id)}">${esc(l.title)} (${plural(l.count, "video", "videos")})</option>`).join("");
        sel.value = ls.some(l => l.id === want) ? want : "";
        sel.onchange = () => { const l = ls.find(x => x.id === sel.value); picked = l ? { id: l.id, title: l.title } : { id: "", title: "" }; }; sel.onchange();
        tx.innerHTML = `${ls.length ? "¿Falta alguna? Créala" : "Tu canal no tiene listas. Crea una"} en ${ext(`https://studio.youtube.com/channel/${encodeURIComponent(yt.channel.id)}/playlists`, "YouTube Studio")} y <button type="button" class="lnk" data-re>actualiza</button>.`;
      } catch (e) { picked = { id: "", title: "" }; sel.value = ""; tx.innerHTML = `<span class="err">${esc(e.message)}</span> <button type="button" class="lnk" data-re>Reintentar</button>`; }
      sel.disabled = false; $("[data-re]", tx).onclick = fill;
    };
    fill();
  }
  function sync() {
    const plan = see.value === "plan", many = list.length > 1;
    $("[data-plan]", d).hidden = !plan; $("[data-gapf]", d).hidden = !many; $("[data-wl]", d).textContent = many ? "El primero sale" : "Fecha y hora";
    $("[data-notf]", d).hidden = !(plan || see.value === "public");
    $("[data-seetx]", d).textContent = { private: "Solo tú lo ves. Puedes cambiarlo luego en YouTube Studio.", unlisted: "Lo ve quien tenga el enlace.", public: "Lo ve cualquiera en cuanto YouTube termine de procesarlo.", plan: "Se sube ahora en privado. Ya subido, YouTube lo publica a esa hora aunque este PC esté apagado." }[see.value];
    $("[data-go]", d).textContent = verb();
    $$("[data-at]", d).forEach(e => { const t = plan && many && at(+e.dataset.at); e.hidden = !t; e.textContent = t ? `Sale ${ytDate(t)}` : ""; });
  }
  function cards() {
    $("[data-list]", d).innerHTML = list.map((x, i) => `<div class="pubc" data-i="${i}"><i class="cvp"></i><div>
        ${list.length > 1 ? `<p class="mut small" style="margin:0 0 4px">${i + 1} de ${list.length}, en ${fmt(x.c.start)} del video</p>` : ""}<label class="fld"><span class="lb"><span>Título</span><output data-n></output></span><input type="text" maxlength="100" data-f="title" value="${esc(x.title)}"></label>
        ${list.length > 1 ? `<details><summary>Portada, descripción y hashtags</summary>` : ""}${coverBar(x)}<label class="fld"><span class="lb">Descripción</span><textarea rows="${list.length > 1 ? 2 : 3}" maxlength="4500" data-f="desc">${esc(x.desc)}</textarea></label><label class="fld"><span class="lb">Hashtags</span><input type="text" maxlength="400" data-f="tags" value="${esc(x.tags)}"></label>${list.length > 1 ? "</details>" : ""}
        ${x.old ? `<p class="small pubold">${x.old.video ? `Ya lo subiste el ${ytDate(x.old.created * 1000)}` : "Ya se está subiendo"}: saldría repetido.</p>` : ""}<p class="small pubat" data-at="${i}" hidden></p></div>
        ${list.length > 1 ? `<button type="button" class="btn gh sq sm" data-rm aria-label="Quitar de la lista">${icon("close", 14)}</button>` : ""}</div>`).join("");
    $$(".pubc", d).forEach(el => {
      const x = list[+el.dataset.i], n = $("[data-n]", el), cnt = () => n.textContent = `${x.title.length}/100`; cnt();
      $$("[data-f]", el).forEach(f => f.oninput = () => { x[f.dataset.f] = f.value; cnt(); err.textContent = ""; if (f.dataset.f === "tags") paintFavs(); });
      coverPick(el, $(".cvp", el), x, pid, x.c.id);
      const rm = $("[data-rm]", el); if (rm) rm.onclick = () => { list = list.filter(y => y !== x); cards(); };
    });
    paintFavs(); sync();
  }
  const cov = $("[data-cov]", d), covs = () => { d.classList.toggle("nocov", !cov.checked); $("[data-covx]", d).innerHTML = cov.checked ? `YouTube la pone al terminar de procesar. Tu cuenta debe estar ${ext("https://www.youtube.com/verify", "verificada")}.` : "YouTube escogerá un fotograma."; };
  cov.checked = pref.get("yt-portada", "si") === "si"; cov.onchange = covs; covs();
  // hashtags favoritos: un clic los pone (o los quita) en todos los clips de la ventana
  const favs = $("[data-favs]", d), tagsOf = (x) => x.tags.split(/[\s,]+/).filter(Boolean).map(t => "#" + t.replace(/^#+/, "")), low = (t) => t.toLowerCase();
  const has = (x, t) => tagsOf(x).some(y => low(y) === low(t)), all = (t) => list.length > 0 && list.every(x => has(x, t));
  let F = { fav: [], used: [] }, editing = false;
  function putTags(ts, on) {
    let full = false;
    for (const x of list) for (const t of ts) {
      if (on && !has(x, t)) { const v = [...tagsOf(x), t].join(" "); if (v.length > 400) full = true; else x.tags = v; }
      if (!on) x.tags = tagsOf(x).filter(y => low(y) !== low(t)).join(" ");
    }
    $$(".pubc", d).forEach(el => $('[data-f="tags"]', el).value = list[+el.dataset.i].tags);
    err.textContent = full ? "Ya no caben más hashtags en uno de los clips." : ""; paintFavs();
  }
  let turn = 0, line = Promise.resolve();
  function saveFavs(l) {                     // se ve al momento; los guardados van uno tras otro para que no se pisen
    const me = ++turn, seen = new Set(), was = F;
    F = { ...F, fav: l.map(t => "#" + t.replace(/[^\p{L}\p{N}_]/gu, "")).filter(t => t.length > 1 && !seen.has(low(t)) && seen.add(low(t))) };
    const fav = F.fav; err.textContent = ""; paintFavs();
    line = line.then(async () => {
      try { const r = await api("/api/hashtags", { method: "PUT", json: { fav } }); if (me === turn) F = r; }
      catch (e) { if (me === turn) F = was; err.textContent = e.message; }
      if (me === turn) paintFavs();
    });
  }
  function paintFavs() {
    const inp = $("[data-new]", favs), typed = inp ? inp.value : "", focus = inp && document.activeElement === inp, many = list.length > 1;
    const chip = (t) => editing ? `<button type="button" data-del="${esc(t)}" aria-label="Quitar ${esc(t)} de tus favoritos">${esc(t)}<small>✕</small></button>` : `<button type="button" data-t="${esc(t)}" class="${all(t) ? "on" : ""}" aria-pressed="${all(t)}">${esc(t)}</button>`;
    const mine = list.length === 1 ? tagsOf(list[0]).filter(t => !F.fav.some(f => low(f) === low(t))) : [];
    favs.innerHTML = `<h3>Hashtags favoritos</h3>
      ${F.fav.length ? `<div class="chips">${F.fav.map(chip).join("")}</div><div class="favact">${editing ? "" : `<button type="button" class="lnk" data-all>${F.fav.every(all) ? "Quitar todos" : "Poner todos"}</button>`}<button type="button" class="lnk" data-edit>${editing ? "Listo" : "Editar"}</button></div>` : `<p class="mut small">Guarda los que más usas y ponlos con un clic${many ? " en todos los clips" : ""}.</p>`}
      ${!editing && F.used.length ? `<p class="mut small favsub">Los que más repites</p><div class="chips">${F.used.map(chip).join("")}</div>` : ""}
      <div class="favnew"><input type="text" data-new maxlength="200" placeholder="#hashtag" aria-label="Hashtag para guardar en favoritos" value="${esc(typed)}"><button type="button" class="btn sm" data-add>Guardar</button></div>
      ${mine.length ? `<button type="button" class="lnk" data-mine>Guardar los de este clip (${mine.length})</button>` : ""}`;
    $$("[data-t]", favs).forEach(b => b.onclick = () => putTags([b.dataset.t], !all(b.dataset.t)));
    $$("[data-del]", favs).forEach(b => b.onclick = () => { const l = F.fav.filter(t => t !== b.dataset.del); if (!l.length) editing = false; saveFavs(l); });
    const on = (k, fn) => { const b = $(`[data-${k}]`, favs); if (b) b.onclick = fn; };
    on("all", () => putTags(F.fav, !F.fav.every(all))); on("edit", () => { editing = !editing; paintFavs(); }); on("mine", () => saveFavs([...F.fav, ...mine]));
    const i2 = $("[data-new]", favs), add = () => { const l = i2.value.split(/[\s,]+/).filter(Boolean); if (l.length) { i2.value = ""; saveFavs([...F.fav, ...l]); } };
    on("add", add); i2.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }; if (focus) i2.focus();
  }
  api("/api/hashtags").then(r => { F = r; paintFavs(); }).catch(() => {});
  when.oninput = gap.oninput = sync; $("[data-x]", d).onclick = () => d.close();
  let sent = false, over; const seenC = new Map(list.map(x => [x.c.id, x]));
  const done = new Promise(r => over = r);
  d.onclose = () => { clips.forEach(c => { const x = seenC.get(c.id); if (x && x.url) URL.revokeObjectURL(x.url); }); d.remove(); over(sent); };
  $("[data-go]", d).onclick = async (e) => {
    const btn = e.currentTarget; err.textContent = "";
    try {
      const plan = see.value === "plan";
      for (const x of list) { if (!x.title.trim()) throw new Error("Falta un título."); if (/[<>]/.test(x.title + x.desc + x.tags)) throw new Error("YouTube no acepta los signos < ni >."); }
      if (!kids.value) throw new Error("Di si está hecho para niños.");
      if (plan && !at(0)) throw new Error("Elige la fecha y la hora.");
      const rep = list.filter(x => x.old).length, one = list.length === 1;
      const how = plan ? (one ? `Se publicará el ${ytDate(at(0))}.` : `Del ${ytDate(at(0))} al ${ytDate(at(list.length - 1))}, uno cada ${gap.value} h.`) : see.value === "public" ? `Cualquiera podrá ${one ? "verlo" : "verlos"}.` : see.value === "unlisted" ? `${one ? "Lo" : "Los"} verá quien tenga el enlace.` : `Solo tú podrás ${one ? "verlo" : "verlos"}.`;
      if (!(await ask({ title: `¿${verb()}?`, text: `${one ? `«${list[0].title.trim()}»` : plural(list.length, "clip", "clips")} en el canal ${yt.channel.title}. ${how}${one ? "" : " En el orden del video."}${picked.id ? ` ${one ? "Se agrega" : "Se agregan"} a la lista «${picked.title}».` : ""}${rep ? ` ${rep === 1 ? "Uno ya se había subido: saldrá" : `${rep} ya se habían subido: saldrán`} ${rep === 1 ? "repetido" : "repetidos"}.` : ""}`, ok: verb() }))) return;
      btn.disabled = true;
      const items = list.map((x, i) => { const h = x.tags.trim().split(/[\s,]+/).filter(Boolean).map(t => t.startsWith("#") ? t : "#" + t); return { pid, cid: x.c.id, title: x.title.trim(), description: [x.desc.trim(), h.join(" ")].filter(Boolean).join("\n\n"), tags: h.map(t => t.slice(1)), privacy: plan ? "private" : see.value, publish_at: plan ? at(i).toISOString() : "", again: !!x.old, cover: cov.checked ? x.cover : null }; });
      await api("/api/publicaciones", { method: "POST", json: { channel: yt.channel.id, kids: kids.value === "si", synthetic: $("[data-syn]", d).checked, notify: $("[data-not]", d).checked, category: $("[data-cat]", d).value, playlist: picked.id, items } });
      if ($("[data-pl]", d)) pref.set(prefList, picked.id);
      if (!yt.first) pref.set("yt-ve", see.value); pref.set("yt-portada", cov.checked ? "si" : "no"); pref.set("yt-horas", gap.value); pref.set("yt-cat", $("[data-cat]", d).value);
      sent = true; d.close(); toast(one ? "En la cola para YouTube" : `${list.length} clips en la cola para YouTube`);
    } catch (e2) { err.textContent = e2.message; btn.disabled = false; }
  };
  document.body.appendChild(d); paintIcons(d); cards(); yt.lists ? showLists() : offerLists(); d.showModal();
  return done;
}

// ------------------------------------------------------------ seguimiento
function ytState(p) {
  if (p.status === "en cola") return "En espera";
  if (p.status === "exportando") return `Exportando, ${Math.round(p.progress)} %`;
  if (p.status === "subiendo") return `Subiendo, ${Math.round(p.progress)} %`;
  if (p.status === "procesando") return "Subido; YouTube lo está procesando";
  if (p.status === "pausada") return `En pausa, sigue el ${ytDate(p.resume_at * 1000)}`;
  if (p.status === "cancelada") return "Cancelada";
  if (p.status === "error") return "No se publicó";
  if (p.publish_at) return new Date(p.publish_at) > new Date() ? `Programado para el ${ytDate(p.publish_at)}` : `Publicado el ${ytDate(p.publish_at)}`;
  return p.note ? p.note : p.privacy === "public" ? "Publicado" : p.privacy === "unlisted" ? "Subido como oculto" : "Subido en privado";
}
const ytSig = (ps) => JSON.stringify(ps.map(p => [p.id, p.status, p.progress, p.error, p.hidden, p.listed, p.resume_at, p.cover_state, p.cover_error]));
function ytRows(ps) {
  return ps.map(p => {
    const on = YT_ON.includes(p.status), pub = p.video && !p.publish_at && p.privacy !== "private" && !p.note;
    const cvOk = p.video && ["procesando", "lista"].includes(p.status);
    return `<div class="file ytf" data-pub="${p.id}"><i style="background-image:url('/api/projects/${p.pid}/thumb/${p.cid}')"></i><span class="n"${p.error ? ` style="white-space:normal"` : ""}><span title="${esc(p.title)}">${esc(p.title)}</span><small>${esc(ytState(p))}${p.channel ? ` · ${esc(p.channel.title)}` : ""}${p.playlist && p.playlist.id ? ` · ${p.listed === "si" ? "En la lista" : p.listed === "pendiente" ? "Agregando a la lista" : "Lista"} «${esc(p.playlist.title)}»` : ""}${cvOk ? { si: " · Portada puesta", pendiente: " · Portada en camino" }[p.cover_state] || "" : ""}</small>${cvOk && p.cover_error ? `<span class="${p.cover_state === "no" ? "err" : "mut small"}">${p.cover_state === "no" ? "Portada: " : ""}${esc(p.cover_error)}</span>` : ""}${p.listed === "no" ? `<span class="err">No entró a la lista: ${esc(p.list_error || "")}</span>` : ""}${p.error ? `<span class="err">${esc(p.error)}</span>` : ""}${p.status === "pausada" ? `<span class="mut small" style="white-space:normal">${esc(p.pause || "")} Sigue solo si ${esc(window.APP_NAME)} está abierto.</span>` : on ? `<div class="line" style="margin-top:6px"><i style="width:${p.progress}%"></i></div>` : ""}</span>
      ${cvOk ? `<button class="btn sm gh" data-cover>${p.cover_state === "si" ? "Cambiar portada" : "Poner portada"}</button>` : ""}${p.video ? `<a class="btn sm" href="${pub ? `https://youtu.be/${encodeURIComponent(p.video)}` : `https://studio.youtube.com/video/${encodeURIComponent(p.video)}/edit`}" target="_blank" rel="noopener noreferrer">${pub ? "Ver" : "Abrir en Studio"}</a>` : ""}${p.listed === "no" ? `<button class="btn sm" data-do="lista">Reintentar la lista</button>` : ""}${!p.video && ["error", "cancelada", "pausada"].includes(p.status) ? `<button class="btn sm" data-do="reintentar">${p.status === "pausada" ? "Seguir ya" : "Reintentar"}</button>` : ""}${on ? `<button class="btn sm gh" data-do="cancelar">${p.stop ? "Cancelando…" : "Cancelar"}</button>` : `<button class="btn sm gh sq" data-do="quitar" aria-label="Quitar de la lista" title="Quitar de la lista">${icon("close", 14)}</button>`}</div>`;
  }).join("");
}
function ytBind(box, again) {
  $$("[data-cover]", box).forEach(b => b.onclick = guard(async () => {
    const i = b.closest("[data-pub]").dataset.pub, p = (await api("/api/publicaciones")).find(y => y.id === i);
    if (p && await ytCover(p)) again();
  }));
  $$("[data-do]", box).forEach(b => b.onclick = guard(async () => {
    const i = b.closest("[data-pub]").dataset.pub;
    if (b.dataset.do === "cancelar" && !(await ask({ title: "¿Cancelar esta subida?", text: "No quedará nada en tu canal.", ok: "Cancelar la subida", danger: true }))) return;
    b.disabled = true; await api(`/api/publicaciones/${i}/${b.dataset.do}`, { method: "POST" }); again();
  }));
}
