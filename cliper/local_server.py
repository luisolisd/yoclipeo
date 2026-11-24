"""Otro servidor de IA: LM Studio, llama.cpp, Jan, vLLM… cualquiera que hable como la API de OpenAI (/v1/chat/completions).

El guion del video sale hacia esa dirección, así que fuera de este PC y de la red de casa solo se usa si la persona lo confirmó.
"""
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import load_settings

# Puertos de fábrica de los servidores más comunes (solo se miran en este PC, al pulsar «Buscar»)
PORTS = {1234: "LM Studio", 8080: "llama.cpp", 1337: "Jan", 5001: "KoboldCpp", 4891: "GPT4All", 8000: "vLLM", 5000: "text-generation-webui"}
OWNERS = {"llamacpp": "llama.cpp", "vllm": "vLLM", "koboldcpp": "KoboldCpp", "library": "Ollama"}
HOME_NETS = [ipaddress.ip_network("100.64.0.0/10")]  # Tailscale y similares: direcciones propias que no salen a internet


class _ServerError(RuntimeError):
    """El servidor contestó con un error dentro de la respuesta."""


class ContextError(RuntimeError):
    """El texto no cabe en el contexto con el que está cargado el modelo."""


# ------------------------------------------------------------ dirección

def normalize(url):
    """«localhost:1234», «http://192.168.1.5:8080/v1/»… → base con /v1. ValueError si no es una dirección válida."""
    u = (url or "").strip().strip('"')
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        p = urllib.parse.urlsplit(u)
        host, port = p.hostname, p.port
    except ValueError:
        raise ValueError("Esa dirección no es válida")
    if p.scheme not in ("http", "https") or not host or re.search(r"[\s\\]", p.netloc + p.path):
        raise ValueError("Esa dirección no es válida. Ejemplo: http://127.0.0.1:1234")
    if p.username or p.password or p.query or p.fragment:
        raise ValueError("Escribe solo la dirección, sin usuario, clave ni parámetros")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    path = re.sub(r"/(chat/completions|completions|models)$", "", p.path.rstrip("/")) or "/v1"
    h = f"[{host}]" if ":" in host else host
    return f"{p.scheme}://{h}{f':{port}' if port else ''}{path}"


def host_of(base):
    p = urllib.parse.urlsplit(base)
    return p.netloc


def is_home(base):
    """¿La dirección es de este PC o de la red de casa? Todas las direcciones a las que apunte deben serlo."""
    host = urllib.parse.urlsplit(base).hostname or ""
    try:
        ips = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except OSError:
        raise RuntimeError(f"No encuentro «{host}» en la red")
    for s in ips:
        ip = ipaddress.ip_address(s)
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not (ip.is_loopback or ip.is_private or any(ip in n for n in HOME_NETS if n.version == ip.version)):
            return False
    return bool(ips)


def check(url):
    """Lo que hay que saber de una dirección antes de usarla."""
    base = normalize(url)
    if not base:
        return {"base": "", "host": "", "home": True, "allowed": True, "secure": True}
    home = is_home(base)
    return {"base": base, "host": host_of(base), "home": home, "secure": base.startswith("https"),
            "allowed": home or load_settings().get("local_ok") == base}


def _guard(base, confirmed=False):
    if not confirmed and not check(base)["allowed"]:
        raise RuntimeError(f"{host_of(base)} está fuera de tu red: confírmalo en Ajustes antes de usarlo")


# ------------------------------------------------------------ conexión

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # una redirección podría llevar el guion a otro lado
        return None


_open = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect).open
_open_out = urllib.request.build_opener(_NoRedirect).open


def _call(base, path, key="", body=None, timeout=3, root=False):
    url = (base.rsplit("/v1", 1)[0] if root else base) + path
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None, headers=h)
    return (_open if is_home(base) else _open_out)(req, timeout=timeout)


def _json(base, path, key="", timeout=3, root=False):
    with _call(base, path, key, None, timeout, root) as r:
        return json.loads(r.read(4_000_000).decode("utf-8"))


def _why(e):
    """El motivo en palabras, sin cabeceras ni claves."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "El servidor pide una clave o la rechazó"
        if 300 <= e.code < 400:
            return "El servidor redirige a otra dirección; escribe la definitiva"
        if e.code == 404:
            return "Responde, pero no como la API de OpenAI (/v1)"
        return f"El servidor respondió con el error {e.code}"
    if isinstance(e, (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError)):
        return "Responde, pero no como la API de OpenAI (/v1)"
    if isinstance(e, (urllib.error.URLError, OSError)):
        return "No responde. Enciende el servidor y revisa la dirección"
    return str(e)[:200]


def _models(base, key="", timeout=3):
    """[{id, ctx, loaded}] y el nombre del programa."""
    d = _json(base, "/models", key, timeout)
    ms = [{"id": str(m["id"]), "ctx": int(m.get("max_model_len") or 0), "loaded": None, "owner": str(m.get("owned_by") or "")}
          for m in d["data"] if m.get("id")]
    port = urllib.parse.urlsplit(base).port
    name = next((OWNERS[m["owner"]] for m in ms if m["owner"] in OWNERS), PORTS.get(port) or "servidor")
    if name not in OWNERS.values():  # LM Studio dice qué está cargado y con cuánto contexto
        try:
            lm = {m["id"]: m for m in _json(base, "/api/v0/models", key, min(timeout, 2), root=True)["data"]}
            name = "LM Studio"
            for m in ms:
                x = lm.get(m["id"])
                if x:
                    m.update(loaded=x.get("state") == "loaded", ctx=int(x.get("loaded_context_length") or 0))
                    if x.get("type") == "embeddings":
                        m["text"] = False
        except Exception:
            pass
    return ms, name


def label(mid):
    """El nombre para mostrar: algunos servidores usan la ruta completa del archivo."""
    n = re.split(r"[\\/]", mid or "")[-1] if re.search(r"^[A-Za-z]:[\\/]|^/|\.gguf$", mid or "", re.I) else mid or ""
    n = re.sub(r"\.gguf$", "", n, flags=re.I)
    return n[:15] if re.match(r"sha256-", n) else n


def _for_text(m):
    from .local_llm import NOT_FOR_TEXT
    return m.get("text", True) and not any(x in m["id"].lower() for x in NOT_FOR_TEXT)


def _pick(ms, want):
    ids = [m["id"] for m in ms]
    if want and want != "auto":
        return want if want in ids or not ids else None
    good = [m for m in ms if _for_text(m)] or ms
    return next((m["id"] for m in good if m["loaded"]), good[0]["id"] if good else None)


def _context(base, key, model):
    """Cuánto texto admite el modelo tal como está cargado; 0 si no lo dice."""
    try:
        ms, name = _models(base, key)
        n = next((m["ctx"] for m in ms if m["id"] == model), 0)
        if not n and name != "LM Studio":
            p = _json(base, "/props", key, 2, root=True)
            n = int((p.get("default_generation_settings") or {}).get("n_ctx") or 0)
        return n
    except Exception:
        return 0


# ------------------------------------------------------------ estado

_cache = {}
_lock = threading.Lock()


def status(fresh=False):
    s = load_settings()
    out = {"url": s.get("local_url") or "", "model": s.get("local_model") or "auto", "on": False, "models": [], "use": None,
           "label": "", "name": "", "host": "", "home": True, "error": ""}
    if not out["url"]:
        return out
    k = (out["url"], out["model"], s.get("local_ok"), s.get("local_key"))
    with _lock:
        hit = _cache.get(k)
    if hit and not fresh and time.time() < hit[0]:
        return dict(hit[1])
    try:
        c = check(out["url"])
        out.update(host=c["host"], home=c["home"])
        _guard(c["base"])
        ms, out["name"] = _models(c["base"], s.get("local_key"), 2)
        out.update(on=True, models=[m["id"] for m in ms], use=_pick(ms, out["model"]))
        out["label"] = label(out["use"])
        if not out["use"]:
            out["error"] = f"No tiene el modelo «{out['model']}»" if out["model"] != "auto" else "No tiene ningún modelo cargado"
    except Exception as e:
        out["error"] = _why(e)
    with _lock:
        _cache.clear()
        _cache[k] = (time.time() + (8 if out["on"] else 15), out)
    return dict(out)


def forget():
    with _lock:
        _cache.clear()


def ready(fresh=False):
    s = status(fresh)
    return bool(s["on"] and s["use"])


def scan():
    """Servidores encendidos en este PC, en sus puertos de fábrica."""
    found = []

    def look(port):
        base = f"http://127.0.0.1:{port}/v1"
        try:
            with socket.create_connection(("127.0.0.1", port), 0.6):
                pass
            ms, name = _models(base, "", 2)
            found.append({"url": f"http://127.0.0.1:{port}", "name": name, "models": [m["id"] for m in ms]})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                found.append({"url": f"http://127.0.0.1:{port}", "name": PORTS[port], "models": [], "locked": True})
        except Exception:
            pass
    ts = [threading.Thread(target=look, args=(p,), daemon=True) for p in PORTS]
    [t.start() for t in ts]
    [t.join(6) for t in ts]
    return sorted(found, key=lambda f: list(PORTS).index(int(f["url"].rsplit(":", 1)[1])))


def test(url, model="auto", key="", confirmed=False):
    """Pide los modelos y una respuesta mínima. {ok, models, use, secs} o {ok: False, error}."""
    out = {"ok": False, "models": [], "use": None, "label": "", "name": "", "error": ""}
    try:
        base = normalize(url)
        if not base:
            raise ValueError("Escribe la dirección del servidor")
        _guard(base, confirmed)
        ms, out["name"] = _models(base, key, 6)
        out.update(models=[m["id"] for m in ms], use=_pick(ms, model))
        out["label"] = label(out["use"])
        if not out["use"]:
            raise RuntimeError(f"No tiene el modelo «{model}»" if model not in ("", "auto") else "El servidor no tiene ningún modelo")
        t0 = time.time()
        d = _chat(base, key, out["use"], "Respondes SOLO con JSON.", 'Responde exactamente {"ok": true}',
                  {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}, None, 120)
        if not isinstance(d, dict) or "ok" not in d:
            raise RuntimeError("Contestó, pero no en el formato que hace falta. Prueba otro modelo")
        out.update(ok=True, secs=round(time.time() - t0, 1))
    except Exception as e:
        out["error"] = str(e)[:300] if type(e) is ValueError or isinstance(e, RuntimeError) else _why(e)
    return out


# ------------------------------------------------------------ elegir momentos

_mode = {}  # (dirección, modelo) -> la forma de pedir JSON que aceptó


def _asks(schema):
    """De la más estricta a la más simple; no todos los servidores aceptan las mismas opciones."""
    js = {"type": "json_schema", "json_schema": {"name": "respuesta", "strict": True, "schema": schema}}
    quiet = {"chat_template_kwargs": {"enable_thinking": False}}  # sin razonar antes: aquí solo alarga la espera
    return [{"response_format": js, **quiet, "reasoning_effort": "none"}, {"response_format": js, **quiet}, {"response_format": js},
            {"response_format": {"type": "json_object"}}, {}]


def _parse(text):
    """El JSON de la respuesta, aunque venga con razonamiento o adornos alrededor. None si no hay."""
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    t = t.rsplit("</think>", 1)[-1]
    dec = json.JSONDecoder()
    for m in re.finditer(r"[{\[]", t):
        try:
            return dec.raw_decode(t[m.start():])[0]
        except json.JSONDecodeError:
            if "clips" in t[m.start():m.start() + 40]:  # se cortó a media lista: se rescatan los clips completos
                body = t[m.start():]
                while "}" in body:
                    body = body[: body.rfind("}") + 1]
                    try:
                        return json.loads(body + "]}")
                    except json.JSONDecodeError:
                        body = body[:-1]
                return None
    return None


def _stream(base, key, body, progress_cb, timeout):
    """Texto de la respuesta y si se cortó por falta de espacio."""
    out, n, t0, cut, end = [], 0, time.time(), False, False

    def take(ev):
        nonlocal n, cut, end
        if ev.get("error"):
            e = ev["error"]
            raise _ServerError(str(e.get("message") if isinstance(e, dict) else e))
        for c in (ev.get("choices") or [])[:1]:
            d = c.get("delta") or c.get("message") or {}
            if d.get("content"):
                out.append(d["content"])
            if d.get("content") or d.get("reasoning_content") or d.get("reasoning"):
                n += 1
                if progress_cb and n % 20 == 0:
                    progress_cb(n, time.time() - t0)
            cut = cut or c.get("finish_reason") == "length"
            end = end or bool(c.get("finish_reason"))

    with _call(base, "/chat/completions", key, body, timeout) as r:
        if "event-stream" in (r.headers.get("Content-Type") or ""):
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                line = line[5:].strip()
                if line == "[DONE]":
                    end = True
                    break
                take(json.loads(line))
        else:
            take(json.loads(r.read().decode("utf-8", "replace")))
            end = True
    if not end:
        raise ConnectionError("respuesta a medias")
    return "".join(out), cut


def _is_context(msg):
    return bool(re.search(r"context (length|size|window)|exceed\w* .{0,40}context|context .{0,40}exceed|n_ctx|maximum context|too many tokens|prompt is too long", msg, re.I))


def _chat(base, key, model, system, user, schema, progress_cb, timeout=900):
    asks = _asks(schema)
    first, last = _mode.get((base, model), 0), "El modelo no respondió en el formato pedido"
    for i in range(first, len(asks)):
        ask = user if i < 3 else f"{user}\n\nResponde SOLO con un JSON que cumpla este esquema:\n{json.dumps(schema, ensure_ascii=False)}"
        body = {"model": model, "stream": True, "temperature": 0.3,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": ask}], **asks[i]}
        try:
            text, cut = _stream(base, key, body, progress_cb, timeout)
        except urllib.error.HTTPError as e:
            msg = e.read(4000).decode("utf-8", "replace")
            if _is_context(msg):
                raise ContextError("El texto no cabe en el contexto del modelo")
            if e.code in (400, 415, 422, 500, 501):
                last = f"El servidor rechazó la petición ({e.code})"
                continue
            raise RuntimeError(_why(e))
        except _ServerError as e:
            if _is_context(str(e)):
                raise ContextError("El texto no cabe en el contexto del modelo")
            last = str(e)[:200]
            continue
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            raise RuntimeError("El servidor dejó de responder" if not isinstance(e, json.JSONDecodeError) else _why(e))
        data = _parse(text)
        if data is not None:
            _mode[(base, model)] = i
            return data
        if cut:
            raise ContextError("El modelo se quedó sin espacio para responder")
    raise RuntimeError(last)


def _tidy(data):
    """Sin esquema forzado, los modelos inventan formas: se deja cada campo como lo espera el resto del programa."""
    if isinstance(data, list):
        data = {"clips": data}
    if not isinstance(data, dict):
        return {"clips": []}
    if not isinstance(data.get("clips"), list):
        data = {"clips": next((v for v in data.values() if isinstance(v, list)), [data] if "id" in data else [])}

    def num(v, d=None):
        m = re.search(r"\d+(\.\d+)?", str(v))
        return int(float(m.group())) if m else d

    def words(v):
        v = re.split(r"[,\s]+", v) if isinstance(v, str) else v if isinstance(v, list) else []
        return [str(x).strip() for x in v if isinstance(x, (str, int)) and str(x).strip()]
    out = []
    for c in data["clips"]:
        if not isinstance(c, dict) or num(c.get("id")) is None:
            continue
        tags = [t if t.startswith("#") else "#" + t for t in words(c.get("hashtags"))]
        em = [{"word": str(e["word"]), "emoji": str(e["emoji"])} for e in (c.get("emojis") if isinstance(c.get("emojis"), list) else [])
              if isinstance(e, dict) and e.get("word") and e.get("emoji")]
        out.append({"id": num(c["id"]), "score": min(100, num(c.get("score"), 50)), "hashtags": tags[:8], "keywords": words(c.get("keywords"))[:8], "emojis": em,
                    **{k: c[k] if isinstance(c.get(k), str) else "" for k in ("category", "title", "reason", "description")}})
    return {"clips": out}


class Session:
    """El servidor elegido en Ajustes, listo para elegir momentos."""

    def __init__(self):
        s = load_settings()
        self.base, self.key = normalize(s.get("local_url")), s.get("local_key") or ""
        if not self.base:
            raise RuntimeError("Falta la dirección del servidor en Ajustes")
        _guard(self.base)
        st = status(fresh=True)
        if not st["use"]:
            raise RuntimeError(f"{st['host']}: {st['error']}")
        self.id, self.model = st["use"], st["label"]
        self.ctx = _context(self.base, self.key, self.id)

    def budget(self, system):
        """Cuántos tokens de transcripción caben por tramo, dejando sitio para las instrucciones y la respuesta."""
        return 4000 if not self.ctx else max(600, min(4000, int(self.ctx * 0.9 - len(system) / 3 - 1700)))

    def chat(self, system, user, schema, num_ctx, progress_cb):
        _guard(self.base)
        return _tidy(_chat(self.base, self.key, self.id, system, user, schema, progress_cb))
