"""Transcripción palabra a palabra con faster-whisper (GPU si se puede, si no CPU)."""
import threading

from . import equipo

_model = None
_model_key = None
_lock = threading.Lock()


def _fast_chunks():
    """faster-whisper une los pedazos con voz copiando todo el audio por cada uno: en un video de 8 horas son
    muchos minutos. Aquí se unen de una vez, con el mismo resultado."""
    import numpy as np
    from faster_whisper import transcribe as fw
    old = fw.collect_chunks
    if getattr(old, "fast", False):
        return

    def collect(audio, chunks, sampling_rate=16000, max_duration=float("inf")):
        if not chunks or max_duration != float("inf"):
            return old(audio, chunks, sampling_rate, max_duration)
        joined = np.concatenate([audio[c["start"]:c["end"]] for c in chunks])
        n = sum(c["end"] - c["start"] for c in chunks)
        return [joined], [{"offset": 0, "duration": n / sampling_rate, "segments": list(chunks)}]

    collect.fast = True
    fw.collect_chunks = collect


def get_model():
    global _model, _model_key
    from faster_whisper import WhisperModel
    _fast_chunks()
    with _lock:
        attempts = equipo.voice_attempts()
        if _model is not None and _model_key in attempts:
            return _model
        last = None
        if attempts[0][1] == "cuda":
            from . import local_llm
            local_llm.make_room(2.5 * 1024 ** 3)
        for key in attempts:
            try:
                _model = WhisperModel(key[0], device=key[1], compute_type=key[2])
                _model_key = key
                return _model
            except Exception as e:  # p. ej. falta una DLL de CUDA → seguimos en CPU
                last = e
        raise RuntimeError(f"No se pudo cargar Whisper: {last}")


def release():
    """Suelta el modelo si está en la GPU: en tarjetas de 4 GB no caben a la vez la voz y la IA local."""
    global _model, _model_key
    with _lock:
        if _model is not None and _model_key and _model_key[1] == "cuda":
            _model, _model_key = None, None
            import gc
            gc.collect()


def transcribe(wav_path, language=None, duration=0, progress_cb=None):
    model = get_model()
    lang = None if (not language or language == "auto") else language
    try:
        segments, info = model.transcribe(str(wav_path), language=lang, word_timestamps=True,
                                          vad_filter=True, beam_size=5,
                                          vad_parameters={"min_silence_duration_ms": 500})
        out = _collect(segments, duration, progress_cb)
    except RuntimeError as e:
        # Si la GPU falla a mitad (memoria, DLL), reintentar en CPU
        if "cuda" not in str(e).lower() and "cublas" not in str(e).lower() and "cudnn" not in str(e).lower():
            raise
        global _model, _model_key
        from faster_whisper import WhisperModel
        _model = WhisperModel("small", device="cpu", compute_type="int8")
        _model_key = ("small", "cpu", "int8")
        segments, info = _model.transcribe(str(wav_path), language=lang, word_timestamps=True, vad_filter=True)
        out = _collect(segments, duration, progress_cb)
    return {"language": info.language, "device": _model_key[1], "model": _model_key[0], "segments": out}


def _collect(segments, duration, progress_cb):
    out = []
    for seg in segments:
        words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                  "p": round(w.probability, 3)} for w in (seg.words or []) if w.word.strip()]
        out.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text.strip(), "words": words})
        if progress_cb and duration:
            progress_cb(min(1.0, seg.end / duration))
    return out


def all_words(transcript):
    return [w for seg in transcript["segments"] for w in seg["words"]]
