"""Predeterminados del usuario: generales y por carpeta.

Se guardan por grupos. Una carpeta puede tener solo algunos; los que no tenga salen de los generales,
y si tampoco están ahí, de los de fábrica.
"""
import json
import threading

from . import config, plan

GROUPS = {
    "titulo": ("title_on", "title_secs", "title_style", "title_font", "title_color", "title_size", "title_y"),
    "subtitulos": ("font", "color", "subs_on", "sub_y", "sub_size", "upper"),
    "marca": ("brand",),
    "chat": ("chat_on", "chat_mode", "chat_names", "chat_count", "chat_safe", "chat_side", "chat_size", "chat_x", "chat_y", "chat_lead"),
    "estilo": ("style", "zooms", "emojis_on", "logos_on", "remove_silence", "filter"),
    "encuadre": ("mode", "swap", "framing", "manual_x", "cam_h"),
    "opciones": ("language", "min_len", "max_len", "max_clips", "download"),
}
EDITOR_GROUPS = ("titulo", "subtitulos", "marca", "chat", "estilo", "encuadre")  # los que se guardan desde un clip
MODES = ("auto", "streamer", "apilado", "full")
QUALITIES = ("auto", "1080", "720", "480")  # calidad al bajar un enlace
LANGS = ("auto", "es", "en", "pt", "fr", "it")

_lock = threading.RLock()


def _file():
    return config.DATA / "predeterminados.json"


def load():
    """{"general": {grupo: {...}}, "carpetas": {id: {grupo: {...}}}}"""
    f = _file()
    raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if raw and "general" not in raw:  # formato anterior: solo título y subtítulos, sueltos
        raw = {"general": {g: {k: raw[k] for k in GROUPS[g] if k in raw} for g in ("titulo", "subtitulos")}}

    def clean(sc):
        return {g: sc[g] for g in GROUPS if isinstance(sc.get(g), dict) and sc[g]}
    return {"general": clean(raw.get("general") or {}),
            "carpetas": {k: v for k, v in ((k, clean(s)) for k, s in (raw.get("carpetas") or {}).items()) if v}}


def _save(d):
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def put(groups, folder=None):
    """Guarda estos grupos en la carpeta (o en los generales); los demás grupos no cambian."""
    with _lock:
        d = load()
        sc = d["carpetas"].setdefault(folder, {}) if folder else d["general"]
        sc.update({g: v for g, v in groups.items() if g in GROUPS and v})
        _save(d)


def remove(folder=None, group=None):
    with _lock:
        d = load()
        sc = d["carpetas"].get(folder, {}) if folder else d["general"]
        for g in [group] if group else list(sc):
            sc.pop(g, None)
        if folder and not sc:
            d["carpetas"].pop(folder, None)
        _save(d)


def copy(src, dst, groups):
    """Copia estos grupos de una carpeta (None = generales) a otra. Lo demás del destino no cambia."""
    if (src or None) == (dst or None):
        raise ValueError("Elige dos carpetas distintas.")
    with _lock:
        d = load()
        sc = d["carpetas"].get(src, {}) if src else d["general"]
        vals = {g: json.loads(json.dumps(sc[g])) for g in GROUPS if g in groups and g in sc}
        if not vals:
            raise ValueError("Marca al menos una opción.")
        put(vals, dst or None)
    return list(vals)


def resolve(folder=None):
    """Lo que toca usar en una carpeta: lo suyo y, en lo que no defina, lo general."""
    d = load()
    out = {**d["general"], **(d["carpetas"].get(folder, {}) if folder else {})}
    if "marca" in out:  # por si el sticker se borró de la biblioteca
        out["marca"] = {"brand": [b for b in out["marca"].get("brand", []) if plan.brand_size(b.get("id", ""))]}
    return out


# ------------------------------------------------------------ sacar de un clip / de las opciones

def mode_of(ed):
    """Opción de encuadre del proyecto que corresponde a este clip (None si es «Dos videos»)."""
    lay = ed.get("layout", "vertical")
    if lay == "streamer":
        return "apilado" if (ed.get("streamer") or {}).get("mode") == "apilado" else "streamer"
    return {"vertical": "auto", "full": "full"}.get(lay)


def from_clip(ed, groups):
    out = {}
    for g in groups:
        if g == "encuadre":
            mode = mode_of(ed)
            if not mode:
                raise ValueError("El encuadre «Dos videos» no se puede dejar como predeterminado")
            st = ed.get("streamer") or {}
            v = {"mode": mode, "framing": ed.get("framing", "auto"), "manual_x": ed.get("manual_x", 0.5)}
            if mode == "apilado":
                v["swap"] = bool(st.get("swap"))
            if mode == "streamer":
                v["cam_h"] = int(st.get("cam_h", 640))
            out[g] = v
        elif g == "marca":
            out[g] = {"brand": ed.get("brand") or []}  # sin stickers también vale: «esta carpeta, sin logo»
        elif g in EDITOR_GROUPS:
            out[g] = {k: ed[k] for k in GROUPS[g] if k in ed}
    return json.loads(json.dumps(out))


def from_options(o, folder=None):
    """Opciones del formulario de inicio → grupos. Conserva lo fino que se guardó desde un clip si sigue valiendo."""
    cur = resolve(folder)
    mode, style = o.get("mode"), o.get("style")
    mn, mx, n = int(o.get("min_len", 20)), int(o.get("max_len", 60)), int(o.get("max_clips", 10))
    if mode not in MODES or style not in ("karaoke", "dinamico") or o.get("language") not in LANGS \
            or str(o.get("download", "auto")) not in QUALITIES:
        raise ValueError("Opciones no válidas")
    if not 5 <= mn < mx <= 180:
        raise ValueError("Revisa la duración: el mínimo debe ser menor que el máximo (5-180 s)")
    if not 1 <= n <= 40:
        raise ValueError("La cantidad de clips va de 1 a 40")
    enc = cur.get("encuadre", {})
    enc = {**enc, "mode": mode} if enc.get("mode") == mode else {"mode": mode}
    est = cur.get("estilo", {})
    base = dict(est) if est.get("style") == style else {k: est[k] for k in ("filter",) if k in est}
    return {"encuadre": enc, "estilo": {**base, "style": style, "remove_silence": bool(o.get("remove_silence"))},
            "opciones": {"language": o["language"], "min_len": mn, "max_len": mx, "max_clips": n,
                         "download": str(o.get("download", "auto"))}}


# ------------------------------------------------------------ poner en un clip

def _look(ed, r):
    for g in ("titulo", "subtitulos", "marca", "chat"):
        ed.update(json.loads(json.dumps(r.get(g, {}))))
    if "filter" in r.get("estilo", {}):
        ed["filter"] = r["estilo"]["filter"]


def dress_manual(clip, folder):
    """Clip hecho a mano: título, subtítulos, marca y filtro (el encuadre es el del proyecto)."""
    _look(clip["edit"], resolve(folder))


def dress(clip, opts, folder, vis):
    """Clip recién elegido: las opciones del proyecto mandan; lo demás sale de los predeterminados."""
    ed, r = clip["edit"], resolve(folder)
    _look(ed, r)
    style, est = opts.get("style", "karaoke"), r.get("estilo", {})
    ed["style"] = style
    if style == "dinamico":
        ed.update(zooms=True, emojis_on=True, logos_on=True)
        if opts.get("font"):
            ed["font"] = opts["font"]
    if est.get("style") == style:
        ed.update({k: est[k] for k in ("zooms", "emojis_on", "logos_on") if k in est})
    ed["remove_silence"] = bool(opts.get("remove_silence"))
    _frame(clip, opts.get("mode", "auto"), r.get("encuadre", {}), vis)


def _frame(clip, mode, enc, vis, keep_boxes=False):
    ed = clip["edit"]
    ed["layout"] = {"streamer": "streamer", "apilado": "streamer", "full": "full"}.get(mode, "vertical")
    mine = enc if enc.get("mode") == mode else {}
    if ed["layout"] == "streamer":
        st = ed.get("streamer") if keep_boxes and ed.get("streamer") else plan.auto_streamer(vis, clip)
        st = {k: v for k, v in st.items() if k not in ("mode", "swap")}
        if mode == "apilado":
            st["mode"] = "apilado"
            if mine.get("swap"):
                st["swap"] = True
        elif "cam_h" in mine:
            st["cam_h"] = mine["cam_h"]
        ed["streamer"] = st
    for k in ("framing", "manual_x"):
        if k in mine:
            ed[k] = mine[k]


def dress_existing(clip, folder, vis, groups=None):
    """Clip que ya existe: solo se cambia lo que haya guardado (y, si se dice, solo esos grupos). Devuelve los grupos aplicados."""
    ed, r = clip["edit"], resolve(folder)
    if groups is not None:
        r = {g: v for g, v in r.items() if g in groups}
    _look(ed, r)
    if "estilo" in r:
        ed.update({k: v for k, v in r["estilo"].items() if k in GROUPS["estilo"]})
    if "encuadre" in r:
        _frame(clip, r["encuadre"].get("mode", "auto"), r["encuadre"], vis, keep_boxes=True)
    return [g for g in EDITOR_GROUPS if g in r]
