"""Aviso de café: cuenta los clips exportados y dice cuándo toca pedir un café. Pocas veces y sin estorbar."""
import json
import threading
import time

from cliper import config, store

STEPS = (10, 50, 200, 500, 1000)   # clips exportados con los que sale el aviso
DAY = 86400
GAP = 30 * DAY                     # como mucho, un aviso al mes
QUIET = {"cafe": 90 * DAY, "hecho": 180 * DAY}   # tras abrir la página del café o decir que ya invitó
ANSWERS = ("visto", "cafe", "hecho", "luego")
_lock = threading.Lock()


def _file():
    return config.DATA / "cafe.json"


def _seed():
    """La primera vez: los clips que ya se exportaron cuentan."""
    keys = []
    for p in store.list_all():
        keys += [f"{p['id']}:{c['id']}" for c in p.get("clips", []) if c.get("exports")]
    return {"keys": keys, "shown": 0, "last": 0, "quiet": 0}


def _load():
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        d = _seed()
        _save(d)
        return d
    except (ValueError, OSError):
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("keys"), list):
        return _seed()
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    return {"keys": [k for k in d["keys"] if isinstance(k, str)], "shown": num(d.get("shown")), "last": num(d.get("last")), "quiet": num(d.get("quiet"))}


def _save(d):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(f)


def _step(d):
    return max([s for s in STEPS if s <= len(d["keys"])], default=0)


def _due(d, now):
    if not config.DONATE_URL.startswith("https://"):
        return None
    m = _step(d)
    return m if m > d["shown"] and now >= d["quiet"] and now - d["last"] >= GAP else None


def count(pid, cid):
    """Un clip más exportado (el mismo clip exportado otra vez no cuenta de nuevo)."""
    with _lock:
        d, k = _load(), f"{pid}:{cid}"
        if k not in d["keys"]:
            d["keys"].append(k)
            _save(d)


def status(now=None):
    with _lock:
        d = _load()
        return {"n": len(d["keys"]), "due": _due(d, now or time.time())}


def answer(a, now=None):
    """visto: ya salió el aviso; cafe: abrió la página del café; hecho: ya invitó; luego: lo cerró."""
    if a not in ANSWERS:
        raise ValueError("Respuesta no válida")
    now = now or time.time()
    with _lock:
        d = _load()
        if a == "visto":
            d["shown"], d["last"] = max(d["shown"], _step(d)), now
        elif a in QUIET:
            d["quiet"] = max(d["quiet"], now + QUIET[a])
        _save(d)
        return {"n": len(d["keys"]), "due": _due(d, now)}
