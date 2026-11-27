"""Bajar solo una parte de un video de Kick.

Kick entrega el video en trozos de hasta 12 segundos. Aquí se piden solo los que tocan a los periodos elegidos y se unen
sin recomprimir, así que cada periodo empieza y termina en el borde de un trozo.
"""
import re
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import chat, directo, media, store
from .config import FFMPEG
from .ingest import LONG, PARALLEL, _detail, pick_res

MIN, MAX_N = 20, 20       # segundos que dura como mínimo un periodo y cuántos se pueden pedir
KEEP = 900                # lo que se recuerda de un video antes de volver a preguntarle a Kick
QUIET = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

_lock, _infos = threading.Lock(), OrderedDict()


# ------------------------------------------------------------ el video en Kick

class Vod:
    def __init__(self, url):
        import yt_dlp
        self.ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30})
        i = self.ydl.extract_info(url, download=False, process=False)
        self.fmts = sorted((f for f in i.get("formats") or [] if f.get("url") and f.get("height")), key=lambda f: f["height"])
        self.title, self.live = i.get("title") or "Video de Kick", bool(i.get("is_live"))
        self.at, self.lists, self.lock = time.time(), {}, threading.Lock()
        if not self.fmts:
            raise ValueError("Kick no da este video.")
        self.dur = float(i.get("duration") or 0) or sum(d for _, d, *_ in self.segs(self.fmts[0]))

    def read(self, url, f):
        from yt_dlp.networking import Request
        return self.ydl.urlopen(Request(url, headers=f.get("http_headers") or {})).read()

    def segs(self, f):
        """[(inicio, duración, enlace, corte)] de una calidad. «corte»: el reloj del video empieza de nuevo ahí."""
        with self.lock:
            if f["format_id"] not in self.lists:
                from urllib.parse import urljoin
                out, t, d, cut = [], 0.0, None, False
                for ln in self.read(f["url"], f).decode("utf-8", "ignore").splitlines():
                    ln = ln.strip()
                    if ln.startswith("#EXTINF:"):
                        d = float(re.match(r"#EXTINF:([\d.]+)", ln)[1])
                    elif ln == "#EXT-X-DISCONTINUITY":
                        cut = True
                    elif ln and not ln.startswith("#") and d is not None:
                        out.append((t, d, urljoin(f["url"], ln), cut))
                        t, d, cut = t + d, None, False
                if not out:
                    raise ValueError("Kick cambió la forma de dar el video.")
                self.lists[f["format_id"]] = out
            return self.lists[f["format_id"]]

    def pick(self, res):
        """La mayor calidad que no pase de «res»; si no hay, la menor."""
        return ([f for f in self.fmts if f["height"] <= res] or self.fmts[:1])[-1]


def vod(url, fresh=False):
    m = chat.VOD.match(url or "")
    if not m:
        raise ValueError("Los periodos solo se pueden elegir en videos de Kick.")
    key = m[0].lower()
    with _lock:
        v = _infos.get(key)
        if not v or fresh or time.time() - v.at > KEEP:
            try:
                v = Vod(m[0])
            except ValueError:
                raise
            except Exception:
                raise ValueError("Kick no da los datos de este video. Puede que ya no exista o que no haya conexión.")
            _infos[key] = v
            while len(_infos) > 6:
                _infos.popitem(last=False)
        return v


def info(url):
    v = vod(url)
    return {"title": v.title, "duration": round(v.dur, 1), "min": MIN, "max_n": MAX_N, "long": LONG,
            "q": [{"h": f["height"], "gb_h": round((f.get("tbr") or 1500) * 450 / 1e6, 3)} for f in v.fmts],
            "free_gb": round(directo.free_gb(), 1), "keep_gb": directo.FREE_GB}


# ------------------------------------------------------------ cuadros para ver dónde cortar

_frames, _few = OrderedDict(), threading.BoundedSemaphore(4)


def frame(url, t):
    """Una imagen pequeña del segundo t, sacada de la calidad más baja."""
    v = vod(url)
    f, t = v.fmts[0], max(0.0, min(float(t), v.dur - .5))
    s = next((x for x in reversed(v.segs(f)) if x[0] <= t), v.segs(f)[0])
    key = (s[2], round(t - s[0]))
    if key in _frames:
        return _frames[key]
    with _few:
        data, out = v.read(s[2], f), b""
        for at in (min(t - s[0], s[1] - .4), 0):
            out = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "mpegts", "-i", "pipe:0", "-ss", f"{max(0, at):.2f}", "-frames:v", "1",
                                  "-vf", "scale=284:160:force_original_aspect_ratio=decrease", "-c:v", "mjpeg", "-q:v", "5", "-f", "image2pipe", "-"],
                                 input=data, capture_output=True, timeout=40, **QUIET).stdout
            if out:
                break
    if not out:
        raise ValueError("No se pudo sacar esa imagen.")
    _frames[key] = out
    while len(_frames) > 400:
        _frames.popitem(last=False)
    return out


# ------------------------------------------------------------ lo que se pide

def clean(ps, dur):
    """Periodos válidos, en orden y sin encimarse. Lista vacía: es todo el video."""
    out = []
    try:
        for a, b in ps:
            a, b = max(0.0, float(a)), min(float(dur), float(b))
            if not (a == a and b == b):
                raise ValueError
            if b - a < min(MIN, dur):
                raise ValueError(f"Cada periodo debe durar al menos {MIN} segundos y estar dentro del video.")
            out.append([a, b])
    except (TypeError, ValueError) as e:
        raise ValueError(str(e) if str(e).startswith("Cada") else "Revisa los periodos.")
    if not out or len(out) > MAX_N:
        raise ValueError(f"Elige de 1 a {MAX_N} periodos.")
    out.sort()
    res = [out[0]]
    for a, b in out[1:]:
        if a <= res[-1][1] + 1:
            res[-1][1] = max(res[-1][1], b)
        else:
            res.append([a, b])
    if len(res) == 1 and res[0][0] < 2 and res[0][1] > dur - 2:
        return []
    return [[round(a, 1), round(b, 1)] for a, b in res]


def total(ps):
    return sum(b - a for a, b in ps)


def ask(url, ps, quality):
    """Revisa los periodos pedidos y que quepan en el disco. Devuelve los que se guardan (vacío: todo)."""
    v = vod(url)
    if v.live:
        raise ValueError("Este directo todavía está en vivo. Vuelve a intentarlo cuando termine.")
    ps = clean(ps, v.dur)
    if ps:
        directo.check_space((v.pick(pick_res(quality, total(ps))).get("tbr") or 1500) * 125 * total(ps) / 1e9 * 1.8)
    return ps


def runs(segs, ps):
    """Los trozos que tocan a los periodos, en grupos seguidos: [[índices]]."""
    out = []
    for a, b in ps:
        for n, (t, d, _, cut) in enumerate(segs):
            if t + d > a + .05 and t < b - .05:
                if out and n <= out[-1][-1]:
                    continue
                if out and n == out[-1][-1] + 1 and not cut:
                    out[-1].append(n)
                else:
                    out.append([n])
    return out


# ------------------------------------------------------------ bajar y unir

def _ff(args, **kw):
    r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, **QUIET, **kw)
    return r.stderr.decode("utf-8", "ignore").strip()[-300:] if r.returncode else ""


COPY = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-avoid_negative_ts", "make_zero"]


def _join(files, dst):
    """Une trozos seguidos. Primero como un solo flujo; si el reloj del video salta dentro, uno por uno."""
    exp = sum(d for _, d in files)
    part = dst.with_name(dst.stem + ".part.mp4")
    log = dst.with_name("unir.log")
    with open(log, "wb") as err:
        pr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "mpegts", "-i", "pipe:0", *COPY, "-movflags", "+faststart", str(part)],
                              stdin=subprocess.PIPE, stderr=err, **QUIET)
        try:
            for f, _ in files:
                with open(f, "rb") as fh:
                    shutil.copyfileobj(fh, pr.stdin, 4 << 20)
            pr.stdin.close()
        except OSError:
            pass
        code = pr.wait()
    got = media.probe(part)["duration"] if not code and part.exists() else 0
    if abs(got - exp) > max(3, exp * .01):
        _concat([f for f, _ in files], part)
        got = media.probe(part)["duration"]
        if abs(got - exp) > max(10, exp * .05):
            raise RuntimeError(f"No se pudieron unir las partes: salieron {got:.0f} s de {exp:.0f}.")
    part.replace(dst)
    log.unlink(missing_ok=True)


def _concat(files, dst):
    lst = dst.with_name("lista.txt")
    lst.write_text("".join(f"file '{Path(f).relative_to(dst.parent).as_posix()}'\n" for f in files), encoding="utf-8")
    err = _ff(["-f", "concat", "-safe", "0", "-i", str(lst), *COPY, "-movflags", "+faststart", str(dst)])
    if err:
        raise RuntimeError("No se pudieron unir las partes: " + err)
    lst.unlink(missing_ok=True)


def fetch(pid, p, out, cb):
    """Baja los periodos del proyecto. Devuelve (ruta, título). cb(fracción, texto). Si se corta, sigue donde iba."""
    out = Path(out)
    url, ps = p["source"]["url"], p["source"]["periods"]
    v = vod(url)
    res = pick_res(p.get("options", {}).get("download", "auto"), total(ps))
    f = v.pick(res)
    segs = v.segs(f)
    groups = runs(segs, ps)
    if not groups:
        raise RuntimeError("Esos periodos no tienen video.")
    box = out / "trozos"
    mark = box / "calidad"
    if box.exists() and (not mark.exists() or mark.read_text(encoding="utf-8") != f["format_id"]):
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    mark.write_text(f["format_id"], encoding="utf-8")
    src = [v]

    def one(n):
        dst = box / f"{n}.ts"
        for k in range(5):
            try:
                x = src[0]
                data = x.read(x.segs(x.pick(f["height"]))[n][2], f)
                if len(data) < 188 or data[0] != 0x47:
                    raise OSError("trozo incompleto")
                tmp = dst.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(dst)
                return len(data)
            except Exception:
                if k == 4:
                    raise RuntimeError("Kick dejó de dar una parte del video. Intenta de nuevo: se sigue donde se quedó.")
                time.sleep(1.5 * (k + 1))
                if k == 2:
                    try:
                        src[0] = vod(url, fresh=True)      # por si los enlaces caducaron
                    except ValueError:
                        pass

    want = [n for k, g in enumerate(groups) for n in g if not (box / f"p{k}.mp4").exists()]
    todo = [n for n in want if not (box / f"{n}.ts").exists()]
    sec, t0, got, done, last = sum(segs[n][1] for n in want) or 1, time.time(), 0, 0.0, 0
    left = sum(segs[n][1] for n in todo)
    ex = ThreadPoolExecutor(PARALLEL)
    try:
        for n, size in zip(todo, ex.map(one, todo)):
            got += size
            done += segs[n][1]
            if time.time() - last > .7:
                last = time.time()
                sp = got / max(.1, last - t0)
                cb((sec - left + done) / sec * .97, _detail({"speed": sp, "eta": (left - done) / max(.1, done / max(.1, last - t0))}, f["height"]))
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    cb(.98, "uniendo las partes")
    pieces, at = [], 0.0
    for k, g in enumerate(groups):
        dst = box / f"p{k}.mp4"
        if not dst.exists():
            _join([(box / f"{n}.ts", segs[n][1]) for n in g], dst)
        for n in g:
            (box / f"{n}.ts").unlink(missing_ok=True)
        d = media.probe(dst)["duration"]
        pieces.append([round(at, 3), round(segs[g[0]][0], 3), round(d, 3)])
        at += d
        cb(.98, "uniendo las partes")
    path = out / "source.mp4"
    if len(groups) == 1:
        (box / "p0.mp4").replace(path)
    else:
        part = box / "todo.mp4"
        _concat([box / f"p{k}.mp4" for k in range(len(groups))], part)
        real = media.probe(part)["duration"]
        if abs(real - at) > 2:
            raise RuntimeError(f"No se pudieron unir los periodos: salieron {real:.0f} s de {at:.0f}.")
        part.replace(path)
    store.update(pid, lambda q: q["source"].update(pieces=pieces))
    shutil.rmtree(box, ignore_errors=True)
    return path, v.title


# ------------------------------------------------------------ los clips no cruzan de un periodo a otro

def joints(p):
    ps = (p.get("source") or {}).get("pieces") or []
    return [y[0] for x, y in zip(ps, ps[1:]) if y[1] - x[1] - x[2] > 1]          # seguidos en el directo: no hay salto


def keep_inside(clips, p, shortest=8):
    """Un clip que quedó entre dos periodos se queda con su parte más larga; si es muy corta, se quita."""
    js, out = joints(p), []
    for c in clips:
        cuts = [c["start"], *[j for j in js if c["start"] < j < c["end"]], c["end"]]
        if len(cuts) > 2:
            a, b = max(zip(cuts, cuts[1:]), key=lambda x: x[1] - x[0])
            if b - a < shortest:
                continue
            c = {**c, "start": round(a, 3), "end": round(b, 3), "words": [w for w in c.get("words", []) if w["s"] >= a - .05 and w["e"] <= b + .05]}
        out.append(c)
    return out
