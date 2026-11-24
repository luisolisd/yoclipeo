"""Versiones nuevas: las busca solo en GitHub y, si la persona lo pide, las deja listas para instalar.

Solo lee páginas públicas del repositorio: no manda nada de este equipo.
"""
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import zipfile

from . import arranque, config, jobs, store

API = f"https://api.github.com/repos/{config.REPO}/commits/{config.BRANCH}"
RAW = f"https://raw.githubusercontent.com/{config.REPO}"
ZIP = f"https://codeload.github.com/{config.REPO}/zip"
PAGE = f"https://github.com/{config.REPO}"
EVERY = 600                 # cada 10 min; GitHub permite 60 consultas por hora sin cuenta
MAX_ZIP, MAX_OUT, MAX_FILES = 80 * 1024 ** 2, 250 * 1024 ** 2, 3000
NEEDED = {"app.py", "cliper/config.py", "cliper/arranque.py", "web/index.html", "requirements.txt"}

_lock = threading.Lock()
_wake = threading.Event()
_seen = {"sha": "", "etag": "", "version": "", "notes": [], "checked": 0.0, "error": ""}
_job = {"stage": "", "progress": 0.0, "error": ""}      # "" | descargando | reiniciando
_watched = False                                        # ¿hay quien instale? (lo abrió arranque.run)


def _tuple(v):
    return tuple(int(x) for x in v.split("."))


def _newer(v):
    return bool(v) and _tuple(v) > _tuple(config.VERSION)


def _get(url, limit, headers=None, cb=None):
    req = urllib.request.Request(url, headers={"User-Agent": "YoClipeo", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        total, out = int(r.headers.get("Content-Length") or 0), io.BytesIO()
        while True:
            b = r.read(65536)
            if not b:
                return out.getvalue(), r.headers
            out.write(b)
            if out.tell() > limit:
                raise RuntimeError("la descarga es más grande de lo esperado")
            if cb:
                cb(out.tell() / total if total else 0)


def version_in(text):
    m = re.search(r'^VERSION\s*=\s*"(\d{1,4}(?:\.\d{1,4}){1,3})"', text, re.M)
    return m.group(1) if m else ""


def notes_in(text):
    """Lo nuevo desde la versión instalada, leído de CAMBIOS.md."""
    out = []
    for m in re.finditer(r"^## +(\d{1,4}(?:\.\d{1,4}){1,3})\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S):
        if _newer(m.group(1)):
            items = [re.sub(r"[*_`]", "", x.strip()[2:]).strip()[:300] for x in m.group(2).splitlines() if x.strip().startswith("- ")]
            out.append({"v": m.group(1), "items": items[:20]})
    return out[:10]


def check():
    """Mira el último commit; solo si cambió, lee qué versión trae."""
    with _lock:
        try:
            h = {"Accept": "application/vnd.github+json"}
            if _seen["etag"]:
                h["If-None-Match"] = _seen["etag"]
            try:
                body, hd = _get(API, 2 * 1024 ** 2, h)
                sha = str(json.loads(body).get("sha", ""))
                if not re.fullmatch(r"[0-9a-f]{40}", sha):
                    raise RuntimeError("respuesta inesperada de GitHub")
                if sha != _seen["sha"]:
                    v = version_in(_get(f"{RAW}/{sha}/cliper/config.py", 512 * 1024)[0].decode("utf-8", "replace"))
                    notes = []
                    if _newer(v):
                        try:
                            notes = notes_in(_get(f"{RAW}/{sha}/CAMBIOS.md", 512 * 1024)[0].decode("utf-8", "replace"))
                        except Exception:
                            pass            # sin la lista de cambios también se puede actualizar
                    _seen.update(sha=sha, version=v, notes=notes)
                _seen["etag"] = hd.get("ETag") or ""
            except urllib.error.HTTPError as e:
                if e.code != 304:           # 304: nada nuevo
                    raise RuntimeError("GitHub pidió esperar" if e.code in (403, 429) else f"GitHub respondió {e.code}")
            _seen.update(checked=time.time(), error="")
        except Exception as e:
            _seen["error"] = "sin conexión con GitHub" if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)) else str(e)[:200]
    return status()


def _loop():
    time.sleep(5)
    while True:
        if config.load_settings()["updates"] == "on":
            check()
        _wake.wait(EVERY)
        _wake.clear()


def start(watched):
    global _watched
    _watched = watched
    threading.Thread(target=_loop, daemon=True, name="actualizaciones").start()


def busy():
    """Por qué no se puede reiniciar ahora (vacío: se puede)."""
    from . import local_llm, youtube
    for j in jobs.list_jobs():
        if j["status"] in ("en cola", "renderizando", "descargando"):
            return "Hay una exportación en marcha." if j["kind"] == "export" else "Hay una descarga en marcha."
    if youtube.active():
        return "Hay un video subiéndose a YouTube."
    for p in store.list_all():
        msg = p.get("message") or ""
        if p.get("status") == "procesando" or (p.get("status") == "en cola" and not msg.startswith("Esperando")):
            return f"Se está trabajando en «{p.get('name', '')[:60]}»."
    return "Se está descargando un modelo de IA." if local_llm._pull["on"] else ""


def blocked():
    """Por qué esta copia no se puede actualizar sola (vacío: sí se puede)."""
    if (config.ROOT / ".git").exists():
        return "Esta copia se maneja con Git: actualízala con «git pull»."
    if not _watched:
        return "Para actualizar sola, ábrela con «Iniciar YoClipeo.bat»."
    return ""


def status():
    s, last = config.load_settings(), arranque.read()
    new = _newer(_seen["version"])
    return {"current": config.VERSION, "enabled": s["updates"] == "on", "available": new and s["updates"] == "on", "version": _seen["version"] if new else "",
            "notes": _seen["notes"] if new else [], "checked": _seen["checked"], "error": _seen["error"], "page": PAGE, "job": dict(_job),
            "busy": busy() if new else "", "blocked": blocked() if new else "",
            "last": {k: last.get(k, "") for k in ("stage", "from", "to", "error")} if last.get("stage") in ("hecha", "fallida") else None}


def unpack(data, version, dest):
    """Revisa el ZIP completo antes de escribir nada y lo deja en dest. Devuelve la lista de archivos."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("la descarga llegó incompleta")
    infos = z.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_OUT:
        raise RuntimeError("el paquete es más grande de lo esperado")
    files = {}
    for i in infos:
        rel = i.filename.partition("/")[2]          # todo viene dentro de una carpeta «repo-commit»
        if i.is_dir() or not rel:
            continue
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            raise RuntimeError("el paquete trae enlaces")
        if arranque.allowed(rel):
            if rel.lower() in {f.lower() for f in files}:
                raise RuntimeError("el paquete trae archivos repetidos")
            files[rel] = z.read(i)                  # también comprueba que no venga dañado
    if not NEEDED <= set(files):
        raise RuntimeError("al paquete le faltan archivos")
    if version_in(files["cliper/config.py"].decode("utf-8")) != version:
        raise RuntimeError("el paquete no es de la versión esperada")
    for rel, b in files.items():
        if rel.endswith(".py"):
            compile(b, rel, "exec")
    shutil.rmtree(dest, ignore_errors=True)
    for rel, b in files.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(b)
    return sorted(files)


def _changed(files):
    """Solo lo que de verdad cambia (lo demás ni se toca)."""
    out = []
    for rel in files:
        a, b = arranque.NEW / rel, config.ROOT / rel
        if not (b.exists() and a.read_bytes() == b.read_bytes()):
            out.append(rel)
    return out


def install(version):
    """Descarga, revisa y pide el reinicio. Lo cambia arranque.py con el programa cerrado."""
    with _lock:
        sha, v = _seen["sha"], _seen["version"]
        if not _newer(v) or v != version:
            raise ValueError("Esa versión ya no es la más nueva. Vuelve a abrir esta ventana.")
        why = blocked() or busy()
        if why:
            raise ValueError(why)
        if _job["stage"]:
            return
        _job.update(stage="descargando", progress=0.0, error="")
    threading.Thread(target=_install, args=(sha, v), daemon=True, name="actualizar").start()


def _install(sha, v):
    try:
        data, _ = _get(f"{ZIP}/{sha}", MAX_ZIP, cb=lambda f: _job.update(progress=round(min(1, f) * 100)))
        files = _changed(unpack(data, v, arranque.NEW))
        why = busy()
        if why:
            raise RuntimeError(f"{why} Actualiza cuando termine.")
        arranque.write(stage="lista", **{"from": config.VERSION, "to": v}, sha=sha, files=files, added=[], error="")
        _job.update(stage="reiniciando", progress=100)
        time.sleep(1.5)                             # que la página alcance a enterarse
        sys.stdout.flush()
        os._exit(arranque.RESTART)
    except Exception as e:
        traceback.print_exc()
        shutil.rmtree(arranque.NEW, ignore_errors=True)
        net = isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError))
        _job.update(stage="", error="No se pudo descargar. Revisa tu internet." if net else f"No se actualizó: {str(e)[:200]}")
