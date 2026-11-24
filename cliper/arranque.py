"""Arranque: abre el programa, lo vigila e instala las actualizaciones con él cerrado.

El proceso que abre la persona solo vigila; el trabajo lo hace otro («--servidor»). Así los archivos y las
librerías se cambian sin que nada los esté usando y, si la versión nueva no abre, se vuelve a la anterior.
Solo usa la biblioteca estándar de Python: tiene que funcionar aunque falle una librería.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "data" / "actualizacion"
STATE = BOX / "estado.json"
NEW, OLD = BOX / "nueva", BOX / "anterior"
RESTART = 42          # código con el que el servidor pide que se instale lo que dejó listo y se vuelva a abrir
TRY_SECS = 180        # lo que se espera a que abra la versión nueva
DIRS = {"cliper", "web", "assets"}      # lo único que toca una actualización: nunca data, models, bin ni .venv
FILES = (".bat", ".md")


def allowed(rel):
    """¿Es un archivo del programa? (rel: ruta con «/» desde la raíz)"""
    parts = rel.split("/")
    if any(x in ("", ".", "..") or x != x.strip() or x.endswith(".") or any(c in x for c in '\\:*?"<>|') for x in parts):
        return False
    if len(parts) > 1:
        return parts[0] in DIRS
    return rel == "app.py" or (rel.startswith("requirements") and rel.endswith(".txt")) or rel.lower().endswith(FILES)


def read():
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def write(**kw):
    s = {**read(), **kw}
    BOX.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    _retry(lambda: os.replace(tmp, STATE))
    return s


def _retry(fn, n=20):
    # en Windows un archivo puede estar ocupado un instante (antivirus, indexador)
    for i in range(n):
        try:
            return fn()
        except PermissionError:
            if i == n - 1:
                raise
            time.sleep(0.2 + 0.1 * i)


def _put(src, dst):
    """Copia a un lado y cambia de golpe: nunca queda un archivo a medias."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".nuevo")
    shutil.copyfile(src, tmp)
    _retry(lambda: os.replace(tmp, dst))


def _files(s):
    return [r for r in s.get("files", []) if isinstance(r, str) and allowed(r)]


def _pip(req):
    """Instala las librerías que pida la versión nueva. Devuelve el error, o vacío."""
    if sys.prefix == sys.base_prefix:
        return "no encuentro la carpeta .venv; abre «Instalar YoClipeo.bat»"
    print("Instalando librerías...", flush=True)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:], flush=True)
        lines = [x for x in r.stderr.splitlines() if x.strip()]
        return f"no se instalaron las librerías nuevas: {lines[-1][:200] if lines else 'sin detalles'}"
    return ""


def _same(a, b):
    try:
        return a.read_bytes().replace(b"\r\n", b"\n") == b.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return False


def apply():
    """Instala lo que quedó listo. Si se cortó a la mitad (se fue la luz), continúa."""
    s = read()
    if s.get("stage") == "lista":
        files = _files(s)
        print(f"Actualizando a la versión {s.get('to')}...", flush=True)
        todo = ["requirements.txt"] + (["requirements-nvidia.txt"] if (Path(sys.prefix) / "Lib/site-packages/nvidia").exists() else [])
        for name in todo:
            if (NEW / name).exists() and not _same(NEW / name, ROOT / name):
                err = _pip(NEW / name)
                if err:
                    write(stage="fallida", error=err)
                    return
        shutil.rmtree(OLD, ignore_errors=True)
        added = []
        for rel in files:
            if (ROOT / rel).exists():
                (OLD / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, OLD / rel)
            else:
                added.append(rel)
        s = write(stage="aplicando", added=added)
    if s.get("stage") == "aplicando":
        try:
            for rel in _files(s):
                _put(NEW / rel, ROOT / rel)
            write(stage="probando")
        except Exception as e:
            traceback.print_exc()
            rollback(f"no se pudieron cambiar los archivos: {e}")


def rollback(why):
    """Vuelve a la versión anterior, archivo por archivo."""
    s = read()
    print(f"La versión {s.get('to')} no quedó bien ({why}). Vuelvo a la {s.get('from')}.", flush=True)
    added = set(s.get("added", []))
    for rel in _files(s):
        try:
            if rel in added:
                (ROOT / rel).unlink(missing_ok=True)
            elif (OLD / rel).exists():
                _put(OLD / rel, ROOT / rel)
        except Exception:
            traceback.print_exc()
    write(stage="fallida", error=why)


def _in_use(port):
    with socket.socket() as k:
        k.settimeout(1)
        return k.connect_ex(("127.0.0.1", port)) == 0


def _watch(p):
    """Espera a que el servidor termine. Devuelve su código, o None si no abrió a tiempo."""
    t0 = time.time()
    while True:
        try:
            return p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if time.time() - t0 > TRY_SECS and read().get("stage") == "probando":
                p.kill()
                p.wait()
                return None


def run(argv, port=8765):
    """Lo que hace «python app.py»."""
    args, done = [a for a in argv if a != "--servidor"], False
    while True:
        if done or not _in_use(port):       # con otra ventana abierta no se toca nada
            try:
                apply()
            except Exception:
                traceback.print_exc()
        p = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--servidor", f"--padre={os.getpid()}", *args])
        try:
            rc = _watch(p)
        except KeyboardInterrupt:
            try:
                p.wait(timeout=10)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                p.kill()
            return 0
        if rc not in (0, RESTART) and read().get("stage") == "probando":
            rollback("no abrió")
        elif rc != RESTART:
            return rc
        done = True
        if "--no-browser" not in args:      # la página ya está abierta: se recarga sola
            args.append("--no-browser")


# ------------------------------------------------------------ del lado del servidor

def follow_parent(argv):
    """Si se cierra el que vigila, se cierra también el servidor. Devuelve si hay quien vigile."""
    pid = next((a[8:] for a in argv if a.startswith("--padre=")), "")
    if not pid.isdigit():
        return False
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    h = k.OpenProcess(0x00100000, False, int(pid))     # SYNCHRONIZE
    if not h:
        os._exit(0)

    def wait():
        k.WaitForSingleObject(h, 0xFFFFFFFF)
        os._exit(0)
    threading.Thread(target=wait, daemon=True, name="padre").start()
    return True


def confirm_when_up(port):
    """La versión nueva abrió bien: ya no hace falta volver atrás."""
    if read().get("stage") != "probando":
        return

    def wait():
        while not _in_use(port):
            time.sleep(0.5)
        time.sleep(3)
        if read().get("stage") == "probando":
            write(stage="hecha", error="", when=time.time())
            shutil.rmtree(NEW, ignore_errors=True)
    threading.Thread(target=wait, daemon=True, name="confirmar").start()
