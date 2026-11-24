"""Rutas y ajustes globales."""
import json
import os
import shutil
import sys
import threading
from pathlib import Path

APP_NAME = "YoClipeo"  # nombre visible: la interfaz y el servidor lo toman de aquí
VERSION = "1.3.5"       # súbela en cada actualización y anótala en CAMBIOS.md: es lo que hace aparecer el botón «Actualizar»
REPO, BRANCH = "luisolisd/yoclipeo", "main"     # de dónde salen las versiones nuevas
AUTHOR = "Desarrollado por luisolisd"
NOTICE = "Gratis. Prohibida su venta."
DONATE_URL = "https://ko-fi.com/luisolisd"   # página para invitar un café (https://…); vacío = no aparece en ningún lado

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROJECTS = DATA / "projects"
DOWNLOADS = DATA / "descargas"
MODELS = ROOT / "models"
FONTS_DIR = ROOT / "assets" / "fonts"
WEB = ROOT / "web"
FACES = ROOT / "assets" / "modelos" / "face_detection_yunet_2023mar.onnx"   # detector de caras (viene con el programa)


def _ffmpeg():
    """El de la carpeta bin; si no está, el del sistema o el que trae el paquete imageio-ffmpeg."""
    own = ROOT / "bin" / "ffmpeg.exe"
    if own.exists():
        return str(own)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return str(own)


FFMPEG = _ffmpeg()
SETTINGS_FILE = DATA / "settings.json"

for p in (DATA, PROJECTS, DOWNLOADS, MODELS):
    p.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("HF_HOME", str(MODELS / "hf"))


def _add_cuda_dlls():
    """Las DLL de CUDA vienen en paquetes pip (nvidia-cublas/cudnn); hay que registrarlas."""
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not base.exists():
        return
    for sub in base.iterdir():
        b = sub / "bin"
        if b.is_dir():
            try:
                os.add_dll_directory(str(b))
            except OSError:
                pass
            os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


_add_cuda_dlls()

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30

# Letras disponibles: clave -> (archivo, variación opcional, nombre para el navegador)
FONTS = {
    "impacto": {"file": str(FONTS_DIR / "Anton-Regular.ttf"), "label": "Impacto", "css": "CliperImpacto"},
    "gruesa": {"file": r"C:\Windows\Fonts\ariblk.ttf", "label": "Gruesa", "css": "CliperGruesa"},
    "clasica": {"file": str(FONTS_DIR / "Montserrat.ttf"), "label": "Clásica", "css": "CliperClasica", "wght": 900},
    "pincel": {"file": str(FONTS_DIR / "PermanentMarker-Regular.ttf"), "label": "Pincel", "css": "CliperPincel"},
    "comic": {"file": str(FONTS_DIR / "Bangers-Regular.ttf"), "label": "Cómic", "css": "CliperComic"},
    "condensada": {"file": str(FONTS_DIR / "BebasNeue-Regular.ttf"), "label": "Condensada", "css": "CliperCondensada"},
}
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"

# Colores del resaltado tipo karaoke
COLORS = {
    "amarillo": "#FFD400",
    "verde": "#39FF6A",
    "rojo": "#FF3B3B",
    "cian": "#2BD9FF",
    "rosa": "#FF4FD8",
}

# Título: estilos y colores (el color pinta la caja o la letra según el estilo)
TITLE_STYLES = {"caja": "Caja", "oscura": "Caja oscura", "contorno": "Sin caja", "cinta": "Cinta"}
TITLE_COLORS = {"blanco": "#FFFFFF", **COLORS, "negro": "#111111"}

# Stickers de marca subidos por el usuario (logos, «sígueme», etc.)
BRAND = DATA / "marca"
BRAND.mkdir(parents=True, exist_ok=True)

_settings_lock = threading.Lock()
DEFAULT_SETTINGS = {"api_key": "", "model": "claude-opus-5-5", "whisper_model": "auto",
                    "engine": "auto",            # auto | claude | servidor | ollama | reglas
                    "ollama_model": "auto",      # auto = el mejor instalado que quepa en el equipo
                    "ollama_dir": "",            # vacío = buscarlo solo
                    "local_url": "",             # otro servidor compatible con la API de OpenAI (LM Studio, llama.cpp…)
                    "local_model": "auto", "local_key": "",
                    "local_ok": "",              # dirección fuera de casa que la persona confirmó
                    "updates": "on",             # on | off: buscar versiones nuevas en GitHub
                    "encoder": "auto"}           # auto | cpu | nvenc | qsv | amf


def load_settings():
    with _settings_lock:
        s = dict(DEFAULT_SETTINGS)
        if SETTINGS_FILE.exists():
            try:
                s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        return s


def save_settings(new):
    with _settings_lock:
        s = dict(DEFAULT_SETTINGS)
        if SETTINGS_FILE.exists():
            try:
                s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        s.update({k: v for k, v in new.items() if k in DEFAULT_SETTINGS})
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
        return s
