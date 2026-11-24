"""Dibujo de capas (subtítulos, título, emojis, logos) con Pillow.

El navegador replica las mismas reglas en web/render.js para la vista previa.
"""
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import COLORS, EMOJI_FONT, FONTS, OUT_W

MAX_TEXT_W = 940


@lru_cache(maxsize=64)
def font(key, size):
    spec = FONTS.get(key) or FONTS["impacto"]
    f = ImageFont.truetype(spec["file"], size)
    if spec.get("wght"):
        try:
            f.set_variation_by_axes([spec["wght"]])
        except Exception:
            pass
    return f


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_back(k):
    c1, c3 = 1.70158, 2.70158
    k = min(max(k, 0.0), 1.0)
    return 1 + c3 * (k - 1) ** 3 + c1 * (k - 1) ** 2


# ------------------------------------------------------------ subtítulos

def page_state(page, t, style):
    """Qué palabras se ven, cuál está activa y la escala de 'pop' de cada una."""
    words = page["words"]
    active = -1
    for i, w in enumerate(words):
        if w["s"] - 0.02 <= t:
            active = i
    vis, scales = [], []
    for i, w in enumerate(words):
        if style == "dinamico":
            shown = t >= w["s"] - 0.04
            k = (t - (w["s"] - 0.04)) / 0.14
            sc = 0.55 + 0.45 * ease_out_back(k) if shown else 0
        else:
            shown = True
            sc = 1.08 if i == active else 1.0
        vis.append(shown)
        scales.append(round(sc * 20) / 20)  # cuantizado para la caché
    return active, tuple(vis), tuple(scales)


def render_page(page_words, font_key, base_size, color_key, style, big, active, vis, scales):
    """Devuelve (RGBA PIL, x0, y_center_offset) de la línea de subtítulos."""
    return _render_page(tuple(w["w"] for w in page_words), font_key, base_size, color_key, style, big,
                        active, vis, scales)


@lru_cache(maxsize=512)
def _render_page(words, font_key, base_size, color_key, style, big, active, vis, scales):
    color = hex2rgb(COLORS.get(color_key, "#FFD400"))
    size = int(base_size * (1.9 if big else 1.0))
    f = font(font_key, size)
    space = f.getlength(" ")
    widths = [f.getlength(w) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    fit = min(1.0, MAX_TEXT_W / total) if total > 0 else 1.0
    if fit < 1.0:
        size = max(20, int(size * fit))
        f = font(font_key, size)
        space = f.getlength(" ")
        widths = [f.getlength(w) for w in words]
        total = sum(widths) + space * (len(words) - 1)
    stroke = max(3, int(size * 0.085))
    pad = int(size * 0.9)
    Wc, Hc = OUT_W, int(size * 2.4)
    img = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
    glow = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0)) if big else None
    x = (Wc - total) / 2
    cy = Hc / 2
    for i, w in enumerate(words):
        if not vis[i]:
            x += widths[i] + space
            continue
        sc = scales[i] if scales[i] > 0 else 1.0
        is_active = (i == active) or big
        fill = color if is_active else (255, 255, 255)
        fw = f if abs(sc - 1.0) < 0.01 else font(font_key, max(10, int(size * sc)))
        ww = fw.getlength(w)
        cxw = x + widths[i] / 2
        d = ImageDraw.Draw(img)
        # sombra
        d.text((cxw + size * 0.04, cy + size * 0.06), w, font=fw, anchor="mm", fill=(0, 0, 0, 150),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        d.text((cxw, cy), w, font=fw, anchor="mm", fill=fill + (255,), stroke_width=stroke,
               stroke_fill=(0, 0, 0, 255))
        if glow is not None:
            ImageDraw.Draw(glow).text((cxw, cy), w, font=fw, anchor="mm", fill=color + (255,),
                                      stroke_width=stroke * 2, stroke_fill=color + (255,))
        x += widths[i] + space
    if glow is not None:
        glow = glow.filter(ImageFilter.GaussianBlur(size * 0.18))
        glow.alpha_composite(img)
        img = glow
    return img, pad


# ------------------------------------------------------------ título

def _contrast(rgb):
    """Negro o blanco, lo que se lea mejor sobre `rgb`."""
    lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
    return (12, 12, 12) if lum > 0.6 else (255, 255, 255)


@lru_cache(maxsize=32)
def render_title(text, font_key="clasica", style="caja", color_key="blanco", size=62):
    """Título gancho. Estilos: caja (caja de color), oscura (caja negra translúcida, letra de color),
    contorno (sin caja, letra de color con borde negro) y cinta (franja de lado a lado)."""
    from .config import TITLE_COLORS
    size = int(max(30, min(130, size)))
    col = hex2rgb(TITLE_COLORS.get(color_key, "#FFFFFF"))
    f = font(font_key, size)
    max_w = 1000 if style == "cinta" else 900
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if f.getlength(cand) > max_w - 60 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lh = int(size * 1.2)
    pad_y = int(size * 0.32)
    tw = max(f.getlength(l) for l in lines) if lines else 0
    bw, bh = int(min(OUT_W, tw + size * 1.1)), int(lh * len(lines) + pad_y * 2)
    img = Image.new("RGBA", (OUT_W, bh + 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = (OUT_W - bw) // 2, 10
    rad = int(size * 0.42)
    stroke = 0
    if style == "oscura":
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=rad, fill=(0, 0, 0, 175))
        fill = col
    elif style == "contorno":
        fill, stroke = col, max(3, int(size * 0.09))
    elif style == "cinta":
        d.rectangle([0, y0 + 6, OUT_W, y0 + bh + 6], fill=(0, 0, 0, 90))
        d.rectangle([0, y0, OUT_W, y0 + bh], fill=col + (250,))
        fill = _contrast(col)
    else:  # caja
        d.rounded_rectangle([x0 + 6, y0 + 8, x0 + bw + 6, y0 + bh + 8], radius=rad, fill=(0, 0, 0, 110))
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=rad, fill=col + (250,))
        fill = _contrast(col)
    for i, l in enumerate(lines):
        cy = y0 + pad_y + lh * i + lh / 2
        if stroke:
            d.text((OUT_W / 2 + size * 0.04, cy + size * 0.06), l, font=f, anchor="mm", fill=(0, 0, 0, 150),
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        d.text((OUT_W / 2, cy), l, font=f, anchor="mm", fill=fill + (255,),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    return img


# ------------------------------------------------------------ stickers de marca

@lru_cache(maxsize=64)
def brand_img(bid, width, opacity=100):
    """Sticker de marca subido por el usuario, escalado a `width` px y con su opacidad."""
    from .config import BRAND
    f = BRAND / f"{bid}.png"
    if not f.exists():
        return None
    im = Image.open(f).convert("RGBA")
    width = int(max(16, min(1080, width)))
    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    if opacity < 100:
        a = im.getchannel("A").point(lambda v: v * max(0, opacity) // 100)
        im.putalpha(a)
    return im


# ------------------------------------------------------------ emojis y logos

@lru_cache(maxsize=64)
def emoji_img(ch, size):
    f = ImageFont.truetype(EMOJI_FONT, 109)
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((80, 80), ch, font=f, anchor="mm", embedded_color=True)
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    r = size / max(im.size)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


LOGO_STYLE = {
    "instagram": ("grad", ["#FEDA75", "#FA7E1E", "#D62976", "#962FBF", "#4F5BD5"]),
    "tiktok": ("#010101", None), "youtube": ("#FF0000", None), "facebook": ("#1877F2", None),
    "whatsapp": ("#25D366", None), "twitch": ("#9146FF", None), "twitter": ("#000000", None),
    "spotify": ("#1DB954", None), "kick": ("#53FC18", None), "telegram": ("#229ED9", None),
    "linkedin": ("#0A66C2", None),
}


@lru_cache(maxsize=32)
def logo_img(name, size):
    """Insignia simplificada de la red social (no es el logo oficial, solo una referencia visual)."""
    S = 400
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    kind, grad = LOGO_STYLE.get(name, ("#333333", None))
    if kind == "grad":
        g = Image.new("RGBA", (S, S))
        cols = [hex2rgb(c) for c in grad]
        arr = np.zeros((S, S, 4), np.uint8)
        yy, xx = np.mgrid[0:S, 0:S]
        tt = ((S - yy) + xx) / (2 * S) * (len(cols) - 1)
        i0 = np.clip(tt.astype(int), 0, len(cols) - 2)
        fr = (tt - i0)[..., None]
        c = np.array(cols, np.float32)
        arr[..., :3] = (c[i0] * (1 - fr) + c[i0 + 1] * fr).astype(np.uint8)
        arr[..., 3] = 255
        g = Image.fromarray(arr, "RGBA")
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=96, fill=255)
        im.paste(g, (0, 0), mask)
        d.rounded_rectangle([90, 90, 310, 310], radius=62, outline="white", width=26)
        d.ellipse([150, 150, 250, 250], outline="white", width=26)
        d.ellipse([255, 115, 285, 145], fill="white")
    else:
        col = hex2rgb(kind)
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=96, fill=col + (255,))
        W = (255, 255, 255, 255)
        if name == "youtube":
            d.rounded_rectangle([0, 60, S - 1, 340], radius=90, fill=col + (255,))
            d.polygon([(160, 130), (160, 270), (285, 200)], fill=W)
        elif name == "tiktok":
            for off, c in ((-10, (37, 244, 238, 255)), (10, (254, 44, 85, 255)), (0, W)):
                d.rectangle([200 + off, 70 + off // 2, 236 + off, 260], fill=c)
                d.ellipse([110 + off, 210 + off // 2, 236 + off, 330 + off // 2], outline=c, width=36)
                d.arc([200 + off, 40, 330 + off, 160], 90, 180, fill=c, width=36)
        elif name == "facebook":
            f = font("gruesa", 300)
            d.text((215, 230), "f", font=f, anchor="mm", fill=W)
        elif name == "whatsapp":
            d.ellipse([70, 70, 330, 330], outline=W, width=26)
            d.polygon([(85, 330), (110, 255), (150, 300)], fill=W)
            d.text((200, 200), "✆", font=ImageFont.truetype(r"C:\Windows\Fonts\seguisym.ttf", 150), anchor="mm", fill=W)
        elif name == "spotify":
            d.ellipse([60, 60, 340, 340], fill=(0, 0, 0, 255))
            for i, (w_, y_) in enumerate(((30, 160), (24, 215), (18, 265))):
                d.arc([110 + i * 12, y_ - 20, 290 - i * 12, y_ + 120], 200, 340, fill=col + (255,), width=w_)
        else:
            label = {"twitch": "▶", "twitter": "X", "kick": "K", "telegram": "➤", "linkedin": "in"}.get(name, name[:1].upper())
            fnt = font("gruesa", 200) if len(label) <= 2 and label.isascii() else ImageFont.truetype(r"C:\Windows\Fonts\seguisym.ttf", 200)
            d.text((200, 205), label, font=fnt, anchor="mm", fill=(0, 0, 0, 255) if name == "kick" else W)
    shadow = Image.new("RGBA", (S + 40, S + 40), (0, 0, 0, 0))
    sm = Image.new("L", (S + 40, S + 40), 0)
    ImageDraw.Draw(sm).rounded_rectangle([20, 30, S + 20, S + 30], radius=96, fill=130)
    shadow.putalpha(sm.filter(ImageFilter.GaussianBlur(14)))
    shadow.alpha_composite(im, (20, 20))
    return shadow.resize((size, size), Image.LANCZOS)


def sticker_scale(t, s, e):
    k = (t - s) / 0.22
    sc = ease_out_back(k)
    if t > e - 0.18:
        sc *= max(0.0, (e - t) / 0.18)
    return max(0.0, sc), math.sin((t - s) * 6) * 4  # escala, ligera rotación


# ------------------------------------------------------------ mezcla sobre numpy BGR

_prep = {}


def _prepare(rgba):
    """Precalcula BGR premultiplicado y alfa inverso (uint16), recortado a la zona visible.
    Las imágenes vienen de cachés lru, así que el mismo objeto se reutiliza entre fotogramas."""
    k = id(rgba)
    hit = _prep.get(k)
    if hit is not None and hit[0] is rgba:
        return hit[1]
    a = np.asarray(rgba)
    ys, xs = np.nonzero(a[..., 3])
    if len(ys) == 0:
        res = None
    else:
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        sub = a[y0:y1, x0:x1]
        al = sub[..., 3:4].astype(np.uint16)
        pre = sub[..., 2::-1].astype(np.uint16) * al  # BGR premultiplicado
        res = (int(x0), int(y0), pre, (255 - al))
    if len(_prep) > 800:
        _prep.clear()
    _prep[k] = (rgba, res)
    return res


def blend(frame, rgba, x, y):
    """Mezcla una imagen RGBA (PIL) sobre el frame BGR uint8 en (x, y) esquina superior izquierda."""
    if rgba is None:
        return
    pr = _prepare(rgba)
    if pr is None:
        return
    ox, oy, pre, inv = pr
    x, y = x + ox, y + oy
    h, w = pre.shape[:2]
    H, W = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sl = (slice(y0 - y, y1 - y), slice(x0 - x, x1 - x))
    roi = frame[y0:y1, x0:x1]
    out = pre[sl] + roi.astype(np.uint16) * inv[sl]
    frame[y0:y1, x0:x1] = ((out + 128) // 255).astype(np.uint8)
