// YouTube: conectar en Ajustes, ventana para publicar y seguimiento de cada subida.
"use strict";

const YT_TERMS = "https://www.youtube.com/t/terms", G_PRIVACY = "https://policies.google.com/privacy", G_PERMS = "https://myaccount.google.com/permissions";
const YT_SEES = { private: "Privado", unlisted: "Oculto", public: "Público" };
const YT_ON = ["en cola", "exportando", "subiendo"];
const ext = (url, txt) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>`;
const ytDate = (d) => new Date(d).toLocaleString("es", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const ytLegal = () => `${ext(YT_TERMS, "Términos de YouTube")} y la ${ext(G_PRIVACY, "política de privacidad de Google")}`;

// ------------------------------------------------------------ Ajustes
const YT_STEPS = [
  `Entra a ${ext("https://console.cloud.google.com/projectcreate", "Google Cloud")} con la cuenta de tu canal y crea un proyecto.`,
  `Abre ${ext("https://console.cloud.google.com/apis/library/youtube.googleapis.com", "YouTube Data API v3")} y pulsa «Habilitar».`,
  `En ${ext("https://console.cloud.google.com/auth/overview", "Google Auth Platform")} pulsa «Comenzar», pon un nombre, tu correo y público «Externo».`,
  `En ${ext("https://console.cloud.google.com/auth/audience", "Público")} pulsa «Publicar app». Si se queda en pruebas, el permiso caduca a los 7 días.`,
  `En ${ext("https://console.cloud.google.com/auth/clients", "Clientes")} crea uno de tipo «App de escritorio» y descarga su archivo JSON en ese momento.`,
  `Elige ese archivo aquí y pulsa «Conectar con YouTube». Google avisará que la app no está verificada: es la tuya, entra en «Configuración avanzada» y continúa. Deja marcados los dos permisos.`];

function ytPanel(el) {
  let sig = "", waiting = 0, open = false;
  const load = async () => { let s; try { s = await api("/api/youtube"); } catch (e) { return; } if (el.isConnected) draw(s); };
  const connect = guard(async () => {
    const w = window.open("about:blank", "_blank");          // se abre ya, para que el navegador no lo bloquee
    try { const { url } = await api("/api/youtube/connect", { method: "POST" }); if (w) { w.opener = null; w.location.replace(url); } else location.assign(url); waiting = Date.now(); sig = ""; load(); }
    catch (e) { if (w) w.close(); throw e; }
  });
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
        <p class="mut small">También puedes quitar el permiso en ${ext(G_PERMS, "tu cuenta de Google")}.</p>`
      : s.configured ? `<div class="ytch"><i class="${s.expired ? "warn" : ""}"></i><div><b>${s.expired ? "El permiso caducó o se quitó" : "Falta conectar tu canal"}</b><span class="mut small">${waiting ? "Termina en la pestaña de Google…" : s.expired ? "Vuelve a conectar para seguir publicando." : "Tu app de Google ya está guardada."}</span></div></div>
        ${s.error ? `<p class="err" style="margin-bottom:10px">${esc(s.error)}</p>` : ""}<div class="eqfoot"><button type="button" class="btn pri" data-on>${s.expired ? "Volver a conectar" : "Conectar con YouTube"}</button>${s.expired ? `<button type="button" class="btn gh" data-off>Desconectar</button>` : `<button type="button" class="btn gh" data-clear>Usar otra app</button>`}</div>`
      : `<div class="eqfoot">${pick("Elegir el archivo de tu app", "pri")}</div>`;
    if (!s.connected) el.innerHTML += `<details class="ythow"${open || !s.configured ? " open" : ""}><summary>Cómo conseguir ese archivo</summary><ol>${YT_STEPS.map(x => `<li>${x}</li>`).join("")}</ol></details>
        <p class="mut small">Con esto, ${esc(window.APP_NAME)} podrá subir videos a tu canal y ver cómo quedaron. El permiso se guarda cifrado en este PC y no pasa por ningún otro servidor. Al conectar aceptas los ${ytLegal()}.</p>`;
    const on = $("[data-on]", el), o = $("[data-off]", el), c = $("[data-clear]", el), inp = $("input[type=file]", el);
    if (on) on.onclick = connect; if (o) o.onclick = () => off(true); if (c) c.onclick = () => off(false);
    if (inp) { inp.onchange = () => file(inp); inp.parentElement.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inp.click(); } }; }
  }
  every(2500, load);
}

// ------------------------------------------------------------ publicar uno o varios clips
const toLocal = (d) => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

async function ytPublish(pid, clips) {
  const [yt, mine] = await Promise.all([api("/api/youtube"), api(`/api/publicaciones?pid=${pid}`)]);
  if (!yt.connected) {
    if (await ask({ title: yt.expired ? "El permiso de YouTube caducó" : "Conecta tu canal de YouTube", text: yt.expired ? "Vuelve a conectar en Ajustes para publicar." : "Se hace una sola vez, en Ajustes.", ok: "Ir a Ajustes" })) location.hash = "#/ajustes/youtube";
    return false;
  }
  if (yt.first && clips.length > 1) throw new Error("La primera publicación va sola y en privado. Elige un solo clip.");
  if (clips.length > 50) throw new Error("Elige hasta 50 clips a la vez.");
  const before = (c) => mine.find(p => p.cid === c.id && (p.video || YT_ON.includes(p.status)));
  let list = clips.map(c => ({ c, title: (c.title || "").replace(/[<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 100), desc: (c.description || "").replace(/[<>]/g, ""), tags: (c.hashtags || []).map(t => t.startsWith("#") ? t : "#" + t).join(" "), old: before(c) }));
  const start = new Date(Date.now() + 3600e3); start.setMinutes(0, 0, 0); start.setHours(start.getHours() + 1);
  const d = document.createElement("dialog"); d.className = "sheet pub";
  d.innerHTML = `<header><h2>Publicar en YouTube</h2><button type="button" class="btn gh sq" data-x aria-label="Cerrar">${icon("close", 18)}</button></header>
    <div class="scroll"><div class="ytch"><i class="on"></i><div><b>${esc(yt.channel.title)}</b><span class="mut small">${esc(yt.channel.handle || "Tu canal")}</span></div></div>
      ${yt.first ? `<p class="pubnote">La primera va en privado para que revises cómo queda. Después podrás publicar y programar.</p>` : ""}
      <div data-list></div>
      <h3>Quién puede verlo</h3><div class="seg" data-see data-value="private"><button data-v="private">Privado</button><button data-v="unlisted">Oculto</button><button data-v="public">Público</button><button data-v="plan">Programado</button></div>
      <div data-plan hidden style="margin-top:14px"><div class="two"><label class="fld"><span class="lb" data-wl>Fecha y hora</span><input type="datetime-local" data-when></label><label class="fld" data-gapf><span class="lb">Uno cada (horas)</span><input type="number" data-gap min="1" max="336" step="1" value="24"></label></div></div>
      <p class="mut small" data-seetx style="margin:8px 0 18px"></p>
      <h3>¿Está hecho para niños?</h3><div class="seg" data-kids data-value=""><button data-v="no">No</button><button data-v="si">Sí</button></div><p class="mut small" style="margin:8px 0 14px">YouTube obliga a decirlo. Si es para niños, quita comentarios y otras funciones.</p>
      <label class="chk"><input type="checkbox" data-syn> <span>Muestra cosas realistas hechas o alteradas con IA</span></label>
      <label class="chk" data-notf><input type="checkbox" data-not checked> <span>Avisar a los suscriptores</span></label>
      <label class="fld" style="margin-top:12px"><span class="lb">Categoría</span><select data-cat>${Object.entries(yt.categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <p class="mut small">Se sube en 1080p; si hace falta, primero se exporta. Al publicar aceptas los ${ytLegal()}.</p></div>
    <footer><div class="err" role="alert"></div><button type="button" class="btn pri lg" data-go></button></footer>`;
  const err = $(".err", d), see = choice($("[data-see]", d), () => sync()), kids = choice($("[data-kids]", d), () => err.textContent = ""), when = $("[data-when]", d), gap = $("[data-gap]", d);
  see.value = pref.get("yt-ve", "private"); if (yt.first || !["private", "unlisted", "public", "plan"].includes(see.value)) see.value = "private";
  if (yt.first) $$("button", see.el).forEach(b => b.disabled = b.dataset.v !== "private");
  when.value = toLocal(start); when.min = toLocal(new Date()); gap.value = pref.get("yt-horas", "24"); $("[data-cat]", d).value = pref.get("yt-cat", "24"); if (!$("[data-cat]", d).value) $("[data-cat]", d).value = "24";
  const at = (i) => { const t = new Date(when.value); return isNaN(t) ? null : new Date(+t + i * Math.max(1, +gap.value || 24) * 3600e3); };
  const verb = () => { const n = list.length, o = n > 1 ? ` ${n} clips` : ""; return see.value === "plan" ? "Programar" + o : see.value === "public" ? "Publicar" + o : `Subir${o} ${see.value === "private" ? "en privado" : "como oculto"}`; };
  function sync() {
    const plan = see.value === "plan", many = list.length > 1;
    $("[data-plan]", d).hidden = !plan; $("[data-gapf]", d).hidden = !many; $("[data-wl]", d).textContent = many ? "El primero sale" : "Fecha y hora";
    $("[data-notf]", d).hidden = !(plan || see.value === "public");
    $("[data-seetx]", d).textContent = { private: "Solo tú lo ves. Puedes cambiarlo luego en YouTube Studio.", unlisted: "Lo ve quien tenga el enlace.", public: "Lo ve cualquiera en cuanto YouTube termine de procesarlo.", plan: "Se sube ahora en privado. Ya subido, YouTube lo publica a esa hora aunque este PC esté apagado." }[see.value];
    $("[data-go]", d).textContent = verb();
    $$("[data-at]", d).forEach(e => { const t = plan && many && at(+e.dataset.at); e.hidden = !t; e.textContent = t ? `Sale ${ytDate(t)}` : ""; });
  }
  function cards() {
    $("[data-list]", d).innerHTML = list.map((x, i) => `<div class="pubc" data-i="${i}"><i style="background-image:url('/api/projects/${pid}/thumb/${x.c.id}?v=${x.c.thumb_v || 0}')"></i><div>
        <label class="fld"><span class="lb"><span>Título</span><output data-n></output></span><input type="text" maxlength="100" data-f="title" value="${esc(x.title)}"></label>
        ${list.length > 1 ? `<details><summary>Descripción y hashtags</summary>` : ""}<label class="fld"><span class="lb">Descripción</span><textarea rows="${list.length > 1 ? 2 : 3}" maxlength="4500" data-f="desc">${esc(x.desc)}</textarea></label><label class="fld"><span class="lb">Hashtags</span><input type="text" maxlength="400" data-f="tags" value="${esc(x.tags)}"></label>${list.length > 1 ? "</details>" : ""}
        ${x.old ? `<p class="small pubold">${x.old.video ? `Ya lo subiste el ${ytDate(x.old.created * 1000)}` : "Ya se está subiendo"}: saldría repetido.</p>` : ""}<p class="small pubat" data-at="${i}" hidden></p></div>
        ${list.length > 1 ? `<button type="button" class="btn gh sq sm" data-rm aria-label="Quitar de la lista">${icon("close", 14)}</button>` : ""}</div>`).join("");
    $$(".pubc", d).forEach(el => {
      const x = list[+el.dataset.i], n = $("[data-n]", el), cnt = () => n.textContent = `${x.title.length}/100`; cnt();
      $$("[data-f]", el).forEach(f => f.oninput = () => { x[f.dataset.f] = f.value; cnt(); err.textContent = ""; });
      const rm = $("[data-rm]", el); if (rm) rm.onclick = () => { list = list.filter(y => y !== x); cards(); };
    });
    sync();
  }
  when.oninput = gap.oninput = sync; $("[data-x]", d).onclick = () => d.close();
  let sent = false, over;
  const done = new Promise(r => over = r);
  d.onclose = () => { d.remove(); over(sent); };
  $("[data-go]", d).onclick = async (e) => {
    const btn = e.currentTarget; err.textContent = "";
    try {
      const plan = see.value === "plan";
      for (const x of list) { if (!x.title.trim()) throw new Error("Falta un título."); if (/[<>]/.test(x.title + x.desc + x.tags)) throw new Error("YouTube no acepta los signos < ni >."); }
      if (!kids.value) throw new Error("Di si está hecho para niños.");
      if (plan && !at(0)) throw new Error("Elige la fecha y la hora.");
      const rep = list.filter(x => x.old).length, one = list.length === 1;
      const how = plan ? (one ? `Se publicará el ${ytDate(at(0))}.` : `Del ${ytDate(at(0))} al ${ytDate(at(list.length - 1))}, uno cada ${gap.value} h.`) : see.value === "public" ? `Cualquiera podrá ${one ? "verlo" : "verlos"}.` : see.value === "unlisted" ? `${one ? "Lo" : "Los"} verá quien tenga el enlace.` : `Solo tú podrás ${one ? "verlo" : "verlos"}.`;
      if (!(await ask({ title: `¿${verb()}?`, text: `${one ? `«${list[0].title.trim()}»` : plural(list.length, "clip", "clips")} en el canal ${yt.channel.title}. ${how}${rep ? ` ${rep === 1 ? "Uno ya se había subido: saldrá" : `${rep} ya se habían subido: saldrán`} ${rep === 1 ? "repetido" : "repetidos"}.` : ""}`, ok: verb() }))) return;
      btn.disabled = true;
      const items = list.map((x, i) => { const h = x.tags.trim().split(/[\s,]+/).filter(Boolean).map(t => t.startsWith("#") ? t : "#" + t); return { pid, cid: x.c.id, title: x.title.trim(), description: [x.desc.trim(), h.join(" ")].filter(Boolean).join("\n\n"), tags: h.map(t => t.slice(1)), privacy: plan ? "private" : see.value, publish_at: plan ? at(i).toISOString() : "", again: !!x.old }; });
      await api("/api/publicaciones", { method: "POST", json: { channel: yt.channel.id, kids: kids.value === "si", synthetic: $("[data-syn]", d).checked, notify: $("[data-not]", d).checked, category: $("[data-cat]", d).value, items } });
      if (!yt.first) pref.set("yt-ve", see.value); pref.set("yt-horas", gap.value); pref.set("yt-cat", $("[data-cat]", d).value);
      sent = true; d.close(); toast(one ? "En la cola para YouTube" : `${list.length} clips en la cola para YouTube`);
    } catch (e2) { err.textContent = e2.message; btn.disabled = false; }
  };
  document.body.appendChild(d); paintIcons(d); cards(); d.showModal();
  return done;
}

// ------------------------------------------------------------ seguimiento
function ytState(p) {
  if (p.status === "en cola") return "En espera";
  if (p.status === "exportando") return `Exportando, ${Math.round(p.progress)} %`;
  if (p.status === "subiendo") return `Subiendo, ${Math.round(p.progress)} %`;
  if (p.status === "procesando") return "Subido; YouTube lo está procesando";
  if (p.status === "cancelada") return "Cancelada";
  if (p.status === "error") return "No se publicó";
  if (p.publish_at) return new Date(p.publish_at) > new Date() ? `Programado para el ${ytDate(p.publish_at)}` : `Publicado el ${ytDate(p.publish_at)}`;
  return p.note ? p.note : p.privacy === "public" ? "Publicado" : p.privacy === "unlisted" ? "Subido como oculto" : "Subido en privado";
}
const ytSig = (ps) => JSON.stringify(ps.map(p => [p.id, p.status, p.progress, p.error, p.hidden]));
function ytRows(ps) {
  return ps.map(p => {
    const on = YT_ON.includes(p.status), pub = p.video && !p.publish_at && p.privacy !== "private" && !p.note;
    return `<div class="file ytf" data-pub="${p.id}"><i style="background-image:url('/api/projects/${p.pid}/thumb/${p.cid}')"></i><span class="n"${p.error ? ` style="white-space:normal"` : ""}><span title="${esc(p.title)}">${esc(p.title)}</span><small>${esc(ytState(p))}${p.channel ? ` · ${esc(p.channel.title)}` : ""}</small>${p.error ? `<span class="err">${esc(p.error)}</span>` : ""}${on ? `<div class="line" style="margin-top:6px"><i style="width:${p.progress}%"></i></div>` : ""}</span>
      ${p.video ? `<a class="btn sm" href="${pub ? `https://youtu.be/${encodeURIComponent(p.video)}` : `https://studio.youtube.com/video/${encodeURIComponent(p.video)}/edit`}" target="_blank" rel="noopener noreferrer">${pub ? "Ver" : "Abrir en Studio"}</a>` : ""}${!p.video && ["error", "cancelada"].includes(p.status) ? `<button class="btn sm" data-do="reintentar">Reintentar</button>` : ""}${on ? `<button class="btn sm gh" data-do="cancelar">${p.stop ? "Cancelando…" : "Cancelar"}</button>` : `<button class="btn sm gh sq" data-do="quitar" aria-label="Quitar de la lista" title="Quitar de la lista">${icon("close", 14)}</button>`}</div>`;
  }).join("");
}
function ytBind(box, again) {
  $$("[data-do]", box).forEach(b => b.onclick = guard(async () => {
    const i = b.closest("[data-pub]").dataset.pub;
    if (b.dataset.do === "cancelar" && !(await ask({ title: "¿Cancelar esta subida?", text: "No quedará nada en tu canal.", ok: "Cancelar la subida", danger: true }))) return;
    b.disabled = true; await api(`/api/publicaciones/${i}/${b.dataset.do}`, { method: "POST" }); again();
  }));
}
