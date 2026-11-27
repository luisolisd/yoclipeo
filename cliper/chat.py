"""Chat de Kick: lee los mensajes que hubo durante un video y prepara lo que se ve en el clip.

Solo sirve para videos de Kick. Kick no documenta esta lectura: si la cambia, lo demás sigue funcionando.
Los mensajes se guardan en data/projects/<id>/chat.json y las imágenes de los emotes en data/emotes.
"""
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import math
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request

from . import config, store

VOD = re.compile(r"^https?://(?:www\.)?kick\.com/[\w-]+/videos/[0-9a-f-]{36}", re.I)
API, FILES = "https://web.kick.com/api/v1/chat/", "https://files.kick.com/emotes/"
PAD = 20                 # se lee un poco de más a cada lado: mover el corte no obliga a volver a pedir
PAGES = 400              # 25 mensajes por página
PAUSE, SLOW = 0.3, 1.0   # segundos entre páginas: lo normal y después de que Kick frene
WAITS = (10, 15, 20, 30, 30, 45, 60)   # cuánto se espera cada vez que Kick frena, si no dice cuánto
BOTS = {"botrix", "kickbot", "streamelements", "streamlabs", "nightbot", "fossabot", "moobot"}
EMOTE = re.compile(r"\[emote:(\d{1,12}):[^\]\[]{0,80}\]")
TOKEN = re.compile(r"\[e:(\d{1,12})\]")
FPS, FRAMES, EH = 12, 36, 96      # emotes animados: cuadros por segundo, cuántos como mucho y su alto
NET = (OSError, TimeoutError, ValueError)

_lock = threading.RLock()
_hold = {"until": 0.0, "slow": 0.0, "front": 0}


class Brake(ValueError):
    """Kick pidió ir más despacio y no bastó con esperar."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_open = urllib.request.build_opener(_NoRedirect).open


def _get(url, limit, timeout=20):
    with _open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        b = r.read(limit + 1)
    if len(b) > limit:
        raise ValueError("respuesta demasiado grande")
    return b


# ------------------------------------------------------------ lo guardado

def source(p):
    """El enlace del video de Kick del proyecto, o None si no es de Kick."""
    m = VOD.match(((p or {}).get("source") or {}).get("url") or "")
    return m[0] if m else None


def _file(pid):
    return store.pdir(pid) / "chat.json"


_cache = {}


def load(pid):
    """{"channel", "start", "have": [[a, b]…], "msgs": [[segundo, id, quién, color, texto]…]}"""
    f = _file(pid)
    try:
        key = f.stat().st_mtime_ns
        if _cache.get(pid, (None,))[0] != key:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not (isinstance(d.get("have"), list) and isinstance(d.get("msgs"), list)):
                return {}
            _cache[pid] = (key, d)
        return _cache[pid][1]
    except (OSError, ValueError, AttributeError):
        return {}


def _save(pid, d):
    f = _file(pid)
    if not f.parent.exists() or not store.load(pid):
        raise ValueError("Ese proyecto ya no existe.")
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def _meta(pid):
    """Canal y hora en que empezó la grabación. Se piden una sola vez."""
    d = load(pid)
    if d.get("channel"):
        return d
    url = source(store.load(pid))
    if not url:
        raise ValueError("El chat solo se puede leer en videos de Kick.")
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "socket_timeout": 20}) as y:
            i = y.extract_info(url, download=False, process=False)
        d = {"channel": int(i["channel_id"]), "start": float(i["timestamp"]), "have": [], "msgs": []}
    except Exception:
        raise ValueError("Kick no da los datos de este video. Puede que ya no exista o que no haya conexión.")
    with _lock:
        if not load(pid).get("channel"):
            _save(pid, d)
    return load(pid)


def remember(pid):
    """Al bajar un video de Kick, guarda su hora de inicio: después Kick puede borrar el video y no el chat."""
    p = store.load(pid)
    if not p or not source(p):
        return

    def run():
        try:
            _meta(pid)
        except ValueError:
            pass
    threading.Thread(target=run, daemon=True, name="chat").start()


# ------------------------------------------------------------ leer de Kick

def waiting():
    """Segundos que faltan para seguir, si Kick frenó la lectura; 0 si no."""
    return max(0, math.ceil(_hold["until"] - time.time()))


def _brake(e, n):
    after = (e.headers.get("Retry-After") or "").strip()
    s = max(2 * (n + 1), min(120, int(after))) if after.isdigit() else WAITS[n]
    _hold.update(until=time.time() + s, slow=time.time() + 600)
    try:
        time.sleep(s)
    finally:
        _hold["until"] = 0.0


def _page(channel, cursor):
    k = held = 0
    while k < 3:
        try:
            d = json.loads(_get(f"{API}{channel}/history?cursor={cursor}", 4_000_000))["data"]
            return d.get("messages") or [], str(d.get("cursor") or "")
        except urllib.error.HTTPError as e:
            if e.code == 429 and held < len(WAITS):
                _brake(e, held)
                held += 1
                continue
            if e.code in (403, 429):
                raise Brake("Kick no dejó leer el chat en este momento. Intenta en unos minutos.")
            if e.code < 500:
                raise ValueError(f"Kick ya no deja leer el chat (respondió {e.code}).")
        except (KeyError, TypeError, AttributeError):
            raise ValueError("Kick cambió la forma de dar el chat.")
        except NET:
            pass
        k += 1
        time.sleep(.6 * k)
    raise ValueError("Kick no responde. Revisa tu conexión e intenta de nuevo.")


def _clean(m):
    """Un mensaje de Kick → [segundo absoluto, id, quién, color, texto], o None si no sirve."""
    try:
        if m.get("type") not in ("message", "reply"):
            return None
        s = dt.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).timestamp()
        u, x = str(m["sender"]["username"])[:40], str(m["content"])[:1000]
        c = str((m["sender"].get("identity") or {}).get("color") or "")
        return [s, str(m["id"])[:8], u, c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "", EMOTE.sub(r"[e:\1]", x)] if u and x.strip() else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def missing(d, a, b):
    """Los tramos de [a, b] que aún no se han leído."""
    out = []
    for x, y in sorted(d.get("have") or []):
        if y <= a or x >= b:
            continue
        if x > a:
            out.append([a, x])
        a = max(a, y)
    if a < b:
        out.append([a, b])
    return out


def _union(have):
    out = []
    for a, b in sorted(have):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def fetch(pid, a, b):
    """Lee el chat de los segundos a–b del video (lo que falte) y lo guarda."""
    with _lock:
        d = _meta(pid)
        for x, y in missing(d, a, b):
            got, cur = [], int((d["start"] + y + 1) * 1e6)
            try:
                for n in range(PAGES):
                    ms, nxt = _page(d["channel"], cur)
                    new = [m for m in map(_clean, ms) if m]
                    got += new
                    # Kick va del más nuevo al más viejo
                    if not ms or not nxt.isdigit() or int(nxt) >= cur or (new and new[-1][0] < d["start"] + x):
                        break
                    cur = int(nxt)
                    time.sleep(SLOW if time.time() < _hold["slow"] else PAUSE)
                else:
                    raise ValueError("Este tramo tiene demasiados mensajes. Prueba con un clip más corto.")
            except ValueError:
                _keep(pid, d, got, math.ceil(cur / 1e6 - d["start"]), y)     # lo ya leído no se vuelve a pedir
                raise
            _keep(pid, d, got, x, y)
        return load(pid)


def _keep(pid, d, got, x, y):
    if x >= y:
        return
    cur = load(pid) or d
    known = {m[1] for m in cur["msgs"]}
    add = {}
    for s, i, u, c, t in reversed(got):
        s = round(s - d["start"], 3)
        if x <= s <= y and i not in known:
            add[i] = [s, i, u, c, t]
    _save(pid, {**cur, "have": _union(cur["have"] + [[x, y]]), "msgs": sorted(cur["msgs"] + list(add.values()), key=lambda m: m[0])})


def _parts(p, clip, before, after):
    """A qué segundos del directo corresponde un clip: [(inicio en el archivo, inicio en el directo, desde, hasta)].
    Solo es más de uno, o no coincide con el archivo, cuando se bajaron periodos sueltos (source.pieces)."""
    a, b = clip["start"], clip["end"]
    ps = p["source"].get("pieces") or [[0, 0, float("inf")]]
    ps = [x for x in ps if x[0] < b and x[0] + x[2] > a] or [max((x for x in ps if x[0] <= a), default=ps[0])]
    out = []
    for n, (f, s, d) in enumerate(ps):
        lo = (a - before if n == 0 else f) - f + s
        hi = (b + after if n == len(ps) - 1 else f + d) - f + s
        out.append((f, s, max(0, lo), hi))
    return out


def spans(p, clip):
    return [(max(0, int(lo)), int(hi) + 1) for _, _, lo, hi in _parts(p, {"start": int(clip["start"]), "end": int(clip["end"])}, PAD, PAD)]


def ensure(pid, cid):
    """Deja listo el chat de un clip: mensajes y emotes. Devuelve cuántos mensajes hubo durante el clip."""
    _hold["front"] += 1                  # lo que se está viendo o exportando va antes que lo de fondo
    try:
        return _ensure(pid, cid)
    finally:
        _hold["front"] -= 1


def _ensure(pid, cid):
    p = store.load(pid)
    clip = store.find_clip(p, cid) if p else None
    if not clip:
        raise ValueError("Ese clip ya no existe.")
    if not source(p):
        raise ValueError("El chat solo se puede leer en videos de Kick.")
    d, ms = load(pid), []
    for a, b in spans(p, clip):
        if not d.get("channel") or missing(d, a, b):
            d = fetch(pid, a, b)
        ms += [m for m in d["msgs"] if a <= m[0] <= b]
    get_emotes({i for m in ms for i in TOKEN.findall(m[4])})
    inside = _parts(p, clip, 0, 0)
    return sum(any(lo <= m[0] <= hi for _, _, lo, hi in inside) for m in ms)


def ensure_many(pid, cids, ready=None):
    def run():
        for c in cids:
            for n in range(3):
                while _hold["front"]:
                    time.sleep(.3)
                try:
                    _ensure(pid, c)
                    break
                except Brake:
                    time.sleep(60)
                except ValueError:
                    return               # al abrir o exportar cada clip se vuelve a intentar y se dice por qué
            else:
                return
            if ready:
                ready(c)
    threading.Thread(target=run, daemon=True, name="chat").start()


# ------------------------------------------------------------ emotes

def _edir():
    d = config.DATA / "emotes"
    d.mkdir(exist_ok=True)
    return d


_emotes = {}


def emote(i):
    """{"n": cuadros, "w", "h"} de un emote ya bajado, o None."""
    if i not in _emotes:
        try:
            m = json.loads((_edir() / f"{i}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        _emotes[i] = m
    return _emotes[i] if _emotes[i].get("n") else None


def strip(i):
    """Archivo con todos los cuadros del emote, uno junto al otro."""
    return _edir() / f"{i}.png" if re.fullmatch(r"\d{1,12}", i) and emote(i) else None


def _convert(raw):
    """GIF, WebP, PNG… → (imagen con los cuadros en fila, cuántos)."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw), formats=("GIF", "WEBP", "PNG", "JPEG"))
    if im.width * im.height > 1024 * 1024 or not im.width or not im.height:
        raise ValueError("tamaño")
    w, h = max(8, min(3 * EH, round(im.width * EH / im.height))), EH
    total, frames, marks = min(getattr(im, "n_frames", 1), 200), [], []
    for k in range(total):
        im.seek(k)
        frames.append(im.convert("RGBA").resize((w, h), Image.LANCZOS))
        marks.append(max(20, im.info.get("duration") or 100))
    ends = [sum(marks[:k + 1]) for k in range(total)]
    n = 1 if total == 1 else max(1, min(FRAMES, round(ends[-1] * FPS / 1000)))
    out = Image.new("RGBA", (w * n, h))
    for k in range(n):
        t = (k + .5) * 1000 / FPS
        out.paste(frames[next((j for j, e in enumerate(ends) if t < e), total - 1)], (w * k, 0))
    return out, n


def _get_emote(i):
    f = _edir() / f"{i}.json"
    try:
        im, n = _convert(_get(f"{FILES}{i}/fullsize", 5_000_000))
        b = io.BytesIO()
        im.save(b, "PNG")
        (_edir() / f"{i}.png").write_bytes(b.getvalue())
        m = {"n": n, "w": im.width // n, "h": im.height}
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            return
        m = {"n": 0}
    except OSError as e:
        if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return                       # sin conexión: se intenta la próxima vez
        m = {"n": 0}
    except Exception:
        m = {"n": 0}                     # no es una imagen que sepamos leer
    f.write_text(json.dumps(m), encoding="utf-8")
    _emotes.pop(i, None)


def get_emotes(ids):
    todo = [i for i in ids if i not in _emotes and not (_edir() / f"{i}.json").exists()]
    if todo:
        with concurrent.futures.ThreadPoolExecutor(6) as ex:
            list(ex.map(_get_emote, todo[:300]))


# ------------------------------------------------------------ qué mensajes salen

def _blockfile():
    return config.DATA / "chat.json"


def blocked():
    try:
        return [str(w) for w in json.loads(_blockfile().read_text(encoding="utf-8"))["block"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def set_blocked(words):
    out = []
    for w in words:
        w = re.sub(r"\s+", " ", str(w)).strip()[:60]
        if w and w.lower() not in [x.lower() for x in out]:
            out.append(w)
    tmp = _blockfile().with_suffix(".tmp")
    tmp.write_text(json.dumps({"block": out[:300]}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_blockfile())
    return out[:300]


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def _filter(words):
    who = {_norm(w[1:]) for w in words if w.startswith("@")}
    ws = [re.escape(_norm(w)) for w in words if not w.startswith("@") and _norm(w)]
    return who, re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(ws)) if ws else None


LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|net|org|gg|tv|io|me|mx|link|shop|xyz)\b", re.I)
KEEP = re.compile(r"[^\u0020-\u024f\u0370-\u052f\u1e00-\u1eff\u2010-\u2027\u2030-\u205e\u20a0-\u20bf\u2190-\u21ff\u2600-\u27bf"
                  r"\u2b00-\u2bff\u231a\u231b\u23e9-\u23fa\u200d\ufe0f\U0001f000-\U0001faff]")


def tidy(x):
    """Texto corto y legible: sin repeticiones, sin letras raras y con pocos emotes."""
    x = KEEP.sub("", unicodedata.normalize("NFKC", x[:400]))
    x = re.sub(r"\s+", " ", x).strip()
    x = re.sub(r"(\[e:\d+\])(?:\s*\1)+", r"\1", x)
    m = re.match(r"(.{3,}?)(?:[\s\-_.,;:!¡|/]*\1){2,}", x)
    if m and m[1].startswith(x[m.end():].strip(" -_.,;:!¡|/")):
        x = m[1]                         # pegada muchas veces y cortada a la mitad de la última
    x = re.sub(r"(.{8,}?)(?:[\s\-_.,;:!¡|/]*\1){2,}", r"\1", x)
    x = re.sub(r"(.{3,}?)(?:[\s\-_.,;:!¡|/]*\1){1,}$", r"\1", x) if len(x) > 12 else x      # la misma frase pegada varias veces
    x = re.sub(r"([^\d\W])\1{4,}", r"\1\1\1", x)
    x = re.sub(r"([^\w\s])\1{3,}", r"\1\1\1", x)
    n, out, size = 0, "", 0
    for part in re.split(r"(\[e:\d+\])", x):
        if TOKEN.fullmatch(part):
            n += 1
            out += part if n <= 4 else ""
        elif size + len(part) > 90:
            return (out + part[:max(0, 90 - size)]).rstrip() + "…"
        else:
            out, size = out + part, size + len(part)
    return out.strip()


def _times(msgs):
    """Kick da la hora al segundo: los de un mismo segundo se reparten dentro de él."""
    out, k = [], 0
    while k < len(msgs):
        j = k
        while j < len(msgs) and int(msgs[j][0]) == int(msgs[k][0]):
            j += 1
        out += [(int(msgs[k][0]) + (m - k) / (j - k), *msgs[m][1:]) for m in range(k, j)]
        k = j
    return out


# groserías e insultos comunes en español e inglés, también con números, símbolos o letras de más
_RUDE = ("put[oa]s?|putit[oa]s?|puter[oi]a?s?|putaz\\w*|hdp|hijue\\w*|verg\\w*|vrg\\w*|verch\\w*|alaver\\w*|ching\\w*|chng\\w*|chigad\\w*|pendej\\w*|pndj\\w*|pendw\\w*"
         "|culer\\w*|culo\\w*|culit\\w*|culia\\w*|mierd\\w*|mrd\\w*|mamad\\w*|mama(?:s|me|mela|las|r|ste|n)|mam[oe]n\\w*|mamaw\\w*|nm+s|nm+n|emput\\w*|ptm|ptms|alv|vtv|vtalv|chtm|ctm|tmr|csm"
         "|cabron\\w*|kbron\\w*|pinche?s?|pnche?s?|joder|jodid\\w*|jodan?|cojon\\w*|coger\\w*|coj[ae]\\w*|follar?\\w*|cona(?:zo)?|concha\\w*|marico\\w*|marica\\w*|maric[ao]s?|jot[oa]s?|joter\\w*|punal|punet\\w*"
         "|ramer\\w*|prostitu\\w*|teton\\w*|tet(?:a|it|ot)\\w*|chich(?:i|is|ona|ota)\\w*|nalg\\w*|pito(?:te)?s?|pene\\w*|polla\\w*|verij\\w*|panoch\\w*|vagin\\w*|porn\\w*|violar?|violad\\w*|viola(?:r|n|ron)"
         "|imbecil\\w*|estupid\\w*|idiota\\w*|retrasad\\w*|mongol\\w*|gat[ao] de|basura|suicid\\w*|matate|muerete|nazi\\w*|hitler|negr(?:o|a)s? de|simio\\w*|prieto\\w*|naco\\w*|indio de|gron(?:e|es)"
         "|fuck\\w*|shit\\w*|bitch\\w*|asshole\\w*|nigg\\w*|fagg?\\w*|cunt\\w*|dick\\w*|pussy|whore\\w*|slut\\w*|retard\\w*|kys|rape\\w*")
RUDE = re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % _RUDE)
LEET = str.maketrans("013457@$!", "oieastasi")


def rude(text):
    """¿Trae groserías? También si van con números, separadas letra por letra o ya tapadas por Kick con ***."""
    t = _norm(text)
    if "***" in t or "**" in t:
        return True
    for v in (t, t.translate(LEET)):
        v = re.sub(r"([a-z])\1+", r"\1", v)
        joined = re.sub(r"(?<![a-z])(?:[a-z][\s._\-*]+){2,}[a-z](?![a-z])", lambda m: re.sub(r"[^a-z]", "", m[0]), v)
        if RUDE.search(t) or RUDE.search(re.sub(r"([a-z])\1+", r"\1", joined)) or RUDE_2.search(t):
            return True
    return False


RUDE_2 = re.compile(r"(?<![a-z])(?:p[uv]t[oa4]?s?|put[o0a4]s?|perras?|perros? de|zorras?|joder|culeros?)(?![a-z])")


def _ok(user, text, who, bad, safe=False):
    u = _norm(user)
    if u in BOTS or u in who:
        return False
    plain = TOKEN.sub(" ", text).strip()
    return not (plain.startswith("!") or LINK.search(plain) or (bad and bad.search(_norm(plain))) or (safe and rude(plain)))


GAP, LIFE, STEP, WINDOW = 0.9, 14.0, 0.5, 5.0
FLY, RISE = 3.4, 700


def build(p, clip, tmap):
    """Lo que dibujan igual la vista previa y la exportación. None si el clip no lleva chat."""
    ed = clip["edit"]
    if not ed.get("chat_on") or not source(p):
        return None
    from . import overlay
    num = lambda k, lo, hi, df: min(hi, max(lo, float(ed[k]))) if isinstance(ed.get(k), (int, float)) else df
    size, lead = int(num("chat_size", 26, 60, 38)), num("chat_lead", -10, 10, 0.0)
    y = int(num("chat_y", 420, 1800, max(620, ed.get("sub_y", 1250) - ed.get("sub_size", 96) * .9 - 40)))
    mode = "emotes" if ed.get("chat_mode") == "emotes" else "mensajes"
    right, names, count = ed.get("chat_side") == "der", ed.get("chat_names", True), ed.get("chat_count", True)
    W, H = round(680 * min(1.25, max(.85, size / 38))), round(440 * size / 38)
    band = 250 if mode == "emotes" else W              # lo que ocupa a lo ancho
    px = num("chat_x", 0, 100, None)                   # 0 = pegado a la izquierda, 100 = pegado a la derecha
    x0 = round((1080 - band) * px / 100) if px is not None else 1080 - 76 - band if right else 76
    out = {"mode": mode, "x": x0 + band - W if right else x0, "px": round(x0 / (1080 - band) * 100), "y": y, "w": W, "h": min(H, y - 40), "right": right, "size": size,
           "items": [], "counts": [], "parts": [], "emotes": {}, "life": LIFE, "fly": FLY, "rise": min(RISE, y - 80), "fps": FPS}
    d, s, e = load(p["id"]), clip["start"], clip["end"]
    if not d.get("channel") or any(missing(d, *x) for x in spans(p, clip)):
        out["missing"] = True
    who, bad = _filter(blocked())
    hide = set(ed.get("chat_hide") or [])
    ms = []
    near = _parts(p, clip, 24, 12)
    for t, i, u, c, x in _times([m for m in d.get("msgs", []) if any(lo <= m[0] <= hi for _, _, lo, hi in near)]):
        f0, s0 = next(((f, q) for f, q, lo, hi in near if lo <= t <= hi + 1), near[-1][:2])
        t = t - s0 + f0 - lead
        if s - 8 <= t <= e and _ok(u, x, who, bad, ed.get("chat_safe", True)):
            ms.append((t - s if t < s else tmap.to_out(t), i, u, c, x))
    used = {}

    def has(i):
        if i not in used:
            m = emote(i)
            used[i] = m
        return used[i]
    if mode == "mensajes":
        last, seen = -99, {}
        for t, i, u, c, x in ms:
            x = TOKEN.sub(lambda m: m[0] if has(m[1]) else "", x)
            x = tidy(x)
            if i in hide or not x or (count and len(re.sub(r"\W", "", TOKEN.sub("", x))) < 2) or t > tmap.duration - .4:
                continue
            k = _norm(x)
            if t - seen.get(k, -99) < 25 or t - last < GAP:
                continue
            seen[k] = last = t
            im = overlay.chat_img(u if names else "", c, x, size, W)
            out["items"].append({"id": i, "s": round(t, 3), "u": u if names else "", "c": c, "x": x, "w": im.width, "h": im.height})
    hits = [(t, i, k) for t, i, u, c, x in ms for k in list(dict.fromkeys(TOKEN.findall(x)))[:2] if has(k)]
    if mode == "emotes":
        per = {}
        for t, i, k in hits:
            if t >= -1.5:
                per.setdefault(int(t // 1), []).append((t, i, k))
        for sec in sorted(per):
            g = per[sec]
            for t, i, k in ([g[len(g) * n // 5] for n in range(5)] if len(g) > 5 else g):
                r = hashlib.md5(f"{i}{k}".encode()).digest()
                out["parts"].append([round(t, 3), k, x0 + round(r[0] / 255 * 170) + 55,
                                     round(size * (1.5, 1.9, 2.3)[r[1] % 3]), (-12, 0, 12)[r[2] % 3], round(r[3] / 255 * 6.28, 2)])
    if count:
        prev = None
        for n in range(int(tmap.duration / STEP) + 1):
            t, tot = n * STEP, {}
            for h, i, k in hits:
                if t - WINDOW < h <= t:
                    tot[k] = tot.get(k, 0) + 1
            top = [[k, v, overlay.chat_text_w(f"×{v}", size)] for k, v in sorted(tot.items(), key=lambda q: (-q[1], q[0])) if v >= 3][:3]
            if top != prev:
                out["counts"].append([t, top])
                prev = top
    need = {q[1] for q in out["parts"]} | {q[0] for c in out["counts"] for q in c[1]}
    out["emotes"] = {i: used[i] for i in sorted(need) if used.get(i)}
    return out
