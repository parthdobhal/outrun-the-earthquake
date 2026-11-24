"""The browser-only build (scripts/build_web.py) must ship the real Python code
and must not change how the Flask version works."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_builder():
    spec = importlib.util.spec_from_file_location("build_web", ROOT / "scripts" / "build_web.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cdn_build_contains_the_unchanged_python_package(tmp_path):
    builder = load_builder()
    out = tmp_path / "site"
    builder.build(out, None, cdn=True)

    bundled = json.loads((out / "static" / "outrun-python.json").read_text())
    expected = {p.relative_to(ROOT).as_posix() for p in (ROOT / "outrun").rglob("*.py")
                if "__pycache__" not in p.parts} - {"outrun/web/app.py"}
    assert set(bundled) == expected
    for rel, text in bundled.items():           # byte-for-byte the same source
        assert text == (ROOT / rel).read_text(encoding="utf-8")
    assert "outrun/web/app.py" not in bundled   # Flask is not needed in the browser


def test_cdn_build_wires_up_the_bridge_and_keeps_the_banner(tmp_path):
    builder = load_builder()
    out = tmp_path / "site"
    builder.build(out, None, cdn=True)
    html = (out / "index.html").read_text()
    assert "SIMULATION" in html and "Not a real warning system" in html
    assert "runs the project's own Python code in your browser" in html
    assert html.index("static/bridge.js") < html.index("static/app.js")
    worker = (out / "static" / "worker.js").read_text()
    assert f'const PYODIDE_BASE = "{builder.CDN_URL}";' in worker
    assert not (out / "static" / "pyodide").exists()


def test_flask_page_has_no_browser_bridge():
    html = (ROOT / "outrun" / "web" / "static" / "index.html").read_text()
    assert "bridge.js" not in html            # Flask version talks to the real server
    assert "<!--web-note-->" in html and "<!--extra-scripts-->" in html
