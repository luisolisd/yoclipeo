// Espacio: qué ocupa el disco, qué quedó de proyectos borrados y qué se puede liberar.
"use strict";

const spTxt = (b) => b >= 1073741824 ? gbTxt(b) : b >= 1048576 ? `${Math.round(b / 1048576)}\u00a0MB` : b ? "menos de 1\u00a0MB" : "0\u00a0MB";
const spUsed = (u) => u.length > 1 ? `Lo tienen abierto ${u.slice(0, -1).join(", ")} y ${u[u.length - 1]}.` : u.length ? `Lo tiene abierto ${u[0]}.` : "";
const spDeleted = (r) => r && r.pending ? toast("Windows tiene abierto algo de ese proyecto. Se termina de borrar solo: míralo en Espacio", true) : toast("Proyecto borrado");

// Aviso en la Biblioteca: solo si un proyecto borrado sigue ocupando sitio.
async function spNotice(box) {
  let l; try { l = (await api("/api/espacio/restos")).filter(x => x.kind === "pendiente" || x.kind === "suelta"); } catch (e) { return; }
  if (!box || !box.isConnected) return;
  const n = l.reduce((a, x) => a + x.size, 0);
  box.innerHTML = l.length ? `<a class="liveb activo" style="color:inherit;text-decoration:none" href="#/espacio"><i></i><div><b>${l.length === 1 ? "Un proyecto borrado sigue en el disco" : `${l.length} proyectos borrados siguen en el disco`}</b><span>${n ? `Ocupa${l.length === 1 ? "" : "n"} ${spTxt(n)}. ` : ""}Ver en Espacio</span></div></a>` : "";
}

function espacio() {
  mount("tpl-espacio");
  let sig = "", busy = false;
  const COL = [["projects", "Proyectos", "var(--acc)"], ["left", "Restos", "var(--warn)"], ["downloads", "Descargas", "var(--sp2)"], ["models", "Modelos", "var(--sp3)"], ["app", "Programa", "var(--faint)"]];
  const part = (p) => [["video", "video"], ["preview", "vista previa"], ["audio", "audio"], ["exports", p.n_exports === 1 ? "1 exportado" : `${p.n_exports} exportados`], ["other", "otros datos"]].filter(([k]) => p.parts[k] >= 1048576 || k === "exports" && p.n_exports).sort((a, b) => p.parts[b[0]] - p.parts[a[0]]).map(([k, t]) => `${t} ${spTxt(p.parts[k])}`).join(" · ");
  const leftTxt = (x) => ({
    pendiente: `${spUsed(x.users) || (x.files ? "Algo lo tiene abierto." : "Windows aún tiene abierta la carpeta.")} Se sigue intentando hasta terminar.`,
    suelta: `Quedó de un proyecto que ya no existe. ${spUsed(x.users)}`,
    danada: "Sus datos no se pueden leer, así que no sale en la Biblioteca. No se borra solo.",
    ajena: "Esta carpeta no es de YoClipeo. No se toca.",
  })[x.kind];
  async function draw(force) {
    if (busy && !force) return;
    let r; try { r = await api("/api/espacio"); } catch (e) { return; }
    const box = $("#spbox"); if (!box) return;
    const s = JSON.stringify([{ ...r, disk: Math.round(r.disk.free / 1e8), away: r.away.map(a => [a.drive, a.size]), sums: 0, total: 0 }]); if (s === sig) return; sig = s;
    const low = r.disk.free < 20 * 1073741824, stuck = r.left.filter(x => x.kind === "pendiente" || x.kind === "suelta"), odd = r.left.filter(x => !stuck.includes(x));
    const rowLeft = (x) => `<div class="file spf spl"><span style="width:27px;display:grid;place-items:center;color:var(--mut)">${icon("folder", 18)}</span><span class="n"><span>${esc(x.name || `Carpeta ${x.id}`)}</span><small>${esc(leftTxt(x))}</small></span><span class="num">${spTxt(x.size)}</span>${stuck.includes(x) ? `<button class="btn sm" data-wipe="${esc(x.id)}">${x.kind === "pendiente" ? "Intentar ahora" : "Borrar"}</button>` : x.kind === "danada" ? `<button class="btn sm gh" data-open="${esc(x.id)}">Abrir carpeta</button>` : ""}</div>`;
    box.innerHTML = `<p class="spsum"><b>${esc(window.APP_NAME)} ocupa ${spTxt(r.total)}</b><span${low ? ` class="bad"` : ""}>Quedan ${spTxt(r.disk.free)} libres en ${esc(r.disk.drive)}</span>${r.away.map(a => `<span>Además, ${spTxt(a.size)} de modelos de IA local en ${esc(a.drive)} (${spTxt(a.free)} libres)</span>`).join("")}</p>
      <div class="spbar" role="img" aria-label="${COL.filter(c => r.sums[c[0]]).map(c => `${c[1]} ${spTxt(r.sums[c[0]])}`).join(", ")}">${COL.filter(c => r.sums[c[0]] / (r.total || 1) > .002).map(c => `<i style="flex:${r.sums[c[0]]};background:${c[2]}" title="${c[1]}: ${spTxt(r.sums[c[0]])}"></i>`).join("")}</div>
      <div class="spleg">${COL.filter(c => r.sums[c[0]]).map(c => `<span><i style="background:${c[2]}"></i>${c[1]} <b>${spTxt(r.sums[c[0]])}</b></span>`).join("")}</div>
      <section class="block"><h2>Proyectos borrados</h2>${stuck.length ? `<div class="files">${stuck.map(rowLeft).join("")}</div>` : `<p class="spok">${icon("check", 16)}No queda nada de proyectos borrados en el disco.</p>`}</section>` +
      (odd.length ? `<section class="block"><h2>Carpetas que no reconozco</h2><div class="files">${odd.map(rowLeft).join("")}</div></section>` : "") +
      `<section class="block"><h2>Proyectos</h2>${r.projects.length ? `<div class="files">${r.projects.map(p => `<div class="file spf"><a class="n" href="#/p/${p.id}"><span title="${esc(p.name)}">${esc(p.name)}</span><small>${esc(isBusy(p) ? `Trabajando · ${part(p)}` : part(p) || "Sin archivos todavía")}${p.outside ? " · El video original está en otra carpeta" : ""}</small><span class="spmini"><i style="width:${r.projects[0].size ? p.size / r.projects[0].size * 100 : 0}%"></i></span></a><span class="num">${spTxt(p.size)}</span><button class="btn gh sq sm" data-more="${p.id}" aria-label="Opciones de «${esc(p.name)}»">${icon("more", 16)}</button></div>`).join("")}</div>` : `<p class="mut small">No hay proyectos.</p>`}</section>` +
      (r.downloads.length ? `<section class="block"><h2>Descargas</h2><div class="files">${r.downloads.map((d, i) => `<div class="file spf"><span class="n"><span title="${esc(d.file)}">${esc(d.file)}</span><small>${d.half ? "Se quedó a medias" : `${fmtDate(d.at)}${d.listed ? "" : " · No sale en Descargas"}`}</small></span><span class="num">${spTxt(d.size)}</span><button class="btn gh sq sm" data-dl="${i}" aria-label="Borrar «${esc(d.file)}»" title="Borrar">${icon("trash", 16)}</button></div>`).join("")}</div></section>` : "") +
      `<section class="block"><h2>Modelos y programa</h2><div class="files">${r.models.map(m => `<div class="file spf"><span class="n"><span>${esc(m.name)}</span><small>${m.kind === "ollama" ? `IA local, en ${esc(m.where)}` : "Transcribe la voz (Whisper)"}</small></span><span class="num">${spTxt(m.size)}</span></div>`).join("")}<div class="file spf"><span class="n"><span>${esc(window.APP_NAME)}</span><small>El programa, sus librerías y tus ajustes</small></span><span class="num">${spTxt(r.sums.app)}</span></div></div>${r.models.some(m => m.kind === "ollama") ? `<p class="mut small" style="margin-top:10px">Los modelos de IA local se borran en <a href="#/ajustes" style="text-decoration:underline">Ajustes</a>. Otros programas también pueden usarlos.</p>` : ""}</section>`;
    $$("[data-wipe]", box).forEach(b => b.onclick = run(b, async () => {
      const x = r.left.find(y => y.id === b.dataset.wipe);
      if (x.kind === "suelta" && !(await ask({ title: "¿Borrar esta carpeta?", text: `Ocupa ${spTxt(x.size)} y quedó de un proyecto que ya no existe. No se puede deshacer.`, ok: "Borrar", danger: true }))) return;
      const a = await api(`/api/espacio/restos/${x.id}`, { method: "POST" });
      a.pending ? toast(`Todavía no se puede. ${spUsed(a.users) || "Algo lo tiene abierto."}`, true) : toast(`Listo${x.size ? `: se liberaron ${spTxt(x.size)}` : ""}`);
    }));
    $$("[data-open]", box).forEach(b => b.onclick = guard(() => api(`/api/espacio/carpeta/${b.dataset.open}`, { method: "POST" })));
    $$("[data-dl]", box).forEach(b => b.onclick = run(b, async () => {
      const d = r.downloads[+b.dataset.dl];
      if (!(await ask({ title: "¿Borrar esta descarga?", text: `«${d.file}» (${spTxt(d.size)}). No se puede deshacer.`, ok: "Borrar", danger: true }))) return;
      await api("/api/espacio/descarga", { method: "POST", json: { file: d.file } }); toast(`Se liberaron ${spTxt(d.size)}`);
    }));
    $$("[data-more]", box).forEach(b => b.onclick = () => {
      const p = r.projects.find(x => x.id === b.dataset.more);
      menu(b, [
        { label: "Abrir proyecto", icon: "film", run: () => { location.hash = `#/p/${p.id}`; } },
        { label: "Abrir su carpeta", icon: "folder", run: guard(() => api(`/api/espacio/carpeta/${p.id}`, { method: "POST" })) }, "-",
        ...(p.n_exports ? [{ label: "Borrar exportados", hint: `Libera ${spTxt(p.parts.exports)}`, icon: "trash", run: run(b, async () => {
          if (!(await ask({ title: "¿Borrar los exportados?", text: `${p.n_exports === 1 ? "1 video exportado" : `${p.n_exports} videos exportados`} de «${p.name}» (${spTxt(p.parts.exports)}). Los clips y sus ediciones se quedan: puedes volver a exportarlos.`, ok: "Borrar exportados", danger: true }))) return;
          const a = await api(`/api/espacio/exportados/${p.id}`, { method: "POST" });
          toast(a.stuck ? `${a.stuck === 1 ? "Uno no se pudo borrar" : `${a.stuck} no se pudieron borrar`}. ${spUsed(a.users)}` : `Se liberaron ${spTxt(a.freed)}`, !!a.stuck);
        }) }] : []),
        { label: "Borrar proyecto", hint: `Libera ${spTxt(p.size)}`, icon: "trash", bad: true, run: run(b, async () => {
          if (!(await ask({ title: "¿Borrar este proyecto?", text: `Se borran «${p.name}», sus clips y todos sus archivos (${spTxt(p.size)}). No se puede deshacer.`, ok: "Borrar proyecto", danger: true }))) return;
          spDeleted(await api(`/api/projects/${p.id}`, { method: "DELETE" }));
        }) }]);
    });
  }
  const run = (b, fn) => guard(async () => { busy = true; b.disabled = true; try { await fn(); } finally { busy = false; if (b.isConnected) b.disabled = false; } await draw(true); });
  draw(); every(5000, () => draw());
}
