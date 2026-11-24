"""IA local con Ollama: lo encuentra donde esté, lo enciende cuando hace falta y elige un modelo que quepa."""
import json
import os
import re
import shutil
import string
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import equipo
from .config import load_settings
from .media import NO_WINDOW

GB = 1024 ** 3
last_stats = {}

# Modelos recomendados, del más modesto al más grande: (nombre, bytes que descarga, memoria de video con la que va entero en la GPU).
CATALOG = [("qwen3.5:2b", int(2.5 * GB), 3.5 * GB), ("qwen3.5:4b", int(3.1 * GB), 3.9 * GB), ("qwen3.5:9b", int(6.1 * GB), 9.5 * GB)]
KNOWN = [n for n, *_ in CATALOG]
# Otros probados con esto o que suelen ir bien; se ofrecen en «Agregar modelo»
MORE = [("qwen3:8b", int(4.9 * GB)), ("gemma4:26b", int(16.8 * GB)), ("qwen3.6:35b", int(21.1 * GB))]
NOT_FOR_TEXT = ("embed", "bge", "minilm", "rerank", "guard", "ocr", "coder", "code", "math", "whisper", "moondream", "llava")


def _host():
    """Dirección de Ollama: la de OLLAMA_HOST si la persona la cambió; si no, la de fábrica."""
    h = (os.environ.get("OLLAMA_HOST") or "").strip().rstrip("/")
    if not h:
        return "http://127.0.0.1:11434"
    scheme, _, rest = h.partition("://") if "://" in h else ("http", "", h)
    name, _, port = rest.partition(":")
    name = "127.0.0.1" if name in ("", "0.0.0.0", "localhost") else name
    return f"{scheme}://{name}:{port or ('443' if scheme == 'https' else '11434')}"


def _drives():
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        # 3 = disco fijo (no se despiertan unidades de red ni lectores vacíos)
        return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1
                and ctypes.windll.kernel32.GetDriveTypeW(f"{c}:\\") == 3]
    except Exception:
        return []


def _candidates():
    """Dónde puede estar Ollama, en orden: la carpeta elegida, la instalación normal de Windows y la versión portátil."""
    d = (load_settings().get("ollama_dir") or "").strip().strip('"')
    if d:
        p = Path(d)
        if p.name.lower() == "ollama.exe":
            yield p
        yield p / "bin" / "ollama.exe"
        yield p / "ollama.exe"
    w = shutil.which("ollama")
    if w:
        yield Path(w)
    for var, sub in (("LOCALAPPDATA", r"Programs\Ollama"), ("ProgramFiles", "Ollama")):
        if os.environ.get(var):
            yield Path(os.environ[var]) / sub / "ollama.exe"
    for r in _drives():
        yield Path(r) / "Ollama" / "bin" / "ollama.exe"
        yield Path(r) / "Ollama" / "ollama.exe"


def _find():
    for p in _candidates():
        try:
            if p.is_file():
                return p
        except OSError:
            pass
    return None


_exe_cache = [None, 0.0, None]  # carpeta elegida, cuándo, resultado


def exe():
    key = load_settings().get("ollama_dir")
    if _exe_cache[0] != key or time.time() - _exe_cache[1] > 30 or (_exe_cache[2] and not _exe_cache[2].exists()):
        _exe_cache[:] = [key, time.time(), _find()]
    return _exe_cache[2]


def models_dir():
    """Dónde guarda sus modelos. La versión portátil los lleva al lado; la instalada, en la carpeta del usuario."""
    e = exe()
    if e and e.parent.name.lower() == "bin" and (e.parent.parent / "models").is_dir():
        return e.parent.parent / "models"
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def _get(path, timeout=3):
    with urllib.request.urlopen(_host() + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path, body, timeout=30):
    req = urllib.request.Request(_host() + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def running():
    try:
        _get("/api/version", 1.5)
        return True
    except Exception:
        return False


_run_cache = [0.0, False]


def available():
    """¿Hay Ollama en este equipo? (instalado o ya encendido)"""
    if exe():
        return True
    if time.time() - _run_cache[0] > 20:
        _run_cache[:] = [time.time(), running()]
    return _run_cache[1]


_use_cache = [0.0, False]


def usable():
    """¿Hay Ollama y algún modelo para elegir momentos?"""
    if time.time() - _use_cache[0] > 15:
        want = load_settings().get("ollama_model") or "auto"
        _use_cache[:] = [time.time(), available() and any(not m["odd"] or want in (m["name"], m["name"].removesuffix(":latest")) for m in installed(every=True))]
    return _use_cache[1]


def ensure_server():
    if running():
        return True
    e = exe()
    if not e:
        raise RuntimeError("No encuentro Ollama en este equipo")
    # CUDA compila sus funciones la primera vez (~1-3 min); con caché grande no lo repite en cada arranque
    env = dict(os.environ, CUDA_CACHE_MAXSIZE=os.environ.get("CUDA_CACHE_MAXSIZE", str(4 * 1024 ** 3)))
    env["OLLAMA_MODELS"] = str(models_dir())
    subprocess.Popen([str(e), "serve"], env=env, creationflags=NO_WINDOW | 0x00000008,  # DETACHED_PROCESS
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        time.sleep(0.5)
        if running():
            return True
    raise RuntimeError("Ollama no arrancó a tiempo")


def _from_disk():
    """Modelos instalados leyendo su carpeta, sin encender Ollama."""
    out, base = [], models_dir() / "manifests"
    try:
        files = [f for f in base.rglob("*") if f.is_file()]
    except OSError:
        return out
    for f in files:
        parts = f.relative_to(base).parts  # registro / … / modelo / etiqueta
        if len(parts) < 3:
            continue
        where = [p for p in parts[:-1] if p != "registry.ollama.ai"]
        if len(where) < len(parts) - 1 and where[0] == "library":
            where = where[1:]
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            size = sum(x.get("size", 0) for x in m.get("layers", []))
        except (OSError, ValueError, AttributeError):
            continue
        out.append({"name": "/".join(where) + ":" + parts[-1], "size": size})
    return out


def installed(every=False):
    """Modelos de texto que hay en el equipo: [{name, size}]. Los «cloud» no cuentan: mandarían el guion a internet.
    Con every, también los que por su nombre parecen de otra cosa (código, matemáticas…)."""
    try:
        ms = [{"name": m["name"], "size": m.get("size") or 0, "remote": bool(m.get("remote_host") or m.get("remote_model")),
               "caps": m.get("capabilities")} for m in _get("/api/tags", 2).get("models", [])]
    except Exception:
        ms = _from_disk()
    out = []
    for m in ms:
        n = m["name"].lower()
        if m.get("remote") or "cloud" in n.rpartition(":")[2] or m["size"] < 0.2 * GB:
            continue
        if m.get("caps") and "completion" not in m["caps"]:
            continue
        odd = any(x in n for x in NOT_FOR_TEXT)
        if odd and (not every or any(x in n for x in ("embed", "bge", "minilm", "rerank", "whisper"))):
            continue
        out.append({"name": m["name"], "size": m["size"], "odd": odd})
    return sorted(out, key=lambda m: m["size"])


def models():
    return [m["name"] for m in installed()]


def _gpu_need(size):
    return size * 1.1 + 0.4 * GB


def pick(ms=None):
    """El mejor modelo instalado para este equipo, o None."""
    ms = installed() if ms is None else ms
    vram, mem = equipo.nvidia_total(), equipo.ram()
    # en la GPU debe caber entero; en el procesador, hasta ~6 GB y la mitad de la memoria: más grande no termina nunca
    roof = min(6 * GB, mem * 0.5) if mem else 6 * GB
    ok = [m for m in ms if vram and _gpu_need(m["size"]) < vram] or [m for m in ms if m["size"] < roof]
    if not ok:
        return min(ms, key=lambda m: m["size"])["name"] if ms else None
    return max(ok, key=lambda m: (KNOWN.index(m["name"]) if m["name"] in KNOWN else -1, m["size"]))["name"]


def recommend():
    """Qué modelo conviene descargar si no hay ninguno: {name, size, where} o None si el equipo no da."""
    vram, mem = equipo.nvidia_total(), equipo.ram()
    fit = [c for c in CATALOG if vram >= c[2]]
    if fit:
        return {"name": fit[-1][0], "size": fit[-1][1], "where": "gpu"}
    amd = max((g["vram"] for g in equipo.gpus() if g["vendor"] == "amd"), default=0)
    fit = [c for c in CATALOG if amd >= c[2]]
    if fit:
        return {"name": fit[-1][0], "size": fit[-1][1], "where": "auto"}
    if mem >= 15 * GB:
        return {"name": CATALOG[1][0], "size": CATALOG[1][1], "where": "cpu"}
    if mem >= 7 * GB:
        return {"name": CATALOG[0][0], "size": CATALOG[0][1], "where": "cpu"}
    return None


def resolve_model(want=None):
    """El modelo elegido en Ajustes si está instalado; si no (o en automático), el mejor que haya."""
    want = want or load_settings().get("ollama_model") or "auto"
    ms = installed(every=True)
    names = {m["name"] for m in ms}
    for n in (want, want + ":latest"):
        if n in names:
            return n
    got = pick([m for m in ms if not m["odd"]])
    if got:
        return got
    if not available():
        raise RuntimeError("No encuentro Ollama en este equipo")
    raise RuntimeError("Ollama no tiene ningún modelo descargado (se descarga en Ajustes)")


def fit(size, name=""):
    """Cómo iría en este equipo: gpu (entero), auto (lo decide Ollama), mixto o cpu (lento), no (no cabe)."""
    need = next((v for n, _, v in CATALOG if n == name), _gpu_need(size))
    vram = equipo.nvidia_total()
    if vram and (need <= vram or _gpu_need(size) < vram and name not in KNOWN):
        return "gpu"
    amd = max((g["vram"] for g in equipo.gpus() if g["vendor"] == "amd"), default=0)
    if amd and need <= amd:
        return "auto"
    if size * 1.15 + 2 * GB < equipo.ram() * 0.75:
        return "mixto" if vram else "cpu"
    return "no"


def status():
    e, up = exe(), running()
    every = installed(every=True) if (e or up) else []
    ms = [m for m in every if not m["odd"]]
    want = load_settings().get("ollama_model") or "auto"
    best = pick(ms)
    use = want if want in {m["name"] for m in every} else best
    free = 0
    try:
        p = models_dir()
        while not p.exists() and p != p.parent:
            p = p.parent
        free = shutil.disk_usage(p).free
    except OSError:
        pass
    return {"installed": bool(e or up), "exe": str(e) if e else "", "running": up, "models": [m["name"] for m in ms],
            "others": [m["name"] for m in every if m["odd"]], "sizes": {m["name"]: m["size"] for m in every}, "model": want, "use": use, "auto": best, "recommend": recommend(),
            "all": [{"name": m["name"], "size": m["size"], "fit": fit(m["size"], m["name"]), "odd": m["odd"]} for m in every],
            "suggest": [{"name": n, "size": z, "fit": fit(z, n)} for n, z in [c[:2] for c in CATALOG] + MORE if n not in {m["name"] for m in every}],
            "models_dir": str(models_dir()), "free": free, "pull": dict(_pull)}


# ------------------------------------------------------------ descargar un modelo (solo si la persona lo pide)

_pull = {"on": False, "model": "", "done": 0, "total": 0, "msg": "", "error": ""}
_pull_stop = threading.Event()
_pull_lock = threading.Lock()


def clean_name(name):
    """Nombre de un modelo de Ollama o de Hugging Face, con etiqueta. Otros servidores de modelos no se aceptan."""
    n = re.sub(r"^(ollama\s+(pull|run)\s+)", "", (name or "").strip(), flags=re.I)
    n = re.sub(r"^https?://(www\.)?", "", n, flags=re.I)
    n = re.sub(r"^ollama\.com/(library/)?", "", n, flags=re.I)
    n = re.sub(r"^huggingface\.co/", "hf.co/", n, flags=re.I).rstrip("/")
    if len(n) > 160 or not re.fullmatch(r"[A-Za-z0-9][\w.-]*(/[A-Za-z0-9][\w.-]*){0,2}(:[\w.-]+)?", n):
        raise ValueError("Ese nombre no es válido. Ejemplos: llama3.1:8b, hf.co/usuario/modelo-GGUF")
    path, _, tag = n.partition(":")
    parts = path.split("/")
    if parts[0] == "hf.co" and len(parts) != 3 or parts[0] != "hf.co" and (len(parts) > 2 or len(parts) == 2 and "." in parts[0]):
        raise ValueError("Solo se aceptan modelos de Ollama (modelo o usuario/modelo) o de Hugging Face (hf.co/usuario/modelo)")
    return f"{path}:{tag or 'latest'}"


def lookup(name):
    """Pregunta a Ollama o a Hugging Face cuánto pesa un modelo, sin descargarlo."""
    n = clean_name(name)
    path, tag = n.rsplit(":", 1)
    if "cloud" in tag.lower():
        raise ValueError("Los modelos «cloud» no son locales: mandarían el guion a internet")
    if any(x in n.lower() for x in ("embed", "bge", "minilm", "rerank", "whisper")):
        raise ValueError("Ese modelo no escribe texto, así que no sirve para elegir momentos")
    hf = path.startswith("hf.co/")
    repo = path[6:] if hf else path if "/" in path else "library/" + path
    url = f"https://{'hf.co' if hf else 'registry.ollama.ai'}/v2/{repo}/manifests/{tag}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json", "User-Agent": "ollama"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            layers = json.loads(r.read(1_000_000).decode("utf-8")).get("layers") or []
    except urllib.error.HTTPError as e:
        raise ValueError("No existe un modelo con ese nombre, o es privado" if e.code in (400, 401, 403, 404) else f"El catálogo respondió con el error {e.code}")
    except (OSError, ValueError, AttributeError):
        raise ValueError("No pude consultar el catálogo. ¿Hay internet?")
    size = sum(int(x.get("size") or 0) for x in layers)
    if not any("model" in str(x.get("mediaType")) for x in layers) or size < 0.2 * GB:
        raise ValueError("Ese modelo no se descarga a este PC, así que no es local")
    low = n.lower()
    return {"name": n, "size": size, "fit": fit(size, n), "odd": any(x in low for x in NOT_FOR_TEXT), "free": status()["free"], "dir": str(models_dir()),
            "installed": n in {m["name"] for m in installed(every=True)}}


def delete(model):
    if _pull["on"] and _pull["model"] == model:
        raise ValueError("Ese modelo se está descargando")
    if model not in {m["name"] for m in installed(every=True)}:
        raise ValueError("Ese modelo no está en este equipo")
    ensure_server()
    req = urllib.request.Request(_host() + "/api/delete", data=json.dumps({"model": model}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        raise ValueError(f"Ollama no pudo borrarlo ({e.code})")
    _use_cache[0] = 0.0


def pull(model):
    size = next((s for n, s, _ in CATALOG if n == model), 0)
    if not size:
        got = lookup(model)
        model, size = got["name"], got["size"]
    free = status()["free"]
    if free and free < size + 2 * GB:
        raise ValueError("No hay espacio suficiente en el disco de los modelos")
    with _pull_lock:
        if _pull["on"]:
            raise ValueError("Ya hay una descarga en marcha")
        _pull.update(on=True, model=model, done=0, total=size, msg="Preparando…", error="")
    _pull_stop.clear()
    threading.Thread(target=_pull_run, args=(model,), daemon=True, name="modelo").start()


def _pull_run(model):
    parts = {}
    try:
        ensure_server()
        with _post("/api/pull", {"model": model, "stream": True}, timeout=600) as r:
            for line in r:
                if _pull_stop.is_set():
                    _pull.update(msg="Descarga detenida")
                    return
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(str(ev["error"]))
                if ev.get("digest") and ev.get("total"):
                    parts[ev["digest"]] = (ev.get("completed", 0), ev["total"])
                    _pull.update(done=sum(a for a, _ in parts.values()), total=max(_pull["total"], sum(b for _, b in parts.values())),
                                 msg="Descargando")
                elif ev.get("status"):
                    _pull["msg"] = "Comprobando" if "verif" in ev["status"] else _pull["msg"]
        _pull.update(msg="Listo", done=_pull["total"])
        _use_cache[0] = 0.0
    except Exception as e:
        _pull.update(error=f"No se pudo descargar: {str(e)[:200]}")
    finally:
        _pull["on"] = False


def pull_stop():
    _pull_stop.set()


# ------------------------------------------------------------ memoria de video

def _loaded():
    try:
        return _get("/api/ps", 1.5).get("models", [])
    except Exception:
        return []


def make_room(need):
    """Libera la memoria de video que ocupa la IA local si la transcripción la necesita (se vuelve a cargar sola)."""
    if not equipo.nvidia_total() or equipo.nvidia_free() >= need or not exe():
        return
    for m in _loaded():
        if m.get("size_vram"):
            try:
                _post("/api/generate", {"model": m["name"], "keep_alive": 0}, 20).read()
            except Exception:
                pass
    t0 = time.time()
    while time.time() - t0 < 8 and equipo.nvidia_free() < need:
        time.sleep(0.5)


def _fits_gpu(model):
    """¿Cabe el modelo entero en lo que queda libre de la GPU? Si no, forzarlo desborda a memoria compartida y va lentísimo."""
    size = next((m["size"] for m in installed(every=True) if m["name"] == model), 0)
    if not size or _gpu_need(size) >= equipo.nvidia_total():
        return False
    # lo que ya ocupa este mismo modelo cuenta como libre: se vuelve a cargar, ahora entero
    mine = sum(m.get("size_vram", 0) for m in _loaded() if m.get("name") == model)
    return size * 1.05 + 0.25 * GB < equipo.nvidia_free() + mine

def chat_json(system, user, schema, model, num_ctx=8192, progress_cb=None):
    """Chat con salida JSON forzada por esquema. Devuelve el objeto ya parseado.
    Si el modelo cabe en la GPU, lo carga entero ahí (mucho más rápido);
    si no cabe o falla, deja que Ollama reparta entre CPU y GPU."""
    ensure_server()
    if not _fits_gpu(model):
        return _chat_json(system, user, schema, model, {"num_ctx": num_ctx}, progress_cb)
    try:
        return _chat_json(system, user, schema, model, {"num_ctx": num_ctx, "num_gpu": 99}, progress_cb)
    except RuntimeError as e:
        if "Ollama" not in str(e) and "memory" not in str(e).lower() and "cuda" not in str(e).lower():
            raise
        return _chat_json(system, user, schema, model, {"num_ctx": num_ctx}, progress_cb)


def _chat_json(system, user, schema, model, opts, progress_cb=None):
    ensure_server()
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.3, **opts},
    }
    req = urllib.request.Request(_host() + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    out, n, t0 = [], 0, time.time()
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            for line in r:
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError("Ollama: " + str(ev["error"]))
                piece = ev.get("message", {}).get("content", "")
                if piece:
                    out.append(piece)
                    n += 1
                    if progress_cb and n % 20 == 0:
                        progress_cb(n, time.time() - t0)
                if ev.get("done"):
                    global last_stats
                    last_stats = {k: ev.get(k) for k in ("prompt_eval_count", "prompt_eval_duration",
                                                          "eval_count", "eval_duration", "load_duration")}
                    break
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama: {e.read().decode('utf-8', 'replace')[:300]}")
    text = "".join(out)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # a veces el modelo corta el JSON; intentamos rescatar los clips completos
        cut = text[: text.rfind("}") + 1] + "]}"
        return json.loads(cut)
