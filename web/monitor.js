// Monitor del proyecto: reproduce a la derecha el momento elegido en el mapa, con audio.
"use strict";

class Monitor {
  // cb: { time(t), select(a, b), create(a, b), opened(), closed() }
  constructor(el, pid, dur, cb) {
    this.el = el; this.dur = dur; this.cb = cb; this.sel = null; this.until = null;
    el.innerHTML = `<header><b>Vista</b><span class="num" data-at></span><button type="button" class="btn gh sq sm" data-x aria-label="Cerrar la vista" title="Cerrar">${icon("close", 16)}</button></header>
      <div class="scr"><video playsinline preload="metadata"></video><span class="ld" hidden>Cargando…</span></div>
      <div class="transport"><button type="button" data-b title="Atrás 5 s" aria-label="Atrás 5 segundos">${icon("back1")}</button><button type="button" class="pl" data-p title="Espacio" aria-label="Reproducir">${icon("play", 19)}</button><button type="button" data-f title="Adelante 5 s" aria-label="Adelante 5 segundos">${icon("fwd1")}</button><input type="range" min="0" max="1" step="0.05" data-v aria-label="Volumen" title="Volumen"></div>
      <div class="marks"><div class="pairb"><button type="button" class="btn sm" data-in title="Tecla I">Empieza aquí</button><button type="button" class="btn sm" data-out title="Tecla O">Termina aquí</button></div>
        <p class="num" data-sel role="status"></p><button type="button" class="btn pri" data-mk hidden>${icon("plus", 15)}Crear clip</button></div>`;
    const v = this.v = $("video", el), q = (k) => $(`[data-${k}]`, el);
    v.volume = Math.min(1, Math.max(0, +pref.get("volumen", "1") || 0)); q("v").value = v.volume;
    q("v").oninput = () => { v.volume = +q("v").value; v.muted = false; pref.set("volumen", String(v.volume)); };
    q("p").onclick = () => this.toggle(); q("b").onclick = () => this.seek(v.currentTime - 5); q("f").onclick = () => this.seek(v.currentTime + 5); q("x").onclick = () => this.close();
    $(".scr", el).onclick = () => this.toggle();
    q("in").onclick = () => this.mark(true); q("out").onclick = () => this.mark(false); q("mk").onclick = () => { const s = this.sel; if (s) { v.pause(); cb.create(s[0], s[1]); } };
    const ld = $(".ld", el), st = () => { const on = !v.paused; q("p").innerHTML = icon(on ? "pause" : "play", 19); q("p").setAttribute("aria-label", on ? "Pausar" : "Reproducir"); };
    v.onplay = v.onpause = v.onended = st;
    v.onwaiting = v.onseeking = () => { clearTimeout(this.lt); this.lt = setTimeout(() => ld.hidden = v.readyState > 2, 250); };
    v.onplaying = v.onseeked = v.oncanplay = () => { clearTimeout(this.lt); ld.hidden = true; };
    v.onerror = () => { if (!v.getAttribute("src")) return; toast("No se pudo reproducir la vista previa de este video.", true); this.close(); };
    this.src = `/api/projects/${pid}/proxy`;
    this.key = (e) => {
      const a = document.activeElement;
      if (this.el.hidden || e.ctrlKey || e.metaKey || e.altKey || $("dialog[open]") || openMenu || isTyping() || (a && a !== document.body && !this.el.contains(a) && !a.closest(".vmap"))) return;
      const k = e.code;
      if (k === "Space") { if (a && a.tagName === "BUTTON") a.blur(); this.toggle(); }
      else if (k === "ArrowLeft" || k === "ArrowRight") { if (a && a.type === "range") return; this.seek(v.currentTime + (k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 5)); }
      else if (k === "KeyI") this.mark(true); else if (k === "KeyO") this.mark(false); else if (k === "Escape") this.close(); else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", this.key);
    const loop = () => {
      this.raf = requestAnimationFrame(loop); if (this.el.hidden) return;
      const t = v.currentTime;
      if (this.until !== null && t >= this.until && !v.paused) { v.pause(); this.until = null; }
      if (t !== this.shown) { this.shown = t; q("at").textContent = `${fmt(t)} / ${fmt(this.dur)}`; cb.time(t); }
    };
    loop();
  }
  // reproduce desde t; con «until» se detiene ahí
  play(t, until = null) {
    if (this.el.hidden) { this.el.hidden = false; this.el.parentElement.classList.add("mon-on"); this.cb.opened(); }
    if (!this.v.getAttribute("src")) { this.v.src = this.src; }
    this.seek(t); this.until = until; this.go();
  }
  go() { const p = this.v.play(); if (p) p.catch(() => {}); }
  seek(t) { this.until = null; t = Math.max(0, Math.min(this.dur - .05, t)); this.v.currentTime = t; }
  toggle() {
    const v = this.v, s = this.sel; if (!v.paused) return v.pause();
    if (s && Math.abs(v.currentTime - s[1]) < .3) return this.play(s[0], s[1]);      // al final del tramo: se ve otra vez
    this.until = s && v.currentTime >= s[0] && v.currentTime < s[1] ? s[1] : null; this.go();
  }
  mark(start) {
    const t = +this.v.currentTime.toFixed(2), s = this.sel, a = start ? t : s && s[0] < t - .5 ? s[0] : Math.max(0, t - 30), b = start ? (s && s[1] > t + .5 ? s[1] : Math.min(this.dur, t + 30)) : t;
    if (b - a < 1) return toast("El tramo debe durar al menos 1 segundo.", true);
    this.until = null; this.cb.select(a, b);
  }
  setSel(s) {
    this.sel = s; const len = s ? s[1] - s[0] : 0;
    $("[data-sel]", this.el).textContent = s ? `${fmt(s[0])} a ${fmt(s[1])} (${fmtLong(len)})${len > 180 ? ". Un clip dura hasta 3 minutos." : ""}` : "";
    $("[data-mk]", this.el).hidden = !(s && len >= 1 && len <= 180);
  }
  close() { this.v.pause(); this.el.hidden = true; this.el.parentElement.classList.remove("mon-on"); this.cb.closed(); }
  destroy() { cancelAnimationFrame(this.raf); clearTimeout(this.lt); document.removeEventListener("keydown", this.key); const v = this.v; v.onerror = null; v.pause(); v.removeAttribute("src"); v.load(); }
}
