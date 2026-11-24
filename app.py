"""Clips verticales con IA, en local. El nombre visible está en cliper/config.py (APP_NAME).

Arranque:  .venv\\Scripts\\python app.py   →  http://127.0.0.1:8765
"""
import sys

if __name__ == "__main__" and "--servidor" not in sys.argv:
    # este proceso solo vigila y actualiza; el trabajo lo hace otro (ver cliper/arranque.py)
    from cliper import arranque
    sys.exit(arranque.run(sys.argv[1:]))

import json
import shutil
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cliper import actualizar, arranque, config, defaults, directo, equipo, jobs, plan, store, sync, youtube
from cliper.analyze import make_clip
from cliper.transcribe import all_words

app = FastAPI(title=config.APP_NAME)
HOST, PORT = "127.0.0.1", 8765


@app.middleware("http")
async def no_cache_ui(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/version")
def ui_version():
    """Cambia cuando se actualiza la interfaz (web/): la página abierta se recarga sola."""
    return {"v": int(max(f.stat().st_mtime for f in config.WEB.iterdir() if f.is_file()))}


@app.get("/app-name.js")
def app_name():
    return Response(f"window.APP_NAME = {json.dumps(config.APP_NAME)}; window.APP_VERSION = {json.dumps(config.VERSION)}; "
                    f"window.APP_AUTHOR = {json.dumps(config.AUTHOR)}; window.APP_NOTICE = {json.dumps(config.NOTICE)}; "
                    f"window.APP_DONATE = {json.dumps(config.DONATE_URL if config.DONATE_URL.startswith('https://') else '')};", media_type="text/javascript")


def _p(pid):
    p = store.load(pid)
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


def _public(p, full=True):
    q = {k: v for k, v in p.items() if k != "clips"}
    q["n_clips"] = len(p.get("clips", []))
    # dónde cae cada clip en el video (para el mapa de la biblioteca)
    q["marks"] = [{"id": c["id"], "t": c.get("title", ""), "s": round(c["start"], 1), "e": round(c["end"], 1), "score": c.get("score", 0),
                   "v": c.get("thumb_v", 0)} for c in p.get("clips", [])]
    q["n_exports"] = sum(1 for c in p.get("clips", []) if c.get("exports"))
    if full:
        q["clips"] = [{k: v for k, v in c.items() if k != "words"} | {"n_words": len(c.get("words", []))}
                      for c in p.get("clips", [])]
    return q


# ------------------------------------------------------------ ajustes

@app.get("/api/settings")
def get_settings():
    s = config.load_settings()
    key = s.get("api_key", "")
    return {"model": s["model"], "whisper_model": s["whisper_model"], "has_key": bool(key),
            "key_hint": (key[:7] + "…" + key[-4:]) if len(key) > 12 else "",
            "engine": s["engine"], "ollama_model": s["ollama_model"], "ollama_dir": s["ollama_dir"],
            "local_url": s["local_url"], "local_model": s["local_model"], "has_local_key": bool(s["local_key"]),
            "encoder": s["encoder"], "updates": s["updates"],
            "fonts": {k: v["label"] for k, v in config.FONTS.items()}, "colors": config.COLORS,
            "title_styles": config.TITLE_STYLES, "title_colors": config.TITLE_COLORS}


@app.post("/api/settings")
def set_settings(body: dict):
    from cliper import local_server
    keys = ("api_key", "model", "whisper_model", "engine", "ollama_model", "ollama_dir", "encoder", "local_url", "local_model", "local_key", "updates")
    clean = {k: v.strip() for k, v in body.items() if k in keys and isinstance(v, str)}
    if "local_url" in clean:
        old = config.load_settings()
        try:
            base = local_server.normalize(clean["local_url"])
            if base and clean["local_url"] != old["local_url"]:
                c = local_server.check(base)
                if not c["allowed"] and body.get("local_confirm") is not True:
                    raise HTTPException(409, f"{c['host']} está fuera de tu red: confírmalo antes de guardarlo")
                clean["local_ok"] = "" if c["home"] else base
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        if not clean.get("local_key"):
            clean.pop("local_key", None)
            if clean["local_url"] != old["local_url"]:  # la clave de un servidor no se manda a otro
                clean["local_key"] = ""
        if body.get("local_key_clear") is True:
            clean["local_key"] = ""
    if clean.get("updates", "on") not in ("on", "off"):
        raise HTTPException(400, "Valor no válido")
    config.save_settings(clean)
    local_server.forget()
    return get_settings()


@app.post("/api/servidor/check")
def servidor_check(body: dict):
    from cliper import local_server
    try:
        return local_server.check(str(body.get("url", "")))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/servidor/scan")
def servidor_scan():
    from cliper import local_server
    return {"found": local_server.scan()}


@app.post("/api/servidor/test")
def servidor_test(body: dict):
    from cliper import local_server
    s, url = config.load_settings(), str(body.get("url", "")).strip()
    key = str(body.get("key") or "") or (s["local_key"] if url == s["local_url"] else "")
    return local_server.test(url, str(body.get("model") or "auto"), key, body.get("confirm") is True)


@app.get("/api/ollama")
def ollama_status():
    from cliper import local_llm
    return local_llm.status()


@app.post("/api/ollama/pull")
def ollama_pull(body: dict):
    from cliper import local_llm
    try:
        local_llm.pull(str(body.get("model", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return local_llm.status()


@app.post("/api/ollama/lookup")
def ollama_lookup(body: dict):
    from cliper import local_llm
    try:
        return local_llm.lookup(str(body.get("model", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/ollama/delete")
def ollama_delete(body: dict):
    from cliper import local_llm
    if _working():
        raise HTTPException(409, "Hay un análisis o una exportación en marcha. Bórralo cuando termine.")
    try:
        local_llm.delete(str(body.get("model", "")))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return local_llm.status()


@app.delete("/api/ollama/pull")
def ollama_pull_stop():
    from cliper import local_llm
    local_llm.pull_stop()
    return {"ok": True}


# ------------------------------------------------------------ actualizaciones

def _from_here(request):
    """Solo desde la página del programa: otra página abierta en el navegador no puede pedirlo."""
    from urllib.parse import urlsplit
    h, o = request.headers.get("host", ""), request.headers.get("origin", "")
    if urlsplit("//" + h).hostname not in ("127.0.0.1", "localhost") or (o and urlsplit(o).netloc != h):
        raise HTTPException(403, "No permitido")


@app.get("/api/update")
def update_status():
    return actualizar.status()


@app.post("/api/update/check")
def update_check(request: Request):
    _from_here(request)
    return actualizar.check()


@app.post("/api/update/install")
def update_install(request: Request, body: dict):
    _from_here(request)
    try:
        actualizar.install(str(body.get("version", "")))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return actualizar.status()


# ------------------------------------------------------------ publicar en YouTube

def _yt(request, fn, *a):
    _from_here(request)
    try:
        return fn(*a)
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "Faltan datos")
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/youtube")
def yt_status():
    return youtube.status()


@app.post("/api/youtube/client")
def yt_client(request: Request, body: dict):
    _yt(request, youtube.set_client, body.get("id", ""), body.get("key", ""))
    return youtube.status()


@app.post("/api/youtube/connect")
def yt_connect(request: Request, body: dict | None = None):
    return {"url": _yt(request, youtube.connect, PORT, bool((body or {}).get("lists")))}


@app.get("/api/youtube/listas")
def yt_lists(request: Request):
    return _yt(request, youtube.playlists)


@app.post("/api/youtube/disconnect")
def yt_disconnect(request: Request):
    return {"note": _yt(request, youtube.clear), **youtube.status()}


@app.get("/youtube/callback")
def yt_callback(state: str = "", code: str = "", error: str = ""):
    """Aquí vuelve Google después de pedir el permiso."""
    import html
    try:
        t, m = "YouTube está conectado", f"Canal: {youtube.callback(state, code, error)}. Ya puedes cerrar esta pestaña y volver a {config.APP_NAME}."
    except Exception as e:
        t, m = "No se pudo conectar", str(e) if isinstance(e, youtube.YTError) else "Algo falló. Vuelve a intentarlo desde Ajustes."
    page = ('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(t) +
            '</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#12181a;color:#e9ece9;font:16px/1.5 system-ui">'
            f'<main style="max-width:30rem;padding:24px"><h1 style="font-size:1.5rem">{html.escape(t)}</h1><p>{html.escape(m)}</p></main>')
    return Response(page, media_type="text/html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                                           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@app.get("/api/hashtags")
def tags_list():
    return youtube.hashtags()


@app.put("/api/hashtags")
def tags_save(request: Request, body: dict):
    return _yt(request, youtube.set_hashtags, body.get("fav"))


@app.get("/api/publicaciones")
def pub_list(pid: str = "", cid: str = ""):
    return youtube.listing(pid, cid)


@app.post("/api/publicaciones")
def pub_add(request: Request, body: dict):
    return _yt(request, youtube.add, body)


@app.post("/api/publicaciones/{i}/{what}")
def pub_do(request: Request, i: str, what: str):
    fn = {"reintentar": youtube.retry, "cancelar": youtube.cancel, "quitar": youtube.forget, "lista": youtube.relist}.get(what)
    if not fn:
        raise HTTPException(404)
    _yt(request, fn, i)
    return {"ok": True}


# ------------------------------------------------------------ tu equipo

def _working():
    return any(j["status"] in ("en cola", "renderizando") for j in jobs.list_jobs() if j["kind"] == "export") or \
        any(p.get("status") == "procesando" and not (p.get("message") or "").startswith(("Descargando", "Grabando")) for p in store.list_all())


@app.get("/api/equipo")
def get_equipo():
    from cliper import local_llm, local_server
    from cliper.analyze import choose_engine
    return {**equipo.report(), "ollama": local_llm.status(), "server": local_server.status(), "engine": choose_engine(), "working": _working()}


@app.post("/api/equipo/test")
def test_equipo():
    if _working():
        raise HTTPException(409, "Hay un análisis o una exportación en marcha. Prueba cuando termine.")
    equipo.test_all()
    return {"ok": True}


@app.post("/api/equipo/seen")
def seen_equipo():
    equipo.set_seen()
    return {"ok": True}


# ------------------------------------------------------------ proyectos

@app.get("/api/projects")
def list_projects():
    return [_public(p, full=False) for p in store.list_all()]


@app.post("/api/projects")
async def create_project(file: UploadFile | None = File(None), url: str = Form(""), options: str = Form("{}")):
    opts = json.loads(options or "{}")
    if opts.get("live"):
        live, fol = opts.pop("live"), opts.pop("folder", None)
        try:
            ps, serie = directo.create(url.strip(), live, opts, fol if fol in {f["id"] for f in _folders()} else None)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e) if isinstance(e, ValueError) else "Faltan datos del directo")
        for p in ps:
            jobs.enqueue_project(p["id"])
        return {"n": len(ps), "serie": serie["id"] if serie else None, **(_public(ps[0]) if ps else {})}
    pid = store.new_id()
    d = store.pdir(pid)
    (d / "src").mkdir(parents=True, exist_ok=True)
    src = {"url": url.strip() or None, "file": None}
    name = opts.get("name") or ""
    if file is not None and file.filename:
        dest = d / "src" / ("source" + Path(file.filename).suffix.lower())
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh, length=8 * 1024 * 1024)
        src["file"] = str(dest)
        name = name or Path(file.filename).stem
    elif opts.get("local_path"):
        lp = Path(opts["local_path"].strip('"'))
        if not lp.is_file():
            raise HTTPException(400, "No existe ese archivo")
        src["file"] = str(lp)
        name = name or lp.stem
    elif not src["url"]:
        raise HTTPException(400, "Sube un archivo o pega un enlace")
    folder = opts.pop("folder", None)
    folder = folder if folder in {f["id"] for f in _folders()} else None
    p = {"id": pid, "name": name or src["url"], "created": time.time(), "source": src, "options": opts,
         "folder": folder, "status": "en cola", "progress": 0, "message": "En cola…", "clips": []}
    store.save(p)
    jobs.enqueue_project(pid)
    return _public(p)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _public(_p(pid))


@app.put("/api/projects/{pid}")
def update_project(pid: str, body: dict):
    """Renombrar el proyecto o moverlo de carpeta (folder = id de carpeta, o null para «Sin carpeta»)."""
    _p(pid)
    fids = {f["id"] for f in _folders()}

    def f(q):
        if "name" in body and str(body["name"]).strip():
            q["name"] = str(body["name"]).strip()[:120]
        if "folder" in body:
            q["folder"] = body["folder"] if body["folder"] in fids else None
    return _public(store.update(pid, f), full=False)


@app.post("/api/projects/{pid}/detener")
def stop_recording(pid: str):
    """Termina la grabación de un directo y sigue con lo que se alcanzó a grabar."""
    p = _p(pid)
    if not p["source"].get("live") or p["source"].get("file"):
        raise HTTPException(400, "Este proyecto ya no está en un directo")
    store.update(pid, lambda q: q["source"]["live"].update(stop=True))
    return {"ok": True}


# ------------------------------------------------------------ directos

@app.get("/api/directo")
def check_live(url: str):
    return directo.inspect(url.strip())


@app.get("/api/directos")
def list_live():
    return directo.listing()


@app.put("/api/directos/{sid}")
def change_live(sid: str, body: dict):
    if not directo.change(sid, body.get("gb"), body.get("hours")):
        raise HTTPException(404, "No existe")
    return {"ok": True}


@app.post("/api/directos/{sid}/detener")
def stop_live(sid: str):
    if not directo.stop(sid):
        raise HTTPException(404, "No existe")
    return {"ok": True}


@app.delete("/api/directos/{sid}")
def forget_live(sid: str):
    directo.forget(sid)
    return {"ok": True}


# ------------------------------------------------------------ carpetas

FOLDERS = config.DATA / "carpetas.json"
FOLDER_COLORS = ["#ffc531", "#53fc18", "#9146ff", "#2bd9ff", "#ff4fd8", "#ff8a1f", "#3ddc84", "#ff5a5a"]


def _folders():
    return json.loads(FOLDERS.read_text(encoding="utf-8")) if FOLDERS.exists() else []


def _save_folders(items):
    FOLDERS.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


@app.get("/api/folders")
def list_folders():
    counts = {}
    for p in store.list_all():
        counts[p.get("folder")] = counts.get(p.get("folder"), 0) + 1
    return {"folders": [dict(f, n=counts.get(f["id"], 0)) for f in _folders()],
            "total": sum(counts.values()), "loose": counts.get(None, 0)}


@app.post("/api/folders")
def new_folder(body: dict):
    name = str(body.get("name", "")).strip()[:40]
    if not name:
        raise HTTPException(400, "Ponle un nombre a la carpeta")
    items = _folders()
    if any(f["name"].lower() == name.lower() for f in items):
        raise HTTPException(400, "Ya existe una carpeta con ese nombre")
    low = name.lower()
    color = "#53fc18" if "kick" in low else "#9146ff" if "twitch" in low else "#ff0000" if "youtube" in low \
        else FOLDER_COLORS[len(items) % len(FOLDER_COLORS)]
    f = {"id": store.new_id(6), "name": name, "color": color}
    _save_folders(items + [f])
    return f


@app.put("/api/folders/{fid}")
def edit_folder(fid: str, body: dict):
    items = _folders()
    for f in items:
        if f["id"] == fid:
            if str(body.get("name", "")).strip():
                f["name"] = str(body["name"]).strip()[:40]
            if isinstance(body.get("color"), str) and body["color"].startswith("#"):
                f["color"] = body["color"][:9]
    _save_folders(items)
    return {"ok": True}


@app.delete("/api/folders/{fid}")
def del_folder(fid: str):
    """Borra solo la carpeta: sus proyectos pasan a «Sin carpeta» (no se borra ningún video)."""
    _save_folders([f for f in _folders() if f["id"] != fid])
    defaults.remove(fid)  # y sus predeterminados
    for p in store.list_all():
        if p.get("folder") == fid:
            store.update(p["id"], lambda q: q.update(folder=None))
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _p(pid)
    store.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/reanalyze")
def reanalyze(pid: str, body: dict | None = None):
    _p(pid)
    body = dict(body or {})
    only_select = bool(body.pop("only_select", False))
    allowed = {"mode", "style", "max_clips", "min_len", "max_len", "remove_silence", "language", "whole"}
    body = {k: v for k, v in body.items() if k in allowed}
    if body:
        store.update(pid, lambda q: q["options"].update(body))
    jobs.enqueue_project(pid, only_select)
    return _public(store.load(pid))


@app.get("/api/projects/{pid}/proxy")
def proxy(pid: str):
    f = store.pdir(pid) / "proxy.mp4"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4")


@app.get("/api/projects/{pid}/thumb/{cid}")
def thumb(pid: str, cid: str):
    f = store.pdir(pid) / "thumbs" / f"{cid}.jpg"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{pid}/wave")
def get_wave(pid: str, a: float = 0, b: float = 0, n: int = 600):
    """Forma de onda del audio entre los segundos a y b (vacía si el video no tiene audio)."""
    from cliper import wave
    f = store.pdir(pid) / "audio.wav"
    return {"peaks": wave.peaks(f, max(0, a), b, n) if f.exists() else []}


@app.get("/api/projects/{pid}/transcript")
def transcript(pid: str):
    f = store.pdir(pid) / "transcript.json"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/json")


# ------------------------------------------------------------ clips

@app.get("/api/projects/{pid}/clips/{cid}")
def get_clip(pid: str, cid: str):
    c = store.find_clip(_p(pid), cid)
    if not c:
        raise HTTPException(404)
    return c


EDITABLE = {"title", "description", "hashtags", "start", "end", "words", "emojis", "keywords"}


@app.put("/api/projects/{pid}/clips/{cid}")
def update_clip(pid: str, cid: str, body: dict):
    p = _p(pid)
    c = store.find_clip(p, cid)
    if not c:
        raise HTTPException(404)
    look = lambda x: json.dumps([x.get("edit"), x.get("title"), x.get("words"), x.get("emojis")], sort_keys=True)
    old_look = look(c)
    retime = ("start" in body or "end" in body) and "words" not in body

    def f(q):
        cc = store.find_clip(q, cid)
        for k, v in body.items():
            if k == "edit" and isinstance(v, dict):
                cc["edit"].update(v)
            elif k in EDITABLE:
                cc[k] = v
        if retime:
            tf = store.pdir(pid) / "transcript.json"
            tr = json.loads(tf.read_text(encoding="utf-8"))
            kws = {w["w"].lower() for w in cc.get("words", []) if w.get("key")}
            mine = {round(w["s"], 3): w for w in cc.get("words", [])}  # conservar lo que ya se corrigió a mano
            cc["words"] = [mine.get(round(w["s"], 3)) or dict(w, key=w["w"].lower() in kws) for w in all_words(tr)
                           if w["s"] >= cc["start"] - 0.05 and w["e"] <= cc["end"] + 0.05]
        if cc["start"] >= cc["end"]:
            cc["end"] = cc["start"] + 1
    q = store.update(pid, f)
    cc = store.find_clip(q, cid)
    if look(cc) != old_look or retime:  # la miniatura muestra título, marca, subtítulos y encuadre
        jobs.schedule_thumb(pid, cid)
    return cc


@app.post("/api/projects/{pid}/clips")
def new_clip(pid: str, body: dict):
    p = _p(pid)
    s, e = float(body.get("start", 0)), float(body.get("end", 30))
    tf = store.pdir(pid) / "transcript.json"
    words = all_words(json.loads(tf.read_text(encoding="utf-8"))) if tf.exists() else []
    layout = p["clips"][0]["edit"]["layout"] if p.get("clips") else "vertical"
    c = make_clip(s, e, words, {"title": body.get("title", "MI CLIP"), "score": 0, "category": "Manual"}, layout)
    defaults.dress_manual(c, p.get("folder"))
    store.update(pid, lambda q: q["clips"].insert(0, c))
    threading.Thread(target=jobs.make_thumb, args=(pid, c["id"]), daemon=True).start()
    return c


@app.post("/api/projects/{pid}/clips/{cid}/duplicate")
def dup_clip(pid: str, cid: str):
    import copy
    p = _p(pid)
    c = store.find_clip(p, cid)
    n = copy.deepcopy(c)
    n["id"] = store.new_id(6)
    n["exports"] = []
    n["title"] = c["title"]
    store.update(pid, lambda q: q["clips"].insert(q["clips"].index(store.find_clip(q, cid)) + 1, n))
    threading.Thread(target=jobs.make_thumb, args=(pid, n["id"]), daemon=True).start()
    return n


@app.delete("/api/projects/{pid}/clips/{cid}")
def del_clip(pid: str, cid: str):
    store.update(pid, lambda q: q.update(clips=[c for c in q["clips"] if c["id"] != cid]))
    return {"ok": True}


@app.post("/api/projects/{pid}/clips/{cid}/plan")
def get_plan(pid: str, cid: str, body: dict | None = None):
    try:
        return plan.build(pid, cid, (body or {}).get("edit"))
    except KeyError:
        raise HTTPException(404)


@app.post("/api/projects/{pid}/clips/{cid}/auto-streamer")
def auto_streamer(pid: str, cid: str):
    from cliper import vision
    p = _p(pid)
    c = store.find_clip(p, cid)
    vf = store.pdir(pid) / "vision.json"
    return plan.auto_streamer(vision.load(vf) if vf.exists() else None, c)


@app.post("/api/projects/{pid}/sync/{other}")
def sync_two(pid: str, other: str):
    a, b = store.pdir(pid) / "audio.wav", store.pdir(other) / "audio.wav"
    if not a.exists() or not b.exists():
        raise HTTPException(400, "Los dos proyectos necesitan audio ya procesado")
    off, conf = sync.offset(a, b)
    return {"offset": round(off, 3), "confidence": round(conf, 3)}


@app.post("/api/projects/{pid}/clips/{cid}/export")
def export(pid: str, cid: str, body: dict):
    q = body.get("quality", "1080p")
    if q not in ("1080p", "720p", "480p", "mp3"):
        raise HTTPException(400, "Calidad no válida")
    return jobs.enqueue_export(pid, cid, q)


@app.get("/api/projects/{pid}/files/{name}")
def get_export(pid: str, name: str):
    f = (store.pdir(pid) / "exportados" / name).resolve()
    if f.parent != (store.pdir(pid) / "exportados").resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, filename=name)


@app.post("/api/projects/{pid}/open-folder")
def open_folder(pid: str):
    import os
    d = store.pdir(pid) / "exportados"
    d.mkdir(exist_ok=True)
    os.startfile(d)
    return {"ok": True}


# ------------------------------------------------------------ trabajos y descargas

@app.get("/api/jobs")
def list_jobs():
    return jobs.list_jobs()


@app.post("/api/downloads")
def new_download(body: dict):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Pega un enlace")
    return jobs.enqueue_download(url, "mp3" if body.get("format") == "mp3" else "video")


@app.get("/api/downloads")
def downloads():
    idx = config.DOWNLOADS / "index.json"
    return json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []


@app.get("/api/downloads/file/{name}")
def download_file(name: str):
    f = (config.DOWNLOADS / name).resolve()
    if f.parent != config.DOWNLOADS.resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, filename=name)


# ------------------------------------------------------------ imágenes compartidas con la vista previa

def _png(img):
    import io
    from fastapi.responses import Response
    b = io.BytesIO()
    img.save(b, "PNG")
    return Response(b.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/img/title")
def img_title(text: str, font: str = "clasica", style: str = "caja", color: str = "blanco", size: int = 62):
    from cliper import overlay
    font = font if font in config.FONTS else "clasica"
    style = style if style in config.TITLE_STYLES else "caja"
    color = color if color in config.TITLE_COLORS else "blanco"
    return _png(overlay.render_title(text[:120], font, style, color, max(30, min(130, size))))


# ------------------------------------------------------------ stickers de marca

def _brand_list():
    idx = config.BRAND / "index.json"
    items = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
    return [b for b in items if (config.BRAND / f"{b['id']}.png").exists()]


@app.get("/api/brand")
def brand_list():
    return _brand_list()


@app.post("/api/brand")
async def brand_upload(file: UploadFile = File(...)):
    import io
    from PIL import Image
    data = await file.read()
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise HTTPException(400, "No es una imagen válida (usa PNG, JPG o WEBP)")
    im = im.convert("RGBA")
    if max(im.size) > 1600:
        r = 1600 / max(im.size)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop(bb)  # quita el margen transparente
    bid = store.new_id(8)
    im.save(config.BRAND / f"{bid}.png", "PNG")
    items = _brand_list() + [{"id": bid, "name": Path(file.filename or "sticker").stem[:40],
                              "w": im.width, "h": im.height}]
    (config.BRAND / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items[-1]


@app.delete("/api/brand/{bid}")
def brand_delete(bid: str):
    items = [b for b in _brand_list() if b["id"] != bid]
    (config.BRAND / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    f = config.BRAND / f"{bid}.png"
    if f.exists() and f.parent == config.BRAND:
        f.unlink()
    return {"ok": True}


@app.get("/api/img/brand/{bid}")
def img_brand(bid: str, w: int = 260, o: int = 100):
    from cliper import overlay
    if not bid.isalnum():
        raise HTTPException(404)
    im = overlay.brand_img(bid, max(16, min(1080, w)), max(5, min(100, o)))
    if im is None:
        raise HTTPException(404)
    return _png(im)


# ------------------------------------------------------------ predeterminados (generales y por carpeta)

def _folder_or_none(fid):
    if not fid:
        return None
    if fid not in {f["id"] for f in _folders()}:
        raise HTTPException(404, "Esa carpeta ya no existe")
    return fid


@app.get("/api/defaults")
def get_defaults():
    d = defaults.load()
    names = {f["id"]: f["name"] for f in _folders()}
    return {"general": d["general"], "carpetas": {k: v for k, v in d["carpetas"].items() if k in names}}


@app.get("/api/defaults/resolved")
def resolved_defaults(folder: str = ""):
    """Lo que tocaría usar en esa carpeta (lo suyo y, en lo que no defina, lo general)."""
    return defaults.resolve(folder or None)


@app.post("/api/defaults")
def set_defaults(body: dict):
    """Guarda predeterminados desde un clip (pid, cid, groups) o desde las opciones del inicio (options).
    folder = id de carpeta; vacío = generales."""
    folder = _folder_or_none(body.get("folder"))
    try:
        if isinstance(body.get("options"), dict):
            vals = defaults.from_options(body["options"], folder)
        else:
            c = store.find_clip(_p(body.get("pid", "")), body.get("cid", ""))
            if not c:
                raise HTTPException(404)
            groups = [g for g in body.get("groups", ("titulo", "subtitulos")) if g in defaults.EDITOR_GROUPS]
            if not groups:
                raise ValueError("Marca al menos una opción")
            vals = defaults.from_clip(c["edit"], groups)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    defaults.put(vals, folder)
    return get_defaults()


@app.delete("/api/defaults")
def remove_defaults(folder: str = "", group: str = ""):
    """Quita un grupo (o todos, si no se dice cuál) de una carpeta o de los generales."""
    if group and group not in defaults.GROUPS:
        raise HTTPException(400, "Grupo desconocido")
    defaults.remove(folder or None, group or None)
    return get_defaults()


@app.post("/api/projects/{pid}/clips/{cid}/use-defaults")
def use_defaults(pid: str, cid: str):
    """Pone en este clip los predeterminados de la carpeta de su proyecto (o los generales)."""
    from cliper import vision
    p = _p(pid)
    if not store.find_clip(p, cid):
        raise HTTPException(404)
    if not any(g in defaults.resolve(p.get("folder")) for g in defaults.EDITOR_GROUPS):
        raise HTTPException(400, "Todavía no has guardado predeterminados para esta carpeta ni generales.")
    vp = store.pdir(pid) / "vision.json"
    vis = vision.load(vp) if vp.exists() else None
    q = store.update(pid, lambda q: defaults.dress_existing(store.find_clip(q, cid), q.get("folder"), vis))
    jobs.schedule_thumb(pid, cid)
    return store.find_clip(q, cid)


APPLY_GROUPS = {
    "encuadre": ("layout", "framing", "manual_x", "streamer", "split"),
    "subtitulos": ("style", "font", "color", "subs_on", "sub_y", "sub_size", "upper"),
    "titulo": ("title_on", "title_secs", "title_style", "title_font", "title_color", "title_size", "title_y"),
    "dinamico": ("zooms", "emojis_on", "logos_on", "remove_silence", "filter"),
    "marca": ("brand",),
}


@app.post("/api/projects/{pid}/clips/{cid}/apply-all")
def apply_all(pid: str, cid: str, body: dict):
    """Copia la configuración de este clip (por grupos) a todos los clips del proyecto.
    No toca lo propio de cada clip: texto del título, subtítulos, inicio/fin ni emojis."""
    p = _p(pid)
    src = store.find_clip(p, cid)
    if not src:
        raise HTTPException(404)
    keys = [k for g in body.get("groups", []) if g in APPLY_GROUPS for k in APPLY_GROUPS[g]]
    if not keys:
        raise HTTPException(400, "Elige al menos un grupo de ajustes")
    vals = json.loads(json.dumps({k: src["edit"][k] for k in keys if k in src["edit"]}))
    changed = []

    def f(q):
        for c in q["clips"]:
            if c["id"] != cid:
                c["edit"].update(json.loads(json.dumps(vals)))
                changed.append(c["id"])
    store.update(pid, f)
    _regen_thumbs(pid, changed)
    return {"ok": True, "n": len(changed)}


def _regen_thumbs(pid, cids):
    """Rehace en segundo plano las miniaturas de varios clips (una tras otra)."""
    def run():
        for c in cids:
            jobs.make_thumb(pid, c)
    threading.Thread(target=run, daemon=True).start()


@app.post("/api/projects/{pid}/brand-all")
def brand_all(pid: str, body: dict):
    """Copia los stickers de marca de un clip a todos los clips del proyecto."""
    _p(pid)
    brand = body.get("brand") or []
    store.update(pid, lambda q: [c["edit"].update(brand=json.loads(json.dumps(brand))) for c in q["clips"]])
    ids = [c["id"] for c in store.load(pid)["clips"]]
    _regen_thumbs(pid, ids)
    return {"ok": True, "n": len(ids)}


@app.get("/api/img/emoji")
def img_emoji(c: str, size: int = 210):
    from cliper import overlay
    return _png(overlay.emoji_img(c[:8], max(16, min(400, size))))


@app.get("/api/img/logo/{name}")
def img_logo(name: str, size: int = 230):
    from cliper import overlay
    return _png(overlay.logo_img(name, max(16, min(400, size))))


# ------------------------------------------------------------ letras para el navegador

@app.get("/fonts/{key}")
def get_font(key: str):
    spec = config.FONTS.get(key)
    if not spec:
        raise HTTPException(404)
    return FileResponse(spec["file"], media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/status")
def status():
    from cliper import local_server
    from cliper.analyze import choose_engine
    s, eng = config.load_settings(), choose_engine()
    return {"cuda": equipo.voice_attempts()[0][1] == "cuda", "has_key": bool(s.get("api_key")), "engine": eng,
            "ollama_model": s.get("ollama_model"), "claude_model": s.get("model"), "server_model": local_server.status()["label"] if eng == "servidor" else ""}


app.mount("/", StaticFiles(directory=str(config.WEB), html=True), name="web")


def _already_open():
    """¿Ya hay una ventana funcionando? Dos a la vez procesarían los mismos videos."""
    import socket
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) == 0


if __name__ == "__main__":
    import uvicorn
    watched = arranque.follow_parent(sys.argv)
    if _already_open():
        print(f"{config.APP_NAME} ya está abierto en http://{HOST}:{PORT}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://{HOST}:{PORT}")
        sys.exit(0)
    arranque.confirm_when_up(PORT)
    jobs.start()
    equipo.start(_working)
    actualizar.start(watched)
    youtube.start()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
