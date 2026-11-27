"""Cuánto ocupa cada cosa en el disco, qué quedó de proyectos borrados y cómo liberarlo."""
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import config, jobs, store

FRESH = 600            # una carpeta sin proyecto pero con archivos de hace menos de esto se está creando: no se toca
PID = re.compile(r"[0-9a-f]{6,32}")
HALF = re.compile(r"\.(part|ytdl|temp|tmp)\b|\.f\d+\.", re.I)      # lo que deja una descarga cortada
_program = 0


def _link(x):
    """Un enlace o una carpeta que en realidad está en otro lado."""
    st = x.stat(follow_symlinks=False)
    return x.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def tree(d):
    """(ruta, tamaño, fecha) de todo lo que hay dentro, sin seguir accesos directos a otras carpetas."""
    out, todo = [], [str(d)]
    while todo:
        try:
            with os.scandir(todo.pop()) as it:
                for e in it:
                    try:
                        if _link(e):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            todo.append(e.path)
                        else:
                            st = os.stat(e.path)      # el de e puede estar atrasado si el archivo está creciendo
                            out.append((e.path, st.st_size, st.st_mtime))
                    except OSError:
                        pass
        except OSError:
            pass
    return out


def size(d):
    return sum(x[1] for x in tree(d))


# ------------------------------------------------------------ quién lo está usando

def who(files):
    """Los programas que tienen abiertos esos archivos, según Windows: [(pid, nombre)]."""
    try:
        import ctypes
        from ctypes import wintypes as w
        rm = ctypes.WinDLL("rstrtmgr")
    except (ImportError, OSError, AttributeError, ValueError):
        return []

    class Proc(ctypes.Structure):
        _fields_ = [("pid", w.DWORD), ("start", w.FILETIME)]

    class Info(ctypes.Structure):
        _fields_ = [("proc", Proc), ("app", w.WCHAR * 256), ("svc", w.WCHAR * 64), ("type", ctypes.c_int), ("status", w.ULONG), ("session", w.DWORD), ("restart", w.BOOL)]

    files = [str(f) for f in files][:200]
    h, key = w.DWORD(), ctypes.create_unicode_buffer(33)
    if not files or rm.RmStartSession(ctypes.byref(h), 0, key):
        return []
    try:
        if rm.RmRegisterResources(h, len(files), (w.LPCWSTR * len(files))(*files), 0, None, 0, None):
            return []
        need, n, why = w.UINT(0), w.UINT(0), w.DWORD()
        rm.RmGetList(h, ctypes.byref(need), ctypes.byref(n), None, ctypes.byref(why))
        if not need.value:
            return []
        n = w.UINT(need.value + 8)
        infos = (Info * n.value)()
        if rm.RmGetList(h, ctypes.byref(need), ctypes.byref(n), infos, ctypes.byref(why)):
            return []
        return [(infos[i].proc.pid, infos[i].app) for i in range(n.value)]
    finally:
        rm.RmEndSession(h)


def users(files):
    """Lo mismo, en palabras y sin repetir."""
    names = [config.APP_NAME if pid == os.getpid() else app or f"un programa (proceso {pid})" for pid, app in who(files)]
    return list(dict.fromkeys(names))


# ------------------------------------------------------------ restos de proyectos borrados

def _kind(d):
    """proyecto, pendiente (borrado a medias), suelta (sin proyecto), danada (no se puede leer) o ajena (no es de YoClipeo)."""
    if (d / store.GONE).exists():
        return "pendiente"
    if not PID.fullmatch(d.name):
        return "ajena"
    if not (d / "project.json").exists():
        return "suelta"
    try:
        return "proyecto" if store.load(d.name) else "suelta"
    except (OSError, ValueError):
        return "danada"


def _dirs():
    try:
        return [d for d in config.PROJECTS.iterdir() if d.is_dir() and not _link(d)]
    except OSError:
        return []


def leftovers():
    out = []
    for d in _dirs():
        k = _kind(d)
        if k == "proyecto":
            continue
        fs = [x for x in tree(d) if Path(x[0]).name != store.GONE]
        if k in ("suelta", "ajena") and (not fs or k == "suelta" and time.time() - max(x[2] for x in fs) < FRESH):
            continue
        out.append({"id": d.name, "kind": k, "name": store.gone_name(d), "size": sum(x[1] for x in fs), "files": len(fs),
                    "users": users(x[0] for x in fs) if k in ("pendiente", "suelta") else []})
    return sorted(out, key=lambda x: -x["size"])


def wipe(pid):
    """Borra (o termina de borrar) un resto. Nunca un proyecto, ni una carpeta que no se entienda."""
    d = config.PROJECTS / pid
    if not d.is_dir():
        return {"ok": True, "pending": False, "users": []}
    if not PID.fullmatch(pid) or _kind(d) not in ("pendiente", "suelta"):
        raise ValueError("Esa carpeta no es un resto de un proyecto borrado.")
    if _kind(d) == "suelta" and any(time.time() - x[2] < FRESH for x in tree(d)):
        raise ValueError("Esa carpeta se acaba de usar. Espera unos minutos.")
    pending = store.delete(pid)
    return {"ok": True, "pending": pending, "users": users(x[0] for x in tree(d) if Path(x[0]).name != store.GONE) if pending else []}


# ------------------------------------------------------------ lo demás

def _project(p):
    d = store.pdir(p["id"])
    parts = {"video": 0, "preview": 0, "audio": 0, "exports": 0, "other": 0}
    n = 0
    for f, s, _ in tree(d):
        rel = Path(f).relative_to(d).parts
        k = "video" if rel[0] == "src" else "exports" if rel[0] == "exportados" else {"proxy.mp4": "preview", "audio.wav": "audio"}.get(rel[0], "other")
        parts[k] += s
        n += k == "exports" and len(rel) == 2 and f.lower().endswith(".mp4")
    src = (p.get("source") or {}).get("file")
    return {"id": p["id"], "name": p.get("name") or "", "status": p.get("status"), "created": p.get("created", 0), "size": sum(parts.values()), "parts": parts, "n_exports": n,
            "outside": bool(src) and not Path(src).is_relative_to(d), "clips": len(p.get("clips") or [])}


def _downloads():
    busy = any(j["kind"] == "download" and j["status"] in ("en cola", "descargando") for j in jobs.list_jobs())
    idx = {x["file"]: x for x in jobs.downloads()}
    out = []
    try:
        fs = [f for f in config.DOWNLOADS.iterdir() if f.is_file() and f.name != "index.json"]
    except OSError:
        fs = []
    for f in fs:
        try:
            st = f.stat()
        except OSError:
            continue
        if f.name not in idx and busy:        # puede ser la que se está bajando
            continue
        out.append({"file": f.name, "size": st.st_size, "at": st.st_mtime, "half": bool(HALF.search(f.name)), "listed": f.name in idx})
    return sorted(out, key=lambda x: -x["size"])


def _models():
    out = []
    hub = config.MODELS / "hf" / "hub"
    for d in (hub.iterdir() if hub.is_dir() else ()):
        if d.is_dir() and d.name.startswith("models--"):
            out.append({"kind": "voz", "name": d.name.split("--")[-1].replace("faster-whisper-", ""), "size": size(d)})
    rest = size(config.MODELS) - sum(x["size"] for x in out)
    if rest > 1 << 20:
        out.append({"kind": "voz", "name": "otros archivos", "size": rest})
    try:
        from . import local_llm
        where = str(local_llm.models_dir())
        out += [{"kind": "ollama", "name": m["name"], "size": m["size"], "where": where} for m in local_llm._from_disk()]
    except Exception:
        pass
    return sorted(out, key=lambda x: -x["size"])


def _app_size():
    """El programa y sus librerías no cambian mientras corre: se mide una vez."""
    global _program
    if not _program:
        _program = sum(size(x) if x.is_dir() else x.stat().st_size for x in config.ROOT.iterdir() if x.resolve() not in (config.DATA.resolve(), config.MODELS.resolve()))
    return _program


def _free(drive):
    try:
        return shutil.disk_usage(drive + os.sep).free
    except OSError:
        return 0


def report():
    ps, left, dl, ms = sorted((_project(p) for p in store.list_all()), key=lambda x: -x["size"]), leftovers(), _downloads(), _models()
    data = sum(size(x) if x.is_dir() else x.stat().st_size for x in config.DATA.iterdir() if x.name not in ("projects", "descargas"))
    du, here = shutil.disk_usage(config.DATA), config.DATA.resolve().drive
    away = {}                         # los modelos que están en otro disco se cuentan aparte
    for m in ms:
        dr = Path(m["where"]).drive if m.get("where") else here
        if dr.lower() != here.lower():
            away[dr] = away.get(dr, 0) + m["size"]
    sums = {"projects": sum(x["size"] for x in ps), "left": sum(x["size"] for x in left), "downloads": sum(x["size"] for x in dl),
            "models": sum(x["size"] for x in ms) - sum(away.values()), "app": _app_size() + data}
    return {"disk": {"drive": here, "total": du.total, "free": du.free}, "total": sum(sums.values()), "away": [{"drive": k, "size": v, "free": _free(k)} for k, v in away.items()], "sums": sums,
            "projects": ps, "left": left, "downloads": dl, "models": ms}


def clear_exports(pid):
    """Borra los videos exportados de un proyecto. Los clips y sus ediciones se quedan: se pueden volver a exportar."""
    from . import youtube
    if not store.load(pid):
        raise ValueError("Ese proyecto ya no existe.")
    if any(j["kind"] == "export" and j["pid"] == pid and j["status"] in ("en cola", "renderizando") for j in jobs.list_jobs()) or \
            any(p["pid"] == pid and p["status"] == "exportando" for p in youtube.pubs()):
        raise ValueError("Hay un clip de este proyecto exportándose. Espera a que termine.")
    d, freed, stuck = store.pdir(pid) / "exportados", 0, []
    for f in (list(d.glob("*.mp4")) if d.is_dir() else []):
        try:
            s = f.stat().st_size
            f.unlink()
            freed += s
        except OSError:
            stuck.append(f)
    keep = {f.name for f in stuck}

    def fn(q):
        for c in q.get("clips", []):
            if c.get("exports"):
                c["exports"] = [x for x in c["exports"] if x["file"] in keep]
    store.update(pid, fn)
    jobs.tidy([j["id"] for j in jobs.list_jobs() if j["kind"] == "export" and j["pid"] == pid and j["status"] == "listo" and j.get("file") not in keep])
    return {"freed": freed, "stuck": len(stuck), "users": users(stuck)}


def drop_download(name):
    f = config.DOWNLOADS / str(name)
    if f.parent.resolve() != config.DOWNLOADS.resolve() or f.name != name or f.name == "index.json":
        raise ValueError("Esa descarga no existe.")
    if f.exists():
        if f.name not in {x["file"] for x in jobs.downloads()} and any(j["kind"] == "download" and j["status"] in ("en cola", "descargando") for j in jobs.list_jobs()):
            raise ValueError("Hay una descarga en marcha. Espera a que termine.")
        try:
            f.unlink()
        except OSError:
            u = users([f])
            raise ValueError("Windows no deja borrarla: " + (f"la tiene abierta {', '.join(u)}." if u else "está en uso."))
    jobs.drop_download(name)
    return {"ok": True}
