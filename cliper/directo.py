"""Directos de YouTube, tres formas de usarlos: lo que ya pasó, lo que viene, o seguirlo hora por hora.

YouTube guarda el directo en trozos de unos segundos numerados en orden y deja pedir cualquiera de los últimos 5 días.
Aquí se calcula qué trozos tocan a un horario, se bajan y se unen sin recomprimir.
"""
import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from . import media, store
from .config import DATA, FFMPEG

HOUR = 3600
OVERLAP = 30              # segundos que comparten dos horas seguidas, para no partir un momento
TAIL = 600                # un resto menor a esto se une a la última hora
MAX_BACK = 5 * 24 * HOUR - 900
MAX_SPAN = 12 * HOUR
FREE_GB = 10              # espacio que siempre se deja libre en el disco
GB_H = {"480": .4, "720": .6, "1080": 1.2}  # peso aproximado del video por hora
PARALLEL = 6
BATCH = 12
SQ = re.compile(r"([?&/]sq[=/])\d+")
FILE = DATA / "directos.json"
MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()


class NotLive(RuntimeError):
    pass


def is_youtube(url):
    h = (urlsplit(url).hostname or "").lower()
    return h == "youtu.be" or h == "youtube.com" or h.endswith(".youtube.com")


def _clock(t):
    return time.strftime("%H:%M", time.localtime(t))


def label(base, a, b):
    """«Nombre, 23 nov, 14:00 a 15:00»."""
    d = time.localtime(a)
    return f"{base}, {d.tm_mday} {MESES[d.tm_mon - 1]}, {_clock(a)} a {_clock(b)}"


def split(a, b):
    """Parte un horario en tramos de una hora."""
    out, s = [], a
    while s < b:
        e = min(s + HOUR, b)
        if b - e < TAIL:
            e = b
        out.append((s, e))
        s = e
    return out


# ------------------------------------------------------------ el directo abierto

class Stream:
    def __init__(self, url):
        self.url, self.lock, self.gen = url, threading.Lock(), 0
        self.open()

    def open(self):
        import yt_dlp
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
                                "live_from_start": True, "ffmpeg_location": FFMPEG})
        info = ydl.extract_info(self.url, download=False)
        if info.get("entries"):
            info = next(iter(info["entries"]))
        st = info.get("live_status")
        if st not in ("is_live", "post_live"):
            raise NotLive("Este directo ya no está en vivo.")
        fm = [f for f in info.get("formats") or [] if f.get("fragments")]
        self.video = [f for f in fm if f.get("vcodec") not in (None, "none") and f.get("height")]
        self.video = [f for f in self.video if f["vcodec"].startswith("avc1")] or self.video
        self.audio = max((f for f in fm if (f.get("acodec") or "").startswith("mp4a")), key=lambda f: f.get("tbr") or 0, default=None)
        if not self.video or not self.audio:
            raise RuntimeError("YouTube no deja bajar este directo por partes.")
        self.ydl, self.ended, self.title, self.bases = ydl, st == "post_live", info.get("title") or "Directo", {}
        # el título de un directo trae la fecha y la hora al final
        self.title = re.sub(r"\s+\d{4}-\d\d-\d\d \d\d:\d\d$", "", self.title)
        self.head, self.seg, self.t = 0, 5.0, time.time()
        self._base(self.audio)
        self.tick()
        self.moved, self.gen, self.opened = time.time(), self.gen + 1, time.time()

    def _base(self, f):
        k = f["format_id"]
        if k not in self.bases:
            fr = f["fragments"]
            first = next(iter(fr({}) if callable(fr) else fr))
            self.bases[k] = first["url"]
            self.head = max(self.head, int(first.get("fragment_count") or 0))
        return self.bases[k]

    def reopen(self, gen):
        with self.lock:
            if self.gen == gen:
                if time.time() - self.opened < 15:
                    time.sleep(15)
                self.open()

    def pick(self, res):
        side = lambda f: min(f["height"], f.get("width") or f["height"])
        ok = [f for f in self.video if side(f) <= res]
        # la mayor por debajo de lo pedido y, entre iguales, la de 30 fps (pesa menos y los clips salen a 30)
        return min(ok, key=lambda f: (-side(f), f.get("fps") or 30)) if ok else min(self.video, key=side)

    def _ask(self, f, n, head_only=False):
        from yt_dlp.networking import Request
        h = dict(f.get("http_headers") or {})
        if head_only:
            h["Range"] = "bytes=0-99"
        with self.ydl.urlopen(Request(SQ.sub(lambda m: m.group(1) + str(n), self._base(f)), headers=h)) as r:
            b = r.read()
            hs, ht = r.headers.get("X-Head-Seqnum"), r.headers.get("X-Head-Time-Sec")
        if hs and int(hs) > self.head:
            self.head, self.moved = int(hs), time.time()
        if hs:
            self.t = time.time()
            if ht and int(hs) > 20:
                self.seg = round(float(ht) / int(hs), 3) or 5.0
        return b

    def tick(self):
        """Actualiza cuál es el último trozo."""
        self._ask(self.audio, self.head, True)

    def get(self, fid, n):
        """Bytes de un trozo, o None si YouTube no lo tiene."""
        last = None
        for i in range(6):
            gen = self.gen
            try:
                f = self.audio if fid == "a" else next(x for x in self.video if x["format_id"] == fid)
                b = self._ask(f, n)
                if b:
                    return b
            except NotLive:
                raise
            except Exception as e:
                last = e
                code = getattr(getattr(e, "status", None), "__int__", lambda: 0)() or getattr(e, "status", 0)
                if code in (403, 410):       # el permiso del enlace caducó
                    self.reopen(gen)
                elif code == 404 and i >= 1:
                    return None
            time.sleep(1 + i)
        if last:
            raise last
        return None

    def seq_at(self, t, anchor=None):
        """Número de trozo de una hora del reloj."""
        if self.ended:
            if not anchor:
                raise NotLive("Este directo ya no está en vivo.")
            return int(anchor["head"] - (anchor["t"] - t) / anchor["seg"])
        return int(self.head - (self.t - t) / self.seg)

    def back(self):
        """Segundos hacia atrás que se pueden pedir de verdad."""
        full = min(self.head * self.seg, MAX_BACK)
        for s in [full] + [h * HOUR for h in (48, 24, 12, 6, 3, 1, .25) if h * HOUR < full]:
            try:
                if self._ask(self.audio, max(1, int(self.head - s / self.seg) + 2), True):
                    return int(s)
            except Exception:
                pass
        return 0


_streams = {}
_slock = threading.Lock()


def _stream(url, fresh=None):
    """El directo abierto, reutilizado entre proyectos del mismo enlace."""
    with _slock:
        s = _streams.get(url)
        if s is None or time.time() - s.opened > (fresh or 3 * HOUR):
            s = _streams[url] = Stream(url)
            for k in [k for k, v in _streams.items() if time.time() - v.opened > 6 * HOUR]:
                _streams.pop(k)
        return s


def _clean(e):
    return re.sub(r"\x1b\[[\d;]*m|^ERROR:\s*(\[[^\]]+\]\s*\S+:\s*)?", "", str(e)).strip()


# ------------------------------------------------------------ Kick: guarda la grabación mientras transmite

KICK = re.compile(r"^https?://(?:www\.)?kick\.com/([\w-]+)(?:/videos(?:/([0-9a-f-]{36}))?)?/?(?:[?#].*)?$", re.I)
WAIT = 60                 # cada cuánto se revisa si ya terminó
WAIT_MAX = 48 * HOUR


def _kick_live(url):
    """La grabación en curso de un canal o enlace de Kick: {url, title, started, live}. None si no está en su lista."""
    import yt_dlp
    m = KICK.match(url)
    if not m or m[1].lower() in ("video", "categories", "search", "auth"):
        return None
    slug, vid = m[1].lower(), (m[2] or "").lower()
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "socket_timeout": 20}) as ydl:
        info = ydl.extract_info(f"https://kick.com/{slug}/videos", download=False, process=False)
        for e in info.get("entries") or []:
            if (e["id"].lower() == vid) if vid else e.get("is_live"):
                return {"url": f"https://kick.com/{slug}/videos/{e['id']}", "title": e.get("title") or "Directo",
                        "started": e.get("timestamp"), "live": bool(e.get("is_live"))}
    return None


def _kick_total(url):
    """Segundos que lleva la grabación."""
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "socket_timeout": 20}) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        f = min(info["formats"], key=lambda f: f.get("height") or 9999)
        txt = ydl.urlopen(yt_dlp.networking.Request(f["url"], headers=f.get("http_headers") or {})).read().decode("utf-8", "ignore")
    return sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", txt))


def wait_end(pid, say):
    """Espera a que termine el directo del proyecto. Devuelve «fin», «parar» (no esperar más) o None si lo borraron."""
    p = store.load(pid)
    url, lv = p["source"]["url"], p["source"]["live"]
    t0, off, bad, gone, since, total, moved, n = time.time(), 0, 0, 0, 0, None, time.time(), 0
    while True:
        try:
            k = _kick_live(url)
            bad, gone = 0, 0 if k else gone + 1
            # dos veces seguidas: Kick a veces parpadea al reconectar
            off = off + 1 if k and not k["live"] else 0
            if off >= 2:
                return "fin"
            if k and k["live"] and n % 5 == 0:      # por si Kick lo deja «en vivo» después de acabar
                t = _kick_total(url)
                if total is None or t > total + 1:
                    total, moved = t, time.time()
                elif time.time() - moved > 15 * 60:
                    return "fin"
            n += 1
            if gone >= 5:
                raise RuntimeError("Kick ya no tiene la grabación de este directo.")
            el = time.time() - (lv.get("started") or t0)
            say("Parece que ya terminó, se confirma en un minuto" if off else f"Esperando a que termine el directo · lleva {_mins(el)}")
        except RuntimeError:
            if gone >= 5:
                raise
            bad += 1
        except Exception:
            bad += 1
        if bad:
            since = since if bad > 1 else time.time()
            if time.time() - since > 12 * HOUR:
                raise RuntimeError("Kick no responde desde hace 12 horas.")
            say("Esperando a que termine el directo · Kick no responde, se vuelve a intentar")
        if time.time() - t0 > WAIT_MAX:
            raise RuntimeError("El directo sigue después de 48 horas.")
        end = time.time() + WAIT
        while time.time() < end:
            q = store.load(pid)
            if q is None:
                return None
            if (q["source"].get("live") or {}).get("stop"):
                return "parar"
            time.sleep(min(2, WAIT))


def inspect(url):
    """¿Está en vivo? Título y hasta dónde se puede ir hacia atrás."""
    if KICK.match(url):
        try:
            k = _kick_live(url)
        except Exception as e:
            return {"live": False, "error": _clean(e)[:300]}
        if not k or not k["live"]:
            return {"live": False}
        return {"live": True, "site": "kick", "title": k["title"], "started": k["started"], "now": time.time(), "free_gb": round(free_gb(), 1),
                "keep_gb": FREE_GB, "gb_h": GB_H, "url": k["url"]}
    if not is_youtube(url):
        return {"live": False}
    try:
        s = _stream(url, 300)
        s.tick()
        if s.ended:
            return {"live": False}
        return {"live": True, "title": s.title, "back": s.back(), "now": time.time(), "free_gb": round(free_gb(), 1),
                "keep_gb": FREE_GB, "gb_h": GB_H, "max_span": MAX_SPAN}
    except NotLive:
        return {"live": False}
    except Exception as e:
        return {"live": False, "error": _clean(e)[:300]}


def free_gb():
    return shutil.disk_usage(DATA).free / 1e9


# ------------------------------------------------------------ bajar y unir

def _res(quality):
    return int(quality) if str(quality) in ("1080", "720", "480") else 720


def fetch_project(pid, p, d, cb):
    """Baja (o graba) el tramo del proyecto. Devuelve (ruta, título). cb(fracción, texto)."""
    lv, out = p["source"]["live"], Path(d) / "src"
    rec = lv["mode"] == "next"
    parts = out / "trozos"
    s = _stream(p["source"]["url"]) if not lv.get("a") else None
    if s:
        s.tick()
        a, b = s.seq_at(lv["from"], lv.get("anchor")), s.seq_at(lv["to"], lv.get("anchor"))
        if not rec:
            b = min(b, s.head - 1)
        a = max(1, a)
        if b <= a:
            raise RuntimeError("Ese horario no tiene video.")
        fid = s.pick(_res(p.get("options", {}).get("download")))["format_id"]
        # se guardan para que, si se corta, siga con los mismos trozos
        store.update(pid, lambda q: q["source"]["live"].update(a=a, b=b, fid=fid, seg=s.seg))
        lv = {**lv, "a": a, "b": b, "fid": fid, "seg": s.seg}
    parts.mkdir(parents=True, exist_ok=True)
    a, b, fid = lv["a"], lv["b"], lv["fid"]
    vf, af = lambda n: parts / f"v{n}", lambda n: parts / f"a{n}"
    res, t0, got = "", time.time(), [0]

    def one(job):
        kind, n = job
        f = vf(n) if kind == "v" else af(n)
        if f.exists():
            return
        data = s.get(fid if kind == "v" else "a", n)
        if data:
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(f)
            got[0] += len(data)

    def state():
        q = store.load(pid)
        return None if q is None else bool(q["source"].get("live", {}).get("stop"))

    missing = [n for n in range(a, b + 1) if not (vf(n).exists() and af(n).exists())]
    if missing:
        try:
            s = s or _stream(p["source"]["url"])
            s.tick()
        except NotLive:
            if len(missing) == b - a + 1:
                raise
            s = None
    if s and missing:
        f = next((x for x in s.video if x["format_id"] == fid), None)
        if f is None:
            raise RuntimeError("La calidad elegida ya no está en este directo.")
        res = f"{f['height']}p"
        n, total, stalled = missing[0], b - a + 1, 0
        with ThreadPoolExecutor(PARALLEL) as ex:
            while n <= b:
                st = state()
                if st is None:
                    shutil.rmtree(d, ignore_errors=True)
                    raise RuntimeError("El proyecto se borró.")
                if st:
                    break
                top = min(b, s.head if s.ended else s.head - 1)
                if n > top:
                    if s.ended:
                        break
                    if time.time() - s.moved > 90:       # no avanza: se cortó o terminó
                        stalled += 1
                        if stalled > 20:
                            break
                        try:
                            s.reopen(s.gen)
                        except NotLive:
                            break
                        except Exception:
                            pass
                    time.sleep(4)
                    try:
                        s.tick()
                    except Exception:
                        pass
                    continue
                stalled = 0
                end = min(top, n + BATCH - 1)
                try:
                    list(ex.map(one, [(k, m) for m in range(n, end + 1) for k in "va"]))
                except NotLive:
                    break
                n = end + 1
                fr = (n - a) / total
                if rec:
                    cb(min(.98, fr), f"Grabando… {_mins((n - a) * lv['seg'])} de {_mins(total * lv['seg'])} · {res}")
                else:
                    el = max(.1, time.time() - t0)
                    cb(min(.98, fr), f"Descargando… {fr * 100:.0f}% · {res} · {got[0] / el / 1e6:.1f} MB/s")
    seqs = [n for n in range(a, b + 1) if vf(n).exists() and af(n).exists()]
    if len(seqs) * lv["seg"] < 20:
        raise RuntimeError("YouTube ya no guarda esa parte del directo." if not rec else "No se alcanzó a grabar nada.")
    cb(.99, "Grabando… uniendo las partes" if rec else "Descargando… uniendo las partes")
    path = out / "source.mp4"
    _join(seqs, vf, af, out / "audio.partes", path)
    shutil.rmtree(parts, ignore_errors=True)
    if rec:   # el nombre lleva la hora real en que acabó
        end = lv["from"] + (seqs[-1] - a + 1) * lv["seg"]
        if end < lv["to"] - 90:
            store.update(pid, lambda q: q.update(name=label(lv["base"], lv["from"], end)) if q.get("name") == p.get("name") else None)
    return path, p.get("name") or "Directo"


def _mins(sec):
    m = round(sec / 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 and m % 60 else f"{m // 60} h" if m >= 60 else f"{m} min"


def _join(seqs, vf, af, tmp, path):
    """Une los trozos sin recomprimir. El video entra por la tubería para no ocupar el doble de disco."""
    with open(tmp, "wb") as fh:
        for n in seqs:
            fh.write(af(n).read_bytes())
    part = path.with_name("source.part.mp4")
    # -copyts: video y audio conservan su reloj, así siguen sincronizados aunque falte algún trozo
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-copyts", "-f", "mp4", "-i", str(tmp), "-f", "mp4", "-i", "pipe:0",
           "-map", "1:v:0", "-map", "0:a:0", "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(part)]
    log = tmp.with_name("unir.log")
    with open(log, "wb") as err:
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for n in seqs:
                pr.stdin.write(vf(n).read_bytes())
            pr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        code = pr.wait()
    if code or not part.exists() or media.probe(part)["duration"] < 5:
        raise RuntimeError("No se pudieron unir las partes: " + log.read_text(encoding="utf-8", errors="ignore").strip()[-300:])
    part.replace(path)
    tmp.unlink(missing_ok=True)
    log.unlink(missing_ok=True)


# ------------------------------------------------------------ crear los proyectos

def check_space(gb):
    if free_gb() - gb < FREE_GB:
        raise ValueError(f"No cabe: hacen falta cerca de {gb:.1f} GB y quedan {free_gb():.0f} GB libres en el disco.")


def _gb(opts, sec):
    return GB_H[str(_res(opts.get("download")))] * sec / HOUR * 1.7   # video más copia de vista previa y audio


def _project(url, name, live, opts, folder, created=None):
    p = {"id": store.new_id(), "name": name, "created": created or time.time(), "source": {"url": url, "file": None, "live": live},
         "options": opts, "folder": folder, "status": "en cola", "progress": 0, "message": "En cola…", "clips": []}
    (store.pdir(p["id"]) / "src").mkdir(parents=True, exist_ok=True)
    store.save(p)
    return p


def create(url, live, opts, folder):
    """Crea lo pedido. Devuelve (proyectos, serie). Los errores para el usuario son ValueError."""
    mode, now = live.get("mode"), time.time()
    if mode in ("after", "sofar"):
        try:
            k = _kick_live(url)
        except Exception as e:
            raise ValueError("Kick no responde. Vuelve a intentarlo en un momento. " + _clean(e)[:150])
        if not k:
            raise ValueError("No encuentro la grabación de este directo en Kick.")
        el = now - (k["started"] or now)
        check_space(_gb(opts, el))
        name = re.sub(r"\s+", " ", str(live.get("name") or "")).strip()[:70] or k["title"]
        # si justo terminó, se baja sin esperar
        lv = {"mode": "after", "base": name, "started": k["started"]} if mode == "after" and k["live"] else None
        return [_project(k["url"], name, lv, opts, folder)], None
    if not is_youtube(url):
        raise ValueError("Por ahora los directos en vivo solo funcionan con YouTube y Kick.")
    base = re.sub(r"\s+", " ", str(live.get("name") or "")).strip()[:70] or "Directo"
    if mode == "past":
        a, b = float(live["from"]), min(float(live["to"]), now)
        if b - a < 60:
            raise ValueError("El horario debe durar al menos 1 minuto y empezar antes de ahora.")
        if b - a > MAX_SPAN + 60:
            raise ValueError("Como máximo 12 horas por pedido.")
        if now - a > MAX_BACK + 900:
            raise ValueError("YouTube solo guarda los últimos 5 días del directo.")
        check_space(_gb(opts, b - a))
        out = []
        for i, (s, e) in enumerate(split(a, b)):
            out.append(_project(url, label(base, s, e), {"mode": "past", "from": s - (OVERLAP if i else 0), "to": e, "base": base},
                                dict(opts), folder, now + i * .01))
        return out, None
    if mode == "next":
        m = int(live.get("minutes") or 60)
        if not 1 <= m <= 240:
            raise ValueError("Graba entre 1 y 240 minutos.")
        check_space(_gb(opts, m * 60))
        return [_project(url, label(base, now, now + m * 60), {"mode": "next", "from": now, "to": now + m * 60, "base": base}, opts, folder)], None
    if mode == "follow":
        h, gb = int(live.get("hours") or 4), float(live.get("gb") or 20)
        if not 1 <= h <= 48:
            raise ValueError("Sigue el directo entre 1 y 48 horas.")
        if not 2 <= gb <= 2000:
            raise ValueError("El límite de espacio debe ser de al menos 2 GB.")
        check_space(_gb(opts, HOUR))
        sr = {"id": store.new_id(), "url": url, "base": base, "options": opts, "folder": folder, "hours": h, "gb": gb,
              "created": now, "next": now, "n": 0, "pids": [], "status": "activo", "note": ""}
        with _flock:
            _save(_load() + [sr])
        return [], sr
    raise ValueError("Elige qué parte del directo quieres.")


# ------------------------------------------------------------ seguir un directo

_flock = threading.RLock()


def _load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def _edit(sid, **kw):
    with _flock:
        items = _load()
        for s in items:
            if s["id"] == sid:
                s.update(kw)
                _save(items)
                return s
    return None


def _size(pids):
    tot = 0
    for pid in pids:
        for f in store.pdir(pid).rglob("*"):
            try:
                tot += f.stat().st_size if f.is_file() else 0
            except OSError:
                pass
    return tot / 1e9


def listing():
    """Los que siguen en marcha y los que acabaron hace poco."""
    out = []
    for s in _load():
        out.append({k: s.get(k) for k in ("id", "base", "hours", "gb", "n", "status", "note", "next", "folder", "pids")} |
                   {"due": s["next"] + HOUR})
    return out


def stop(sid):
    return _edit(sid, status="parado", note="Lo detuviste. Los proyectos que ya se crearon se quedan.")


def change(sid, gb=None, hours=None):
    kw = {}
    if gb is not None:
        kw["gb"] = max(2, min(2000, float(gb)))
    if hours is not None:
        kw["hours"] = max(1, min(48, int(hours)))
    return _edit(sid, **kw)


def forget(sid):
    with _flock:
        _save([s for s in _load() if s["id"] != sid])


def _step(sr, enqueue):
    now = time.time()
    if sr["status"] not in ("activo", "lleno") or now < sr["next"] + HOUR + 25 or now < sr.get("retry", 0):
        return
    sid = sr["id"]
    # no amontonar: si el equipo va atrasado, la hora que falta se baja después (YouTube la guarda 5 días)
    pend = [p for p in map(store.load, sr["pids"]) if p and p.get("status") in ("en cola", "procesando")]
    if len(pend) >= 2:
        _edit(sid, status="activo", note="El equipo va atrasado. La hora siguiente se baja cuando termine una de las anteriores.", retry=now + 30)
        return
    used, need = _size(sr["pids"]), _gb(sr["options"], HOUR)
    if used + need > sr["gb"] or free_gb() - need < FREE_GB:
        why = f"Los proyectos de este directo ya ocupan {used:.1f} GB de {sr['gb']:.0f}." if used + need > sr["gb"] else f"Quedan {free_gb():.0f} GB libres en el disco."
        _edit(sid, status="lleno", note=why + " Sube el límite o borra algún proyecto y sigue solo. No se borra nada sin ti.", retry=now + 60)
        return
    a, b = sr["next"], sr["next"] + HOUR
    if now - a > MAX_BACK:     # lo que YouTube ya no guarda se salta
        _edit(sid, next=a + HOUR)
        return
    try:
        s = _stream(sr["url"], 600)
        s.tick()
    except NotLive:
        _edit(sid, status="terminado", note="El directo terminó. Lo último puedes bajarlo con el enlace, como un video normal.")
        return
    except Exception as e:
        _edit(sid, note=f"No se pudo revisar el directo, se vuelve a intentar: {_clean(e)[:120]}", retry=now + 120)
        return
    anchor = sr.get("anchor") if s.ended else {"head": s.head, "t": s.t, "seg": s.seg}
    live = {"mode": "past", "from": a - (OVERLAP if sr["n"] else 0), "to": b, "base": sr["base"], "series": sid, "anchor": anchor}
    with _flock:
        cur = next((x for x in _load() if x["id"] == sid), None)
        if not cur or cur["status"] not in ("activo", "lleno"):
            return
        p = _project(sr["url"], label(sr["base"], a, b), live, dict(sr["options"]), sr["folder"])
        n = sr["n"] + 1
        done = n >= cur["hours"] or s.ended
        _edit(sid, n=n, next=b, pids=sr["pids"] + [p["id"]], anchor=anchor, retry=0, status="terminado" if done else "activo",
              note=("El directo terminó." if s.ended else f"Listo: se crearon {n} de {cur['hours']} horas.") if done else "")
    enqueue(p["id"])


def run(enqueue):
    """Hilo que crea el proyecto de cada hora."""
    while True:
        for sr in _load():
            try:
                _step(sr, enqueue)
            except Exception as e:
                _edit(sr["id"], note=f"Error: {str(e)[:150]}", retry=time.time() + 120)
        time.sleep(10)
