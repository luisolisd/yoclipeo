"""Análisis visual: caras (YuNet), quién habla (movimiento de boca), cortes de plano y movimiento.

Recorre la copia de vista previa a 4 fps y guarda vision.json con, por muestra:
  t, faces=[[x,y,w,h,score,act]] (normalizado 0-1), motion (0-1), cut (bool)
"""
import json
import subprocess
import threading

import cv2
import numpy as np

from .config import FACES, FFMPEG, MODELS
from .media import NO_WINDOW

SAMPLE_FPS = 4
AW = 640  # ancho de análisis


def _iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0


def _faces_model():
    old = MODELS / FACES.name     # donde estaba en versiones anteriores
    f = FACES if FACES.exists() or not old.exists() else old
    if not f.exists():
        raise RuntimeError(f"Falta el detector de caras: {f}. Vuelve a descargar el programa completo.")
    return f      # se lee como bytes: OpenCV no abre rutas con acentos en Windows


def analyze(proxy_path, width, height, duration, out_path, progress_cb=None):
    aw = AW if width >= height else int(AW * 9 / 16) // 2 * 2
    ah = int(round(aw * height / width / 2)) * 2
    det = cv2.FaceDetectorYN.create("onnx", np.frombuffer(_faces_model().read_bytes(), np.uint8), np.zeros(0, np.uint8), (aw, ah),
                                    score_threshold=0.7, nms_threshold=0.3, top_k=20)
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-i", str(proxy_path), "-an",
           "-vf", f"fps={SAMPLE_FPS},scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    fsize = aw * ah * 3
    samples = []
    prev_gray = None
    prev_hist = None
    prev_faces = []  # [(box_px, patch)]
    i = 0
    while True:
        buf = p.stdout.read(fsize)
        if len(buf) < fsize:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
        t = i / SAMPLE_FPS
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)
        motion = 0.0 if prev_gray is None else float(np.mean(np.abs(small - prev_gray)) / 255.0)
        hist = cv2.calcHist([cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 8], [0, 180, 0, 256])
        hist = cv2.normalize(hist, None).flatten()
        cut = False
        if prev_hist is not None:
            d = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            cut = bool(d > 0.45)
        _, faces = det.detect(frame)
        cur = []
        out_faces = []
        if faces is not None:
            for f in faces:
                x, y, w, h, sc = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
                if w < aw * 0.03:
                    continue
                x0, y0 = max(0, int(x)), max(0, int(y + h * 0.55))
                x1, y1 = min(aw, int(x + w)), min(ah, int(y + h * 1.05))
                patch = None
                if x1 - x0 > 4 and y1 - y0 > 4:
                    patch = cv2.resize(gray[y0:y1, x0:x1], (24, 12), interpolation=cv2.INTER_AREA).astype(np.float32)
                act = 0.0
                if patch is not None and not cut:
                    best, bp = 0.0, None
                    for (pb, pp) in prev_faces:
                        iou = _iou((x, y, w, h), pb)
                        if iou > best:
                            best, bp = iou, pp
                    if bp is not None and best > 0.3:
                        act = float(np.mean(np.abs(patch - bp)) / 255.0)
                cur.append(((x, y, w, h), patch))
                out_faces.append([round(x / aw, 4), round(y / ah, 4), round(w / aw, 4), round(h / ah, 4),
                                  round(sc, 3), round(act, 4)])
        samples.append({"t": round(t, 3), "faces": out_faces, "motion": round(motion, 4), "cut": cut})
        prev_gray, prev_hist = small, hist
        prev_faces = [(b, pt) for (b, pt) in cur if pt is not None]
        i += 1
        if progress_cb and duration and i % 20 == 0:
            progress_cb(min(1.0, t / duration))
    p.wait()
    data = {"fps": SAMPLE_FPS, "w": width, "h": height, "samples": samples}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return data


_cache = {}
_cache_lock = threading.Lock()


def load(path):
    path = str(path)
    with _cache_lock:
        if path not in _cache:
            with open(path, encoding="utf-8") as fh:
                _cache[path] = json.load(fh)
        return _cache[path]
