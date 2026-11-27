"""Colas de trabajo en segundo plano: análisis de proyectos, exportaciones y descargas."""
import gc
import hashlib
import json
import os
import queue
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

from . import analyze, cafe, chat, defaults, directo, ingest, media, periodos, plan, pulso, render, store, transcribe, vision
from .config import DOWNLOADS

JOBS = {}            # id -> dict (exportaciones y descargas)
_jobs_lock = threading.Lock()
_analysis_q = queue.Queue()
_render_q = queue.Queue()


def _job(kind, **kw):
    jid = store.new_id(10)
    j = {"id": jid, "kind": kind, "status": "en cola", "progress": 0.0, "created": time.time(), **kw}
    with _jobs_lock:
        JOBS[jid] = j
    return j


def _set(j, **kw):
    with _jobs_lock:
        j.update(kw)


def tidy(ids):
    """Quita de la lista trabajos que ya acabaron (los archivos no se tocan). Devuelve cuántos se quedaron."""
    with _jobs_lock:
        for i in [i for i in ids if JOBS.get(i, {}).get("status") in ("listo", "error")]:
            del JOBS[i]
        return sum(i in JOBS for i in ids)


def list_jobs():
    with _jobs_lock:
        return sorted((dict(j) for j in JOBS.values()), key=lambda j: -j["created"])


# ------------------------------------------------------------ análisis de un proyecto

class Replaced(BaseException):
    """Se pidió otra vez el mismo proyecto: esta elección ya no sirve. (BaseException para que ningún «except Exception» la tome por un fallo de la IA.)"""


class Gone(BaseException):
    """Se borró el proyecto mientras se trabajaba en él: hay que parar y no dejar archivos."""


def _sweep(pid):
    """Termina de borrar la carpeta de un proyecto borrado (Windows no deja borrar lo que estaba en uso)."""
    if not re.fullmatch(r"[0-9a-f]{6,}", pid or ""):   # nunca una carpeta que no sea la de un proyecto
        return
    d = store.pdir(pid)
    for i in range(10):
        if store.load(pid) is not None or not d.exists():
            return
        gc.collect()
        if not store._wipe(d):
            time.sleep(.5 + i * .5)
    if d.exists() and store.load(pid) is None:
        store.delete(pid)          # sigue marcada y se termina en cuanto se suelte


_ask_lock = threading.Lock()
_asked = {}    # pid -> {"n": número de la última petición, "only": solo elegir, "waiting": aún no empieza}
_running = {}  # {"pid", "n"} de lo que está en marcha


def _replaced(pid):
    with _ask_lock:
        return _running.get("pid") == pid and _asked.get(pid, {}).get("n") != _running["n"]


STAGES = [("descargando", 0, 12), ("preparando", 12, 25), ("transcribiendo", 25, 65),
          ("analizando imagen", 65, 85), ("eligiendo momentos", 85, 96), ("miniaturas", 96, 100)]


def _stage(pid, name, frac=0.0, msg=None):
    if name == "eligiendo momentos" and _replaced(pid):
        raise Replaced()
    for n, a, b in STAGES:
        if n == name:
            if store.set_status(pid, status="procesando", progress=a + (b - a) * frac, message=msg or name.capitalize() + "…") is None:
                raise Gone()
            return


def _kept_voice(d):
    """La transcripción que alcanzó a terminar antes de un cierre (None si no hay o ya no corresponde).
    El audio se saca antes de transcribir: si es más nuevo, esa transcripción es de un análisis anterior."""
    t, a = d / "transcript.json", d / "audio.wav"
    try:
        if a.exists() and t.stat().st_mtime < a.stat().st_mtime:
            return None
        tr = json.loads(t.read_text(encoding="utf-8"))
        return tr if isinstance(tr.get("segments"), list) and "language" in tr else None
    except (OSError, ValueError, AttributeError):
        return None


def process_project(pid, only_select=False, resume=False):
    d = store.pdir(pid)
    p = store.load(pid)
    opts = p.get("options", {})
    if only_select and (d / "transcript.json").exists() and (d / "vision.json").exists() and p.get("media"):
        _select_stage(pid, p, opts, json.loads((d / "transcript.json").read_text(encoding="utf-8")), p["media"])
        _ensure_proxy(pid)
        return
    try:
        if not resume and (d / "audio.wav").exists():
            os.utime(d / "audio.wav")      # análisis nuevo: la transcripción de antes deja de valer
        if p["source"].get("url") and not p["source"].get("file"):
            _stage(pid, "descargando", 0, "Descargando el video…")
            path, title = _fetch(pid, p, d)
            store.update(pid, lambda q: (q["source"].update(file=str(path)), q.update(name=q.get("name") or title)))
            p = store.load(pid)
            chat.remember(pid)
        src = Path(p["source"]["file"])
        info = media.probe(src)
        if not info["has_video"] or not info["width"]:
            raise RuntimeError("El archivo no tiene video legible.")
        store.update(pid, lambda q: q.update(media=info))
        pulso.start(pid)          # las reacciones del chat se leen mientras se transcribe
        _stage(pid, "preparando", 0, "Creando copia para la vista previa…")
        if not media.proxy_ready(src, d / "proxy.mp4", info):     # si se cortó después, no se repite
            media.make_proxy(src, d / "proxy.mp4", lambda f: _stage(pid, "preparando", f * 0.85), info["duration"])
        tr = _kept_voice(d) if resume else None
        if tr:
            _stage(pid, "transcribiendo", 1, "La voz ya estaba transcrita…")
        else:
            if info["has_audio"]:
                media.extract_audio(src, d / "audio.wav")
            _stage(pid, "transcribiendo", 0, "Buscando en qué partes hablan…")
        if tr:
            pass
        elif info["has_audio"]:
            tr = transcribe.transcribe(d / "audio.wav", opts.get("language"), info["duration"],
                                       lambda f: _stage(pid, "transcribiendo", f, f"Transcribiendo… {f * 100:.0f}%"))
        else:
            tr = {"language": "", "device": "", "model": "", "segments": []}
        transcribe.release()
        if not (resume and _kept_voice(d) == tr):
            (d / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
        _stage(pid, "analizando imagen", 0, "Buscando caras y cortes de plano…")
        pinfo = media.probe(d / "proxy.mp4")
        vision.analyze(d / "proxy.mp4", pinfo["width"], pinfo["height"], info["duration"], d / "vision.json",
                       lambda f: _stage(pid, "analizando imagen", f, f"Analizando imagen… {f * 100:.0f}%"))
        vision._cache.pop(str(d / "vision.json"), None)
        _select_stage(pid, p, opts, tr, info)
    except Exception as e:
        traceback.print_exc()
        store.set_status(pid, status="error", message="Error", error=str(e)[:1500])


def _fetch(pid, p, d):
    """Baja el video del enlace con la calidad elegida (sin elegir = 1080p, como los proyectos de antes)."""
    if p["source"].get("live"):
        return directo.fetch_project(pid, p, d, lambda f, txt: _stage(pid, "descargando", f, txt))
    if p["source"].get("periods"):
        return periodos.fetch(pid, p, d / "src", lambda f, txt="": _stage(pid, "descargando", f, f"Descargando… {f * 100:.0f}%" + (f" · {txt}" if txt else "")))
    return ingest.download(p["source"]["url"], d / "src",
                           progress_cb=lambda f, txt="": _stage(pid, "descargando", f,
                                                                f"Descargando… {f * 100:.0f}%" + (f" · {txt}" if txt else "")),
                           name_template="source.%(ext)s", quality=p.get("options", {}).get("download", "1080"),
                           for_clips=True)


def _ensure_proxy(pid):
    """Rehace la copia de vista previa si quedó vacía (p. ej. por un cierre a media copia)."""
    d = store.pdir(pid)
    px = d / "proxy.mp4"
    if px.exists() and px.stat().st_size > 1024:
        return
    p = store.load(pid)
    if p.get("status") != "listo" or not p["source"].get("file"):
        return
    msg = p.get("message", "")
    try:
        dur = p.get("media", {}).get("duration", 0)
        media.make_proxy(Path(p["source"]["file"]), px,
                         lambda f: store.set_status(pid, status="listo", progress=100,
                                                    message=f"{msg} · rehaciendo vista previa {f * 100:.0f}%"), dur)
    except Exception:
        traceback.print_exc()
    store.set_status(pid, status="listo", progress=100, message=msg)


def _select_stage(pid, p, opts, tr, info):
    d = store.pdir(pid)
    try:
        _stage(pid, "eligiendo momentos", 0.02, "La IA está eligiendo los mejores momentos…")
        layout = {"auto": "vertical", "streamer": "streamer", "apilado": "streamer",
                  "full": "full"}.get(opts.get("mode", "auto"), "vertical")
        if not tr["segments"]:
            dur = info["duration"]
            clips = [analyze.make_clip(0, dur, [], {"title": p.get("name", ""), "score": 50}, layout)]
            sel = {"engine": "sin audio"}
        else:
            def reading(f, mins):
                _stage(pid, "eligiendo momentos", 0.02, f"Leyendo las reacciones del chat… {f * 100:.0f}% (faltan unos {mins} min)")
            pulse, why = pulso.wait(pid, reading, most=1.6 * pulso.STEP * len(pulso.wanted(store.load(pid) or p)) / 8 + 300)
            clips, sel = analyze.select_clips(tr, info["duration"], opts, layout,
                                              lambda f, msg: _stage(pid, "eligiendo momentos", 0.02 + 0.96 * f, msg), pulse)
            if pulse:
                sel["chat"] = True
            elif why:
                sel["chat_error"] = why[:200]
        if not opts.get("whole"):
            clips = periodos.keep_inside(clips, store.load(pid) or p)
        vis = vision.load(d / "vision.json") if layout == "streamer" else None
        folder = (store.load(pid) or p).get("folder")  # la carpeta pudo cambiar mientras se procesaba
        for c in clips:
            defaults.dress(c, opts, folder, vis)
        store.update(pid, lambda q: q.update(clips=clips, selection=sel, language=tr["language"],
                                             transcriber=f"{tr['model']} ({tr['device']})", error=None))
        _stage(pid, "miniaturas", 0, "Creando miniaturas…")
        (d / "thumbs").mkdir(exist_ok=True)
        for i, c in enumerate(clips):
            make_thumb(pid, c["id"])
            _stage(pid, "miniaturas", (i + 1) / max(1, len(clips)))
        n = len(clips)
        msg = f"{n} clip{'s' if n != 1 else ''} listo{'s' if n != 1 else ''}"
        if sel.get("engine") in ("ollama", "servidor"):
            msg += f" · elegidos por la IA local ({sel.get('model')})"
        elif sel.get("engine") == "reglas":
            why = sel.get("fallback_reason", "")
            if "authentication" in why or "api_key" in why:
                why = "no hay API key de Claude"
            if sel.get("tried") == "reglas":
                msg += " · elegidos por reglas"
            else:
                msg += " · elegidos por reglas, sin IA (" + why[:160] + ")"
        if sel.get("chat"):
            msg += " · con las reacciones del chat"
        elif sel.get("chat_error"):
            msg += f" · sin el chat ({sel['chat_error'].rstrip('.')})"
        store.set_status(pid, status="listo", progress=100, message=msg)
    except Exception as e:
        traceback.print_exc()
        store.set_status(pid, status="error", message="Error", error=str(e)[:1500])


THUMB_FMT = 2  # 2: la miniatura lleva título, marca y subtítulos


def refresh_old_thumbs():
    """Rehace en segundo plano las miniaturas hechas con un formato anterior."""
    def run():
        for p in store.list_all():
            if p.get("status") != "listo":
                continue
            for c in p.get("clips", []):
                if c.get("thumb_fmt") != THUMB_FMT:
                    make_thumb(p["id"], c["id"])
    threading.Thread(target=run, daemon=True).start()


_thumb_timers = {}
_thumb_lock = threading.Lock()


def schedule_thumb(pid, cid, delay=1.2):
    """Rehace la miniatura un momento después del último cambio (los deslizadores mandan
    muchos cambios seguidos; así se hace una sola)."""
    key = (pid, cid)
    with _thumb_lock:
        old = _thumb_timers.pop(key, None)
        if old:
            old.cancel()
        t = threading.Timer(delay, lambda: (_thumb_timers.pop(key, None), make_thumb(pid, cid)))
        t.daemon = True
        _thumb_timers[key] = t
        t.start()


_cover_lock = threading.Semaphore(2)


def cover(pid, cid, t=0.0, width=1080):
    """Portada: el fotograma del clip en el segundo t. Devuelve (JPEG, duración del clip)."""
    p = store.load(pid)
    if not p or not store.find_clip(p, cid):
        raise ValueError("Ese clip ya no existe.")
    if not Path(p["source"]["file"]).exists():
        raise ValueError("Falta el video original.")
    with _cover_lock:
        pl = plan.build(pid, cid)
        B = pl["sources"].get("B")
        pB = store.load(B["pid"]) if B else None
        return render.cover(pl, p["source"]["file"], t, width, pB["source"]["file"] if pB else None), pl["duration"]


def make_thumb(pid, cid):
    try:
        p = store.load(pid)
        pl = plan.build(pid, cid)
        out = store.pdir(pid) / "thumbs" / f"{cid}.jpg"
        out.parent.mkdir(exist_ok=True)
        render.thumbnail(pl, p["source"]["file"], out)
        store.update(pid, lambda q: store.find_clip(q, cid).update(thumb_v=int(time.time()), thumb_fmt=THUMB_FMT))
    except Exception:
        traceback.print_exc()


# ------------------------------------------------------------ exportación

def _sig(pl):
    return hashlib.sha1(json.dumps(pl, sort_keys=True, default=str).encode()).hexdigest()


def clip_sig(pid, cid):
    """Huella de cómo saldría el clip ahora mismo (para saber si lo ya exportado sigue igual)."""
    try:
        return _sig(plan.build(pid, cid))
    except (KeyError, TypeError):
        return None


def run_export(j):
    pid, cid, quality = j["pid"], j["cid"], j["quality"]
    try:
        _set(j, status="renderizando")
        p = store.load(pid)
        clip = store.find_clip(p, cid)
        if quality != "mp3" and clip["edit"].get("chat_on") and chat.source(p):
            try:
                chat.ensure(pid, cid)
            except ValueError as e:
                raise RuntimeError(f"No se pudo leer el chat de Kick: {e} Para exportar sin chat, apágalo en la sección «Chat» del clip.")
        pl = plan.build(pid, cid)
        out_dir = store.pdir(pid) / "exportados"
        out_dir.mkdir(exist_ok=True)
        safe = "".join(ch for ch in (clip.get("title") or cid) if ch.isalnum() or ch in " -_").strip()[:50] or cid
        ext = "mp3" if quality == "mp3" else "mp4"
        out = out_dir / f"{safe} [{cid}] {quality}.{ext}"
        srcB = None
        if pl["sources"].get("B"):
            pB = store.load(pl["sources"]["B"]["pid"])
            srcB = pB["source"]["file"] if pB else None
        render.export(pl, p["source"]["file"], out, quality,
                      lambda f, fps: _set(j, progress=round(f * 100, 1), fps=round(fps, 1)), srcB)
        rec = {"quality": quality, "file": out.name, "size": out.stat().st_size, "created": time.time(), "sig": _sig(pl)}
        store.update(pid, lambda q: _add_export(q, cid, rec))
        _set(j, status="listo", progress=100, file=out.name)
        try:
            cafe.count(pid, cid)
        except Exception:
            traceback.print_exc()
    except Exception as e:
        traceback.print_exc()
        _set(j, status="error", error=str(e)[:1500])


def _add_export(q, cid, rec):
    c = store.find_clip(q, cid)
    c["exports"] = [x for x in c.get("exports", []) if x["file"] != rec["file"]] + [rec]


# ------------------------------------------------------------ descargas de original / MP3

def run_download(j):
    try:
        _set(j, status="descargando")
        path, title = ingest.download(j["url"], DOWNLOADS, lambda f, txt="": _set(j, progress=round(f * 100, 1)),
                                      audio_only=(j["format"] == "mp3"))
        info = media.probe(path)
        _set(j, status="listo", progress=100, file=path.name, title=title, size=path.stat().st_size,
             duration=info["duration"], height=info["height"])
        with _dl_lock:
            _save_downloads([{k: j[k] for k in ("id", "url", "format", "file", "title", "size", "duration", "created")}] + downloads())
    except Exception as e:
        traceback.print_exc()
        _set(j, status="error", error=str(e)[:800])


_dl_lock = threading.RLock()


def downloads():
    idx = DOWNLOADS / "index.json"
    with _dl_lock:
        return json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []


def _save_downloads(data):
    (DOWNLOADS / "index.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def drop_download(name):
    """Una descarga que se borró: sale de la lista y de los terminados de la Cola."""
    with _dl_lock:
        ds = downloads()
        if any(x["file"] == name for x in ds):
            _save_downloads([x for x in ds if x["file"] != name])
    tidy([j["id"] for j in list_jobs() if j["kind"] == "download" and j["status"] == "listo" and j.get("file") == name])


# ------------------------------------------------------------ hilos

_fetch_q = queue.Queue()


def enqueue_project(pid, only_select=False, resume=False):
    p = store.load(pid)
    if p and p["source"].get("url") and not p["source"].get("file"):
        # las descargas largas van en su propia fila para no bloquear otros proyectos
        mode = (p["source"].get("live") or {}).get("mode")
        if mode == "after":
            if pid not in _waiting:
                _waiting.add(pid)
                store.set_status(pid, status="en cola", progress=0, message="Esperando a que termine el directo")
                threading.Thread(target=_wait_live, args=(pid,), daemon=True, name="esperar").start()
            return
        if mode == "next":
            # grabar un directo dura lo que dure: va en su propio hilo para no detener las demás descargas
            threading.Thread(target=_download, args=(pid,), daemon=True, name="grabar").start()
            return
        store.set_status(pid, status="en cola", progress=0, message="En cola para descargar…")
        _fetch_q.put(pid)
        return
    # una sola petición viva por proyecto: la nueva quita la que esperaba y detiene la elección en marcha
    with _ask_lock:
        old = _asked.get(pid, {"n": 0})
        if old.get("waiting"):
            only_select = only_select and old["only"]
        n = old["n"] + 1
        _asked[pid] = {"n": n, "only": only_select, "resume": resume, "waiting": True}
        msg = "Deteniendo la elección anterior para empezar esta…" if _running.get("pid") == pid else "En cola…"
        store.set_status(pid, status="en cola", progress=0, message=msg)
    _analysis_q.put((pid, n))


def _download(pid):
    p = store.load(pid)
    if not p:
        return
    d = store.pdir(pid)
    try:
        rec = (p["source"].get("live") or {}).get("mode") == "next"
        if store.load(pid) is None:
            raise Gone()
        _stage(pid, "descargando", 0, "Grabando el directo…" if rec else "Descargando el video…")
        path, title = _fetch(pid, p, d)
        store.update(pid, lambda q: (q["source"].update(file=str(path)),
                                     q.update(name=title if q.get("name", "").startswith("http") else q.get("name") or title)))
        chat.remember(pid)
        enqueue_project(pid)
    except Gone:
        pass
    except Exception as e:
        if store.load(pid):
            traceback.print_exc()
            store.set_status(pid, status="error", message="Error", error=f"No se pudo descargar: {str(e)[:1200]}")
    _sweep(pid)


_waiting = set()


def _wait_live(pid):
    """Espera a que acabe el directo y luego lo baja como un video normal."""
    try:
        if not store.load(pid):
            return
        r = directo.wait_end(pid, lambda m: store.set_status(pid, status="en cola", progress=0, message=m))
        if r:
            store.update(pid, lambda q: q["source"].update(live=None))
            enqueue_project(pid)
    except Exception as e:
        if store.load(pid):
            traceback.print_exc()
            store.set_status(pid, status="error", message="Error", error=str(e)[:800])
    finally:
        _waiting.discard(pid)
        _sweep(pid)


def _fetch_worker():
    while True:
        _download(_fetch_q.get())


def enqueue_export(pid, cid, quality):
    j = _job("export", pid=pid, cid=cid, quality=quality)
    _render_q.put(("export", j))
    return j


def enqueue_download(url, fmt):
    j = _job("download", url=url, format=fmt)
    _render_q.put(("download", j))
    return j


def _analysis_worker():
    while True:
        pid, n = _analysis_q.get()
        with _ask_lock:
            a = _asked.get(pid)
            if not a or a["n"] != n:
                continue
            a["waiting"] = False
            _running.update(pid=pid, n=n)
        try:
            if store.load(pid):
                process_project(pid, a["only"], a["resume"])
        except Replaced:
            pass
        except Gone:
            transcribe.release()
        except Exception:
            traceback.print_exc()
        finally:
            with _ask_lock:
                _running.clear()
            _sweep(pid)


def _render_worker():
    while True:
        kind, j = _render_q.get()
        (run_export if kind == "export" else run_download)(j)


def start():
    store.finish_deleted()
    threading.Thread(target=_analysis_worker, daemon=True, name="analisis").start()
    threading.Thread(target=_fetch_worker, daemon=True, name="descargas").start()
    threading.Thread(target=_render_worker, daemon=True, name="render").start()
    # proyectos interrumpidos por un cierre → volver a encolarlos
    for p in reversed(store.list_all()):  # del más viejo al más nuevo: en el orden en que se pidieron
        if p.get("status") in ("en cola", "procesando"):
            # si ya estaba transcrito, solo repetir la elección (no re-transcribir horas de video)
            d = store.pdir(p["id"])
            t, v = d / "transcript.json", d / "vision.json"
            done = p.get("media") and v.exists() and _kept_voice(d) and v.stat().st_mtime >= t.stat().st_mtime
            enqueue_project(p["id"], only_select=bool(done), resume=True)
    threading.Thread(target=directo.run, args=(enqueue_project,), daemon=True, name="directos").start()
    refresh_old_thumbs()
