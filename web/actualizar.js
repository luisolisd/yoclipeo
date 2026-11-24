// Versiones nuevas: botón sobre el de claro u oscuro, ventana para actualizar y opción en Ajustes.
"use strict";

let UPD = null, updGoing = false;
const updAgo = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "hace un momento" : m < 60 ? `hace ${m} min` : `hace ${plural(Math.round(m / 60), "hora", "horas")}`; };

async function updTick() {
  try { UPD = await api("/api/update"); } catch (e) { return; }
  const b = $("#upd"); b.hidden = !UPD.available;
  b.title = `Hay una versión nueva: ${UPD.version}`; b.setAttribute("aria-label", b.title);
  if (UPD.job.stage && !updGoing) updWait();        // se pidió desde otra pestaña
  window.dispatchEvent(new Event("actualizacion"));
}

// Se avisa una sola vez, al volver a abrir con la versión nueva (o si no se pudo)
function updNews() {
  const was = pref.get("version", ""), now = window.APP_VERSION; if (!now) return; pref.set("version", now);
  if (was && was !== now) return toast(`${window.APP_NAME} ya está en la versión ${now}`);
  const l = UPD && UPD.last, k = l && l.stage === "fallida" ? `${l.to} ${l.error}` : "";
  if (k && k !== pref.get("fallo", "")) { pref.set("fallo", k); toast(`No quedó la versión ${l.to}: ${l.error}. Sigues en la ${now}.`, true); }
}

function updOpen() {
  if (!UPD || !UPD.available) return;
  const d = document.createElement("dialog"); d.className = "dlg";
  const many = UPD.notes.length > 1;
  d.innerHTML = `<div class="in"><h2>Versión ${esc(UPD.version)} disponible</h2><p class="mut">Tienes la ${esc(UPD.current)}.</p>
    <ul class="updnotes">${UPD.notes.map(n => (many ? `<li class="v">${esc(n.v)}</li>` : "") + n.items.map(i => `<li>${esc(i)}</li>`).join("")).join("")}</ul>
    <p class="mut small" style="margin-top:14px" data-info></p><div class="line" data-line hidden style="margin-top:10px"><i style="width:0"></i></div></div>
    <div class="acts"><a class="btn gh" style="margin-right:auto" href="${esc(UPD.page)}" target="_blank" rel="noopener noreferrer">Ver en GitHub</a><button type="button" class="btn gh" data-no>Ahora no</button><button type="button" class="btn pri" data-yes>Actualizar</button></div>`;
  const info = $("[data-info]", d), yes = $("[data-yes]", d), no = $("[data-no]", d), line = $("[data-line]", d);
  const draw = () => {
    if (!d.isConnected || !UPD) return;
    const j = UPD.job, stop = UPD.blocked || UPD.busy;
    yes.disabled = !!(stop || j.stage || updGoing); no.textContent = updGoing ? "Cerrar" : "Ahora no"; line.hidden = j.stage !== "descargando"; $("i", line).style.width = (j.progress || 0) + "%";
    info.style.color = j.error && !updGoing ? "var(--bad)" : "";
    info.textContent = j.stage === "descargando" ? "Descargando…" : updGoing ? "Instalando y volviendo a abrir. La página se recarga sola; si hay librerías nuevas tarda unos minutos." : j.error || (UPD.blocked ? UPD.blocked : UPD.busy ? `${UPD.busy} Podrás actualizar cuando termine.` : "Se descarga de GitHub, se instala y se vuelve a abrir sola. Tus videos, proyectos y ajustes no se tocan.");
  };
  yes.onclick = async () => {
    yes.disabled = true;
    try { UPD = await api("/api/update/install", { method: "POST", json: { version: UPD.version } }); updWait(); } catch (e) { UPD.job.error = e.message; }
    draw();
  };
  no.onclick = () => d.close();
  window.addEventListener("actualizacion", draw);
  d.onclose = () => { window.removeEventListener("actualizacion", draw); d.remove(); };
  document.body.appendChild(d); draw(); d.showModal();
}

// Sigue la actualización hasta que el programa vuelve a abrir
async function updWait() {
  if (updGoing) return; updGoing = true;
  const from = window.APP_VERSION; let down = false;
  for (;;) {
    await new Promise(r => setTimeout(r, 700));
    let s; try { s = await api("/api/update"); } catch (e) { down = true; continue; }
    UPD = s;
    if (s.current !== from) return location.reload();
    if (down && !s.job.stage) { updGoing = false; if (s.last && s.last.stage === "fallida") s.job.error = `No quedó: ${s.last.error}. Sigues en la ${s.current}.`; break; }
    if (!down && !s.job.stage) { updGoing = false; break; }       // falló la descarga
    window.dispatchEvent(new Event("actualizacion"));
  }
  window.dispatchEvent(new Event("actualizacion"));
}

// Ajustes, «Acerca de»
function updPanel(el) {
  if (!el) return;
  el.innerHTML = `<p class="mut small" role="status" data-st></p><div class="eqfoot"><button type="button" class="btn sm" data-now></button></div>
    <label class="chk"><input type="checkbox" data-on> <span>Avisarme de versiones nuevas<span class="mut small">Consulta la página del proyecto en GitHub. No manda nada tuyo.</span></span></label>`;
  const st = $("[data-st]", el), now = $("[data-now]", el), on = $("[data-on]", el);
  const draw = () => {
    if (!el.isConnected) return window.removeEventListener("actualizacion", draw);
    if (!UPD) return;
    on.checked = UPD.enabled; now.textContent = UPD.available ? `Actualizar a la ${UPD.version}` : "Buscar ahora"; now.classList.toggle("pri", UPD.available); now.disabled = !UPD.enabled;
    st.textContent = !UPD.enabled ? "No se buscan versiones nuevas." : UPD.error ? `No se pudo revisar: ${UPD.error}.` : UPD.available ? `Hay una versión nueva: ${UPD.version}.` : UPD.checked ? `Tienes la versión más reciente. Se revisó ${updAgo(UPD.checked)}.` : "Todavía no se revisa.";
  };
  now.onclick = guard(async () => {
    if (UPD && UPD.available) return updOpen();
    now.disabled = true; st.textContent = "Buscando…";
    try { UPD = await api("/api/update/check", { method: "POST" }); } finally { now.disabled = false; updTick(); }
  });
  on.onchange = guard(async () => { await api("/api/settings", { method: "POST", json: { updates: on.checked ? "on" : "off" } }); if (on.checked) UPD = await api("/api/update/check", { method: "POST" }); updTick(); });
  window.addEventListener("actualizacion", draw); draw();
}

$("#upd").onclick = updOpen;
updTick().then(updNews); setInterval(updTick, 20000);
