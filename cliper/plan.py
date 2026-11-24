"""Plan de render: describe un clip editado de forma que el navegador (vista previa)
y el motor de exportación dibujen EXACTAMENTE lo mismo.

Tiempos: "src" = segundos del video original; "out" = segundos del clip final
(difieren si se quitan silencios).
"""
import re

from . import store, vision
from .analyze import SOCIAL
from .config import OUT_FPS, OUT_H, OUT_W

GAP_CUT = 0.55     # silencios más largos que esto se recortan
GAP_PAD = 0.15     # margen que se deja a cada lado
MOTION_KEEP = 0.03  # si en el silencio hay este movimiento, se conserva ("si enseñas algo, se queda")


# ------------------------------------------------------------ segmentos y mapa de tiempo

def kept_segments(clip, vis):
    s, e = clip["start"], clip["end"]
    if not clip["edit"].get("remove_silence"):
        return [[s, e]]
    words = sorted(clip["words"], key=lambda w: w["s"])
    marks = [(s, s)] + [(w["s"], w["e"]) for w in words] + [(e, e)]
    cuts = []
    for (a0, a1), (b0, b1) in zip(marks, marks[1:]):
        gap_a, gap_b = a1, b0
        if gap_b - gap_a > GAP_CUT:
            c0, c1 = gap_a + GAP_PAD, gap_b - GAP_PAD
            if gap_a == s:
                c0 = s
            if gap_b == e:
                c1 = e
            if c1 - c0 > 0.2 and _motion(vis, c0, c1) < MOTION_KEEP:
                cuts.append((c0, c1))
    segs, cur = [], s
    for c0, c1 in cuts:
        if c0 > cur + 0.05:
            segs.append([round(cur, 3), round(c0, 3)])
        cur = max(cur, c1)
    if e > cur + 0.05:
        segs.append([round(cur, 3), round(e, 3)])
    return segs or [[s, e]]


def _motion(vis, a, b):
    if not vis:
        return 0
    fps = vis["fps"]
    sm = vis["samples"][int(a * fps): int(b * fps) + 1]
    if not sm:
        return 0
    return sum(x["motion"] for x in sm) / len(sm)


class TimeMap:
    def __init__(self, segs):
        self.segs = segs
        self.offs = []
        acc = 0.0
        for a, b in segs:
            self.offs.append(acc)
            acc += b - a
        self.duration = acc

    def to_out(self, t):
        """src → out; si t cae en un hueco recortado, devuelve el inicio del siguiente tramo."""
        for (a, b), o in zip(self.segs, self.offs):
            if t < a:
                return o
            if t <= b:
                return o + (t - a)
        return self.duration

    def to_src(self, t):
        for (a, b), o in zip(self.segs, self.offs):
            if t <= o + (b - a):
                return a + max(0.0, t - o)
        return self.segs[-1][1]


# ------------------------------------------------------------ encuadre

def base_crop(aspect, W, H):
    """Tamaño de recorte normalizado (cw, ch) con relación de aspecto `aspect` (ancho/alto)."""
    A = W / H
    if A > aspect:
        return aspect / A, 1.0
    return 1.0, A / aspect


def face_track(vis, segs, tmap, aspect, W, H, offset=0.0, manual_x=None):
    """Keyframes [t_out, cx, cy, cw, ch] siguiendo a quien habla."""
    cw, ch = base_crop(aspect, W, H)
    t0, t1 = segs[0][0], segs[-1][1]
    if manual_x is not None or not vis:
        cx = 0.5 if manual_x is None else manual_x
        cx = min(max(cx, cw / 2), 1 - cw / 2)
        return [[0.0, cx, 0.5, cw, ch], [tmap.duration, cx, 0.5, cw, ch]]
    fps = vis["fps"]
    samples = vis["samples"]
    i0 = max(0, int((t0 + offset) * fps) - 2)
    i1 = min(len(samples), int((t1 + offset) * fps) + 3)
    slots = []          # [{"x":..,"y":..,"ema":..,"seen":t}]
    cur = None          # índice de slot actual
    cam_x = None
    challenger, chal_n, missing = None, 0, 0
    keys = []
    for smp in samples[i0:i1]:
        ts = smp["t"] - offset
        if smp["cut"]:
            slots, cur, challenger, chal_n = [], None, None, 0
        vis_slots = []
        for f in smp["faces"]:
            fx, fy = f[0] + f[2] / 2, f[1] + f[3] / 2
            best, bd = None, 0.12
            for k, sl in enumerate(slots):
                d = abs(sl["x"] - fx)
                if d < bd and k not in vis_slots:
                    best, bd = k, d
            if best is None:
                slots.append({"x": fx, "y": fy, "ema": 0.0, "size": f[2]})
                best = len(slots) - 1
            sl = slots[best]
            sl["x"] = sl["x"] * 0.6 + fx * 0.4
            sl["y"] = sl["y"] * 0.6 + fy * 0.4
            sl["size"] = f[2]
            sl["ema"] = sl["ema"] * 0.75 + f[5] * 0.25
            vis_slots.append(best)
        snap = smp["cut"]
        if vis_slots:
            if cur is None or cur not in vis_slots:
                missing += 1
                if cur is None or missing >= 2:
                    cur = max(vis_slots, key=lambda k: (slots[k]["ema"], slots[k]["size"]))
                    snap, missing = True, 0
            else:
                missing = 0
                top = max(vis_slots, key=lambda k: slots[k]["ema"])
                if top != cur and slots[top]["ema"] > slots[cur]["ema"] * 1.4 + 0.002:
                    chal_n = chal_n + 1 if challenger == top else 1
                    challenger = top
                    if chal_n >= 3:
                        cur, challenger, chal_n, snap = top, None, 0, True
                else:
                    challenger, chal_n = None, 0
        target = slots[cur]["x"] if cur is not None and cur < len(slots) else (cam_x if cam_x is not None else 0.5)
        target = min(max(target, cw / 2), 1 - cw / 2)
        if cam_x is None:
            cam_x, snap = target, True
        if snap:
            old = cam_x
            cam_x = target
            if ts >= t0 and ts <= t1 and keys:
                to = tmap.to_out(ts)
                keys.append([max(0.0, to - 0.001), old, 0.5, cw, ch])
        elif abs(target - cam_x) > cw * 0.06:
            cam_x += (target - cam_x) * 0.35
        if t0 - 0.3 <= ts <= t1 + 0.3:
            keys.append([round(tmap.to_out(min(max(ts, t0), t1)), 3), round(cam_x, 4), 0.5, round(cw, 4), round(ch, 4)])
    if not keys:
        return [[0.0, 0.5, 0.5, cw, ch], [tmap.duration, 0.5, 0.5, cw, ch]]
    keys.sort(key=lambda k: k[0])
    keys[0][0] = 0.0
    if keys[-1][0] < tmap.duration:
        keys.append([tmap.duration, *keys[-1][1:]])
    return keys


def rect_crop(rect, aspect, W, H):
    """Recorte (cover) dentro de un rectángulo normalizado [x,y,w,h]."""
    x, y, w, h = rect
    rw, rh = w * W, h * H
    if rw / rh > aspect:
        chp, cwp = rh, rh * aspect
    else:
        cwp, chp = rw, rw / aspect
    return [x + w / 2, y + h / 2, cwp / W, chp / H]


def auto_streamer(vis, clip):
    """Busca la cámara del streamer (cara pequeña y quieta) y propone recuadros."""
    if not vis:
        return {"cam": [0.0, 0.0, 0.3, 0.3], "game": [0.0, 0.0, 1.0, 1.0], "cam_h": 640}
    fps = vis["fps"]
    sm = vis["samples"][int(clip["start"] * fps): int(clip["end"] * fps) + 1]
    faces = [f for s in sm for f in s["faces"]]
    if not faces:
        return {"cam": [0.0, 0.0, 0.3, 0.3], "game": [0.0, 0.0, 1.0, 1.0], "cam_h": 640}
    import statistics as st
    cx = st.median(f[0] + f[2] / 2 for f in faces)
    cy = st.median(f[1] + f[3] / 2 for f in faces)
    fw = st.median(f[2] for f in faces)
    fh = st.median(f[3] for f in faces)
    w = min(1.0, fw * 3.2)
    h = min(1.0, fh * 3.0)
    x = min(max(0.0, cx - w / 2), 1 - w)
    y = min(max(0.0, cy - h / 2.4), 1 - h)
    return {"cam": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)], "game": [0.0, 0.0, 1.0, 1.0], "cam_h": 640}


# ------------------------------------------------------------ subtítulos

def _display(w, upper):
    t = w.strip()
    t = re.sub(r"[,.;:…]+$", "", t)
    t = re.sub(r"^[\"'«]+|[\"'»]+$", "", t)
    return t.upper() if upper else t


def build_pages(clip, tmap, dynamic):
    ed = clip["edit"]
    words = [w for w in sorted(clip["words"], key=lambda w: w["s"]) if w["w"].strip()]
    max_words = 3
    max_chars = 14 if dynamic else 18
    pages, cur, chars = [], [], 0
    for i, w in enumerate(words):
        disp = _display(w["w"], ed.get("upper", True))
        if not disp:
            continue
        ow = {"w": disp, "s": round(tmap.to_out(w["s"]), 3), "e": round(tmap.to_out(w["e"]), 3),
              "key": bool(w.get("key"))}
        if dynamic and ow["key"]:
            if cur:
                pages.append(cur)
            pages.append([ow])
            cur, chars = [], 0
            continue
        if cur and (len(cur) >= max_words or chars + len(disp) > max_chars or ow["s"] - cur[-1]["e"] > 0.6):
            pages.append(cur)
            cur, chars = [], 0
        cur.append(ow)
        chars += len(disp) + 1
        if re.search(r"[.!?…]$", w["w"]):
            pages.append(cur)
            cur, chars = [], 0
    if cur:
        pages.append(cur)
    out = []
    for i, pg in enumerate(pages):
        s = pg[0]["s"]
        nxt = pages[i + 1][0]["s"] if i + 1 < len(pages) else None
        e = pg[-1]["e"] + 0.35
        if nxt is not None:
            e = min(e if nxt - pg[-1]["e"] > 0.7 else nxt, nxt)
        out.append({"s": s, "e": round(e, 3), "big": bool(dynamic and len(pg) == 1 and pg[0]["key"]), "words": pg})
    return out


def zoom_keys(pages, duration):
    keys = [[0.0, 1.0]]
    z = 1.0
    for i, pg in enumerate(pages):
        t = pg["s"]
        if t <= keys[-1][0]:
            continue
        keys.append([t, z])
        if pg["big"]:
            keys.append([t + 0.08, 1.30])
            z = 1.16
            keys.append([t + 0.5, z])
        else:
            z = 1.12 if z < 1.06 else 1.0
            keys.append([t + 0.18, z])
    keys.append([duration, z])
    out = []
    for k in keys:
        if out and k[0] <= out[-1][0]:
            continue
        out.append([round(k[0], 3), k[1]])
    return out


def norm(s):
    return re.sub(r"[^\wáéíóúüñ]", "", s.lower())


def stickers(clip, tmap, ed):
    out = []
    y = ed.get("sub_y", 1250) - 270

    def free(t):
        return all(abs(t - o["s"]) > 0.8 for o in out)

    if ed.get("logos_on"):
        for w in clip["words"]:
            n = norm(w["w"])
            for net in SOCIAL:
                if n == net or (net == "twitter" and n == "x" and False):
                    t = tmap.to_out(w["s"])
                    if free(t):
                        out.append({"kind": "logo", "value": net, "s": round(t, 3), "e": round(t + 1.3, 3),
                                    "x": 540, "y": y, "size": 230})
    if ed.get("emojis_on"):
        for pair in clip.get("emojis", []):
            target = norm(pair.get("word", ""))
            for w in clip["words"]:
                if target and norm(w["w"]) == target:
                    t = tmap.to_out(w["s"])
                    if free(t):
                        out.append({"kind": "emoji", "value": pair["emoji"], "s": round(t, 3),
                                    "e": round(t + 1.2, 3), "x": 540, "y": y, "size": 210})
                    break
    out.sort(key=lambda o: o["s"])
    return out


_brand_sizes = {}


def brand_size(bid):
    """(ancho, alto) del sticker de marca original, o None si ya no existe."""
    from .config import BRAND
    f = BRAND / f"{bid}.png"
    if not f.exists():
        return None
    key = (bid, f.stat().st_mtime)
    if key not in _brand_sizes:
        from PIL import Image
        with Image.open(f) as im:
            _brand_sizes[key] = im.size
    return _brand_sizes[key]


def brand_items(ed, dur):
    """Stickers de marca colocados en el clip: posición (centro), ancho, opacidad y cuándo se ven."""
    out = []
    for i, b in enumerate(ed.get("brand") or []):
        sz = brand_size(b.get("id", ""))
        if not sz:
            continue
        w = int(max(16, min(1080, b.get("w", 260))))
        h = max(1, round(sz[1] * w / sz[0]))
        when = b.get("when", "todo")
        s, e = (0.0, min(dur, 5.0)) if when == "inicio" else (max(0.0, dur - 5.0), dur) if when == "final" else (0.0, dur)
        out.append({"i": i, "id": b["id"], "x": int(b.get("x", 540)), "y": int(b.get("y", 1700)), "w": w, "h": h,
                    "opacity": int(max(5, min(100, b.get("opacity", 100)))), "s": round(s, 3), "e": round(e, 3)})
    return out


# ------------------------------------------------------------ plan completo

def build(pid, cid, edit_override=None):
    p = store.load(pid)
    clip = store.find_clip(p, cid)
    if clip is None:
        raise KeyError("clip no encontrado")
    if edit_override:
        clip = {**clip, "edit": {**clip["edit"], **edit_override}}
    ed = clip["edit"]
    vpath = store.pdir(pid) / "vision.json"
    vis = vision.load(vpath) if vpath.exists() else None
    W, H = p["media"]["width"], p["media"]["height"]
    segs = kept_segments(clip, vis)
    tmap = TimeMap(segs)
    dur = tmap.duration
    layout = ed.get("layout", "vertical")
    manual = ed.get("manual_x") if ed.get("framing") == "manual" else None
    panels = []
    srcB = None
    offset = 0.0
    if layout == "full":
        cw, ch = base_crop(OUT_W / OUT_H, W, H)
        panels.append({"src": "A", "dst": [0, 0, OUT_W, OUT_H], "blur": True,
                       "track": [[0, 0.5, 0.5, cw, ch], [dur, 0.5, 0.5, cw, ch]], "zoom": False})
        if W / H >= OUT_W / OUT_H:
            fh = round(OUT_W * H / W)
            dst = [0, (OUT_H - fh) // 2, OUT_W, fh]
        else:
            fw = round(OUT_H * W / H)
            dst = [(OUT_W - fw) // 2, 0, fw, OUT_H]
        panels.append({"src": "A", "dst": dst, "track": [[0, 0.5, 0.5, 1, 1], [dur, 0.5, 0.5, 1, 1]], "zoom": True})
    elif layout == "streamer" and (ed.get("streamer") or {}).get("mode") == "apilado":
        # vertical (siguiendo a quien habla) arriba; el video horizontal completo abajo
        bh = int(min(1100, max(300, round(OUT_W * H / W))))
        if ed["streamer"].get("swap"):   # opcional: horizontal arriba, vertical abajo
            vert_dst, bot_dst = [0, bh, OUT_W, OUT_H - bh], [0, 0, OUT_W, bh]
        else:
            vert_dst, bot_dst = [0, 0, OUT_W, OUT_H - bh], [0, OUT_H - bh, OUT_W, bh]
        panels.append({"src": "A", "dst": vert_dst,
                       "track": face_track(vis, segs, tmap, OUT_W / (OUT_H - bh), W, H, 0.0, manual), "zoom": True})
        g = rect_crop([0, 0, 1, 1], OUT_W / bh, W, H)
        panels.append({"src": "A", "dst": bot_dst, "track": [[0, *g], [dur, *g]], "zoom": False})
    elif layout == "streamer":
        stc = ed.get("streamer") or auto_streamer(vis, clip)
        cam_h = int(stc.get("cam_h", 640))
        a_cam = OUT_W / cam_h
        a_game = OUT_W / (OUT_H - cam_h)
        c = rect_crop(stc["cam"], a_cam, W, H)
        g = rect_crop(stc["game"], a_game, W, H)
        panels.append({"src": "A", "dst": [0, 0, OUT_W, cam_h], "track": [[0, *c], [dur, *c]], "zoom": False})
        panels.append({"src": "A", "dst": [0, cam_h, OUT_W, OUT_H - cam_h], "track": [[0, *g], [dur, *g]], "zoom": True})
    elif layout == "split" and ed.get("split") and ed["split"].get("pid"):
        sp = ed["split"]
        pB = store.load(sp["pid"])
        offset = float(sp.get("offset", 0.0))
        half = OUT_H // 2
        panels.append({"src": "A", "dst": [0, 0, OUT_W, half],
                       "track": face_track(vis, segs, tmap, OUT_W / half, W, H, 0.0, manual), "zoom": True})
        if pB:
            vB = store.pdir(sp["pid"]) / "vision.json"
            visB = vision.load(vB) if vB.exists() else None
            WB, HB = pB["media"]["width"], pB["media"]["height"]
            panels.append({"src": "B", "dst": [0, half, OUT_W, OUT_H - half],
                           "track": face_track(visB, segs, tmap, OUT_W / (OUT_H - half), WB, HB, offset, None),
                           "zoom": True})
            srcB = {"pid": sp["pid"], "w": WB, "h": HB, "offset": offset,
                    "proxy": f"/api/projects/{sp['pid']}/proxy"}
    else:
        layout = "vertical"
        panels.append({"src": "A", "dst": [0, 0, OUT_W, OUT_H],
                       "track": face_track(vis, segs, tmap, OUT_W / OUT_H, W, H, 0.0, manual), "zoom": True})
    dynamic = ed.get("style") == "dinamico"
    pages = build_pages(clip, tmap, dynamic) if ed.get("subs_on", True) else []
    zooms = zoom_keys(pages, dur) if ed.get("zooms") else [[0, 1.0], [dur, 1.0]]
    return {
        "pid": pid, "cid": cid,
        "W": OUT_W, "H": OUT_H, "fps": OUT_FPS,
        "segments": segs, "duration": round(dur, 3),
        "layout": layout, "panels": panels, "zoom": zooms,
        "filter": ed.get("filter", "ninguno"),
        "title": {"on": bool(ed.get("title_on", True) and clip.get("title")), "text": clip.get("title", ""),
                  "until": float(ed.get("title_secs") or 0) or dur,
                  "font": ed.get("title_font", "clasica"), "style": ed.get("title_style", "caja"),
                  "color": ed.get("title_color", "blanco"), "size": int(ed.get("title_size", 62)),
                  "y": int(ed.get("title_y", 250))},
        "brand": brand_items(ed, dur),
        "subs": {"on": bool(ed.get("subs_on", True)), "style": ed.get("style", "karaoke"),
                 "font": ed.get("font", "impacto"), "color": ed.get("color", "amarillo"),
                 "y": int(ed.get("sub_y", 1250)), "size": int(ed.get("sub_size", 96)), "pages": pages},
        "stickers": stickers(clip, tmap, ed),
        "sources": {"A": {"pid": pid, "w": W, "h": H, "proxy": f"/api/projects/{pid}/proxy"}, "B": srcB},
    }


def interp(keys, t):
    """Interpolación lineal de keyframes [t, v1, v2, ...]."""
    if t <= keys[0][0]:
        return keys[0][1:]
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            span = b[0] - a[0]
            k = 0 if span <= 0 else (t - a[0]) / span
            return [x + (y - x) * k for x, y in zip(a[1:], b[1:])]
    return keys[-1][1:]
