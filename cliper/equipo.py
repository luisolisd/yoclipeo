"""Qué equipo es este y qué de él funciona de verdad.

Detecta procesador, memoria y GPU (NVIDIA, AMD o Intel) y prueba, con una tarea corta de verdad, la transcripción en
la GPU y los codificadores de video. Lo que no pasa la prueba se hace en el procesador. Los resultados se guardan en
data/equipo.json y se descartan solos si cambia la GPU, su controlador o las librerías.
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import config
from .config import load_settings
from .media import NO_WINDOW

STATE_FILE = config.DATA / "equipo.json"
GB = 1024 ** 3
ENCODERS = {"cpu": "Procesador (x264)", "nvenc": "NVIDIA (NVENC)", "qsv": "Intel (Quick Sync)", "amf": "AMD (AMF)"}
VENDOR_ENC = {"nvidia": "nvenc", "intel": "qsv", "amd": "amf"}
VOICE_MODELS = {"large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "medium": "Systran/faster-whisper-medium",
                "small": "Systran/faster-whisper-small", "base": "Systran/faster-whisper-base"}

_lock = threading.RLock()
_cache = {}


def _cached(key, ttl, fn):
    with _lock:
        v = _cache.get(key)
        if v and time.time() - v[0] < ttl:
            return v[1]
    r = fn()
    with _lock:
        _cache[key] = (time.time(), r)
    return r


# ------------------------------------------------------------ qué hay

def cpu():
    name = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except Exception:
        pass
    return {"name": name or "Procesador", "threads": os.cpu_count() or 1}


def ram():
    """Memoria del equipo en bytes (0 si no se sabe)."""
    class Mem(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in (
            "total", "avail", "page", "page_avail", "virt", "virt_avail", "ext")]
    try:
        m = Mem()
        m.len = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.total)
    except Exception:
        return 0


def nvidia():
    """GPU NVIDIA según nvidia-smi: nombre, memoria total y libre (bytes) y controlador."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.free,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW).stdout
        rows = [[c.strip() for c in ln.split(",")] for ln in out.splitlines() if ln.count(",") >= 3]
        return [{"name": r[0], "vram": int(r[1]) * 1024 ** 2, "free": int(r[2]) * 1024 ** 2, "driver": r[3]} for r in rows]
    except Exception:
        return []


def nvidia_total():
    """Memoria de la mayor GPU NVIDIA, en bytes (0 si no hay)."""
    return max((g["vram"] for g in _cached("nvidia", 60, nvidia)), default=0)


def nvidia_free():
    return max((g["free"] for g in nvidia()), default=0)


def _vendor(name):
    n = name.lower()
    if any(x in n for x in ("nvidia", "geforce", "quadro", "rtx", "gtx")):
        return "nvidia"
    if any(x in n for x in ("amd", "radeon")):
        return "amd"
    if "intel" in n:
        return "intel"
    return ""


def _adapters():
    """Tarjetas de video presentes ahora (las del registro pueden ser de una que ya se quitó)."""
    class Dev(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("name", ctypes.c_wchar * 32), ("text", ctypes.c_wchar * 128),
                    ("flags", ctypes.c_ulong), ("id", ctypes.c_wchar * 128), ("key", ctypes.c_wchar * 128)]
    names = []
    try:
        for i in range(32):
            d = Dev()
            d.cb = ctypes.sizeof(d)
            if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
                break
            if d.text and d.text not in names:
                names.append(d.text)
    except Exception:
        pass
    return names


def _registry_vram():
    out = {}
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = winreg.QueryValueEx(k, "DriverDesc")[0]
                        ver = winreg.QueryValueEx(k, "DriverVersion")[0]
                        try:
                            mem = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                        except OSError:
                            mem = 0
                        out[name] = (mem, ver)
                except OSError:
                    pass
    except Exception:
        pass
    return out


def _gpus():
    nv, reg, out = nvidia(), _registry_vram(), []
    for g in nv:
        out.append({"name": g["name"], "vendor": "nvidia", "vram": g["vram"], "driver": g["driver"]})
    for name in _adapters():
        v = _vendor(name)
        if not v or (v == "nvidia" and nv):
            continue
        mem, ver = reg.get(name, (0, ""))
        out.append({"name": name, "vendor": v, "vram": mem if v != "intel" else 0, "driver": ver})
    return out


def gpus():
    return _cached("gpus", 60, _gpus)


# ------------------------------------------------------------ resultados guardados

def cuda_count():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def _fingerprint():
    ver = ""
    try:
        import ctranslate2
        ver = ctranslate2.__version__
    except Exception:
        pass
    nv = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    libs = sorted(p.name for p in nv.iterdir()) if nv.exists() else []
    ff = Path(config.FFMPEG)
    size = ff.stat().st_size if ff.exists() else 0
    raw = json.dumps([[g["name"], g["driver"]] for g in gpus()] + [ver, libs, size])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(**kw):
    with _lock:
        s = _load()
        s.update(kw)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)


def results():
    """Pruebas guardadas, si todavía valen para este equipo."""
    s = _load()
    if s.get("fp") != _cached("fp", 60, _fingerprint):
        return {}
    return s


# ------------------------------------------------------------ voz

def voice_cached(model):
    """¿El modelo de voz ya está en el disco? (para no descargar nada en las pruebas)"""
    repo = VOICE_MODELS.get(model)
    if not repo:
        return False
    d = Path(os.environ.get("HF_HOME", config.MODELS / "hf")) / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots"
    return d.exists() and any(d.glob("*/model.bin"))


def voice_attempts(name=None):
    """Qué probar, en orden: [(modelo, dispositivo, precisión)]. Lo último siempre es el procesador."""
    name = name or load_settings().get("whisper_model") or "auto"
    out = []
    vram, voice = nvidia_total(), results().get("voice") or {}
    if cuda_count() and voice.get("ok") is not False and (vram == 0 or vram >= 1.8 * GB):
        g = name if name != "auto" else ("large-v3-turbo" if vram == 0 or vram >= 3.5 * GB else "small")
        out += [(g, "cuda", "int8_float16"), (g, "cuda", "int8")]
    small_pc = cpu()["threads"] <= 4 or 0 < ram() < 6 * GB
    out.append((name if name != "auto" else ("base" if small_pc else "small"), "cpu", "int8"))
    return out


def test_voice():
    """Transcribe unos segundos en la GPU, en un proceso aparte (si una librería falla, no tumba la app)."""
    if not cuda_count():
        why = "No hay una GPU NVIDIA disponible." if not any(g["vendor"] == "nvidia" for g in gpus()) else \
            "La GPU NVIDIA no responde a CUDA: revisa su controlador."
        return {"ok": None, "why": why}
    att = [a for a in voice_attempts("auto") if a[1] == "cuda"] or [("small", "cuda", "int8_float16")]
    model = att[0][0]
    local = next((m for m in (model, "large-v3-turbo", "small", "base", "medium") if voice_cached(m)), None)
    if not local:
        ok, why = _cuda_libs()
        return {"ok": ok, "why": why if not ok else "Librerías listas; se confirma con el primer video.", "partial": True}
    try:
        r = subprocess.run([sys.executable, "-m", "cliper.equipo", "voz", local], cwd=str(config.ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=240, creationflags=NO_WINDOW)
        line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), "")
        if r.returncode == 0 and line:
            return {**json.loads(line), "model": local}
        err = (r.stderr.strip().splitlines() or [f"se cerró con código {r.returncode}"])[-1]
        return {"ok": False, "why": _explain(err), "model": local}
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "Tardó demasiado en responder.", "model": local}


def _cuda_libs():
    for dll in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(dll)
        except OSError:
            return False, f"Falta la librería {dll}. Instálala con: pip install -r requirements-nvidia.txt"
    return True, ""


def _explain(err):
    e = err.lower()
    if "cublas" in e or "cudnn" in e or ".dll" in e:
        return "Faltan las librerías de NVIDIA. Instálalas con: pip install -r requirements-nvidia.txt"
    if "out of memory" in e:
        return "A la GPU no le alcanza la memoria."
    return err[:200]


def _voice_child(model):
    import numpy as np
    from faster_whisper import WhisperModel
    t0 = time.time()
    m = WhisperModel(model, device="cuda", compute_type="int8_float16", local_files_only=True)
    t1 = time.time()
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.02, 16000 * 6).astype(np.float32) + 0.1 * np.sin(np.arange(16000 * 6) * 0.07).astype(np.float32)
    segs, _ = m.transcribe(x, language="es", beam_size=1, word_timestamps=True)
    list(segs)
    print(json.dumps({"ok": True, "load": round(t1 - t0, 1), "secs": round(time.time() - t1, 1)}), flush=True)
    os._exit(0)  # al cerrar, algunas versiones de CUDA fallan; el resultado ya está impreso


# ------------------------------------------------------------ exportación

def test_encoders():
    """Codifica dos segundos con cada codificador que podría servir en este equipo."""
    out = {}
    with tempfile.TemporaryDirectory(dir=str(config.DATA)) as d:
        for enc in ["cpu"] + sorted({VENDOR_ENC[g["vendor"]] for g in gpus() if g["vendor"] in VENDOR_ENC}):
            out[enc] = _try_encoder(enc, Path(d) / f"{enc}.mp4")
    return out


def _try_encoder(enc, path):
    from .render import QUALITIES, video_args
    _, _, crf, maxrate = QUALITIES["1080p"]
    n = 60
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
           f"testsrc2=s={config.OUT_W}x{config.OUT_H}:r={config.OUT_FPS}", "-frames:v", str(n), "-vf",
           "format=" + ("yuv420p" if enc == "cpu" else "nv12"), *video_args(enc, crf, maxrate), str(path)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW)
        secs = time.time() - t0
        if r.returncode != 0:
            lines = r.stderr.decode("utf-8", "replace").strip().splitlines()
            return {"ok": False, "why": (lines[0] if lines else "ffmpeg falló")[:160]}
        # que el archivo se pueda leer entero
        chk = subprocess.run([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path), "-f", "null",
                              "-"], capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if chk.returncode != 0 or chk.stderr.strip():
            return {"ok": False, "why": "El video de prueba salió dañado."}
        return {"ok": True, "fps": round(n / max(0.01, secs))}
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "Tardó demasiado."}
    except OSError as e:
        return {"ok": False, "why": str(e)[:160]}


def encoder():
    """Codificador a usar: el elegido en Ajustes si pasó la prueba; en automático, el procesador salvo que sea
    claramente más lento (componer cada fotograma es lo que más tarda, así que la GPU rara vez acelera)."""
    want, enc = load_settings().get("encoder") or "auto", results().get("encoders") or {}
    if want != "auto":
        return want if want in ENCODERS and (want == "cpu" or enc.get(want, {}).get("ok")) else "cpu"
    cpu_fps = enc.get("cpu", {}).get("fps") or 0
    best = max((k for k in enc if k != "cpu" and enc[k].get("ok")), key=lambda k: enc[k].get("fps") or 0, default=None)
    if best and 0 < cpu_fps < 60 and (enc[best].get("fps") or 0) > cpu_fps * 1.5:
        return best
    return "cpu"


def note_encoder_failed(enc):
    e = dict(results().get("encoders") or {})
    e[enc] = {"ok": False, "why": "Falló en una exportación; se repitió con el procesador."}
    _save(encoders=e)


# ------------------------------------------------------------ prueba completa

_testing = {"on": False, "step": ""}


def test_all():
    with _lock:
        if _testing["on"]:
            return False
        _testing.update(on=True, step="Buscando tarjetas de video")

    def run():
        try:
            _cache.clear()
            _testing["step"] = "Probando la voz en la GPU"
            from . import local_llm
            local_llm.make_room(2.5 * GB)
            voice = test_voice()
            _testing["step"] = "Probando la exportación"
            enc = test_encoders()
            _save(fp=_cached("fp", 60, _fingerprint), voice=voice, encoders=enc, tested=time.time())
        except Exception as e:
            _save(error=str(e)[:300])
        finally:
            _testing.update(on=False, step="")
    threading.Thread(target=run, daemon=True, name="prueba-equipo").start()
    return True


def start(working):
    """Al arrancar, si este equipo aún no se ha probado, se prueba cuando no haya nada en marcha."""
    def run():
        time.sleep(4)
        while not results().get("tested"):
            if not working():
                test_all()
                return
            time.sleep(60)
    threading.Thread(target=run, daemon=True, name="equipo").start()


def set_seen():
    _save(seen=True)


def report():
    r = results()
    att = voice_attempts()
    return {"cpu": cpu(), "ram": ram(), "gpus": gpus(), "voice": r.get("voice"), "voice_use": {
        "model": att[0][0], "device": att[0][1], "cached": voice_cached(att[0][0])}, "encoders": r.get("encoders") or {},
        "encoder": encoder(), "encoder_names": ENCODERS, "encoder_setting": load_settings().get("encoder") or "auto",
        "tested": r.get("tested"), "testing": dict(_testing), "seen": bool(_load().get("seen"))}


if __name__ == "__main__":
    if sys.argv[1:2] == ["voz"]:
        _voice_child(sys.argv[2])
