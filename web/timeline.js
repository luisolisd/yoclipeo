// Mapa del video completo (página del proyecto) y línea de tiempo del clip (editor).
"use strict";

function fitCanvas(cv) {
  const r = cv.getBoundingClientRect(), d = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.max(1, Math.round(r.width * d)), h = Math.max(1, Math.round(r.height * d));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const c = cv.getContext("2d"); c.setTransform(d, 0, 0, d, 0, 0); c.clearRect(0, 0, r.width, r.height);
  return [c, r.width, r.height];
}
// separación «redonda» entre marcas de la regla
function niceStep(span, width, minPx = 78) {
  const raw = span * minPx / Math.max(1, width);
  return [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].find(s => s >= raw) || 14400;
}

// Fotograma del video bajo el cursor del mapa. Lee la copia ligera en el navegador: no le pide trabajo al servidor.
class Peek {
  constructor(pid) { this.src = `/api/projects/${pid}/proxy`; this.want = null; this.last = -1; this.on = false; }
  start() {
    const v = this.v = document.createElement("video"); v.muted = true; v.playsInline = true; v.preload = "metadata";
    v.onloadeddata = () => this.next(); v.onseeked = () => { this.busy = false; this.paint(); this.next(); };
    v.onerror = () => { this.bad = true; this.hide(); }; v.src = this.src; v.load();
  }
  show(t, x, box) {
    if (this.bad) return;
    if (!this.v) this.start();
    this.on = true; this.want = t; this.x = x; this.box = box;
    if (!this.el) { this.el = document.createElement("div"); this.el.className = this.ever ? "peek" : "peek wait"; this.el.setAttribute("aria-hidden", "true"); this.el.innerHTML = "<canvas></canvas>"; document.body.appendChild(this.el); }
    this.place(); this.next();
  }
  place() {
    const el = this.el, v = this.v; if (!el) return;
    const ar = v.videoWidth ? v.videoWidth / v.videoHeight : 16 / 9, w = Math.round(ar >= 1 ? 256 : 170 * ar), h = Math.round(w / ar), cv = el.firstChild;
    cv.style.width = w + "px"; cv.style.height = h + "px";
    const r = this.box.getBoundingClientRect(), up = r.top - h - 12;
    el.style.left = Math.max(8, Math.min(innerWidth - w - 10, this.x - w / 2)) + "px"; el.style.top = (up > 6 ? up : r.bottom + 12) + "px";
  }
  next() {
    const v = this.v; if (!this.on || this.busy || !v || v.readyState < 1 || this.want === null) return;
    const t = Math.max(0, Math.min((v.duration || 1e9) - .1, this.want));
    if (Math.abs(t - this.last) < .04) return;
    this.busy = true; this.last = t; v.currentTime = t;
  }
  paint() {
    if (!this.on || !this.el || !this.v.videoWidth) return;
    const v = this.v, cv = this.el.firstChild; this.place();
    const d = Math.min(2, window.devicePixelRatio || 1), w = Math.round(parseFloat(cv.style.width) * d), h = Math.round(parseFloat(cv.style.height) * d);
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    try { cv.getContext("2d").drawImage(v, 0, 0, w, h); this.el.className = "peek ok"; this.ever = true; } catch (e) {}
  }
  hide() { this.on = false; this.want = null; this.last = -1; if (this.el) { this.el.remove(); this.el = null; } }
  destroy() { this.hide(); if (this.v) { this.v.onerror = this.v.onseeked = this.v.onloadeddata = null; this.v.removeAttribute("src"); this.v.load(); this.v = null; } this.bad = true; }
}

// ------------------------------------------------------------ mapa del video
class VideoMap {
  // cb: { open(clip), create(a, b), hover(clipId|null), play(t, until|null), selected([a, b]|null) }
  constructor(box, pid, duration, cb) {
    this.box = box; this.pid = pid; this.dur = duration; this.cb = cb; this.va = 0; this.vb = duration;
    this.peaks = []; this.clips = []; this.sel = null; this.peek = new Peek(pid);
    box.innerHTML = `<div class="top"><b>Mapa del video</b><span class="hide-sm" data-hint></span><span class="sp"></span>
      <span class="num" data-seltxt></span><button class="btn sm pri" data-mk hidden>${icon("plus", 15)}Crear clip aquí</button><button class="btn sm" data-zoomsel hidden>${icon("zoomin", 15)}Ampliar</button><button class="btn sm gh" data-all hidden>Ver todo</button></div>
      <div class="cv"><canvas></canvas></div>`;
    this.wrap = $(".cv", box); this.cv = $("canvas", box);
    const wrap = this.wrap, at = (e) => { const r = wrap.getBoundingClientRect(); return this.va + Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * (this.vb - this.va); };
    let down = null, hov = null;
    wrap.onpointerdown = (e) => { if (e.target.closest(".pin") || e.button) return; down = { t: at(e), x: e.clientX }; wrap.setPointerCapture(e.pointerId); };
    wrap.onpointermove = (e) => {
      if (!hov) { hov = document.createElement("div"); hov.className = "hov"; hov.innerHTML = "<span></span>"; wrap.appendChild(hov); }
      const t = at(e); hov.style.left = this.x(t) + "%"; hov.firstChild.textContent = fmt(t); this.peek.show(t, e.clientX, wrap);
      if (down && Math.abs(e.clientX - down.x) > 4) this.select(Math.min(down.t, t), Math.max(down.t, t));
    };
    // clic: ver ese momento (si cae dentro del tramo marcado, el tramo se queda). Al soltar un arrastre: ver el tramo
    wrap.onpointerup = (e) => {
      if (!down) return; const s = this.sel, d = down; down = null;
      if (Math.abs(e.clientX - d.x) > 4) { if (s && s[1] - s[0] >= 1) cb.play(s[0], s[1]); return; }
      const inside = s && d.t >= s[0] && d.t <= s[1]; if (!inside) this.select(); cb.play(d.t, inside ? s[1] : null);
    };
    wrap.onpointerleave = wrap.onpointercancel = () => { this.peek.hide(); if (hov) { hov.remove(); hov = null; } };
    wrap.onwheel = (e) => {
      if (!e.deltaY || e.shiftKey) return; e.preventDefault();
      const t = at(e), k = e.deltaY > 0 ? 1.35 : 1 / 1.35, span = Math.min(this.dur, Math.max(20, (this.vb - this.va) * k));
      const f = (t - this.va) / (this.vb - this.va); this.setView(t - f * span, t - f * span + span);
    };
    this.onScroll = () => this.peek.hide(); window.addEventListener("scroll", this.onScroll, true);
    $("[data-mk]", box).onclick = () => { const s = this.sel; this.select(); cb.create(s[0], s[1]); };
    $("[data-zoomsel]", box).onclick = () => { const s = this.sel; this.select(); this.setView(s[0], s[1]); };
    $("[data-all]", box).onclick = () => { this.select(); this.setView(0, this.dur); };
    this.ro = new ResizeObserver(() => { this.draw(); const w = wrap.clientWidth; if (w !== this.w0) { this.w0 = w; this.pins(); } }); this.ro.observe(wrap);
    this.onTheme = () => this.draw(); window.addEventListener("tema", this.onTheme);
    this.load(); this.hint();
  }
  destroy() { this.ro.disconnect(); window.removeEventListener("tema", this.onTheme); window.removeEventListener("scroll", this.onScroll, true); this.peek.destroy(); this.hideTip(); clearTimeout(this.lt); }
  x(t) { return (t - this.va) / (this.vb - this.va) * 100; }
  hint() { $("[data-hint]", this.box).textContent = this.dur > 180 ? "Clic para ver ese momento. Arrastra para marcar un tramo. Rueda para acercar." : "Clic para ver ese momento. Arrastra para marcar un tramo."; }
  setView(a, b) {
    const span = Math.min(this.dur, Math.max(5, b - a)); a = Math.min(Math.max(0, a), this.dur - span);
    this.va = a; this.vb = a + span; $("[data-all]", this.box).hidden = span >= this.dur - 0.5;
    this.pins(); this.draw(); if (this.sel) this.select(...this.sel); this.head(this.now);
    clearTimeout(this.lt); this.lt = setTimeout(() => this.load(), 160);
  }
  async load() {
    const a = this.va, b = this.vb;
    try { const r = await api(`/api/projects/${this.pid}/wave?a=${a.toFixed(2)}&b=${b.toFixed(2)}&n=720`); if (a === this.va && b === this.vb) { this.peaks = r.peaks; this.pa = a; this.pb = b; this.draw(); } } catch (e) {}
  }
  // por dónde va la reproducción
  head(t) {
    this.now = t; let el = $(".now", this.wrap); const x = t === undefined || t === null ? -1 : this.x(t);
    if (x < 0 || x > 100) { el && el.remove(); return; }
    if (!el) { el = document.createElement("div"); el.className = "now"; this.wrap.appendChild(el); }
    el.style.left = x + "%";
  }
  select(a, b) {
    let el = $(".sel", this.wrap); const ok = a !== undefined; this.sel = ok ? [a, b] : null;
    if (!ok) el && el.remove();
    else {
      if (!el) { el = document.createElement("div"); el.className = "sel"; this.wrap.appendChild(el); }
      el.style.left = Math.max(0, this.x(a)) + "%"; el.style.right = Math.max(0, 100 - this.x(b)) + "%";
    }
    this.cb.selected(this.sel);
    const len = ok ? b - a : 0;
    $("[data-seltxt]", this.box).textContent = ok ? `${fmt(a)} a ${fmt(b)} (${fmtLong(len)})` : "";
    $("[data-mk]", this.box).hidden = !(ok && len >= 1 && len <= 180); $("[data-zoomsel]", this.box).hidden = !(ok && len > 5);
  }
  setClips(clips) { this.clips = clips; this.pins(); }
  pins() {
    $$(".pin", this.wrap).forEach(p => p.remove());
    const W = this.wrap.clientWidth || 800; let lastX = -99;
    for (const c of this.clips) {
      const l = this.x(c.start), r = this.x(c.end); if (r < 0 || l > 100) continue;
      const p = document.createElement("button"); p.className = "pin"; p.dataset.id = c.id; p.setAttribute("aria-label", `Clip ${c.no}: ${c.title}`);
      p.style.left = Math.max(0, l) + "%"; p.style.width = Math.max(0, Math.min(100, r) - Math.max(0, l)) + "%";
      const px = l / 100 * W;
      if (px - lastX > 17) { p.innerHTML = `<b>${c.no}</b>`; lastX = px; }
      p.onclick = () => this.cb.open(c);
      p.onpointerenter = () => { this.tip(c, p); this.cb.hover(c.id); }; p.onpointerleave = () => { this.hideTip(); this.cb.hover(null); };
      p.onfocus = () => this.tip(c, p); p.onblur = () => this.hideTip();
      this.wrap.appendChild(p);
    }
  }
  hot(id) { $$(".pin", this.wrap).forEach(p => p.classList.toggle("hot", p.dataset.id === id)); }
  tip(c, p) {
    this.hideTip(); const el = this.tipEl = document.createElement("div"), r = p.getBoundingClientRect(); el.className = "tip";
    el.innerHTML = `<i style="background-image:url('/api/projects/${this.pid}/thumb/${c.id}?v=${c.thumb_v || 0}')"></i><div><b>${esc(c.title)}</b><span class="num">${fmt(c.start)} a ${fmt(c.end)}</span><span>${esc(c.reason || c.category || "")}</span></div>`;
    document.body.appendChild(el);
    el.style.left = Math.max(8, Math.min(innerWidth - 300, r.left + r.width / 2 - 145)) + "px"; el.style.top = Math.min(innerHeight - 140, r.bottom + 10) + "px";
  }
  hideTip() { if (this.tipEl) { this.tipEl.remove(); this.tipEl = null; } }
  draw() {
    if (!this.cv.isConnected) return;
    const [c, W, H] = fitCanvas(this.cv), mid = 63, half = 36, span = this.vb - this.va;
    c.font = `11px ${cssVar("--din")}`; c.textBaseline = "alphabetic";
    const step = niceStep(span, W, 96); c.fillStyle = cssVar("--faint"); c.strokeStyle = cssVar("--line");
    for (let t = Math.ceil(this.va / step) * step; t <= this.vb; t += step) {
      const x = (t - this.va) / span * W; c.beginPath(); c.moveTo(x + .5, 22); c.lineTo(x + .5, 106); c.stroke();
      if (x < W - 34) c.fillText(fmt(t), x + 4, 120);
    }
    const n = this.peaks.length; c.fillStyle = cssVar("--line2");
    if (n) for (let i = 0; i < n; i++) {
      const t0 = this.pa + i / n * (this.pb - this.pa), t1 = this.pa + (i + 1) / n * (this.pb - this.pa), x0 = (t0 - this.va) / span * W, x1 = (t1 - this.va) / span * W;
      if (x1 < 0 || x0 > W) continue;
      const h = Math.max(1, this.peaks[i] / 100 * half); c.fillRect(x0, mid - h, Math.max(.8, (x1 - x0) * .72), h * 2);
    } else { c.fillRect(0, mid, W, 1); }
  }
}

// ------------------------------------------------------------ línea de tiempo del clip
class Timeline {
  // cb: { seek(src), trimming(start, end), trim(start, end), playing() }
  constructor(box, cb) {
    this.box = box; this.cb = cb; this.d = null; this.zoom = 1;
    box.innerHTML = `<div class="top"><span>Corte</span><b data-range></b><span class="hide-sm">Arrastra los bordes para alargar o acortar el clip.</span><span class="sp"></span>
      <button class="btn sm gh sq" data-z="out" title="Ver más alrededor" aria-label="Ver más alrededor">${icon("zoomout", 17)}</button><button class="btn sm gh sq" data-z="in" title="Acercar" aria-label="Acercar">${icon("zoomin", 17)}</button><button class="btn sm gh sq" data-z="fit" title="Ajustar al clip" aria-label="Ajustar al clip">${icon("fit", 17)}</button></div>
      <div class="cv"><canvas></canvas><div class="ph"></div></div>
      <div class="bar" role="scrollbar" tabindex="0" aria-orientation="horizontal" aria-label="Mover la línea de tiempo" aria-valuemin="0" aria-valuemax="100" title="Arrastra para moverte. También con Shift y la rueda."><u></u><i></i></div>`;
    this.wrap = $(".cv", box); this.cv = $("canvas", box); this.ph = $(".ph", box); this.bar = $(".bar", box);
    $$("[data-z]", box).forEach(b => b.onclick = () => b.dataset.z === "fit" ? this.fit() : this.scale(b.dataset.z === "in" ? 1 / 1.6 : 1.6));
    const w = this.wrap, at = (e) => { const r = w.getBoundingClientRect(); return this.va + (e.clientX - r.left - this.gut()) / Math.max(1, r.width - this.gut()) * (this.vb - this.va); };
    const edge = (e) => {
      if (!this.d) return null; const r = w.getBoundingClientRect(), x = e.clientX - r.left, slack = e.pointerType === "touch" ? 18 : 9;
      const ds = Math.abs(x - this.x(this.d.start)), de = Math.abs(x - this.x(this.d.end)); return Math.min(ds, de) > slack ? null : ds <= de ? "start" : "end";
    };
    let drag = null, from = 0, last = null, raf = 0, tap = false, two = null;
    const fingers = new Map(), inView = (t) => Math.min(this.vb, Math.max(this.va, t));
    const undo = () => { if (drag && this.trimming) { [this.d.start, this.d.end] = this.orig; this.draw(); cb.trimming(...this.orig); } drag = null; this.busy = this.trimming = false; };
    // dos dedos: mover y acercar
    const pair = () => { const [a, b] = [...fingers.values()]; return { x: (a + b) / 2, gap: Math.max(12, Math.abs(a - b)) }; };
    const inner = (x) => { const r = w.getBoundingClientRect(); return (x - r.left - this.gut()) / Math.max(1, r.width - this.gut()); };
    const pinch = () => {
      const p = pair(), span = this.span(two.span * two.gap / p.gap), f = inner(p.x); this.view(two.t - f * span, two.t - f * span + span);
    };
    // al llegar a la orilla con algo agarrado, la vista avanza sola
    const nudge = (now) => {
      raf = 0; if (!drag || !last || !this.d) return; const r = w.getBoundingClientRect(), x = last.clientX - r.left, m = 26, lo = this.gut() + m, hi = r.width - m;
      const over = x < lo ? x - lo : x > hi ? x - hi : 0, dt = Math.min(.05, (now - (this.nt || now)) / 1000); this.nt = now;
      if (over && Math.sign(over) === Math.sign(last.clientX - from) && Math.abs(last.clientX - from) > 5) {
        const a = this.va; this.pan(Math.max(-1.5, Math.min(1.5, over / 40)) * (this.vb - this.va) * .7 * dt); if (this.va !== a) move(last);
      }
      raf = requestAnimationFrame(nudge);
    };
    w.onpointerdown = (e) => {
      if (!this.d || e.button) return; e.preventDefault(); w.setPointerCapture(e.pointerId);
      if (e.pointerType === "touch") {
        fingers.set(e.pointerId, e.clientX);
        if (fingers.size === 2) { undo(); const p = pair(); two = { gap: p.gap, span: this.vb - this.va, t: this.va + inner(p.x) * (this.vb - this.va) }; return; }
        if (fingers.size > 2 || two) return;
      }
      drag = edge(e) || "seek"; from = e.clientX; last = e; this.busy = true; this.nt = 0; tap = drag === "seek" && e.pointerType === "touch";
      if (drag !== "seek") this.orig = [this.d.start, this.d.end]; else if (!tap) cb.seek(inView(at(e)));
      if (!raf) raf = requestAnimationFrame(nudge);
    };
    w.onpointermove = (e) => {
      if (!this.d) return;
      if (fingers.has(e.pointerId)) fingers.set(e.pointerId, e.clientX);
      if (two) { if (fingers.size === 2) pinch(); return; }
      if (!drag) { w.style.cursor = edge(e) ? "ew-resize" : "default"; return; }
      last = e; if (tap && Math.abs(e.clientX - from) < 6) return; tap = false; move(e);
    };
    const move = (e) => {
      if (drag === "seek") return cb.seek(inView(at(e)));
      let t = at(e); const px = (this.vb - this.va) / Math.max(1, w.clientWidth - this.gut()) * 7;
      // se pega al borde de la palabra más cercana
      for (const x of this.d.ctx) { const k = drag === "start" ? x.s - 0.08 : x.e + 0.25; if (Math.abs(k - t) < px) { t = k; break; } }
      if (drag === "start") this.d.start = Math.min(this.d.end - 1, Math.max(0, t)); else this.d.end = Math.max(this.d.start + 1, Math.min(this.d.media, t));
      this.trimming = true; this.draw(); cb.trimming(this.d.start, this.d.end);
    };
    w.onpointerup = (e) => {
      fingers.delete(e.pointerId); if (two) { if (!fingers.size) two = null; return; }
      if (tap && drag) cb.seek(inView(at(e))); tap = false;
      if (drag && drag !== "seek" && this.trimming && (this.orig[0] !== this.d.start || this.orig[1] !== this.d.end)) cb.trim(+this.d.start.toFixed(2), +this.d.end.toFixed(2));
      drag = null; this.busy = this.trimming = false;
    };
    w.onpointercancel = (e) => { fingers.delete(e.pointerId); if (!fingers.size) two = null; tap = false; undo(); };
    // rueda: acercar. Con Shift, o a los lados en un touchpad: mover
    const px = (e, v) => v * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? w.clientWidth : 1);
    const side = (e) => Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.shiftKey ? e.deltaY : 0;
    const slide = (e, v) => { e.preventDefault(); this.pan(px(e, v) / Math.max(1, w.clientWidth - this.gut()) * (this.vb - this.va)); };
    w.onwheel = (e) => {
      if (!this.d || drag) return; const s = side(e); if (s) return slide(e, s);
      if (!e.deltaY) return; e.preventDefault(); this.scale(Math.exp(Math.max(-100, Math.min(100, px(e, e.deltaY))) * .0022), at(e));
    };
    const b = this.bar; let grab = null;
    const slideTo = (x) => { const g = this.room(), r = b.getBoundingClientRect(), p = (x - r.left - grab) / Math.max(1, r.width - g.w), a = g.lo + Math.min(1, Math.max(0, p)) * (g.hi - g.lo - g.span); this.view(a, a + g.span); };
    b.onpointerdown = (e) => {
      if (!this.d || e.button) return; e.preventDefault(); b.setPointerCapture(e.pointerId);
      const g = this.room(), x = e.clientX - b.getBoundingClientRect().left - g.x; grab = x >= 0 && x <= g.w ? x : g.w / 2; b.classList.add("on"); slideTo(e.clientX);
    };
    b.onpointermove = (e) => { if (grab !== null) slideTo(e.clientX); };
    b.onpointerup = b.onpointercancel = () => { grab = null; b.classList.remove("on"); };
    b.onwheel = (e) => { if (this.d) slide(e, side(e) || e.deltaY); };
    b.onkeydown = (e) => {
      if (!this.d || e.ctrlKey || e.altKey || e.metaKey) return; const s = this.vb - this.va, k = { ArrowLeft: -s / 10, ArrowRight: s / 10, PageUp: -s * .9, PageDown: s * .9, Home: -1e9, End: 1e9 }[e.key];
      if (k === undefined) return; e.preventDefault(); e.stopPropagation(); this.pan(k);
    };
    this.ro = new ResizeObserver(() => { this.draw(); this.head(this.src); }); this.ro.observe(w);
    this.onTheme = () => this.draw(); window.addEventListener("tema", this.onTheme);
  }
  destroy() { this.ro.disconnect(); window.removeEventListener("tema", this.onTheme); this.d = null; }
  // hasta dónde se puede ver. Mientras se arrastra un borde no cambia
  lims() { const [s, e] = this.trimming ? this.orig : [this.d.start, this.d.end]; return [Math.max(0, s - 60), Math.min(this.d.media, e + 60)]; }
  span(s) { const [a, b] = this.lims(); return Math.min(b - a, Math.max(3, s)); }
  pan(dt) { const s = this.vb - this.va, [lo, hi] = this.lims(), a = Math.min(Math.max(lo, this.va + dt), Math.max(lo, hi - s)); this.view(a, a + s); }
  room() { const [lo, hi] = this.lims(), W = this.bar.clientWidth, span = Math.min(hi - lo, this.vb - this.va), w = Math.min(W, Math.max(32, W * span / Math.max(.1, hi - lo))), free = hi - lo - span; return { lo, hi, span, w, x: free > .01 ? (this.va - lo) / free * (W - w) : 0, free, W }; }
  drawBar() {
    this.bar.style.marginLeft = 14 + this.gut() + "px";
    const g = this.room(), k = g.W / Math.max(.1, g.hi - g.lo), [u, i] = this.bar.children, full = g.free <= .01;
    u.style.left = (this.d.start - g.lo) * k + "px"; u.style.width = Math.max(2, (this.d.end - this.d.start) * k) + "px";
    i.style.width = g.w + "px"; i.style.transform = `translateX(${g.x}px)`; this.bar.classList.toggle("full", full);
    this.bar.setAttribute("aria-valuenow", full ? 0 : Math.round((this.va - g.lo) / g.free * 100)); this.bar.setAttribute("aria-valuetext", `${fmt(Math.max(0, this.va))} a ${fmt(this.vb)}`);
  }
  gut() { return this.wrap.clientWidth < 560 ? 0 : 62; }
  x(t) { const g = this.gut(); return g + (t - this.va) / (this.vb - this.va) * (this.wrap.clientWidth - g); }
  // d: {start,end,segs,words,ctx,title,brand,stickers,media,toSrc}
  set(d) {
    const old = this.d, first = !old; if (this.trimming) return; this.d = d; if (first) this.fit(); else {
      const gone = (t, t0) => Math.abs(t - t0) > .001 && (t < this.va || t > this.vb);      // cambió un borde que no se está viendo
      if (gone(d.start, old.start) || gone(d.end, old.end) || d.end <= this.va || d.start >= this.vb) this.fit(); else this.view(this.va, this.vb);
    }
  }
  setWave(peaks, a, b) { this.w = { peaks, a, b }; this.draw(); }
  fit() { if (!this.d) return; const pad = Math.max(1.5, (this.d.end - this.d.start) * 0.08); this.view(this.d.start - pad, this.d.end + pad); }
  scale(k, at = (this.va + this.vb) / 2) { if (!this.d) return; const span = Math.max(3, Math.min(this.d.end - this.d.start + 120, (this.vb - this.va) * k)), f = (at - this.va) / (this.vb - this.va); this.view(at - f * span, at - f * span + span); }
  view(a, b) {
    const [lim0, lim1] = this.lims(), span = Math.min(b - a, lim1 - lim0); a = Math.min(Math.max(lim0, a), lim1 - span);
    this.va = a; this.vb = a + span; this.draw(); this.head(this.src);
  }
  // t: momento del clip. Si la aguja sale de la vista al reproducir o al moverla, la vista va con ella;
  // si te fuiste a ver otra parte mientras se reproduce, se queda donde la dejaste
  head(src, t) {
    const went = t !== undefined && this.t !== undefined && Math.abs(t - this.t) > .005, seen = this.ph.style.opacity === "1"; if (t !== undefined) this.t = t;
    if (went && this.d && !this.busy && (seen || !this.cb.playing()) && (src < this.va || src > this.vb)) {
      const s = this.vb - this.va; this.src = src; return this.view(src - s * .12, src + s * .88);
    }
    this.src = src; if (src === undefined || this.va === undefined) return; const x = this.x(src), out = x < this.gut() - 1 || x > this.wrap.clientWidth + 1;
    this.ph.style.transform = `translateX(${x}px)`; this.ph.style.opacity = out ? 0 : 1;
  }
  draw() {
    const d = this.d; if (!d || !this.cv.isConnected || this.va === undefined) return;
    this.drawBar();
    $("[data-range]", this.box).textContent = `${fmt(d.start)} a ${fmt(d.end)} (${(d.end - d.start).toFixed(1)} s)`;
    const [c, W, H] = fitCanvas(this.cv), g = this.gut(), span = this.vb - this.va, X = (t) => this.x(t);
    const col = { line: cssVar("--line"), line2: cssVar("--line2"), faint: cssVar("--faint"), mut: cssVar("--mut"), text: cssVar("--text"), cut: cssVar("--cut"), soft: cssVar("--cut-soft"), s2: cssVar("--s2"), s3: cssVar("--s3"), ink: cssVar("--cut-ink") };
    const din = cssVar("--din"), tall = H > 120, yR = 14, yW = 22, hW = tall ? 46 : 32, yT = yW + hW + 8, hT = 20, yL = yT + hT + 6, hL = 9;
    c.textBaseline = "middle";
    // regla: tiempo desde el inicio del clip
    c.font = `11px ${din}`; const step = niceStep(span, W - g, 70); c.strokeStyle = col.line; c.fillStyle = col.faint; c.lineWidth = 1;
    for (let k = Math.ceil((this.va - d.start) / step); k * step + d.start <= this.vb; k++) {
      const x = X(d.start + k * step); if (x < g) continue; c.beginPath(); c.moveTo(x + .5, 4); c.lineTo(x + .5, H); c.stroke();
      const t = k * step; if (x < W - 30) c.fillText((t < 0 ? "−" : "") + (step < 1 ? Math.abs(t).toFixed(1) : fmt(Math.abs(t))), x + 4, 8);
    }
    c.save(); c.beginPath(); c.rect(g, 0, W - g, H); c.clip();
    // dentro del corte
    const xs = X(d.start), xe = X(d.end); c.fillStyle = col.soft; c.fillRect(xs, yW - 4, xe - xs, H - yW + 4);
    // audio
    const inSeg = (t) => t >= d.start && t <= d.end && (this.trimming || d.segs.some(([a, b]) => t >= a && t <= b)), mid = yW + hW / 2;
    if (this.w && this.w.peaks.length) {
      const n = this.w.peaks.length, dt = (this.w.b - this.w.a) / n, i0 = Math.max(0, Math.floor((this.va - this.w.a) / dt)), i1 = Math.min(n, Math.ceil((this.vb - this.w.a) / dt)), bw = dt / span * (W - g), skip = Math.max(1, Math.floor(1.6 / bw));
      for (let i = i0; i < i1; i += skip) {
        let m = 0; for (let j = i; j < Math.min(i1, i + skip); j++) m = Math.max(m, this.w.peaks[j]);
        const t = this.w.a + (i + skip / 2) * dt, h = Math.max(.7, m / 100 * hW / 2); c.fillStyle = inSeg(t) ? col.cut : col.line2; c.fillRect(X(this.w.a + i * dt), mid - h, Math.max(1, bw * skip - 0.8), h * 2);
      }
    } else { c.fillStyle = col.line2; c.fillRect(g, mid, W - g, 1); }
    // silencios quitados
    if (!this.trimming) { let cur = d.start; for (const [a, b] of [...d.segs, [d.end, d.end]]) { if (a - cur > 0.05) this.hatch(c, X(cur), yW - 2, X(a) - X(cur), hW + 4, col.faint); cur = b; } }
    // guion: las palabras se juntan en frases hasta que el texto quepa; al acercar se separan
    c.font = `12.5px ${cssVar("--ui")}`;
    const px = (W - g) / span, minW = 92, groups = [];
    // Si el grupo no cabe, se quitan palabras enteras y se marca con puntos suspensivos.
    const fit = (s, max) => { if (c.measureText(s).width <= max) return s; const ws = s.split(" "); while (ws.length > 1) { ws.pop(); const r = ws.join(" ") + "…"; if (c.measureText(r).width <= max) return r; } return s; };
    const add = (w, on) => {
      const l = groups[groups.length - 1];
      if (l && l.on === on && w.s - l.e < 0.6 && (l.e - l.s) * px < minW) { l.e = w.e; l.t += " " + w.w; l.key = l.key || w.key; } else groups.push({ s: w.s, e: w.e, t: w.w, on, key: on && w.key });
    };
    const all = [];
    for (const w of d.ctx) if (this.trimming || w.s < d.start - 0.05 || w.e > d.end + 0.05) all.push([w, this.trimming && w.s >= d.start - 0.05 && w.e <= d.end + 0.05]);
    if (!this.trimming) for (const w of d.words) if (w.w) all.push([w, true]);
    all.sort((p, q) => p[0].s - q[0].s).forEach(([w, on]) => add(w, on));
    for (const q of groups) {
      const x0 = X(q.s), x1 = X(q.e); if (x1 < g || x0 > W) continue; const ww = Math.max(2, x1 - x0 - 1);
      if (q.on) { c.fillStyle = col.s3; c.fillRect(x0, yT, ww, hT); if (q.key) { c.fillStyle = col.cut; c.fillRect(x0, yT + hT - 2, ww, 2); } }
      else { c.fillStyle = col.line; c.fillRect(x0, yT + hT - 1, ww, 1); }
      if (ww > 18) { c.save(); c.beginPath(); c.rect(x0, yT, ww - 2, hT); c.clip(); c.fillStyle = q.on ? col.text : col.faint; c.fillText(fit(q.t, ww - 8), x0 + 4, yT + hT / 2 + .5); c.restore(); }
    }
    // titular y marca
    const lane = (y, s, e, fill) => { c.fillStyle = fill; const a = X(d.toSrc(s)), b = X(d.toSrc(e)); c.fillRect(a, y, Math.max(3, b - a - 1), hL); };
    if (!this.trimming) {
      if (d.title) lane(yL, 0, d.title, col.mut);
      d.brand.forEach(b => lane(yL + hL + 5, b.s, b.e, col.mut)); d.stickers.forEach(b => lane(yL + hL + 5, b.s, b.e, col.text));
    }
    // bordes del corte
    for (const [x, dir] of [[xs, 1], [xe, -1]]) {
      c.fillStyle = col.cut; c.fillRect(dir > 0 ? x - 7 : x, yW - 4, 7, hW + 8); c.fillRect(x - 1, yW - 4, 2, H - yW + 4);
      c.fillStyle = col.ink; c.fillRect(dir > 0 ? x - 5 : x + 2.5, mid - 7, 1.2, 14); c.fillRect(dir > 0 ? x - 3 : x + 4.5, mid - 7, 1.2, 14);
    }
    c.restore();
    if (g) { c.font = `11.5px ${din}`; c.fillStyle = col.faint; c.fillText("Audio", 0, mid); c.fillText("Guion", 0, yT + hT / 2); c.fillText("Titular", 0, yL + hL / 2); c.fillText("Marca", 0, yL + hL * 1.5 + 5); }
  }
  hatch(c, x, y, w, h, col) { c.save(); c.beginPath(); c.rect(x, y, w, h); c.clip(); c.fillStyle = cssVar("--s1"); c.fillRect(x, y, w, h); c.strokeStyle = col; c.lineWidth = 1; for (let k = x - h; k < x + w; k += 6) { c.beginPath(); c.moveTo(k, y + h); c.lineTo(k + h, y); c.stroke(); } c.restore(); }
}
