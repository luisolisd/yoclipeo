// Vista previa: dibuja el plan de render en un <canvas> con las mismas reglas que cliper/render.py
"use strict";

const FONT_CSS = {
  impacto: "CliperImpacto", gruesa: "CliperGruesa", clasica: "CliperClasica",
  pincel: "CliperPincel", comic: "CliperComic", condensada: "CliperCondensada",
};
const COLORS = { amarillo: "#FFD400", verde: "#39FF6A", rojo: "#FF3B3B", cian: "#2BD9FF", rosa: "#FF4FD8" };
const CSS_FILTERS = {
  ninguno: "none",
  calido: "sepia(0.12) saturate(1.12) brightness(1.03)",
  cine: "contrast(1.1) saturate(0.92) brightness(0.97)",
  vivo: "saturate(1.38) contrast(1.06)",
  bn: "grayscale(1) contrast(1.15) brightness(0.95)",
};

function interp(keys, t) {
  if (t <= keys[0][0]) return keys[0].slice(1);
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1];
    if (t <= b[0]) {
      const span = b[0] - a[0];
      const k = span <= 0 ? 0 : (t - a[0]) / span;
      return a.slice(1).map((x, j) => x + (b[j + 1] - x) * k);
    }
  }
  return keys[keys.length - 1].slice(1);
}

function easeOutBack(k) {
  const c1 = 1.70158, c3 = 2.70158;
  k = Math.min(Math.max(k, 0), 1);
  return 1 + c3 * Math.pow(k - 1, 3) + c1 * Math.pow(k - 1, 2);
}

class TimeMap {
  constructor(segs) {
    this.segs = segs; this.offs = []; let acc = 0;
    for (const [a, b] of segs) { this.offs.push(acc); acc += b - a; }
    this.duration = acc;
  }
  toOut(t) {
    for (let i = 0; i < this.segs.length; i++) {
      const [a, b] = this.segs[i];
      if (t < a) return this.offs[i];
      if (t <= b) return this.offs[i] + (t - a);
    }
    return this.duration;
  }
  toSrc(t) {
    for (let i = 0; i < this.segs.length; i++) {
      const [a, b] = this.segs[i];
      if (t <= this.offs[i] + (b - a)) return a + Math.max(0, t - this.offs[i]);
    }
    return this.segs[this.segs.length - 1][1];
  }
  segIndex(src) {
    for (let i = 0; i < this.segs.length; i++) if (src < this.segs[i][1] - 0.01) return i;
    return -1;
  }
}

const imgCache = new Map();
const CHAT_URL = (it, ch) => `/api/img/chat?x=${encodeURIComponent(it.x)}&u=${encodeURIComponent(it.u)}&c=${encodeURIComponent(it.c)}&s=${ch.size}&w=${ch.w}`;
const titleUrl = (ti) => `/api/img/title?text=${encodeURIComponent(ti.text)}&font=${ti.font}&style=${ti.style}&color=${ti.color}&size=${ti.size}`;
function cachedImg(url) {
  if (!imgCache.has(url)) { const im = new Image(); im.src = url; imgCache.set(url, im); }
  const im = imgCache.get(url);
  return im.complete && im.naturalWidth ? im : null;
}

class Preview {
  constructor(canvas, onTime) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.onTime = onTime || (() => {});
    this.vA = this._mkVideo(); this.vB = this._mkVideo();
    this.plan = null; this.tmap = null; this.t = 0; this.playing = false;
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }
  _mkVideo() {
    const v = document.createElement("video");
    v.preload = "auto"; v.playsInline = true; v.crossOrigin = "anonymous";
    const redraw = () => { if (this.plan) this.draw(this.t); };
    v.addEventListener("seeked", redraw); v.addEventListener("loadeddata", redraw);
    return v;
  }
  setPlan(plan, keepTime = true) {
    const first = !this.plan;
    this.plan = plan; this.tmap = new TimeMap(plan.segments);
    if (this.vA.dataset.src !== plan.sources.A.proxy) { this.vA.src = plan.sources.A.proxy; this.vA.dataset.src = plan.sources.A.proxy; }
    const B = plan.sources.B;
    if (B && this.vB.dataset.src !== B.proxy) { this.vB.src = B.proxy; this.vB.dataset.src = B.proxy; this.vB.muted = true; }
    if (!keepTime || first || this.t > plan.duration) this.seek(0); else this.seek(this.t);
  }
  get duration() { return this.plan ? this.plan.duration : 0; }
  seek(tOut) {
    if (!this.plan) return;
    this.t = Math.max(0, Math.min(tOut, this.plan.duration));
    const src = this.tmap.toSrc(this.t);
    this.vA.currentTime = src;
    if (this.plan.sources.B) this.vB.currentTime = Math.max(0, src + this.plan.sources.B.offset);
    this.onTime(this.t);
  }
  play() {
    if (!this.plan) return;
    if (this.t >= this.plan.duration - 0.05) this.seek(0);
    this.playing = true; this.vA.play().catch(() => {});
    if (this.plan.sources.B) this.vB.play().catch(() => {});
  }
  pause() { this.playing = false; this.vA.pause(); this.vB.pause(); }
  toggle() { this.playing ? this.pause() : this.play(); }

  destroy() { this.dead = true; this.pause(); this.plan = null; this.vA.removeAttribute("src"); this.vB.removeAttribute("src"); this.vA.load(); this.vB.load(); }

  _loop() {
    if (this.dead) return;
    requestAnimationFrame(this._loop);
    if (!this.plan) return;
    if (this.playing) {
      const src = this.vA.currentTime;
      const segs = this.plan.segments;
      const i = this.tmap.segIndex(src);
      if (i < 0 || src >= segs[segs.length - 1][1]) { this.pause(); this.t = this.plan.duration; }
      else {
        if (src < segs[i][0] - 0.02) this.vA.currentTime = segs[i][0];
        this.t = this.tmap.toOut(src);
        // salto de silencio: si estamos al final de un tramo, ir al siguiente
        if (src >= segs[i][1] - 0.04 && i + 1 < segs.length) this.vA.currentTime = segs[i + 1][0];
      }
      if (this.plan.sources.B) {
        const tgt = this.vA.currentTime + this.plan.sources.B.offset;
        if (Math.abs(this.vB.currentTime - tgt) > 0.2) this.vB.currentTime = Math.max(0, tgt);
      }
      this.onTime(this.t);
    }
    this.draw(this.t);
  }

  draw(t) {
    const p = this.plan, ctx = this.ctx, cv = this.cv;
    const s = cv.width / p.W;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.scale(s, s);
    const z = p.zoom && p.zoom.length ? interp(p.zoom, t)[0] : 1;
    const filt = CSS_FILTERS[p.filter] || "none";
    for (const pn of p.panels) {
      const v = pn.src === "B" ? this.vB : this.vA;
      if (!v.videoWidth) continue;
      const fw = v.videoWidth, fh = v.videoHeight;
      let [cx, cy, cw, ch] = interp(pn.track, t);
      const zz = pn.zoom ? z : 1;
      if (zz > 1.0001) { const ch0 = ch; cw /= zz; ch /= zz; cy = cy - 0.35 * (ch0 - ch); }
      cx = Math.min(Math.max(cx, cw / 2), 1 - cw / 2);
      cy = Math.min(Math.max(cy, ch / 2), 1 - ch / 2);
      const [dx, dy, dw, dh] = pn.dst;
      ctx.filter = pn.blur ? `blur(28px) brightness(0.55) ${filt === "none" ? "" : filt}` : filt;
      try { ctx.drawImage(v, (cx - cw / 2) * fw, (cy - ch / 2) * fh, cw * fw, ch * fh, dx, dy, dw, dh); } catch (e) {}
      ctx.filter = "none";
    }
    if (p.chat) this._drawChat(p.chat, t);
    // título
    if (p.title.on && t <= p.title.until) {
      const ti = p.title;
      const im = cachedImg(titleUrl(ti));
      if (im) ctx.drawImage(im, 0, ti.y);
    }
    // stickers de marca
    for (const b of p.brand || []) {
      if (t < b.s || t > b.e) continue;
      const im = cachedImg(`/api/img/brand/${b.id}?w=${b.w}&o=${b.opacity}`);
      if (im) ctx.drawImage(im, Math.round(b.x - im.width / 2), Math.round(b.y - im.height / 2));
      if (this.selBrand === b.i) {
        ctx.save(); ctx.strokeStyle = "#ff6b47"; ctx.lineWidth = 5; ctx.setLineDash([18, 12]);
        ctx.strokeRect(b.x - b.w / 2 - 6, b.y - b.h / 2 - 6, b.w + 12, b.h + 12); ctx.restore();
      }
    }
    // stickers
    for (const st of p.stickers) {
      if (t < st.s || t > st.e) continue;
      let sc = easeOutBack((t - st.s) / 0.22);
      if (t > st.e - 0.18) sc *= Math.max(0, (st.e - t) / 0.18);
      const rot = Math.sin((t - st.s) * 6) * 4;
      const url = st.kind === "emoji" ? `/api/img/emoji?c=${encodeURIComponent(st.value)}&size=${st.size}`
                                      : `/api/img/logo/${st.value}?size=${st.size}`;
      const im = cachedImg(url);
      if (!im || sc <= 0.01) continue;
      ctx.save(); ctx.translate(st.x, st.y); ctx.rotate(-rot * Math.PI / 180); ctx.scale(sc, sc);
      ctx.drawImage(im, -im.width / 2, -im.height / 2); ctx.restore();
    }
    // subtítulos
    const sb = p.subs;
    if (sb.on) {
      for (const pg of sb.pages) {
        if (pg.s <= t && t < pg.e) { this._drawPage(pg, t, sb); break; }
      }
    }
    ctx.restore();
  }

  // chat: mismas cuentas que draw_chat en cliper/render.py
  _drawChat(ch, t) {
    const ctx = this.ctx, size = ch.size, fr = Math.floor(t * ch.fps);
    const emote = (i, x, y, w, h) => { const m = ch.emotes[i], im = m && cachedImg(`/api/img/emote/${i}`); if (im) ctx.drawImage(im, (fr % m.n) * m.w, 0, m.w, m.h, x, y, w, h); };
    for (const [s, i, x, h, rot, ph] of ch.parts) {
      const k = (t - s) / ch.fly, m = ch.emotes[i]; if (k < -.3 || k >= 1 || !m) continue;
      if (k < 0) { cachedImg(`/api/img/emote/${i}`); continue; }
      const pop = Math.min(1, k / .06), a = Math.min(1, (1 - k) / .3) * pop, hh = h * (.5 + .5 * pop), ww = hh * m.w / m.h;
      ctx.save(); ctx.globalAlpha = a; ctx.translate(x + Math.sin(k * 6 + ph) * 16, ch.y - ch.rise * (1 - Math.pow(1 - k, 1.6))); ctx.rotate(-rot * Math.PI / 180);
      emote(i, -ww / 2, -hh / 2, ww, hh); ctx.restore();
    }
    const gap = Math.round(size * .22), top = ch.y - ch.h; let y = ch.y;
    for (let n = ch.items.length - 1; n >= 0; n--) {
      const it = ch.items[n]; if (it.s > t + 5) continue;
      const im = cachedImg(CHAT_URL(it, ch)); if (it.s > t || t - it.s >= ch.life) continue;
      const k = 1 - Math.pow(1 - Math.min(1, Math.max(0, (t - it.s) / .22)), 3);
      y += (1 - k) * (it.h + gap) - it.h; if (y + it.h < top) break;
      const a = Math.min(k, (ch.life - (t - it.s)) / .4, 1 - Math.max(0, top - y) / 24);
      if (a > .06 && im) { ctx.globalAlpha = Math.min(1, a); ctx.drawImage(im, ch.x + (ch.right ? ch.w - it.w : 0), Math.round(y)); ctx.globalAlpha = 1; }
      y -= gap;
    }
    let cur = []; for (const c of ch.counts) { if (c[0] > t) break; cur = c[1]; }
    const g = Math.round(size * .28), H = Math.round(size * 1.5), eh = Math.round(size * 1.15);
    const boxes = cur.filter(([i]) => ch.emotes[i]).map(([i, n, tw]) => { const m = ch.emotes[i], ew = Math.min(Math.round(eh * 2.2), Math.round(eh * m.w / m.h)); return { i, n, tw, ew, rw: Math.round(eh * m.w / m.h), w: Math.round(ew + tw + size * 1.15) }; });
    const tot = boxes.reduce((a, b) => a + b.w, 0) + g * (boxes.length - 1); let bx = Math.max(0, Math.min(1080 - tot, ch.x + (ch.right ? ch.w - tot : 0))); const by = ch.y - (ch.items.length ? ch.h + g : 0) - H;
    for (const b of boxes) {
      ctx.fillStyle = "rgba(0,0,0,0.65)"; ctx.beginPath(); ctx.roundRect(bx, by, b.w, H, H / 2); ctx.fill();
      ctx.font = `bold ${size}px "Segoe UI"`; ctx.textAlign = "left"; ctx.textBaseline = "alphabetic"; ctx.fillStyle = "#fff"; ctx.fillText("×" + b.n, bx + size * .65 + b.ew, by + H / 2 + size * .35);
      emote(b.i, bx + size * .4 + (b.ew - b.rw) / 2, by + (H - eh) / 2, b.rw, eh); bx += b.w + g;
    }
  }

  pageBox(pg, sb) {                  // lo que ocupa una frase de los subtítulos
    const ctx = this.ctx, size = Math.round(sb.size * (pg.big ? 1.9 : 1.0));
    ctx.save(); ctx.font = `${sb.font === "clasica" ? "900 " : ""}${size}px ${FONT_CSS[sb.font] || FONT_CSS.impacto}`;
    const w = pg.words.reduce((a, x) => a + ctx.measureText(x.w).width, 0) + ctx.measureText(" ").width * (pg.words.length - 1); ctx.restore();
    const h = size * Math.min(1, 940 / (w || 1)) * 1.15, ww = Math.max(0, Math.min(940, w));
    return { x: (1080 - ww) / 2, y: sb.y - h / 2, w: ww, h };
  }

  _drawPage(pg, t, sb) {
    const ctx = this.ctx, fam = FONT_CSS[sb.font] || FONT_CSS.impacto;
    const color = COLORS[sb.color] || COLORS.amarillo;
    const weight = sb.font === "clasica" ? "900 " : "";
    let size = Math.round(sb.size * (pg.big ? 1.9 : 1.0));
    const words = pg.words;
    let active = -1;
    words.forEach((w, i) => { if (w.s - 0.02 <= t) active = i; });
    const setF = (sz) => { ctx.font = `${weight}${sz}px ${fam}`; };
    setF(size);
    let space = ctx.measureText(" ").width;
    let widths = words.map(w => ctx.measureText(w.w).width);
    let total = widths.reduce((a, b) => a + b, 0) + space * (words.length - 1);
    if (total > 940) {
      size = Math.max(20, Math.floor(size * 940 / total)); setF(size);
      space = ctx.measureText(" ").width; widths = words.map(w => ctx.measureText(w.w).width);
      total = widths.reduce((a, b) => a + b, 0) + space * (words.length - 1);
    }
    const stroke = Math.max(3, Math.floor(size * 0.085));
    let x = (1080 - total) / 2;
    const cy = sb.y;
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineJoin = "round";
    words.forEach((w, i) => {
      let shown = true, sc;
      if (sb.style === "dinamico") {
        shown = t >= w.s - 0.04;
        const k = (t - (w.s - 0.04)) / 0.14;
        sc = shown ? 0.55 + 0.45 * easeOutBack(k) : 0;
      } else sc = i === active ? 1.08 : 1.0;
      sc = Math.round(sc * 20) / 20;
      const cx = x + widths[i] / 2;
      x += widths[i] + space;
      if (!shown) return;
      const fs = Math.abs(sc - 1) < 0.01 ? size : Math.max(10, Math.floor(size * (sc || 1)));
      setF(fs);
      const isAct = i === active || pg.big;
      // sombra
      ctx.lineWidth = stroke * 2; ctx.strokeStyle = "rgba(0,0,0,0.59)"; ctx.fillStyle = "rgba(0,0,0,0.59)";
      ctx.strokeText(w.w, cx + size * 0.04, cy + size * 0.06); ctx.fillText(w.w, cx + size * 0.04, cy + size * 0.06);
      if (pg.big) { ctx.shadowColor = color; ctx.shadowBlur = size * 0.36; }
      ctx.strokeStyle = "#000"; ctx.strokeText(w.w, cx, cy);
      ctx.shadowBlur = 0; ctx.shadowColor = "transparent";
      ctx.fillStyle = isAct ? color : "#fff"; ctx.fillText(w.w, cx, cy);
      setF(size);
    });
  }
}

window.CliperPreview = { Preview, cachedImg, titleUrl, TimeMap, interp, FONT_CSS, COLORS };
