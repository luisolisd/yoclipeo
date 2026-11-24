"""Utilidades de ffmpeg: inspección, proxy, audio, miniaturas."""
import re
import subprocess
from pathlib import Path

import numpy as np

from .config import FFMPEG

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW en Windows


def run(args, check=True):
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", *args], capture_output=True,
                       creationflags=NO_WINDOW)
    if check and r.returncode != 0:
        tail = r.stderr.decode("utf-8", "replace")[-1500:]
        raise RuntimeError(f"ffmpeg falló:\n{tail}")
    return r


def probe(path):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True,
                       creationflags=NO_WINDOW)
    txt = r.stderr.decode("utf-8", "replace")
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 30.0, "has_audio": False, "has_video": False,
            "rotation": 0}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    for line in txt.splitlines():
        if "Stream #" in line and "Video:" in line and not info["has_video"]:
            if "attached pic" in line:
                continue
            info["has_video"] = True
            sm = re.search(r", (\d{2,5})x(\d{2,5})", line)
            if sm:
                info["width"], info["height"] = int(sm[1]), int(sm[2])
            fm = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
            if fm:
                info["fps"] = float(fm[1])
        if "Stream #" in line and "Audio:" in line:
            info["has_audio"] = True
    rm = re.search(r"rotation of (-?[\d.]+) degrees", txt) or re.search(r"rotate\s*:\s*(-?\d+)", txt)
    if rm:
        rot = int(float(rm[1])) % 360
        info["rotation"] = rot
        if rot in (90, 270):
            info["width"], info["height"] = info["height"], info["width"]
    return info


def proxy_ready(src, dst, info):
    """¿La copia de vista previa ya está entera? (una cortada a medias no tiene duración legible)"""
    try:
        if dst.stat().st_size < 1024 or dst.stat().st_mtime < Path(src).stat().st_mtime:
            return False
    except OSError:
        return False
    p = probe(dst)
    return bool(p["has_video"] and p["width"] and p["has_audio"] == info["has_audio"] and info["duration"] > 0
                and abs(p["duration"] - info["duration"]) <= max(1.0, info["duration"] * 0.0005))


def make_proxy(src, dst, progress_cb=None, duration=0):
    """Copia ligera H.264 (máx. 720p) para la vista previa en el navegador y el análisis visual."""
    args = ["-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale='if(gt(iw,ih),-2,min(720,iw))':'if(gt(iw,ih),min(720,ih),-2)',fps=30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", "30",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", str(dst)]
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", *args], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    import threading
    err = []
    threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True).start()
    try:
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us=") and progress_cb and duration > 0:
                try:
                    progress_cb(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
    except BaseException:
        p.kill()
        p.wait()
        raise
    p.wait()
    if p.returncode != 0:
        raise RuntimeError("No se pudo crear la copia de vista previa:\n" +
                           (err[0].decode("utf-8", "replace")[-1200:] if err else ""))


def extract_audio(src, dst, sr=16000):
    run(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)])


def read_wav_mono(path):
    import wave
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return data, sr


def frame_at(src, t, width=None):
    """Devuelve un fotograma BGR (numpy) en el instante t."""
    import cv2
    vf = [f"scale={width}:-2"] if width else []
    for back in (0, 0.5, 1.5):  # cerca del final puede no haber fotograma: retroceder un poco
        r = run(["-ss", f"{max(0, t - back):.3f}", "-i", str(src), "-frames:v", "1",
                 *(["-vf", ",".join(vf)] if vf else []), "-f", "image2pipe", "-vcodec", "png", "-"])
        if r.stdout:
            return cv2.imdecode(np.frombuffer(r.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None
