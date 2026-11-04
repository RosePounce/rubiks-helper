"""Assemble le site statique GitHub Pages (version Pyodide) dans `site/`.

Ne dépend que de la bibliothèque standard (lançable tel quel en CI) :

    python web/build.py

Produit `site/` : les fichiers de `static/` avec leurs chemins absolus `/static/`
réécrits en relatif, `index.html` modifié pour charger Pyodide puis `boot.js`,
et `rubik_helper.zip` (le moteur Python, sans FastAPI) chargé dans le navigateur.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

# doit correspondre à la version dans web/boot.js
PYODIDE_VERSION = "0.26.4"

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "rubik_helper" / "static"
PKG = ROOT / "src" / "rubik_helper"
WEB = ROOT / "web"
OUT = ROOT / "site"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 1. interface statique telle quelle
    shutil.copytree(STATIC, OUT, dirs_exist_ok=True)

    # 2. chemins absolus /static/ -> relatifs (Pages sert souvent sous un sous-chemin)
    for p in [*OUT.rglob("*.js"), *OUT.rglob("*.html")]:
        txt = p.read_text(encoding="utf-8")
        new = txt.replace("/static/", "./")
        if new != txt:
            p.write_text(new, encoding="utf-8")

    # 3. index.html : charger Pyodide puis boot.js au lieu d'app.js directement
    idx = OUT / "index.html"
    html = idx.read_text(encoding="utf-8")
    marker = '<script type="module" src="./app.js"></script>'
    if marker not in html:
        raise SystemExit("index.html : balise de chargement d'app.js introuvable (build à mettre à jour).")
    html = html.replace(
        marker,
        f'<script src="https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/pyodide.js"></script>\n'
        '  <script type="module" src="./boot.js"></script>',
    )
    idx.write_text(html, encoding="utf-8")

    # 4. pont navigateur
    shutil.copy(WEB / "boot.js", OUT / "boot.js")

    # 5. moteur Python zippé (uniquement les .py ; pas de static, de cache, ni
    #    server.py et lan.py qui dépendent de FastAPI et cryptography, absents du navigateur)
    skip = {"server.py", "lan.py"}
    with zipfile.ZipFile(OUT / "rubik_helper.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for py in sorted(PKG.rglob("*.py")):
            if "__pycache__" in py.parts or py.name in skip:
                continue
            z.write(py, py.relative_to(PKG.parent))  # arcname : rubik_helper/....py

    print(f"Site construit dans {OUT}")


if __name__ == "__main__":
    main()
