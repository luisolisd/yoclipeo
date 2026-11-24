"""Publicar en YouTube con la cuenta y la app de Google de cada persona.

El permiso se guarda cifrado con la cuenta de Windows (DPAPI): copiado a otro equipo no sirve.
Nada se sube sin que la persona lo confirme en la ventana de publicar.
"""
import base64
import ctypes
import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, jobs, store

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",      # subir
          "https://www.googleapis.com/auth/youtube.readonly"]    # decir en qué canal y cómo quedó cada video
FILE = config.DATA / "youtube.json"
PUBS = config.DATA / "publicaciones.json"
TMP = config.DATA / "publicar"
CHUNK = 4 * 1024 * 1024          # múltiplo de 256 KB, como pide YouTube
WAITS = (1, 2, 4, 8, 16, 32, 64)
CATEGORIES = {"24": "Entretenimiento", "22": "Gente y blogs", "23": "Comedia", "20": "Videojuegos", "17": "Deportes", "10": "Música",
              "25": "Noticias y política", "27": "Educación", "28": "Ciencia y tecnología", "1": "Cine y animación", "19": "Viajes"}
NET = (urllib.error.URLError, OSError, http.client.HTTPException)
ACTIVE = ("en cola", "exportando", "subiendo")


class YTError(RuntimeError):
    def __init__(self, msg, code=0, reason=""):
        super().__init__(msg)
        self.code, self.reason = code, reason


class Stopped(Exception):
    pass


# ------------------------------------------------------------ cifrado con la cuenta de Windows

class _Blob(ctypes.Structure):
    _fields_ = [("n", ctypes.c_uint32), ("p", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    c = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = c.CryptProtectData if protect else c.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise OSError("Windows no pudo " + ("cifrar" if protect else "descifrar"))
    try:
        return ctypes.string_at(out.p, out.n)
    finally:
        k = ctypes.WinDLL("kernel32")
        k.LocalFree.argtypes = [ctypes.c_void_p]
        k.LocalFree(ctypes.cast(out.p, ctypes.c_void_p))


def seal(obj):
    return base64.b64encode(_dpapi(json.dumps(obj).encode(), True)).decode()


def unseal(s):
    try:
        return json.loads(_dpapi(base64.b64decode(s), False))
    except (OSError, ValueError, TypeError):
        return {}


_lock = threading.RLock()
_mem = {"token": "", "until": 0.0}
_pending = {}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.1 + 0.05 * i)


def _read():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return {**d, "secret": unseal(d.get("secret", ""))} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    _write(FILE, {**d, "secret": seal(d.get("secret", {}))})


# ------------------------------------------------------------ llamadas a Google

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None            # el permiso nunca viaja a otra dirección; además, 308 aquí significa «sigue»


_open = urllib.request.build_opener(_NoRedirect).open
REASONS = {
    "quotaExceeded": "Se acabó la cuota de hoy de tu app de Google. Se renueva a medianoche, hora del Pacífico.",
    "rateLimitExceeded": "YouTube pidió esperar un momento.", "userRateLimitExceeded": "YouTube pidió esperar un momento.",
    "uploadLimitExceeded": "Tu canal llegó a su límite de videos por hoy. Intenta mañana.",
    "youtubeSignupRequired": "Esa cuenta de Google no tiene canal de YouTube.",
    "accessNotConfigured": "Falta activar «YouTube Data API v3» en tu proyecto de Google.",
    "SERVICE_DISABLED": "Falta activar «YouTube Data API v3» en tu proyecto de Google.",
    "insufficientPermissions": "El permiso no alcanza. Desconecta y vuelve a conectar YouTube.",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "El permiso no alcanza. Desconecta y vuelve a conectar YouTube.",
    "invalidTitle": "YouTube no aceptó el título.", "invalidDescription": "YouTube no aceptó la descripción.", "invalidTags": "YouTube no aceptó las etiquetas.",
    "invalidPublishAt": "YouTube no aceptó la fecha.", "invalidCategoryId": "YouTube no aceptó la categoría.", "mediaBodyRequired": "El video llegó vacío.",
    "invalid_client": "Google no reconoce la app. Vuelve a elegir su archivo.", "invalid_grant": "El permiso caducó o se quitó. Vuelve a conectar YouTube.",
    "redirect_uri_mismatch": "La app de Google debe ser de tipo «App de escritorio».", "access_denied": "No se dio el permiso.",
    "client_user_mismatch": "Esa app de Google solo funciona con la cuenta que la creó.",
}


def _fail(e):
    """Pasa un error de Google a algo que se entienda. Nunca incluye claves."""
    try:
        j = json.loads(e.read(65536))
    except Exception:
        j = {}
    err = j.get("error") if isinstance(j, dict) else None
    reason = msg = ""
    if isinstance(err, str):
        reason, msg = err, str(j.get("error_description", ""))
    elif isinstance(err, dict):
        errs = [x for x in err.get("errors") or [] if isinstance(x, dict)]
        details = [x for x in err.get("details") or [] if isinstance(x, dict) and x.get("reason")]
        reason = str((errs[0].get("reason") if errs else "") or (details[0]["reason"] if details else "") or err.get("status", ""))
        if reason not in REASONS and details and details[0]["reason"] in REASONS:
            reason = str(details[0]["reason"])
        msg = re.sub(r"<[^>]+>", "", str(err.get("message", "")))
    return YTError(REASONS.get(reason) or (f"YouTube respondió {e.code}" + (f": {msg[:200]}" if msg else "")), e.code, reason)


def _call(url, method="GET", headers=None, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "YoClipeo", **(headers or {})})
    with _open(req, timeout=timeout) as r:
        return r.status, r.headers, r.read()


def _form(url, **kw):
    try:
        return json.loads(_call(url, "POST", {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(kw).encode())[2] or b"{}")
    except urllib.error.HTTPError as e:
        raise _fail(e)
    except NET:
        raise YTError("No hay conexión con Google.", reason="net")


def token(force=False):
    with _lock:
        if not force and _mem["token"] and time.time() < _mem["until"]:
            return _mem["token"]
        d = _read()
        s = d.get("secret", {})
        if not s.get("refresh"):
            raise YTError("YouTube no está conectado. Conéctalo en Ajustes.")
        try:
            r = _form(TOKEN, client_id=s["id"], client_secret=s["key"], refresh_token=s["refresh"], grant_type="refresh_token")
        except YTError as e:
            if e.reason == "invalid_grant":
                d["expired"] = True
                _save(d)
            raise
        _mem.update(token=r["access_token"], until=time.time() + max(60, int(r.get("expires_in", 3600)) - 120))
        return _mem["token"]


def _api(path, **q):
    for again in (False, True):
        try:
            return json.loads(_call(f"{API}/{path}?{urllib.parse.urlencode(q)}", headers={"Authorization": f"Bearer {token(again)}"})[2])
        except urllib.error.HTTPError as e:
            if e.code == 401 and not again:
                continue
            raise _fail(e)
        except NET:
            raise YTError("No hay conexión con YouTube.", reason="net")


# ------------------------------------------------------------ conectar

def set_client(cid, key):
    """La app de Google de cada persona (tipo «App de escritorio»)."""
    cid, key = str(cid).strip(), str(key).strip()
    if not re.fullmatch(r"[\w.-]{10,200}\.apps\.googleusercontent\.com", cid) or not re.fullmatch(r"[\w-]{10,200}", key):
        raise ValueError("Ese archivo no es el de una app de escritorio de Google.")
    with _lock:
        if _read().get("secret", {}).get("refresh"):
            raise ValueError("Primero desconecta YouTube.")
        _save({"secret": {"id": cid, "key": key}})


def clear():
    """Quita el permiso en Google y borra todo lo guardado aquí."""
    with _lock:
        if any(p["status"] in ACTIVE for p in pubs()):
            raise ValueError("Hay videos subiéndose. Cancélalos o espera a que terminen.")
        s = _read().get("secret", {})
        _mem.update(token="", until=0.0)
        FILE.unlink(missing_ok=True)
    if not s.get("refresh"):
        return ""
    try:
        _form(REVOKE, token=s["refresh"])
        return ""
    except YTError as e:
        return "" if e.reason in ("invalid_token", "invalid_grant") else "Se borró de este equipo, pero no se pudo avisar a Google. Quítalo también en myaccount.google.com/permissions."


def connect(port):
    s = _read().get("secret", {})
    if not s.get("id"):
        raise ValueError("Primero elige el archivo de tu app de Google.")
    ver, state, back = secrets.token_urlsafe(64), secrets.token_urlsafe(32), f"http://127.0.0.1:{port}/youtube/callback"
    with _lock:
        _pending.clear()
        _pending.update(state=state, ver=ver, back=back, t=time.time(), error="")
    ch = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()
    return AUTH + "?" + urllib.parse.urlencode({"client_id": s["id"], "redirect_uri": back, "response_type": "code", "scope": " ".join(SCOPES), "state": state,
                                                "code_challenge": ch, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent select_account"})


def callback(state, code, error):
    """Vuelta de Google. Devuelve el nombre del canal."""
    with _lock:
        p = dict(_pending)
        if not p.get("state") or not hmac.compare_digest(p["state"].encode(), str(state).encode()) or time.time() - p["t"] > 900:
            raise YTError("Este enlace ya no sirve. Vuelve a pulsar «Conectar con YouTube».")
        _pending["state"] = ""           # sirve una sola vez
    try:
        if error or not code:
            raise YTError(REASONS.get(error, "No se dio el permiso."))
        d = _read()
        s = d.get("secret", {})
        r = _form(TOKEN, client_id=s.get("id", ""), client_secret=s.get("key", ""), code=code, code_verifier=p["ver"], grant_type="authorization_code", redirect_uri=p["back"])
        got = set(str(r.get("scope", "")).split())
        if not set(SCOPES) <= got or not r.get("refresh_token"):
            if r.get("access_token"):
                _quiet(lambda: _form(REVOKE, token=r["access_token"]))
            raise YTError("Faltó marcar los dos permisos de YouTube. Vuelve a conectar y deja los dos marcados.")
        with _lock:
            _mem.update(token=r["access_token"], until=time.time() + max(60, int(r.get("expires_in", 3600)) - 120))
        try:
            it = _api("channels", part="snippet", mine="true").get("items") or []
            if not it:
                raise YTError(REASONS["youtubeSignupRequired"])
        except YTError:
            _quiet(lambda: _form(REVOKE, token=r["refresh_token"]))
            _mem.update(token="", until=0.0)
            raise
        ch = {"id": it[0]["id"], "title": it[0]["snippet"].get("title", ""), "handle": it[0]["snippet"].get("customUrl", "")}
        with _lock:
            _save({"secret": {"id": s["id"], "key": s["key"], "refresh": r["refresh_token"]}, "channel": ch, "since": time.time(), "expired": False})
        return ch["title"]
    except YTError as e:
        _pending["error"] = str(e)
        raise


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass


def status():
    d = _read()
    s = d.get("secret", {})
    return {"configured": bool(s.get("id")), "connected": bool(s.get("refresh")) and not d.get("expired"), "expired": bool(s.get("refresh")) and bool(d.get("expired")),
            "channel": d.get("channel") if s.get("refresh") else None, "error": _pending.get("error", ""), "categories": CATEGORIES, "first": first()}


# ------------------------------------------------------------ publicaciones

_q = queue.Queue()
_queued = set()
_wake = threading.Event()


def pubs():
    with _lock:
        try:
            return json.loads(PUBS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []


def _set(pid, **kw):
    with _lock:
        ps = pubs()
        for p in ps:
            if p["id"] == pid:
                p.update(kw)
                _write(PUBS, ps)
                return p
    return None


def _one(i):
    return next((p for p in pubs() if p["id"] == i), None)


def public(p):
    return {k: v for k, v in p.items() if k != "session"}


def listing(pid="", cid=""):
    return [public(p) for p in reversed(pubs()) if (not pid or p["pid"] == pid) and (not cid or p["cid"] == cid)]


def first():
    """¿Es la primera? La ventana sugiere subirla en privado."""
    return not any(p.get("video") for p in pubs())


def active():
    return any(p["status"] in ACTIVE for p in pubs())


def _tags(tags):
    out, n = [], 0
    for t in tags if isinstance(tags, list) else []:
        t = re.sub(r'[<>",]', "", str(t)).strip().lstrip("#").strip()
        k = len(t) + (2 if " " in t else 0) + (1 if out else 0)      # así cuenta YouTube
        if t and t.lower() not in [x.lower() for x in out] and n + k <= 480:
            out.append(t)
            n += k
    return out


def _when(s):
    if not s:
        return ""
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        assert t.tzinfo
    except (ValueError, AssertionError):
        raise ValueError("Revisa la fecha y la hora.")
    now = dt.datetime.now(dt.timezone.utc)
    if t < now + dt.timedelta(minutes=15):
        raise ValueError("Programa con al menos 15 minutos de margen, para que dé tiempo de exportar y subir.")
    if t > now + dt.timedelta(days=365):
        raise ValueError("La fecha es a más de un año.")
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def add(body):
    """Pone en cola lo que la persona confirmó. Todo se revisa antes de aceptar nada."""
    st = status()
    if not st["connected"]:
        raise ValueError("YouTube no está conectado. Conéctalo en Ajustes.")
    if body.get("channel") != st["channel"]["id"]:
        raise ValueError("Cambió el canal conectado. Cierra esta ventana y revisa otra vez.")
    if not isinstance(body.get("kids"), bool):
        raise ValueError("Di si el video está hecho para niños.")
    cat = str(body.get("category") or "24")
    if cat not in CATEGORIES:
        raise ValueError("Categoría no válida.")
    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("Elige entre 1 y 50 clips.")
    old, new = pubs(), []
    for it in items:
        p = store.load(str(it.get("pid", "")))
        c = store.find_clip(p, it.get("cid")) if p else None
        if not c:
            raise ValueError("Uno de los clips ya no existe.")
        title, desc = re.sub(r"\s+", " ", str(it.get("title") or "")).strip(), str(it.get("description") or "").strip()
        tag = f" («{title[:40]}»)" if len(items) > 1 else ""
        if not 1 <= len(title) <= 100:
            raise ValueError("El título va de 1 a 100 letras" + tag + ".")
        if re.search(r"[<>]", title + desc):
            raise ValueError("YouTube no acepta los signos < ni > en el título o la descripción" + tag + ".")
        if len(desc.encode()) > 5000:
            raise ValueError("La descripción es demasiado larga" + tag + ".")
        privacy, when = it.get("privacy"), _when(it.get("publish_at"))
        if privacy not in ("private", "unlisted", "public"):
            raise ValueError("Elige quién puede verlo.")
        if when and privacy != "private":
            raise ValueError("Un video programado se sube en privado hasta su hora.")
        if not it.get("again") and any(x["pid"] == p["id"] and x["cid"] == c["id"] and (x.get("video") or x["status"] in ACTIVE) for x in old + new):
            raise ValueError("Ese clip ya se subió o se está subiendo" + tag + ".")
        new.append({"id": store.new_id(10), "pid": p["id"], "cid": c["id"], "channel": st["channel"], "title": title, "description": desc, "tags": _tags(it.get("tags")),
                    "privacy": privacy, "publish_at": when, "kids": body["kids"], "category": cat, "notify": body.get("notify") is not False,
                    "synthetic": body.get("synthetic") is True, "status": "en cola", "progress": 0, "created": time.time(), "video": "", "error": "", "session": "", "sent": 0})
    with _lock:
        _write(PUBS, pubs() + new)
    for p in new:
        _push(p["id"])
    return [public(p) for p in new]


def _push(i):
    with _lock:
        if i in _queued:
            return
        _queued.add(i)
    _q.put(i)


def retry(i):
    p = _one(i)
    if not p or p["status"] not in ("error", "cancelada") or p.get("video"):
        raise ValueError("No hay nada que reintentar.")
    if p["publish_at"]:
        _when(p["publish_at"])
    _set(i, status="en cola", progress=0, error="", stop=False)
    _push(i)


def cancel(i):
    p = _one(i)
    if not p or p["status"] not in ACTIVE:
        raise ValueError("Ya no se puede cancelar.")
    _set(i, stop=True, **({"status": "cancelada"} if p["status"] == "en cola" else {}))


def forget(i):
    """Quita la fila de la lista. El video de YouTube no se toca."""
    with _lock:
        p = _one(i)
        if not p or p["status"] in ACTIVE:
            raise ValueError("Primero cancélala.")
        if p.get("video"):
            _set(i, hidden=True)       # se conserva para no subir dos veces el mismo clip sin avisar
        else:
            _write(PUBS, [x for x in pubs() if x["id"] != i])
    (TMP / f"{i}.mp4").unlink(missing_ok=True)


def _check_stop(i):
    p = _one(i)
    if not p or p.get("stop"):
        raise Stopped()
    return p


def _export(p):
    """El video a subir: el 1080p ya exportado si sigue igual que el clip; si no, se exporta. Se sube una copia
    aparte, por si se vuelve a exportar mientras tanto."""
    out = TMP / f"{p['id']}.mp4"
    if p.get("session") and out.exists():
        return out                       # se continúa una subida a medias: tiene que ser el mismo archivo
    _set(p["id"], status="exportando", progress=0, session="", sent=0)
    sig, rec = jobs.clip_sig(p["pid"], p["cid"]), None
    pr = store.load(p["pid"])
    c = store.find_clip(pr, p["cid"]) if pr else None
    if not c or sig is None:
        raise YTError("El clip ya no existe.")
    for x in c.get("exports", []):
        if x["quality"] == "1080p" and x.get("sig") == sig:
            f = store.pdir(p["pid"]) / "exportados" / x["file"]
            rec = x["file"] if f.exists() and f.stat().st_size == x["size"] else rec
    mine = lambda x: x["kind"] == "export" and (x["pid"], x["cid"], x["quality"]) == (p["pid"], p["cid"], "1080p")
    run = next((x["id"] for x in jobs.list_jobs() if mine(x) and x["status"] in ("en cola", "renderizando")), "")
    if run or not rec:                   # si ya se está exportando, se espera a esa
        run = run or jobs.enqueue_export(p["pid"], p["cid"], "1080p")["id"]
        while True:
            _check_stop(p["id"])
            k = next((x for x in jobs.list_jobs() if x["id"] == run), None)
            if not k or k["status"] == "error":
                raise YTError("No se pudo exportar: " + (k or {}).get("error", "")[:200])
            if k["status"] == "listo":
                rec = k["file"]
                break
            _set(p["id"], progress=round(k.get("progress") or 0))
            time.sleep(1)
    TMP.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.pdir(p["pid"]) / "exportados" / rec, out)
    return out


def _late(p):
    if p["publish_at"] and dt.datetime.fromisoformat(p["publish_at"].replace("Z", "+00:00")) < dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1):
        raise YTError("La hora programada ya pasó y no se subió, para que no saliera de inmediato. Publícalo otra vez con otra hora.")


def _start_session(p, size):
    st = {"privacyStatus": p["privacy"], "selfDeclaredMadeForKids": p["kids"]}
    if p["publish_at"]:
        st["publishAt"] = p["publish_at"]
    if p["synthetic"]:
        st["containsSyntheticMedia"] = True
    body = json.dumps({"snippet": {"title": p["title"], "description": p["description"], "tags": p["tags"], "categoryId": p["category"]}, "status": st}).encode()
    url = UPLOAD + "?" + urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true" if p["notify"] else "false"})
    for again in (False, True):
        try:
            _, h, _ = _call(url, "POST", {"Authorization": f"Bearer {token(again)}", "Content-Type": "application/json; charset=UTF-8",
                                          "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, body)
        except urllib.error.HTTPError as e:
            if e.code == 401 and not again:
                continue
            raise _fail(e)
        except NET:
            raise YTError("No hay conexión con YouTube.", reason="net")
        loc = h.get("Location", "")
        a, b = urllib.parse.urlsplit(loc), urllib.parse.urlsplit(UPLOAD)
        if a.scheme != b.scheme or not (a.hostname == b.hostname or (a.hostname or "").endswith(".googleapis.com")):
            raise YTError("YouTube respondió algo inesperado.")
        return loc


def _put(url, data, start, size, again=False):
    """Manda un pedazo (o pregunta por dónde va, si data es None). Devuelve (video, siguiente byte)."""
    rng = f"bytes */{size}" if data is None else f"bytes {start}-{start + len(data) - 1}/{size}"
    try:
        _, _, body = _call(url, "PUT", {"Authorization": f"Bearer {token(again)}", "Content-Type": "video/mp4", "Content-Range": rng}, data or b"", 180)
        return json.loads(body), size
    except urllib.error.HTTPError as e:
        if e.code == 308:
            m = re.fullmatch(r"bytes=0-(\d+)", e.headers.get("Range", "") or "")
            return None, int(m.group(1)) + 1 if m else 0
        if e.code == 401 and not again:
            return _put(url, data, start, size, True)
        raise


def _upload(p, f):
    size, i = f.stat().st_size, p["id"]
    url, at, ask = (unseal(p["session"]) if p.get("session") else {}).get("url", ""), 0, bool(p.get("session"))
    if not url:
        _late(p)
        url, ask = _start_session(p, size), False
        _set(i, session=seal({"url": url}))
    tries, best = 0, 0
    with open(f, "rb") as fh:
        while True:
            q = _check_stop(i)
            if not ask:
                _late(q)
            try:
                if ask:
                    video, at = _put(url, None, 0, size)
                    ask = False
                else:
                    fh.seek(at)
                    video, nxt = _put(url, fh.read(CHUNK), at, size)
                    if nxt <= at and not video:
                        raise YTError("La subida no avanza. Reintenta.")
                    at = nxt
                if at > best:                # solo lo que avanza borra los intentos fallidos
                    tries, best = 0, at
                _set(i, status="subiendo", progress=round(100 * at / size, 1), sent=at)
                if video:
                    return video
            except urllib.error.HTTPError as e:
                if e.code == 404 or e.code == 410:
                    _set(i, session="", sent=0)
                    if q.get("sent", 0) + CHUNK >= size:
                        raise YTError("No se sabe si alcanzó a subir. Revisa tu canal antes de reintentar.")
                    raise YTError("La subida caducó. Reintenta.")
                if e.code not in (500, 502, 503, 504):
                    raise _fail(e)
                tries, ask = tries + 1, True
            except YTError as e:
                if e.reason != "net":
                    raise
                tries, ask = tries + 1, True
            except (*NET, ValueError):          # se cortó: primero se pregunta por dónde iba
                tries, ask = tries + 1, True
            if ask:
                if tries > len(WAITS):
                    raise YTError("Se perdió la conexión. Reintenta: sigue donde se quedó.")
                _wake.wait(WAITS[tries - 1])


def _run(i):
    p = _one(i)
    if not p or p["status"] not in ACTIVE:
        return
    try:
        d = _read()
        if (d.get("channel") or {}).get("id") != p["channel"]["id"]:
            raise YTError("El canal conectado ya no es el mismo.")
        _late(p)
        f = _export(_check_stop(i))
        _check_stop(i)
        v = _upload(_one(i), f)
        got = (v.get("status") or {}).get("privacyStatus", "")
        note = "YouTube lo dejó en privado." if got == "private" and p["privacy"] != "private" else ""
        _set(i, status="procesando", progress=100, video=str(v["id"]), session="", error="", note=note, done=time.time())
        _quiet(f.unlink)                 # si no se puede ahora, se borra al volver a abrir
    except Stopped:
        _set(i, status="cancelada", session="", sent=0)
        _quiet((TMP / f"{i}.mp4").unlink)
    except Exception as e:
        if not isinstance(e, YTError):
            traceback.print_exc()
        _set(i, status="error", error=str(e)[:400] if isinstance(e, YTError) else f"No se pudo publicar: {str(e)[:200]}")


def _worker():
    while True:
        i = _q.get()
        with _lock:
            _queued.discard(i)
        _run(i)


FAILS = {"duplicate": "YouTube dice que es un duplicado.", "copyright": "YouTube lo rechazó por derechos de autor.", "length": "YouTube lo rechazó por su duración.",
         "inappropriate": "YouTube lo rechazó por su contenido.", "termsOfUse": "YouTube lo rechazó por sus términos de uso.", "claim": "Tiene un reclamo de derechos."}


def check_processed():
    """Pregunta cómo quedaron los que YouTube está procesando."""
    ps = [p for p in pubs() if p["status"] == "procesando"]
    if not ps:
        return
    by = {v["id"]: v for v in _api("videos", part="status", id=",".join(p["video"] for p in ps[:50])).get("items", [])}
    for p in ps[:50]:
        s = by.get(p["video"], {}).get("status", {})
        up = s.get("uploadStatus", "")
        if up == "processed" or (up == "uploaded" and time.time() - p.get("done", 0) > 7200):
            _set(p["id"], status="lista")
        elif up in ("failed", "rejected"):
            why = s.get("rejectionReason") or s.get("failureReason") or ""
            _set(p["id"], status="error", error=FAILS.get(why, f"YouTube no pudo usar el video ({why or up})."))
        elif not up and time.time() - p.get("done", 0) > 900:
            _set(p["id"], status="error", error="El video ya no está en YouTube.")


def _checker():
    while True:
        time.sleep(30)
        try:
            check_processed()
        except Exception:
            pass


def start():
    TMP.mkdir(parents=True, exist_ok=True)
    live = {p["id"] for p in pubs() if not p.get("video")}
    for f in TMP.glob("*.mp4"):
        if f.stem not in live:
            f.unlink(missing_ok=True)
    threading.Thread(target=_worker, daemon=True, name="youtube").start()
    threading.Thread(target=_checker, daemon=True, name="youtube-estado").start()
    for p in pubs():                     # lo que la persona ya había confirmado sigue donde se quedó
        if p["status"] in ACTIVE:
            _push(p["id"])
