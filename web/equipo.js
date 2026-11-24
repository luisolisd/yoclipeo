// «Tu equipo»: qué se detectó, qué funciona y qué conviene (en Ajustes y en el aviso de la primera vez).
"use strict";

const VOICE_GB = { "large-v3-turbo": "1,6 GB", medium: "1,5 GB", small: "0,5 GB", base: "0,15 GB" };
const gbTxt = (b) => `${(b / 1073741824).toFixed(b < 10e9 ? 1 : 0).replace(".", ",").replace(",0", "")}\u00a0GB`;

// Cada renglón: {st: ok | warn | off | wait, name, main, note, act}
function equipoRows(e) {
  const o = e.ollama, sv = e.server, gpuNv = e.gpus.find(g => g.vendor === "nvidia"), vram = gpuNv ? gpuNv.vram : 0, rows = [];
  const other = e.engine === "claude" ? "Ahora elige Claude." : "Mientras tanto se elige por reglas.";
  if (e.engine === "servidor") rows.push({ st: sv.on && sv.use ? "ok" : "warn", name: "Momentos", main: sv.on && sv.use ? `${sv.label}, en ${sv.name === "servidor" ? sv.host : sv.name}` : `${sv.host || "El servidor"} no está listo`,
    note: sv.on && sv.use ? (sv.home ? `Otro servidor: ${sv.host}.` : `El guion se manda a ${sv.host}, fuera de tu red.`) : `${sv.error || "Falta la dirección en Ajustes"}. Mientras tanto se elige por reglas.` });
  else if (!o.installed) rows.push({ st: "off", name: "Momentos", main: "No encontré una IA local", note: `Se usa Ollama: es gratis y trabaja sin internet. También puedes conectar otro servidor, como LM Studio, en Ajustes. ${other}`, act: `<a class="btn sm" href="https://ollama.com/download" target="_blank" rel="noopener">Descargar Ollama</a>` });
  else if (o.pull.on) rows.push({ st: "wait", name: "Momentos", main: `${o.pull.msg} ${o.pull.model}`, note: `<div class="line"><i style="width:${o.pull.total ? o.pull.done / o.pull.total * 100 : 0}%"></i></div>${gbTxt(o.pull.done)} de ${gbTxt(o.pull.total)}`, raw: true, act: `<button type="button" class="btn sm gh" data-pull-stop>Detener</button>` });
  else if (!o.use) rows.push({ st: "warn", name: "Momentos", main: "Ollama está, pero sin modelos", note: (o.pull.error ? o.pull.error + " " : "") + (o.recommend ? `Para este equipo recomiendo ${o.recommend.name}${{ cpu: ", en el procesador (más lento)", gpu: ", entero en la GPU", auto: "" }[o.recommend.where]}. ${other}` : `Este equipo tiene poca memoria para una IA local. ${other}`),
    act: o.recommend ? `<button type="button" class="btn sm pri" data-pull="${esc(o.recommend.name)}" data-size="${o.recommend.size}">Descargar ${esc(gbTxt(o.recommend.size))}</button>` : "" });
  else {
    const fits = vram && o.sizes[o.use] * 1.1 + 4.3e8 < vram, better = o.recommend && !o.models.includes(o.recommend.name) && !fits && o.recommend.size < o.sizes[o.use] ? o.recommend : null;
    const miss = o.model !== "auto" && o.model !== o.use;
    rows.push({ st: e.engine === "reglas" ? "off" : fits ? "ok" : "warn", name: "Momentos", main: `${o.use}, ${fits ? "entero en la GPU" : gpuNv ? "entre la GPU y el procesador" : e.gpus.some(g => g.vendor === "amd") ? "Ollama decide si usa la GPU" : "en el procesador"}`,
      note: `${miss ? `«${o.model}» no está instalado, así que se usa este. ` : ""}${e.engine === "claude" ? "Está lista, pero ahora elige Claude. " : e.engine === "reglas" ? "Está lista, pero en «Quién elige» está puesto «Solo reglas». " : ""}Ollama en ${o.exe || "este equipo"}, ${plural(o.models.length, "modelo", "modelos")}.${better ? ` Con ${better.name} iría más rápido.` : ""}`,
      act: better ? `<button type="button" class="btn sm" data-pull="${esc(better.name)}" data-size="${better.size}">Descargar ${esc(gbTxt(better.size))}</button>` : "" });
  }
  const v = e.voice, u = e.voice_use, onGpu = u.device === "cuda", dl = u.cached ? "" : ` El modelo se descarga con el primer video (${VOICE_GB[u.model] || "unos GB"}).`;
  rows.push({ st: !onGpu ? (v && v.ok === false ? "warn" : "off") : v && v.ok && !v.partial ? "ok" : "warn", name: "Voz", main: `${u.model}, en ${onGpu ? "la GPU" : "el procesador"}`,
    note: (onGpu ? (v && v.ok && !v.partial ? "Comprobado en este equipo." : v && v.why || "Aún sin probar.") : (v && v.why) || "Sin GPU NVIDIA: tarda más, pero funciona igual.") + dl });
  const enc = e.encoders, oks = Object.keys(enc).filter(k => enc[k].ok), bad = Object.keys(enc).filter(k => !enc[k].ok);
  rows.push({ st: oks.length ? "ok" : "warn", name: "Exportar", main: e.encoder_names[e.encoder], note: oks.length ? `${oks.map(k => `${e.encoder_names[k]}: ${enc[k].fps} fps`).join(". ")}.${bad.length ? ` No disponible: ${bad.map(k => e.encoder_names[k]).join(", ")}.` : ""}` : "Aún sin probar." });
  return rows;
}

function equipoHtml(e) {
  const hw = [e.cpu.name.replace(/\((R|TM)\)/g, "").replace(/\s+CPU.*$/, ""), plural(e.cpu.threads, "hilo", "hilos"), e.ram ? gbTxt(e.ram) + " de memoria" : "", ...e.gpus.map(g => g.name.replace(/\((R|TM)\)/g, "") + (g.vram ? `, ${gbTxt(g.vram)}` : ""))].filter(Boolean);
  return `<p class="hw">${hw.map(esc).join("<span>·</span>")}</p><div class="eqs">${equipoRows(e).map(r => `<div class="eq s-${r.st}"><i></i><span class="k">${r.name}</span><div class="d"><b>${esc(r.main)}</b><div class="mut small">${r.raw ? r.note : esc(r.note)}</div></div>${r.act ? `<div>${r.act}</div>` : ""}</div>`).join("")}</div>`;
}

function equipoPanel(box, foot, onData) {
  let sig = "";
  const draw = async () => {
    let e; try { e = await api("/api/equipo"); } catch (x) { return; }
    if (!box.isConnected) return;
    const s = JSON.stringify(e); if (s === sig) return; sig = s;
    box.innerHTML = equipoHtml(e);
    if (foot) foot.innerHTML = e.testing.on ? `<span class="mut small">${esc(e.testing.step)}…</span>` : `<button type="button" class="btn sm" data-test>${e.tested ? "Probar de nuevo" : "Probar"}</button><span class="mut small">${e.tested ? `Probado el ${fmtDate(e.tested)}.` : ""}</span>`;
    const t = foot && $("[data-test]", foot); if (t) t.onclick = guard(async () => { await api("/api/equipo/test", { method: "POST" }); sig = ""; draw(); });
    $$("[data-pull]", box).forEach(b => b.onclick = guard(async () => {
      const free = e.ollama.free;
      if (!(await ask({ title: `¿Descargar ${b.dataset.pull}?`, text: `Son ${gbTxt(+b.dataset.size)} desde ollama.com, a ${e.ollama.models_dir}${free ? ` (${gbTxt(free)} libres)` : ""}.`, ok: "Descargar" }))) return;
      await api("/api/ollama/pull", { method: "POST", json: { model: b.dataset.pull } }); sig = ""; draw();
    }));
    const st = $("[data-pull-stop]", box); if (st) st.onclick = guard(async () => { await api("/api/ollama/pull", { method: "DELETE" }); sig = ""; draw(); });
    if (onData) onData(e);
  };
  every(2000, draw);
}

// Primera vez: un aviso en la biblioteca con lo que se encontró.
async function equipoNotice(box) {
  let e; try { e = await api("/api/equipo"); } catch (x) { return; }
  if (e.seen || !box.isConnected || $(".eqnotice", box.parentNode)) return;
  const n = document.createElement("section"); n.className = "eqnotice"; n.setAttribute("aria-label", "Tu equipo");
  n.innerHTML = `<header><h2>Tu equipo</h2><a class="btn sm gh" href="#/ajustes">Abrir Ajustes</a><button class="btn gh sq sm" aria-label="Cerrar">${icon("close", 16)}</button></header><div></div>`;
  box.prepend(n);
  $("button", n).onclick = guard(async () => { await api("/api/equipo/seen", { method: "POST" }); n.remove(); });
  equipoPanel($("div", n), null);
}
