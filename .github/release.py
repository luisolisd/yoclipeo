"""Crea la Release de la versión actual, si todavía no existe. Lo ejecuta .github/workflows/release.yml."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def number(v):
    return tuple(int(x) for x in v.split("."))


def notes(text, version, last):
    """Lo de CAMBIOS.md después de la última Release (todo, si es la primera)."""
    out = []
    for m in re.finditer(r"^## +(\d+(?:\.\d+){1,3})\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S):
        if number(m[1]) <= number(version) and (not last or number(m[1]) > number(last)):
            out.append((m[1], m[2].strip()))
    body = out[0][1] if len(out) == 1 else "\n\n".join(f"### {v}\n{t}" for v, t in out)
    return (body or "Los cambios están en CAMBIOS.md.") + "\n"


def main():
    m = re.search(r'^VERSION\s*=\s*"(\d+(?:\.\d+){1,3})"', Path("cliper/config.py").read_text(encoding="utf-8"), re.M)
    if not m:
        sys.exit("No encuentro VERSION en cliper/config.py")
    version, tag = m[1], f"v{m[1]}"
    done = [r["tagName"] for r in json.loads(run("gh", "release", "list", "--limit", "200", "--json", "tagName"))]
    if tag in done:
        return print(f"{tag} ya tiene su Release.")
    old = sorted((t[1:] for t in done if re.fullmatch(r"v\d+(\.\d+){1,3}", t)), key=number)
    if old and number(old[-1]) > number(version):
        return print(f"Ya hay una Release más nueva: v{old[-1]}.")
    name = f"YoClipeo-{version}.zip"
    run("git", "archive", "--format=zip", "--prefix=YoClipeo/", "-o", name, "HEAD", "--", ".", ":(exclude).github", ":(exclude).gitattributes", ":(exclude).gitignore")
    intro = f"Descarga **{name}**, extráelo y abre `Instalar YoClipeo.bat`. Si ya lo tienes, usa el botón «Actualizar».\n\n"
    Path("notas.md").write_text(intro + notes(Path("CAMBIOS.md").read_text(encoding="utf-8"), version, old[-1] if old else ""), encoding="utf-8")
    run("gh", "release", "create", tag, name, "--target", os.environ["GITHUB_SHA"], "--title", f"YoClipeo {version}", "--notes-file", "notas.md", "--latest")
    print(f"Release {tag} creada.")


if __name__ == "__main__":
    main()
