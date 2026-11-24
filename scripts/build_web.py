"""Build the browser-only version of the website (no Flask server needed).

The website normally runs as:  browser  <--HTTP-->  Flask (outrun/web/app.py)
                                                       └─ Python code (outrun/)

This script builds a version where the SAME Python package runs inside the
browser, using Pyodide (CPython compiled to WebAssembly):

    browser ── app.js ── bridge.js ── worker.js (Pyodide) ── Python code (outrun/)

Nothing is pre-computed: the site contains the Python source files, and every
number is calculated when the visitor clicks, exactly as on the Flask server.

Usage:
    # Pyodide loaded from the jsDelivr CDN (simplest; e.g. for GitHub Pages)
    python scripts/build_web.py --out site --cdn

    # Pyodide hosted next to the site (no third-party CDN at run time).
    # PYODIDE_DIR must contain pyodide.js, pyodide.asm.js, pyodide.asm.wasm,
    # python_stdlib.zip, pyodide-lock.json and the numpy wheel from the
    # Pyodide 0.26.4 release (github.com/pyodide/pyodide/releases/tag/0.26.4).
    python scripts/build_web.py --out site --pyodide-dir PYODIDE_DIR

Then serve the folder, for example:  python -m http.server -d site 8000
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "outrun" / "web" / "static"
BROWSER = ROOT / "outrun" / "web" / "browser"
PYODIDE_VERSION = "0.26.4"
CDN_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json"]
BASE64_FILES = ["python_stdlib.zip"]          # plus the numpy wheel (found by name)
WEB_NOTE = ('<span class="banner-note">This page runs the project\'s own Python code in your '
            'browser (Pyodide); nothing is pre-recorded.</span>')


def python_sources() -> dict[str, str]:
    """Every .py file of the outrun package except the Flask app."""
    files = {}
    for path in sorted((ROOT / "outrun").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "outrun/web/app.py" or "__pycache__" in rel:
            continue
        files[rel] = path.read_text(encoding="utf-8")
    return files


def build(out: Path, pyodide_dir: Path | None, cdn: bool) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for marker in ("<!--web-note-->", "<!--extra-scripts-->"):
        if marker not in html:
            sys.exit(f"index.html is missing the {marker} marker")
    html = html.replace("<!--web-note-->", WEB_NOTE)
    html = html.replace("<!--extra-scripts-->", '<script src="static/bridge.js"></script>')
    html = html.replace("Loading the simulated region…",
                        "Starting Python in your browser… (the first visit downloads about 25 MB)")
    (out / "index.html").write_text(html, encoding="utf-8")

    for name in ("style.css", "app.js"):
        shutil.copy2(STATIC / name, out / "static" / name)
    shutil.copy2(BROWSER / "bridge.js", out / "static" / "bridge.js")

    worker = (BROWSER / "worker.js").read_text(encoding="utf-8")
    base = CDN_URL if cdn else "local"
    marker = 'const PYODIDE_BASE = "local";'
    if marker not in worker:
        sys.exit("worker.js is missing the PYODIDE_BASE line")
    (out / "static" / "worker.js").write_text(
        worker.replace(marker, f'const PYODIDE_BASE = "{base}";'), encoding="utf-8")

    (out / "static" / "outrun-python.json").write_text(json.dumps(python_sources()), encoding="utf-8")

    if not cdn:
        dest = out / "static" / "pyodide"
        dest.mkdir()
        for name in PYODIDE_FILES:
            shutil.copy2(pyodide_dir / name, dest / name)
        wheels = sorted(pyodide_dir.glob("numpy-*.whl"))
        if len(wheels) != 1:
            sys.exit(f"expected exactly one numpy-*.whl in {pyodide_dir}, found {len(wheels)}")
        for path in [pyodide_dir / n for n in BASE64_FILES] + wheels:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            (dest / (path.name + ".b64.txt")).write_text(encoded, encoding="ascii")
    print(f"Built {out} ({'Pyodide from CDN' if cdn else 'Pyodide hosted locally'})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cdn", action="store_true", help="load Pyodide from the jsDelivr CDN")
    group.add_argument("--pyodide-dir", type=Path, help="folder with Pyodide's files to host locally")
    args = parser.parse_args()
    build(args.out, args.pyodide_dir, args.cdn)


if __name__ == "__main__":
    main()
