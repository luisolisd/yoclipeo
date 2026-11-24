// Arranque: nombre y marca, navegación, estado del sistema y recarga al actualizar.
"use strict";

document.title = window.APP_NAME || "Clips";
$(".rail .mark").innerHTML = MARK(28); $(".rail .mark").title = document.title; $(".rail .mark").setAttribute("aria-label", `${document.title}: biblioteca`);
paintIcons();
if (window.APP_DONATE) { $("#cafe").href = window.APP_DONATE; $("#cafe").hidden = false; }
if (window.APP_VERSION) { const v = $("#ver"); v.hidden = false; v.textContent = `v${window.APP_VERSION}`; v.title = `${document.title} ${window.APP_VERSION}. ${window.APP_AUTHOR}. ${window.APP_NOTICE}`; }
$("#railnew").onclick = () => newSheet({ folder: (location.hash.match(/^#\/f\/(\w+)/) || [])[1] || "" });
$("#theme").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");

// ------------------------------------------------------------ rutas
async function route() {
  closeMenu(); $$("dialog[open]").forEach(d => d.close());
  timers.forEach(clearInterval); timers = []; cleanup.forEach(f => f()); cleanup = [];
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean), here = parts[0] || "";
  $$(".rail a.nav").forEach(a => { const on = a.dataset.nav === here || (a.dataset.nav === "home" && ["", "p", "f"].includes(here)); a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
  try {
    if (here === "p" && parts[2] === "c") return await editor(parts[1], parts[3]);
    if (here === "p") return project(parts[1]);
    if (here === "f") return library(parts[1]);
    if (here === "cola") return cola();
    if (here === "descargas") return descargas();
    if (here === "ajustes") return await ajustes();
    library();
  } catch (e) { view.className = ""; view.innerHTML = noOpen(e.message === "Not Found" ? "Ese clip ya no existe." : e.message); }
}
window.addEventListener("hashchange", route);

// Si la interfaz se actualizó, recargar la página sola. Espera si estás en el editor, con una ventana
// abierta, escribiendo, con un archivo elegido o subiendo algo, para no perder nada a medias.
let uiVersion = null;
const uiBusy = () => location.hash.includes("/c/") || $("dialog[open]") || isTyping() || openMenu || $(".clip.sel") || $(".mon:not([hidden])") ||
  $$("input[type=file]").some(f => f.files.length) || $$("input[type=text],input[type=password],textarea").some(i => i.value !== i.defaultValue && i.offsetParent && i.id !== "s-odir");
async function checkVersion() {
  try { const { v } = await api("/api/version"); if (uiVersion === null) uiVersion = v; else if (v !== uiVersion && !uiBusy()) location.reload(); } catch (e) {}
}
checkVersion(); setInterval(checkVersion, 5000);

// ------------------------------------------------------------ estado: motor y trabajos en marcha
async function sysBadge() {
  try {
    const s = await api("/api/status");
    $("#sysbadge").innerHTML = `<i class="${s.engine === "reglas" ? "off" : "on"}"></i>${s.engine === "claude" ? "Claude" : s.engine === "ollama" ? "IA local" : s.engine === "servidor" ? "Servidor" : "Sin IA"}<br>${s.cuda ? "GPU" : "CPU"}`;
    $("#sysbadge").title = (s.engine === "ollama" ? `Elige los momentos: ${s.ollama_model}. ` : s.engine === "servidor" ? `Elige los momentos: ${s.server_model || "tu servidor"}. ` : s.engine === "claude" ? `Elige los momentos: ${s.claude_model}. ` : "Sin IA: elige por reglas. ") + (s.cuda ? "La voz se transcribe en la GPU." : "La voz se transcribe en el procesador.");
  } catch (e) {}
}
async function badge() {
  try {
    const [js, ps, lv] = await Promise.all([api("/api/jobs"), api("/api/projects"), api("/api/directos")]);
    const n = lv.filter(liveOn).length + js.filter(j => ["en cola", "renderizando", "descargando"].includes(j.status)).length + ps.filter(isBusy).length, b = $("#qbadge");
    b.hidden = !n; b.textContent = n; document.title = (n ? `(${n}) ` : "") + (window.APP_NAME || "Clips");
  } catch (e) {}
}
badge(); setInterval(badge, 4000);
sysBadge();
route();
