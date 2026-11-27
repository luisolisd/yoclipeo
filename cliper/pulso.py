"""Pulso del chat: cuánto reaccionó el chat de Kick en cada parte del video, para ayudar a elegir los momentos.

No lee el chat entero (serían miles de páginas): toma una muestra cada pocos segundos y mide cuántas personas
distintas escriben. Se compara con lo normal de esos minutos, así que no gana la parte con más público sino la
que más movió al chat. Lo leído se guarda en data/projects/<id>/pulso.json y no se vuelve a pedir.
"""
import bisect
import json
import re
import statistics
import threading
import time
import traceback

from . import chat, store

STEP, MOST = 8, 1500        # segundos entre muestras y cuántas como mucho (un directo muy largo se muestrea más abierto)
PACE = 1.0                  # segundos entre lecturas: lo que Kick aguanta de seguido
LATE = (2, 12)              # la reacción a lo que pasa en [a, b] se escribe entre a+2 y b+12
NEAR = 600                  # lo normal se calcula con los 10 minutos de cada lado
RISA = re.compile(r"(?:j[aeiou]){2,}j?|jsjs|ks{2,}|\bx+d+\b|\blo+l\b|\blmf?ao|kek|lulw?|omegalul|🤣|😂|😹", re.I)
SUSTO = re.compile(r"\bwt+f|\bomg\b|\bno ma+mes|\bnmms?\b|\bque\?|\bqué\?|\?{2,}|\bwow\b|pog|monka|😱|😮|😳|🤯|\bno+ pue|dios m[ií]o", re.I)
HYPE = re.compile(r"clap|hype|\bgo+d\b|\bgg+\b|vamo+s|\bo?le{3,}|fire|🔥|👏|🎉|❤", re.I)
KINDS = (("risa", "risas", RISA), ("susto", "sorpresa", SUSTO), ("hype", "emoción", HYPE))
WORD = {"risa": "risas", "susto": "sorpresa", "hype": "emoción"}

_lock = threading.Lock()
_busy = {}                  # pid -> {"n", "of"} mientras se lee


def _file(pid):
    return store.pdir(pid) / "pulso.json"


def load(pid):
    try:
        d = json.loads(_file(pid).read_text(encoding="utf-8"))
        return {"pts": [x for x in d["pts"] if isinstance(x, list) and len(x) == 5 and all(type(v) in (int, float) for v in x)]}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return {"pts": []}


def _save(pid, d):
    if not store.load(pid):
        raise ValueError("Ese proyecto ya no existe.")
    f = _file(pid)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(f)


def measure(ms, start, t):
    """Una página de Kick (del más nuevo al más viejo) → [segundo, personas por segundo, risa, susto, hype]."""
    got = []
    for m in ms:
        c = chat._clean(m)
        if c and chat._norm(c[2]) not in chat.BOTS and not c[4].startswith("!"):
            got.append((int(c[0] - start), c[2], str(m["content"])[:1000]))
    if not got:
        return [t, 0.0, 0, 0, 0]
    old = min(g[0] for g in got)
    if len(ms) >= 20 and old < t:                  # del segundo más viejo quizá solo llegó una parte
        got = [g for g in got if g[0] > old] or got
        old += 1
    span = max(1, t - old + 1)
    if len(ms) < 20:
        span = max(span, 1)
    who = {}
    for _, u, x in got:
        who[u] = who.get(u, "") + " " + x
    return [t, round(len(who) / span, 3)] + [sum(bool(r.search(x)) for x in who.values()) for _, _, r in KINDS]


def wanted(p):
    """Los segundos del directo en que se toma muestra."""
    dur = (p.get("media") or {}).get("duration") or 0
    if not dur:
        return []
    step = max(STEP, dur / MOST)
    out = []
    for _, _, lo, hi in chat._parts(p, {"start": 0, "end": dur}, 0, LATE[1]):
        t = lo + step
        while t <= hi + step / 2:
            out.append(int(t))
            t += step
    return sorted(set(out))


def ready(p, d=None):
    """Qué parte de las muestras ya está (0 a 1)."""
    ts = wanted(p)
    have = {x[0] for x in (d or load(p["id"]))["pts"]}
    return sum(t in have for t in ts) / len(ts) if ts else 0.0


def read(pid, stop=lambda: False):
    """Toma las muestras que falten. Va despacio y cede el paso a lo que se está viendo o exportando."""
    p = store.load(pid)
    if not p or not chat.source(p):
        raise ValueError("El chat solo se puede leer en videos de Kick.")
    m = chat._meta(pid)
    d = load(pid)
    have = {x[0] for x in d["pts"]}
    todo = [t for t in wanted(p) if t not in have]
    _busy[pid] = {"n": len(have), "of": len(have) + len(todo)}
    try:
        for n, t in enumerate(todo):
            while chat._hold["front"] and not stop():
                time.sleep(.3)
            if stop() or (n % 20 == 0 and not store.load(pid)):
                break
            t0 = time.time()
            ms, _ = chat._page(m["channel"], int((m["start"] + t + 1) * 1e6))
            d["pts"].append(measure(ms, m["start"], t))
            _busy[pid]["n"] += 1
            if n % 25 == 24:
                _save(pid, d)
            time.sleep(max(.2, PACE - (time.time() - t0)))
    finally:
        _busy.pop(pid, None)
        if todo:
            d["pts"].sort()
            try:
                _save(pid, d)
            except (OSError, ValueError):
                pass
    return d


_threads = {}


def start(pid):
    """Empieza a leer en segundo plano, mientras el video se transcribe."""
    p = store.load(pid)
    if not p or not chat.source(p) or p.get("options", {}).get("chat_guide") is False or p.get("options", {}).get("whole"):
        return
    with _lock:
        if pid in _threads and _threads[pid].is_alive():
            return

        def run():
            try:
                read(pid)
            except ValueError as e:
                _errors[pid] = str(e)
            except Exception:                     # sin chat se sigue igual
                traceback.print_exc()
                _errors[pid] = "no se pudo leer el chat"
        _errors.pop(pid, None)
        _threads[pid] = threading.Thread(target=run, daemon=True, name="pulso")
        _threads[pid].start()


_errors = {}


def wait(pid, progress=None, most=None):
    """Espera a que termine de leerse y devuelve el Pulso, o (None, por qué no)."""
    p = store.load(pid)
    if not p or not chat.source(p) or p.get("options", {}).get("chat_guide") is False or p.get("options", {}).get("whole"):
        return None, ""
    start(pid)
    t0 = time.time()
    while True:
        th, b = _threads.get(pid), _busy.get(pid)
        if not th or not th.is_alive():
            break
        if most and time.time() - t0 > most:
            break
        if progress and b and b["of"]:
            progress(b["n"] / b["of"], max(1, round((b["of"] - b["n"]) * PACE * 1.15 / 60)))
        th.join(1)
    d, p = load(pid), store.load(pid)
    if not p:
        return None, ""
    if ready(p, d) < .6:                           # con huecos grandes la comparación engaña
        return None, _errors.get(pid) or "no se pudo leer bastante del chat"
    return Pulso(p, d), ""


class Pulso:
    """Cuánto reaccionó el chat en un tramo del archivo, comparado con lo normal de esos minutos."""

    def __init__(self, p, d):
        dur = (p.get("media") or {}).get("duration") or 0
        pts = []
        for f, s, lo, hi in chat._parts(p, {"start": 0, "end": dur}, 0, LATE[1]):
            pts += [(x[0] - s + f, *x[1:]) for x in d["pts"] if lo <= x[0] <= hi + 1]
        self.pts = sorted(pts)
        self.ts = [x[0] for x in self.pts]
        rates = [x[1] for x in self.pts]
        floor = max(.05, .25 * statistics.median(rates)) if rates else 1
        self.ratio = []
        for x in self.pts:
            i, j = bisect.bisect_left(self.ts, x[0] - NEAR), bisect.bisect_right(self.ts, x[0] + NEAR)
            self.ratio.append(x[1] / max(floor, statistics.median(rates[i:j])))
        wins = sorted(self._heat(t, t + 40) for t in range(0, max(1, int(dur) - 39), 10))
        q = lambda f: wins[min(len(wins) - 1, int(len(wins) * f))] if wins else 9
        self.high, self.top = max(1.25, q(.80)), max(1.5, q(.95))

    def _range(self, a, b):
        return range(bisect.bisect_left(self.ts, a + LATE[0]), bisect.bisect_right(self.ts, b + LATE[1]))

    def _heat(self, a, b):
        """El promedio de las dos muestras más altas: un remate al final no se diluye, y una sola muestra rara no manda."""
        r = sorted((self.ratio[k] for k in self._range(a, b)), reverse=True)
        return sum(r[:2]) / 2 if len(r) > 1 else 0.0

    def look(self, a, b):
        """{"x": veces lo normal, "level": 0–2, "kind": "risa"|"susto"|"hype"|""}"""
        x = self._heat(a, b)
        level = 2 if x >= self.top else 1 if x >= self.high else 0
        idx = list(self._range(a, b))
        sums = [sum(self.pts[k][2 + n] for k in idx) for n in range(3)]
        people = sum(max(1, self.pts[k][2] + self.pts[k][3] + self.pts[k][4]) for k in idx) or 1
        n = max(range(3), key=lambda q: sums[q])
        kind = KINDS[n][0] if sums[n] >= 3 and sums[n] >= .45 * people else ""
        return {"x": round(x, 1), "level": level, "kind": kind}

    def note(self, a, b):
        """Lo que se le dice a la IA de ese tramo; nada si el chat estuvo como siempre."""
        k = self.look(a, b)
        if not k["level"]:
            return ""
        return f"(chat {'MUY ALTO' if k['level'] == 2 else 'alto'}, {k['x']:.1f}x lo normal{', ' + WORD[k['kind']] if k['kind'] else ''})"

    def bonus(self, a, b):
        return (0, 4, 8)[self.look(a, b)["level"]]

    def peaks(self, most=40):
        """Los picos, para un modelo que lee la transcripción entera: [(segundo, veces, tipo)]."""
        out = []
        for k in sorted(range(len(self.ts)), key=lambda k: -self.ratio[k]):
            t = self.ts[k] - 6
            if t >= 0 and all(abs(t - o[0]) > 30 for o in out):
                q = self.look(max(0, t - 15), t + 10)
                if q["level"]:
                    out.append((int(t), q["x"], WORD.get(q["kind"], "")))
            if len(out) >= most:
                break
        return sorted(out)
