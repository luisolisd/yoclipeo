"""Reemplazar palabras del guion: en un clip o en todo el proyecto (sus clips y la transcripción)."""
import json
import re
import unicodedata

from . import store

EDGES = re.compile(r"^([^\w]*)(.*?)([^\w]*)$", re.S)
MOST = 80                   # letras que se aceptan al buscar o cambiar


def _parts(x):
    """("¿", "Vicor", "?")"""
    return EDGES.match(unicodedata.normalize("NFC", x)).groups()


def _same(x):
    return _parts(x)[1].casefold()


def _cased(new, old):
    """Si se escribió en minúsculas, sigue las mayúsculas de lo que había."""
    if not new or new != new.lower() or not old[:1].isupper():
        return new
    return new.upper() if len(old) > 1 and old.isupper() else new[0].upper() + new[1:]


def _dress(new, old):
    """El texto nuevo con los signos que tenía el de antes (salvo que el nuevo ya traiga los suyos)."""
    a, core, z = _parts(old)
    na, nc, nz = _parts(new)
    return (na or a) + _cased(nc, core) + (nz or z) if nc else ""


def changes(words, find, to):
    """Qué cambiaría: [[posición, antes, después], …]. Compara palabras enteras, sin fijarse en mayúsculas ni en signos."""
    find, to = [_same(x) for x in find.split() if _same(x)], to.split()
    if not find:
        return []
    live = [(n, w["w"]) for n, w in enumerate(words) if w["w"].strip()]
    out, k, size = [], 0, len(find)
    inner = re.compile(r"(?<!\w)" + r"[^\w]+".join(re.escape(x) for x in find) + r"(?!\w)", re.I)
    while k < len(live):
        n, x = live[k]
        if len(x.split()) > 1:                         # alguien ya escribió varias palabras en esta
            y = inner.sub(lambda m: _cased(" ".join(to), m[0]), unicodedata.normalize("NFC", x))
            y = re.sub(r"\s+", " ", y).strip()
            if y != unicodedata.normalize("NFC", x).strip():
                out.append([n, x, y if re.search(r"\w", y) else ""])
            k += 1
            continue
        got = live[k:k + size]
        if len(got) == size and all(len(t.split()) == 1 and _same(t) == f for (_, t), f in zip(got, find)):
            new = [""] * size
            for q in range(min(size, len(to))):
                new[q] = to[q] if q < size - 1 else " ".join(to[q:])
            if to:                                     # los signos de los extremos se quedan en lo que se ve
                last = min(size, len(to)) - 1
                a, z = _parts(got[0][1])[0], _parts(got[-1][1])[2]
                na, nz = _parts(new[0])[0], _parts(new[last])[2]
                for q in range(last + 1):
                    b, core, e = _parts(new[q])
                    new[q] = b + _cased(core, _parts(got[q][1])[1]) + e if core else new[q]
                new[0] = ("" if na else a) + new[0]
                new[last] += "" if nz else z
            out += [[m, t, y] for (m, t), y in zip(got, new) if t != y]
            k += size
        else:
            k += 1
    return out


def count(words, find, ch):
    """Cuántas veces sale, no cuántas palabras se tocan."""
    size = max(1, len([x for x in find.split() if _same(x)]))
    n, last = 0, None
    for k, _, _ in ch:
        if size == 1 or last is None or k - last >= size:
            n, last = n + 1, k
    return n


def _flat(tr):
    return [w for s in tr.get("segments", []) for w in s.get("words", [])]


def _retext(tr, touched):
    """El texto de cada línea tocada, que es lo que lee la IA si se vuelve a elegir."""
    n = 0
    for s in tr.get("segments", []):
        ws = s.get("words", [])
        if any(n <= k < n + len(ws) for k in touched):
            s["text"] = " ".join(w["w"] for w in ws if w["w"].strip())
        n += len(ws)


def _tfile(pid):
    return store.pdir(pid) / "transcript.json"


def _read(pid):
    try:
        return json.loads(_tfile(pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(pid, tr):
    f = _tfile(pid)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def _text(v, what):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    if len(v) > MOST:
        raise ValueError(f"{what}: usa menos de {MOST} letras.")
    return v


def look(pid, cid, find):
    """Cuántas hay, sin cambiar nada: {"clip", "idx", "all", "clips"}."""
    p = store.load(pid)
    c = store.find_clip(p, cid) if p else None
    if not c:
        raise ValueError("Ese clip ya no existe.")
    find = _text(find, "Buscar")
    if not any(_same(x) for x in find.split()):
        return {"clip": 0, "idx": [], "all": 0, "clips": 0}
    here = changes(c["words"], find, "")               # quitarlas las cambia todas: así se cuentan
    per = [count(q["words"], find, changes(q["words"], find, "")) for q in p.get("clips", [])]
    return {"clip": count(c["words"], find, here), "idx": [k for k, _, _ in here],
            "all": sum(per), "clips": sum(x > 0 for x in per)}


def replace(pid, cid, find, to, everywhere=False):
    """Cambia y devuelve lo necesario para deshacerlo: {"n", "clips", "done"}."""
    find, to = _text(find, "Buscar"), _text(to, "Cambiar por")
    if not any(_same(x) for x in find.split()):
        raise ValueError("Escribe qué palabra buscar.")
    if not store.find_clip(store.load(pid) or {"clips": []}, cid):
        raise ValueError("Ese clip ya no existe.")
    done = {"clips": {}, "emojis": {}, "tr": []}
    total = [0]

    def f(q):
        for c in q["clips"]:
            if c["id"] != cid and not everywhere:
                continue
            ch = changes(c["words"], find, to)
            if not ch:
                continue
            total[0] += count(c["words"], find, ch)
            for k, _, y in ch:
                c["words"][k]["w"] = y
            done["clips"][c["id"]] = [[round(c["words"][k].get("s", 0), 3), x, y] for k, x, y in ch]   # por su tiempo: el corte puede cambiar
            if len(find.split()) == 1 and to:          # el emoji sigue saliendo con su palabra
                em = []
                for k, e in enumerate(c.get("emojis") or []):
                    if _same(str(e.get("word", ""))) == _same(find):
                        em.append([k, e["word"], to])
                        e["word"] = to.split()[0] if len(to.split()) == 1 else to
                if em:
                    done["emojis"][c["id"]] = em
    store.update(pid, f)
    if everywhere and to:                              # en la transcripción se corrige, no se borra
        tr = _read(pid)
        ch = changes(_flat(tr), find, to) if tr else []
        if ch:
            ws = _flat(tr)
            for k, _, y in ch:
                ws[k]["w"] = y
            _retext(tr, {k for k, _, _ in ch})
            _write(pid, tr)
            done["tr"] = ch
    return {"n": total[0], "clips": len(done["clips"]), "tr": len(done["tr"]), "done": done}


def undo(pid, done):
    """Deshace un reemplazo. Lo que se haya vuelto a cambiar a mano se respeta."""
    if not isinstance(done, dict) or not store.load(pid):
        raise ValueError("Ya no se puede deshacer.")
    touched = []

    def back(words, ch, key):
        n = 0
        for k, x, y in ch:
            if isinstance(k, int) and 0 <= k < len(words) and words[k].get(key) == y:
                words[k][key] = str(x)
                n += 1
        return n

    def f(q):
        for c in q["clips"]:
            n = 0
            for s, x, y in (done.get("clips") or {}).get(c["id"], []):
                w = next((w for w in c["words"] if w["w"] == y and round(w.get("s", 0), 3) == s), None)
                if w:
                    w["w"] = str(x)
                    n += 1
            if n:
                touched.append(c["id"])
            back(c.get("emojis") or [], (done.get("emojis") or {}).get(c["id"], []), "word")
    store.update(pid, f)
    tr = _read(pid) if done.get("tr") else None
    if tr and back(_flat(tr), done["tr"], "w"):
        _retext(tr, {k for k, _, _ in done["tr"]})
        _write(pid, tr)
    return {"clips": touched}
