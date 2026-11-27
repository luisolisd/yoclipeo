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
    if (here === "espacio") return espacio();
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
    const [js, ps, lv, yt] = await Promise.all([api("/api/jobs"), api("/api/projects"), api("/api/directos"), api("/api/publicaciones")]);
    const n = lv.filter(liveOn).length + yt.filter(p => YT_ON.includes(p.status)).length + js.filter(j => ["en cola", "renderizando", "descargando"].includes(j.status) && !ytExports(yt, j)).length + ps.filter(isBusy).length, b = $("#qbadge");
    b.hidden = !n; b.textContent = n; document.title = (n ? `(${n}) ` : "") + (window.APP_NAME || "Clips");
    cafeCheck(js);
  } catch (e) {}
}
badge(); setInterval(badge, 4000);

// ------------------------------------------------------------ aviso de café: al terminar una exportación, pocas veces y sin estorbar
let expRun = null;
async function cafeCheck(js) {
  if (!window.APP_DONATE) return;
  const run = new Set(js.filter(j => j.kind === "export" && ["en cola", "renderizando"].includes(j.status)).map(j => j.id));
  const ended = expRun && [...expRun].some(id => !run.has(id) && (js.find(j => j.id === id) || { status: "listo" }).status === "listo");
  expRun = run;
  if (!ended || $("#cafecard")) return;
  try { const c = await api("/api/cafe"); if (c.due && !$("#cafecard")) cafeCard(c.n); } catch (e) {}
}
function cafeCard(n) {
  const el = document.createElement("div"); el.id = "cafecard"; el.className = "cafecard"; el.setAttribute("role", "status");
  el.innerHTML = `<button class="btn gh sq sm x" data-a="luego" aria-label="Cerrar">${icon("close", 14)}</button>
    <b>${icon("coffee", 18)}<span>Llevas ${n} clips con ${esc(window.APP_NAME || "este programa")}</span></b>
    <p>Es gratis y lo hago en mis ratos. Si te ahorra tiempo, invítame un café: me ayuda a seguir mejorándolo.</p>
    <a class="next" href="#/ajustes/lo-que-viene" data-a="next">Ver lo que viene</a>
    <div class="row"><a class="btn pri sm" href="${esc(window.APP_DONATE)}" target="_blank" rel="noopener noreferrer" data-a="cafe">Invitar un café</a><button class="btn sm" data-a="hecho">Ya lo hice</button><button class="btn gh sm" data-a="luego">Ahora no</button></div>`;
  document.body.appendChild(el);
  const say = (a) => api("/api/cafe", { method: "POST", json: { answer: a } }).catch(() => {});
  say("visto");
  $$("[data-a]", el).forEach(b => b.addEventListener("click", () => {
    const a = b.dataset.a; if (a === "next") return;
    el.remove(); if (a !== "luego") say(a);
    if (a === "hecho") toast("¡Gracias de corazón!");
  }));
}
sysBadge();
route();
