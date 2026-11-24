"""Descarga desde enlaces (YouTube, TikTok, Twitch, Kick, Drive, Zoom...) con yt-dlp."""
import re
import threading
import time
from pathlib import Path

from .config import FFMPEG


LONG = 3600          # a partir de 1 h, la calidad automática baja a 720p
PARALLEL = 8         # trozos a la vez en directos y videos por partes (HLS/DASH)


def pick_res(quality, duration):
    """Calidad pedida («auto», «1080», «720», «480») → lado corto del video en píxeles."""
    if str(quality) in ("1080", "720", "480"):
        return int(quality)
    if quality == "auto":
        return 720 if (duration or 0) > LONG else 1080
    return 1080


def _detail(d, res):
    """«720p · 5.2 MB/s · faltan 14 min» para el mensaje de avance."""
    out = [f"{res}p"]
    if d.get("speed"):
        out.append(f"{d['speed'] / 1e6:.1f} MB/s")
    if d.get("eta"):
        m = round(d["eta"] / 60)
        out.append(f"faltan {m // 60} h {m % 60} min" if m >= 60 else f"faltan {m} min" if m else "falta menos de 1 min")
    return " · ".join(out)


def _settle_live(ydl, info):
    """Un directo recién terminado sigue marcado «en vivo» un rato. Si su lista ya está cerrada, se trata como video
    normal (baja en varias partes a la vez, con avance y con la calidad según su duración)."""
    f = next((f for f in reversed(info.get("formats") or []) if "m3u8" in (f.get("protocol") or "") and f.get("url")), None)
    if not f:
        return
    try:
        import yt_dlp
        req = yt_dlp.networking.Request(f["url"], headers=f.get("http_headers") or info.get("http_headers") or {})
        txt = ydl.urlopen(req).read().decode("utf-8", "ignore")
    except Exception:
        return
    if "#EXT-X-ENDLIST" not in txt:
        return
    info["is_live"], info["live_status"] = False, "was_live"
    info["duration"] = info.get("duration") or round(sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", txt))) or None


def _ydl(opts, watch=None):
    import yt_dlp

    class Ydl(yt_dlp.YoutubeDL):
        def process_video_result(self, info_dict, download=True):
            live = lambda: info_dict.get("is_live") or info_dict.get("live_status") == "is_live"  # YouTube solo usa lo segundo
            if live():
                _settle_live(self, info_dict)
                if live():
                    raise RuntimeError("Este directo todavía está en vivo. Vuelve a intentarlo cuando termine.")
            return super().process_video_result(info_dict, download)

        def process_info(self, info_dict):
            if watch:
                watch.total = info_dict.get("filesize") or info_dict.get("filesize_approx") or \
                    (info_dict.get("tbr") or 0) * 125 * (info_dict.get("duration") or 0)
            return super().process_info(info_dict)
    return Ydl(opts)


class _Watch:
    """Avance por el tamaño del archivo, para las descargas que no avisan cuánto llevan."""

    def __init__(self, out_dir, cb, res):
        self.dir, self.cb, self.res, self.total, self.last_hook = out_dir, cb, res, 0, time.time()
        self.stop = threading.Event()
        self.before = {p: p.stat().st_mtime for p in out_dir.glob("*") if p.is_file()}
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        hist = []
        while not self.stop.wait(2):
            if time.time() - self.last_hook < 6:
                hist = []
                continue
            size = 0
            for p in self.dir.glob("*"):
                try:
                    if p.is_file() and self.before.get(p) != p.stat().st_mtime:
                        size += p.stat().st_size
                except OSError:
                    pass
            hist = (hist + [(time.time(), size)])[-8:]
            if not size or len(hist) < 2 or hist[-1][1] <= hist[0][1]:
                continue
            speed = (hist[-1][1] - hist[0][1]) / max(0.1, hist[-1][0] - hist[0][0])
            d = {"speed": speed, "eta": (self.total - size) / speed if self.total > size else None}
            self.cb(min(0.99, size / self.total) if self.total else 0, f"{size / 1e9:.2f} GB · " + _detail(d, self.res))


def _opts(outtmpl, progress_cb, audio_only=False, res=1080, fps30=False, watch=None):
    last = [0.0]

    def hook(d):
        if not progress_cb:
            return
        if d.get("status") == "downloading":
            if time.time() - last[0] < 0.7:  # con varios trozos a la vez llegan muchos avisos por segundo
                return
            last[0] = time.time()
            if watch:
                watch.last_hook = time.time()
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                progress_cb(min(0.99, d.get("downloaded_bytes", 0) / tot), _detail(d, res))
        elif d.get("status") == "finished":
            progress_cb(1.0, f"{res}p")

    o = {
        "outtmpl": outtmpl,
        "ffmpeg_location": FFMPEG,
        "progress_hooks": [hook],
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "concurrent_fragment_downloads": PARALLEL,
    }
    if audio_only:
        o["format"] = "bestaudio/best"
        o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        # «res» es el lado corto: sirve igual para videos horizontales y verticales. Si no hay esa
        # calidad, toma la mayor por debajo; si tampoco, la menor por encima. Los clips salen a 30 fps.
        o["format"] = "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b"
        o["format_sort"] = [f"res:{res}"] + (["fps:30"] if fps30 else [])
        o["merge_output_format"] = "mp4"
    return o


def download(url, out_dir, progress_cb=None, audio_only=False, name_template="%(title).80s.%(ext)s", quality="1080",
             for_clips=False):
    """Descarga y devuelve (ruta_final, título). progress_cb(fracción, detalle)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = None
    if quality == "auto" and not audio_only:  # hay que saber cuánto dura para decidir
        with _ydl({"quiet": True, "no_warnings": True, "noplaylist": True, "playlist_items": "1"}) as ydl:
            pre = ydl.extract_info(url, download=False)
            if pre.get("entries"):
                pre = next(iter(pre["entries"]))
            dur = pre.get("duration")
    res = pick_res(quality, dur)
    watch = _Watch(out_dir, progress_cb, res) if progress_cb else None
    opts = _opts(str(out_dir / name_template), progress_cb, audio_only=audio_only, res=res, fps30=for_clips, watch=watch)
    try:
        with _ydl(opts, watch) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            path = Path(ydl.prepare_filename(info))
    finally:
        if watch:
            watch.stop.set()
    if audio_only:
        path = path.with_suffix(".mp3")
    elif not path.exists():
        alt = path.with_suffix(".mp4")
        if alt.exists():
            path = alt
    if not path.exists():
        cands = sorted(out_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            raise RuntimeError("La descarga terminó pero no encuentro el archivo.")
        path = cands[0]
    return path, info.get("title") or path.stem
