"""Elección de momentos virales: Claude API (preferido) o reglas locales como respaldo."""
import json
import re

from .config import load_settings
from .store import new_id
from .transcribe import all_words

CATEGORIES = ["Historia", "Dato curioso", "Polémico", "Humor", "Emotivo", "Consejo", "Opinión fuerte",
              "Alta retención", "Revelación", "Reacción"]

SOCIAL = ["instagram", "tiktok", "youtube", "facebook", "whatsapp", "twitch", "twitter", "spotify",
          "kick", "telegram", "linkedin"]


def _factory_edit(layout="vertical"):
    return {
        "layout": layout,            # vertical | full | streamer | split
        "framing": "auto",           # auto | manual
        "manual_x": 0.5,             # centro horizontal si framing=manual (0-1)
        "streamer": None,            # {"cam":[x,y,w,h], "game":[x,y,w,h], "cam_h":640}
        "split": None,               # {"pid":..., "offset":0.0}
        "style": "karaoke",          # karaoke | dinamico
        "font": "impacto",
        "color": "amarillo",
        "subs_on": True,
        "sub_y": 1250,
        "sub_size": 96,
        "upper": True,
        "title_on": True,
        "title_secs": 0,             # 0 = todo el clip
        "title_style": "caja", "title_font": "clasica", "title_color": "blanco", "title_size": 62, "title_y": 250,
        "filter": "ninguno",         # ninguno | calido | cine | vivo | bn
        "zooms": False,
        "emojis_on": False,
        "logos_on": False,
        "remove_silence": False,
    }


# ---------------------------------------------------------------- transcripción → líneas

def build_lines(transcript, max_words=28, gap=0.8):
    lines, cur = [], []
    words = all_words(transcript)
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sentence = bool(re.search(r"[.!?…]$", w["w"]))
        if (nxt is None or end_sentence or len(cur) >= max_words or (nxt["s"] - w["e"]) > gap):
            lines.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
    return lines


def snap(start, end, words, min_len, max_len):
    """Ajusta inicio/fin a palabras completas y, si se puede, al final de una frase."""
    if not words:
        return start, end
    starts = [w for w in words if w["s"] >= start - 0.35]
    if not starts:
        return start, end
    sw = starts[0]
    s = max(0.0, sw["s"] - 0.08)
    inside = [w for w in words if w["e"] <= end + 0.35 and w["s"] >= s]
    if not inside:
        return start, end
    ew = inside[-1]
    # extender hasta fin de frase si está cerca
    if not re.search(r"[.!?…]$", ew["w"]):
        idx = words.index(ew)
        for w in words[idx + 1: idx + 14]:
            if w["e"] - s > max_len:
                break
            ew = w
            if re.search(r"[.!?…]$", w["w"]):
                break
    e = ew["e"] + 0.25
    if e - s < min_len:
        idx = words.index(ew)
        for w in words[idx + 1:]:
            e = w["e"] + 0.25
            if e - s >= min_len and re.search(r"[.!?…]$", w["w"]):
                break
            if e - s >= max_len:
                break
    if e - s > max_len + 3:
        e = s + max_len
    return round(s, 3), round(e, 3)


def make_clip(start, end, words, meta, layout="vertical"):
    cw = [dict(w) for w in words if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
    kws = {k.lower().strip(".,!?¡¿") for k in meta.get("keywords", [])}
    for w in cw:
        w["key"] = w["w"].lower().strip(".,!?¡¿\"'") in kws
    return {
        "id": new_id(6),
        "start": start, "end": end,
        "title": meta.get("title", "")[:90],
        "score": int(max(0, min(100, meta.get("score", 50)))),
        "category": meta.get("category", ""),
        "reason": meta.get("reason", ""),
        "description": meta.get("description", ""),
        "hashtags": meta.get("hashtags", []),
        "keywords": meta.get("keywords", []),
        "emojis": meta.get("emojis", []),
        "words": cw,
        "edit": _factory_edit(layout),  # los predeterminados los pone defaults.py
        "exports": [],
    }


# ---------------------------------------------------------------- Claude

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "score": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "reason": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "emojis": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"word": {"type": "string"}, "emoji": {"type": "string"}},
                        "required": ["word", "emoji"], "additionalProperties": False}},
                },
                "required": ["start", "end", "title", "score", "category", "reason", "description",
                             "hashtags", "keywords", "emojis"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM = """Eres un editor experto en videos cortos virales (TikTok, Reels, Shorts) para creadores hispanohablantes.
Recibes la transcripción con marcas de tiempo (segundos) de un video largo y eliges los momentos que mejor funcionarían como clips independientes.

Criterios:
- Cada clip se entiende solo, sin contexto previo. Empieza con gancho (frase fuerte, pregunta, dato sorprendente, conflicto) y termina cuando la idea se cierra, nunca a mitad de frase.
- Prioriza: historias con giro, opiniones fuertes o polémicas, datos sorprendentes, humor, emoción, consejos concretos.
- Sin solapes entre clips. Usa exactamente las marcas de tiempo de la transcripción para inicio y fin.
- score (0-100): probabilidad realista de retención y viralidad. Sé exigente y calibrado: 90+ solo para momentos excepcionales.
- title: título gancho corto (máx. 45 caracteres) en MAYÚSCULAS, en el idioma del video, que genere curiosidad sin mentir.
- reason: una frase sobre por qué engancha.
- description: 1-2 frases listas para publicar, en el idioma del video.
- hashtags: 4-7 hashtags relevantes, con #.
- keywords: 3-8 palabras EXACTAS que aparecen en el clip y merecen resaltarse en grande (las que cargan la idea).
- emojis: 2-5 pares {word, emoji} donde word es una palabra EXACTA del clip y emoji un único emoji que la ilustre.
Ordena los clips de mejor a peor."""


def claude_select(transcript, duration, n_max, min_len, max_len, whole=False):
    import anthropic
    st = load_settings()
    client = anthropic.Anthropic(api_key=st["api_key"]) if st.get("api_key") else anthropic.Anthropic()
    lines = build_lines(transcript)
    tx = "\n".join(f"[{l['s']:.2f} - {l['e']:.2f}] {l['text']}" for l in lines)
    if whole:
        ask = (f"Este video dura {duration:.1f} s y se publicará completo como un solo clip. "
               f"Devuelve exactamente 1 clip con start={lines[0]['s'] if lines else 0} y end={lines[-1]['e'] if lines else duration}, "
               "con su título, puntaje y demás campos.")
    else:
        ask = (f"El video dura {duration / 60:.1f} minutos. Elige hasta {n_max} clips de entre {min_len} y {max_len} segundos "
               "(solo los que valgan la pena; si hay pocos momentos buenos, devuelve menos).")
    resp = client.beta.messages.create(
        model=st.get("model") or "claude-opus-5-5",
        max_tokens=20000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"{ask}\n\nTRANSCRIPCIÓN:\n{tx}"}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude rechazó la petición.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta de Claude se cortó (max_tokens).")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["clips"], {"input_tokens": resp.usage.input_tokens,
                                       "output_tokens": resp.usage.output_tokens, "model": resp.model}


# ---------------------------------------------------------------- respaldo por reglas

HOOKS = ["nadie", "nunca", "secreto", "error", "verdad", "increíble", "mentira", "jamás", "importante",
         "cuidado", "problema", "dinero", "miedo", "historia", "pasó", "loco", "mejor", "peor", "truco",
         "no sabías", "por qué", "imagínate", "atención", "real", "gratis"]


def heuristic_select(transcript, duration, n_max, min_len, max_len, whole=False):
    lines = build_lines(transcript)
    if not lines:
        return []
    if whole:
        txt = " ".join(l["text"] for l in lines)
        return [{"start": lines[0]["s"], "end": lines[-1]["e"], "title": _title(lines[0]["text"]), "score": 60,
                 "category": "Alta retención", "reason": "Video completo.", "description": txt[:140],
                 "hashtags": ["#viral", "#parati"], "keywords": _keywords(txt), "emojis": []}]
    target = (min_len + max_len) / 2
    cands = []
    for i in range(len(lines)):
        s = lines[i]["s"]
        txt, j = [], i
        while j < len(lines) and lines[j]["e"] - s <= max_len:
            txt.append(lines[j]["text"])
            e = lines[j]["e"]
            if e - s >= min_len and (e - s >= target or j == len(lines) - 1):
                break
            j += 1
        else:
            e = lines[min(j, len(lines) - 1)]["e"]
        if e - s < min_len:
            continue
        t = " ".join(txt)
        low = t.lower()
        first = lines[i]["text"].lower()
        sc = 40
        sc += 6 * sum(1 for h in HOOKS if h in first)
        sc += 2 * sum(1 for h in HOOKS if h in low)
        sc += 5 * first.count("?") + 3 * low.count("!")
        sc += 4 * len(re.findall(r"\d", first))
        sc += min(10, len(t.split()) / max(1, e - s) * 3)  # densidad de habla
        cands.append((min(95, int(sc)), s, e, t, lines[i]["text"]))
    cands.sort(reverse=True)
    chosen = []
    for sc, s, e, t, first in cands:
        if any(not (e <= c["start"] or s >= c["end"]) for c in chosen):
            continue
        chosen.append({"start": s, "end": e, "title": _title(first), "score": sc, "category": "Alta retención",
                       "reason": "Elegido por reglas (sin IA): gancho y densidad de habla.",
                       "description": t[:150], "hashtags": ["#viral", "#parati", "#clips"],
                       "keywords": _keywords(t), "emojis": []})
        if len(chosen) >= n_max:
            break
    return chosen


def _title(text):
    t = re.sub(r"\s+", " ", text).strip().upper()
    return (t[:42] + "…") if len(t) > 45 else t


def _keywords(text):
    ws = [w.strip(".,!?¡¿\"'").lower() for w in text.split()]
    ws = [w for w in ws if len(w) >= 6]
    seen = []
    for w in sorted(set(ws), key=lambda x: -ws.count(x)):
        seen.append(w)
        if len(seen) >= 5:
            break
    return seen


# ---------------------------------------------------------------- IA local (Ollama)

LOCAL_SYSTEM = """Eres un editor experto en videos cortos virales (TikTok, Reels, Shorts).
Recibes BLOQUES candidatos numerados de un video, ya cortados a la duración correcta. Elige los bloques que mejor funcionarían como clip viral independiente y descríbelos.

Prioriza bloques con: gancho fuerte al inicio, historia con giro, revelación, dato sorprendente, humor, emoción, opinión fuerte o consejo concreto. Descarta bloques confusos o sin una idea clara.

Para cada bloque elegido:
- id: el número del bloque, tal cual.
- score (0-100): retención realista. Sé exigente: no pongas a todos lo mismo; usa todo el rango.
- category: elige la que de verdad corresponda:
  Historia (relato), Revelación (se descubre algo), Dato curioso, Humor, Emotivo, Polémico (choque de opiniones), Opinión fuerte, Consejo (solo si se recomienda hacer algo), Reacción, Alta retención.
- title: gancho corto (máx. 45 caracteres) en MAYÚSCULAS, en el idioma del video, que genere curiosidad sin mentir. Debe hablar de lo que pasa EN ESE bloque; cada bloque lleva un título distinto.
- reason: máx. 12 palabras.
- description: máx. 25 palabras, lista para publicar.
- hashtags: exactamente 4, con #.
- keywords: 3-5 palabras EXACTAS del bloque que merecen resaltarse.
- emojis: 2-3 pares {word, emoji}; word es una palabra EXACTA del bloque.
Ordena de mejor a peor. Responde SOLO con el JSON."""

LOCAL_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {**{k: v for k, v in SCHEMA["properties"]["clips"]["items"]["properties"].items()
                          if k not in ("start", "end")}, "id": {"type": "integer"}},
        "required": ["id"] + [k for k in SCHEMA["properties"]["clips"]["items"]["required"] if k not in ("start", "end")],
        "additionalProperties": False}}},
    "required": ["clips"], "additionalProperties": False,
}


def build_blocks(lines, min_len, max_len):
    """Corta la transcripción en bloques candidatos de la duración pedida (respetando líneas).
    Dos pasadas desfasadas medio bloque para ofrecer distintos puntos de corte."""
    target = (min_len + max_len) / 2

    def one_pass(start_idx):
        out, i = [], start_idx
        while i < len(lines):
            j, s = i, lines[i]["s"]
            while j + 1 < len(lines) and lines[j + 1]["e"] - s <= max_len and lines[j]["e"] - s < target:
                j += 1
            e = lines[j]["e"]
            if e - s >= min_len * 0.7:
                out.append((i, j))
            i = j + 1
        return out

    first = one_pass(0)
    blocks = set(first)
    if first:
        mid_t = (lines[first[0][0]]["s"] + lines[first[0][1]]["e"]) / 2
        k = next((n for n, l in enumerate(lines) if l["s"] >= mid_t), None)
        if k:
            blocks.update(one_pass(k))
    blocks = sorted(blocks)
    return [{"s": lines[i]["s"], "e": lines[j]["e"], "text": " ".join(l["text"] for l in lines[i:j + 1])}
            for i, j in blocks]


class _Ollama:
    def __init__(self):
        from . import local_llm
        self.ai, self.model = local_llm, local_llm.resolve_model()

    def budget(self, system):
        return 4000  # caben, con el modelo, en los 4 GB de la GPU

    def chat(self, system, user, schema, num_ctx, progress_cb):
        return self.ai.chat_json(system, user, schema, self.model, num_ctx, progress_cb)


def local_select(ai, transcript, duration, n_max, min_len, max_len, whole=False, progress_cb=None):
    import math
    from .local_server import ContextError
    model = ai.model
    lines = build_lines(transcript)
    if not lines:
        return [], {"model": model}
    if whole:
        blocks = [{"s": lines[0]["s"], "e": lines[-1]["e"], "text": " ".join(l["text"] for l in lines)}]
    else:
        blocks = build_blocks(lines, min_len, max_len)
    for n, b in enumerate(blocks, 1):
        b["id"] = n
    room = ai.budget(LOCAL_SYSTEM)
    chunks, cur, size = [], [], 0
    for b in blocks:
        tok = len(b["text"]) / 3.2 + 20
        if cur and size + tok > room:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += tok
    if cur:
        chunks.append(cur)
    by_id = {b["id"]: b for b in blocks}
    found = []
    k = 0
    while k < len(chunks):
        ch = chunks[k]
        tx = "\n\n".join(f"#{b['id']} [{b['s']:.0f}-{b['e']:.0f} s] {b['text']}" for b in ch)
        if whole:
            ask = "Este video se publicará completo: devuelve exactamente 1 clip con id=1."
        else:
            # pide de más: entre bloques que se pisan solo sobrevive el mejor
            n = max(1, min(len(ch), math.ceil(1.6 * n_max * len(ch) / max(1, len(blocks))) + 1))
            ask = f"Elige los {n} mejores bloques de esta lista (ids distintos)."
        toks = int(len(tx) / 3.2 + len(LOCAL_SYSTEM) / 3 + 1500)
        num_ctx = 8192 if toks <= 8192 else min(32768, (toks // 4096 + 1) * 4096)

        def prog(n_tok, secs, k=k):
            if progress_cb:
                progress_cb((k + min(0.95, n_tok / 600)) / len(chunks),
                            f"IA local ({model}) · tramo {k + 1}/{len(chunks)} · escribiendo… ({n_tok} fragmentos)")

        if progress_cb:
            progress_cb(k / len(chunks), f"IA local ({model}) · tramo {k + 1}/{len(chunks)} · leyendo la transcripción…")
        try:
            data = ai.chat(LOCAL_SYSTEM, f"{ask}\n\nBLOQUES:\n{tx}", LOCAL_SCHEMA, num_ctx, prog)
        except ContextError:
            if len(ch) < 2:
                raise
            chunks[k:k + 1] = [ch[:len(ch) // 2], ch[len(ch) // 2:]]  # no cupo: se parte y se repite
            continue
        k += 1
        seen = set()
        for c in data.get("clips", []):
            b = by_id.get(c.get("id"))
            if not b or b["id"] in seen:
                continue
            seen.add(b["id"])
            c["start"], c["end"] = b["s"], b["e"]
            c.setdefault("emojis", [])
            c["category"] = c.get("category") if c.get("category") in CATEGORIES else "Alta retención"
            found.append(c)
    found.sort(key=lambda c: -int(c.get("score", 0)))
    # sin solapes (las dos pasadas de bloques se pisan entre sí)
    # (se compara con el largo que tendrá tras ajustarse al mínimo pedido)
    chosen, titles = [], set()
    for c in found:
        e = max(c["end"], c["start"] + min_len)
        if all(e <= o["start"] + 0.5 or c["start"] >= max(o["end"], o["start"] + min_len) - 0.5 for o in chosen):
            t = (c.get("title") or "").strip().upper()
            if t in titles:
                c["title"] = ""          # título repetido: mejor sin título que uno copiado
            titles.add(t)
            chosen.append(c)
    return chosen[: max(1, n_max)], {"model": model}


def choose_engine(fresh=False):
    st = load_settings()
    eng = st.get("engine") or "auto"
    if eng != "auto":
        return eng
    if st.get("api_key"):
        return "claude"
    from . import local_llm, local_server
    if st.get("local_url") and local_server.ready(fresh):  # si alguien lo configuró, es el que quiere usar
        return "servidor"
    if local_llm.usable():
        return "ollama"
    return "reglas"


def select_clips(transcript, duration, opts, layout, progress_cb=None):
    n_max = int(opts.get("max_clips", 10))
    min_len = float(opts.get("min_len", 20))
    max_len = float(opts.get("max_len", 60))
    whole = bool(opts.get("whole"))
    words = all_words(transcript)
    engine = choose_engine(fresh=True)
    info = {"engine": "reglas"}
    raw = None
    try:
        if engine == "claude":
            raw, usage = claude_select(transcript, duration, n_max, min_len, max_len, whole)
            info = {"engine": "claude", **usage}
        elif engine in ("ollama", "servidor"):
            from .local_server import Session
            ai = _Ollama() if engine == "ollama" else Session()
            raw, usage = local_select(ai, transcript, duration, n_max, min_len, max_len, whole, progress_cb)
            info = {"engine": engine, **usage}
            if not raw:
                raise RuntimeError("la IA local no devolvió clips válidos")
        else:
            raise RuntimeError("motor configurado: reglas")
    except Exception as e:  # sin key, sin red, Ollama apagado, etc.
        info = {"engine": "reglas", "tried": engine, "fallback_reason": str(e)[:300]}
        raw = heuristic_select(transcript, duration, n_max, min_len, max_len, whole)
    clips = []
    keep_min = max(3.0, min(min_len * 0.75, 15.0))
    for m in sorted(raw, key=lambda m: -int(m.get("score", 0))):
        s, e = float(m["start"]), float(m["end"])
        if not whole:
            s, e = snap(s, e, words, min_len, max_len)
        # si pisa a un clip mejor, se recorta contra él (a palabra completa) en vez de descartarlo
        for c in sorted(clips, key=lambda c: c["start"]):
            if e <= c["start"] + 0.5 or s >= c["end"] - 0.5:
                continue
            if s >= c["start"]:                      # empieza dentro del otro → arrancar después
                nxt = [w for w in words if w["s"] >= c["end"]]
                s = nxt[0]["s"] - 0.05 if nxt else e
            else:                                    # termina dentro del otro → cerrar antes
                prev = [w for w in words if w["e"] <= c["start"] and w["s"] >= s]
                e = prev[-1]["e"] + 0.05 if prev else s
        if e - s < (3 if whole else keep_min):
            continue
        if any(not (e <= c["start"] + 0.3 or s >= c["end"] - 0.3) for c in clips):
            continue
        clips.append(make_clip(round(s, 3), round(e, 3), words, m, layout))
    clips.sort(key=lambda c: -c["score"])
    return clips, info
