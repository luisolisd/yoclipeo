"""Persistencia simple de proyectos en JSON (un archivo por proyecto)."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from .config import PROJECTS

_lock = threading.RLock()
GONE = ".borrado"     # marca de un proyecto borrado cuya carpeta aún tiene archivos en uso


def new_id(n=8):
    return uuid.uuid4().hex[:n]


def pdir(pid) -> Path:
    return PROJECTS / pid


def load(pid):
    with _lock:
        f = pdir(pid) / "project.json"
        if not f.exists() or (f.parent / GONE).exists():
            return None
        return json.loads(f.read_text(encoding="utf-8"))


def save(p):
    with _lock:
        d = pdir(p["id"])
        d.mkdir(parents=True, exist_ok=True)
        data = json.dumps(p, ensure_ascii=False, indent=1)
        # en Windows el archivo puede estar ocupado un instante (antivirus, indexador, otro proceso): reintentar
        for i in range(20):
            try:
                tmp = d / f"project.json.{uuid.uuid4().hex[:6]}.tmp"
                tmp.write_text(data, encoding="utf-8")
                tmp.replace(d / "project.json")
                return
            except PermissionError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                if i == 19:
                    raise
                time.sleep(0.1 + 0.05 * i)


def update(pid, fn):
    """Carga, aplica fn(p) y guarda de forma atómica respecto a otros hilos."""
    with _lock:
        p = load(pid)
        if p is None:
            return None
        fn(p)
        save(p)
        return p


def set_status(pid, status=None, progress=None, message=None, error=None):
    def f(p):
        if status is not None:
            p["status"] = status
        if progress is not None:
            p["progress"] = round(float(progress), 1)
        if message is not None:
            p["message"] = message
        if error is not None:
            p["error"] = error
        p["updated"] = time.time()
    return update(pid, f)


def list_all():
    out = []
    for d in PROJECTS.iterdir():
        if (d / "project.json").exists():
            try:
                p = load(d.name)
                if p:
                    out.append(p)
            except Exception:
                pass
    out.sort(key=lambda p: p.get("created", 0), reverse=True)
    return out


def gone_name(d):
    """Cómo se llamaba un proyecto borrado a medias."""
    try:
        return (d / GONE).read_text(encoding="utf-8")[:200]
    except (OSError, ValueError):
        return ""


def _mark(d, name):
    try:
        if d.exists() and not (d / GONE).exists():
            (d / GONE).write_text(name, encoding="utf-8")
    except OSError:
        pass


def _wipe(d, name=""):
    """Borra la carpeta; si algo está en uso (Windows no deja), queda marcada para terminar después.
    La marca se pone antes y se quita al final: si se apaga a la mitad, no queda un resto sin dueño."""
    with _lock:
        name = gone_name(d) or name
        _mark(d, name)
        try:
            inside = [x for x in d.iterdir() if x.name != GONE]
        except OSError:
            inside = []
        for x in inside:
            if x.is_dir() and not x.is_symlink():      # rmtree no entra en enlaces a otras carpetas
                shutil.rmtree(x, ignore_errors=True)
            else:
                try:
                    x.unlink()
                except OSError:
                    pass
        try:
            if all(x.name == GONE for x in d.iterdir()):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
        _mark(d, name)                # la carpeta misma seguía abierta
        return not d.exists()


_wiping = set()


def _wipe_later(d):
    try:
        i = 0
        while (d / GONE).exists() and not _wipe(d):       # lo intenta mientras esté abierto, cada vez más espaciado
            time.sleep(1 if i < 20 else 5 if i < 400 else 60)
            i += 1
    finally:
        with _lock:
            _wiping.discard(d)


def _keep_wiping(d):
    with _lock:
        if d in _wiping:
            return
        _wiping.add(d)
    threading.Thread(target=_wipe_later, args=(d,), daemon=True, name="borrar").start()


def delete(pid):
    """Borra el proyecto. Lo que esté abierto (la vista previa en el navegador, una descarga) se borra en cuanto se suelta.
    Devuelve si quedó algo pendiente."""
    d = pdir(pid)
    try:
        name = (load(pid) or {}).get("name") or ""
    except (OSError, ValueError):
        name = ""
    for i in range(3):
        if _wipe(d, name):
            return False
        time.sleep(.3)
    _keep_wiping(d)
    return True


def finish_deleted():
    """Al abrir: termina de borrar las carpetas que quedaron marcadas. Nunca toca una sin la marca."""
    for d in list(PROJECTS.iterdir()):
        if (d / GONE).exists() and not _wipe(d):
            _keep_wiping(d)


def find_clip(p, cid):
    for c in p.get("clips", []):
        if c["id"] == cid:
            return c
    return None
