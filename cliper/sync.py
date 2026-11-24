"""Sincronización automática de dos videos por su audio (correlación cruzada de la envolvente)."""
import numpy as np

from .media import read_wav_mono

RATE = 100  # muestras de envolvente por segundo


def envelope(path):
    x, sr = read_wav_mono(path)
    hop = sr // RATE
    n = len(x) // hop
    e = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-9)
    e = np.log(e)
    d = np.diff(e, prepend=e[0])          # "ataques": más robusto a distinto volumen/micro
    d = np.maximum(d, 0)
    return (d - d.mean()) / (d.std() + 1e-9)


def offset(wav_a, wav_b):
    """Devuelve (offset, confianza) con tB = tA + offset."""
    a, b = envelope(wav_a), envelope(wav_b)
    n = 1
    while n < len(a) + len(b):
        n *= 2
    fa, fb = np.fft.rfft(a, n), np.fft.rfft(b, n)
    corr = np.fft.irfft(np.conj(fa) * fb, n)
    k = int(np.argmax(corr))
    lag = k if k < n // 2 else k - n
    peak = corr[k]
    conf = float(peak / (np.std(corr) * 10 + 1e-9))
    return lag / RATE, min(1.0, conf)
