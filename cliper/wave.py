"""Forma de onda para la interfaz (mapa del video y línea de tiempo)."""
import wave

import numpy as np

HEADER = 44      # cabecera WAV estándar (la escribe ffmpeg)
CHUNK = 512      # muestras por lectura cuando el tramo es muy largo
READS = 6        # lecturas repartidas en cada barra


def peaks(path, a=0.0, b=0.0, n=600):
    """`n` barras (0-100) del audio entre los segundos a y b (b=0: hasta el final)."""
    n = max(1, min(4000, int(n)))
    with wave.open(str(path), "rb") as w:
        rate, total, ch, width = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        if width != 2:
            return []
    total = min(total, max(0, (path.stat().st_size - HEADER) // (2 * ch)))
    data = np.memmap(path, dtype="<i2", mode="r", offset=HEADER, shape=(total * ch,))
    i0 = max(0, int(a * rate))
    i1 = min(total, int(b * rate)) if b > a else total
    if i1 - i0 < 2:
        return []
    edges = np.linspace(i0, i1, n + 1).astype(np.int64)
    out = np.zeros(n, dtype=np.float32)
    for k in range(n):
        s, e = int(edges[k]), max(int(edges[k]) + 1, int(edges[k + 1]))
        if e - s <= CHUNK * READS:
            x = np.asarray(data[s * ch:e * ch], dtype=np.float32)
            out[k] = np.abs(x).max() if x.size else 0
        else:
            m = 0.0
            for p in np.linspace(s, e - CHUNK, READS).astype(np.int64):
                x = np.asarray(data[int(p) * ch:(int(p) + CHUNK) * ch], dtype=np.float32)
                m += float(np.sqrt(np.mean(x * x))) if x.size else 0.0
            out[k] = m / READS
    # escala a lo más fuerte del propio tramo (percentil 98: un golpe aislado no aplasta el resto)
    top = float(np.percentile(out, 98)) or 1.0
    return [int(v) for v in np.clip(out / top * 100, 0, 100)]
