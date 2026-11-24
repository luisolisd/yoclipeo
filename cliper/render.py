"""Exportación de clips: compone fotograma a fotograma a partir del plan y codifica con ffmpeg."""
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import overlay, store
from .config import FFMPEG, OUT_FPS, OUT_H, OUT_W
from .media import NO_WINDOW, probe
from .plan import interp

QUALITIES = {"1080p": (1080, 1920, 20, "14M"), "720p": (720, 1280, 22, "8M"), "480p": (480, 854, 24, "4M")}


# ------------------------------------------------------------ filtros de color

def _lut(fn):
    x = np.arange(256, dtype=np.float32)
    return np.clip(fn(x), 0, 255).astype(np.uint8)


_LUTS = {
    "calido": (_lut(lambda x: x * 0.88), _lut(lambda x: x * 1.0 + 4), _lut(lambda x: x * 1.08 + 8)),  # B, G, R
    "cine": (_lut(lambda x: 255 * ((x / 255) ** 0.95) * 1.04 + 6), _lut(lambda x: 255 * ((x / 255) ** 1.05)),
             _lut(lambda x: 255 * ((x / 255) ** 1.1) * 1.06)),
}


def apply_filter(img, name):
    if name in ("calido", "cine"):
        b, g, r = _LUTS[name]
        img[..., 0] = cv2.LUT(img[..., 0], b)
        img[..., 1] = cv2.LUT(img[..., 1], g)
        img[..., 2] = cv2.LUT(img[..., 2], r)
        if name == "cine":
            img[:] = cv2.convertScaleAbs(img, alpha=1.08, beta=-10)
    elif name == "vivo":
        g = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        cv2.addWeighted(img, 1.35 * 1.06, g, -0.35 * 1.06, -4, dst=img)
    elif name == "bn":
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g = cv2.convertScaleAbs(g, alpha=1.15, beta=-12)
        img[:] = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


# ------------------------------------------------------------ decodificación

class Decoder:
    def __init__(self, path, start, span, info, pad_frames=0):
        W, H = info["width"], info["height"]
        if W >= H:
            dh = min(1080, H)
            dw = int(round(W * dh / H / 2)) * 2
        else:
            dw = min(1080, W)
            dh = int(round(H * dw / W / 2)) * 2
        self.w, self.h = dw, dh
        self.size = dw * dh * 3
        self.pad = pad_frames
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-ss", f"{max(0, start):.3f}", "-i", str(path),
               "-t", f"{span:.3f}", "-an", "-vf", f"fps={OUT_FPS},scale={dw}:{dh}:flags=bicubic",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=NO_WINDOW, bufsize=self.size * 2)
        self.last = np.zeros((dh, dw, 3), np.uint8)
        self.done = False

    def read(self):
        if self.pad > 0:
            self.pad -= 1
            return np.zeros((self.h, self.w, 3), np.uint8)
        if self.done:
            return self.last
        buf = self.p.stdout.read(self.size)
        if len(buf) < self.size:
            self.done = True
            return self.last
        self.last = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
        return self.last

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass


# ------------------------------------------------------------ composición

def crop_rect(track, t, zoom, fw, fh):
    cx, cy, cw, ch = interp(track, t)
    if zoom > 1.0001:
        ch0 = ch
        cw, ch = cw / zoom, ch / zoom
        cy = cy - 0.35 * (ch0 - ch)
    cx = min(max(cx, cw / 2), 1 - cw / 2)
    cy = min(max(cy, ch / 2), 1 - ch / 2)
    x0 = int(round((cx - cw / 2) * fw))
    y0 = int(round((cy - ch / 2) * fh))
    w = max(2, int(round(cw * fw)))
    h = max(2, int(round(ch * fh)))
    x0 = min(max(0, x0), fw - w)
    y0 = min(max(0, y0), fh - h)
    return x0, y0, w, h


def compose(plan, t, frames, canvas):
    z = interp(plan["zoom"], t)[0] if plan["zoom"] else 1.0
    for pn in plan["panels"]:
        src = frames.get(pn["src"])
        if src is None:
            continue
        fh, fw = src.shape[:2]
        x0, y0, w, h = crop_rect(pn["track"], t, z if pn.get("zoom") else 1.0, fw, fh)
        dx, dy, dw, dh = pn["dst"]
        crop = src[y0:y0 + h, x0:x0 + w]
        if pn.get("blur"):
            small = cv2.resize(crop, (max(2, dw // 10), max(2, dh // 10)), interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (0, 0), 3)
            out = cv2.resize(small, (dw, dh), interpolation=cv2.INTER_LINEAR)
            out = cv2.convertScaleAbs(out, alpha=0.55)
        else:
            out = cv2.resize(crop, (dw, dh), interpolation=cv2.INTER_LINEAR)
        canvas[dy:dy + dh, dx:dx + dw] = out
    if plan["filter"] != "ninguno":
        apply_filter(canvas, plan["filter"])
    draw_overlays(plan, t, canvas)


def draw_overlays(plan, t, canvas):
    ti = plan["title"]
    if ti["on"] and t <= ti["until"]:
        img = overlay.render_title(ti["text"], ti.get("font", "clasica"), ti.get("style", "caja"),
                                   ti.get("color", "blanco"), ti.get("size", 62))
        overlay.blend(canvas, img, 0, ti.get("y", 250))
    for b in plan.get("brand", []):
        if b["s"] <= t <= b["e"]:
            im = overlay.brand_img(b["id"], b["w"], b["opacity"])
            if im is not None:
                overlay.blend(canvas, im, int(round(b["x"] - im.width / 2)), int(round(b["y"] - im.height / 2)))
    for st in plan["stickers"]:
        if st["s"] <= t <= st["e"]:
            sc, rot = overlay.sticker_scale(t, st["s"], st["e"])
            size = int(st["size"] * sc)
            if size < 4:
                continue
            base = overlay.emoji_img(st["value"], st["size"]) if st["kind"] == "emoji" else overlay.logo_img(st["value"], st["size"])
            im = base.resize((max(1, int(base.width * sc)), max(1, int(base.height * sc))))
            im = im.rotate(rot, expand=True, resample=3)
            overlay.blend(canvas, im, int(st["x"] - im.width / 2), int(st["y"] - im.height / 2))
    sb = plan["subs"]
    if sb["on"]:
        for pg in sb["pages"]:
            if pg["s"] <= t < pg["e"]:
                active, vis, scales = overlay.page_state(pg, t, sb["style"])
                img, _ = overlay.render_page(pg["words"], sb["font"], sb["size"], sb["color"], sb["style"],
                                             pg["big"], active, vis, scales)
                overlay.blend(canvas, img, 0, int(sb["y"] - img.height / 2))
                break


# ------------------------------------------------------------ exportación

def _audio_filter(plan, s0):
    sel = "+".join(f"between(t,{a - s0:.3f},{b - s0:.3f})" for a, b in plan["segments"])
    return (f"aselect='{sel}',asetpts=N/SR/TB,loudnorm=I=-14:TP=-1.5:LRA=11,"
            f"aresample=48000")


def video_args(enc, crf, maxrate):
    """Argumentos de ffmpeg para codificar el video con cada codificador. La calidad es equivalente a la de libx264."""
    cap = ["-maxrate", maxrate, "-bufsize", "20M"]
    if enc == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", str(crf + 3), "-b:v", "0",
                "-spatial-aq", "1", *cap]
    if enc == "qsv":
        return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", str(crf + 2), *cap]
    if enc == "amf":
        return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak",
                "-b:v", f"{int(maxrate[:-1]) * 6 // 10}M", *cap]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), *cap]


def export(plan, src_path, out_path, quality="1080p", progress_cb=None, srcB_path=None, encoder=None):
    """Exporta el clip. Si el codificador de la GPU falla a mitad, se repite con el procesador."""
    from . import equipo
    enc = encoder or equipo.encoder()
    try:
        return _export(plan, src_path, out_path, quality, progress_cb, srcB_path, enc)
    except EncodeError:
        if enc == "cpu" or quality == "mp3":
            raise
        equipo.note_encoder_failed(enc)
        return _export(plan, src_path, out_path, quality, progress_cb, srcB_path, "cpu")


class EncodeError(RuntimeError):
    pass


def _export(plan, src_path, out_path, quality, progress_cb, srcB_path, encoder):
    out_path = Path(out_path)
    info = probe(src_path)
    s0 = plan["segments"][0][0]
    span = plan["segments"][-1][1] - s0
    if quality == "mp3":
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-ss", f"{s0:.3f}", "-t", f"{span:.3f}", "-i", str(src_path),
                "-vn", "-af", _audio_filter(plan, s0), "-c:a", "libmp3lame", "-b:a", "192k", str(out_path)]
        r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace")[-1200:])
        return out_path
    ow, oh, crf, maxrate = QUALITIES.get(quality, QUALITIES["1080p"])
    decA = Decoder(src_path, s0, span + 0.2, info)
    decB = None
    if plan["sources"].get("B") and srcB_path:
        infoB = probe(srcB_path)
        bstart = s0 + plan["sources"]["B"]["offset"]
        pad = int(round(-bstart * OUT_FPS)) if bstart < 0 else 0
        decB = Decoder(srcB_path, max(0, bstart), span + 0.2, infoB, pad)
    if info["has_audio"]:
        ain = ["-ss", f"{s0:.3f}", "-t", f"{span + 0.1:.3f}", "-i", str(src_path)]
        afilter = f"[1:a]{_audio_filter(plan, s0)}[a]"
    else:
        ain = ["-f", "lavfi", "-t", f"{plan['duration']:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        afilter = "[1:a]anull[a]"
    pix = "yuv420p" if encoder == "cpu" else "nv12"
    vfilter = f"[0:v]scale={ow}:{oh}:flags=lanczos,format={pix}[v]" if ow != OUT_W else f"[0:v]format={pix}[v]"
    enc = [FFMPEG, "-hide_banner", "-nostdin", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(OUT_FPS), "-i", "-",
           *ain, "-filter_complex", f"{vfilter};{afilter}", "-map", "[v]", "-map", "[a]",
           *video_args(encoder, crf, maxrate),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(out_path)]
    ep = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    err = []
    threading.Thread(target=lambda: err.append(ep.stderr.read()), daemon=True).start()
    segs = plan["segments"]
    total_src = int(round(span * OUT_FPS))
    j = 0
    t_start = time.time()
    # Tubería en 3 hilos: decodificar → componer (este hilo) → escribir a ffmpeg
    import queue
    inq, outq = queue.Queue(maxsize=6), queue.Queue(maxsize=6)

    stop = threading.Event()

    def put(item):
        while not stop.is_set():
            try:
                inq.put(item, timeout=0.2)
                return True
            except queue.Full:
                pass
        return False

    def reader():
        for i in range(total_src):
            ts = s0 + i / OUT_FPS
            fa = decA.read()
            fb = decB.read() if decB else None
            if any(a - 1e-6 <= ts < b for a, b in segs):
                if not put((i, fa.copy(), None if fb is None else fb.copy())):
                    return
        put(None)

    write_err = []

    def writer():
        while True:
            buf = outq.get()
            if buf is None:
                break
            if write_err:  # ffmpeg ya falló: seguir vaciando la fila para no dejar colgada la exportación
                continue
            try:
                ep.stdin.write(buf)
            except Exception as e:
                write_err.append(e)

    tr = threading.Thread(target=reader, daemon=True)
    tw = threading.Thread(target=writer, daemon=True)
    tr.start()
    tw.start()
    try:
        while True:
            item = inq.get()
            if item is None:
                break
            i, fa, fb = item
            t_out = j / OUT_FPS
            if t_out > plan["duration"] or write_err:
                break
            canvas = np.zeros((OUT_H, OUT_W, 3), np.uint8)
            compose(plan, t_out, {"A": fa, "B": fb}, canvas)
            outq.put(canvas.tobytes())
            j += 1
            if progress_cb and j % 15 == 0:
                progress_cb(min(0.99, i / max(1, total_src)), j / max(0.01, time.time() - t_start))
        outq.put(None)
        tw.join()
        try:
            ep.stdin.close()
        except OSError:
            pass
        ep.wait()
    finally:
        stop.set()
        decA.close()
        if decB:
            decB.close()
    if ep.returncode != 0:
        raise EncodeError("Error al codificar:\n" + (err[0].decode("utf-8", "replace")[-1500:] if err else ""))
    return out_path


def thumbnail(plan, src_path, out_path, width=360):
    """Miniatura vertical del clip: fotograma a 1/3 del clip con su encuadre, título, marca,
    subtítulos y filtro, tal como se verá (el título y la marca se muestran aunque a esa altura
    del clip ya no estén en pantalla)."""
    from .media import frame_at
    t = plan["duration"] / 3
    pages = [pg for pg in plan["subs"]["pages"] if pg["e"] - pg["s"] > 0.2] if plan["subs"]["on"] else []
    if pages:  # que se vea un subtítulo: la frase más cercana a 1/3 del clip
        pg = min(pages, key=lambda pg: abs((pg["s"] + pg["e"]) / 2 - t))
        t = pg["s"] + 0.75 * (pg["e"] - pg["s"])
    from .plan import TimeMap
    ts = TimeMap(plan["segments"]).to_src(t)
    fr = frame_at(src_path, ts, width=960)
    if fr is None:
        return None
    canvas = np.zeros((OUT_H, OUT_W, 3), np.uint8)
    frames = {"A": fr, "B": None}
    big = 10 ** 9
    lite = {**plan, "title": {**plan["title"], "until": big},
            "brand": [{**b, "s": 0, "e": big} for b in plan.get("brand", [])]}
    compose(lite, t, frames, canvas)
    small = cv2.resize(canvas, (width, int(width * OUT_H / OUT_W)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])   # imwrite no guarda en rutas con acentos
    if ok:
        Path(out_path).write_bytes(jpg.tobytes())
    return out_path
