"""Data-wall check: code in outrun/server must never import the simulated world
(outrun.sim) or the evaluation code (outrun.evaluation).

outrun.sim owns and generates the hidden ground truth. outrun.evaluation may
receive that truth only after a run, to compare it with the server's estimate.
The server must work from reports alone, so it must import neither.

HOW IT WORKS
This is a STATIC check: it reads each server file's source with Python's own
parser (ast) and lists every module the file's import statements could load.
It does not run the code.

  * `import a.b.c`              -> a.b.c
  * `from a.b import c`         -> a.b  and  a.b.c   (c may be a submodule)
  * `from .. import sim`        -> resolved against the file's real package,
                                   e.g. in outrun/server/x.py: outrun, outrun.sim
  * `from a import *`           -> a  and  "a.*"; a star import is forbidden if
                                   `a` is a forbidden package OR a parent of one
                                   (e.g. `from outrun import *`), because it can
                                   expose already-loaded forbidden submodules
  * imports inside functions, classes, if/try blocks are all checked
    (ast.walk visits every node in the file).

LIMITATIONS (this is a guard against mistakes, NOT a security sandbox)
It cannot see imports that are not written as import statements, for example:
  * importlib.import_module("outrun.sim") or __import__("outrun.sim")
  * module names built from strings at run time
  * `import outrun` followed by `outrun.sim...` attribute access (works at run
    time if something else already imported outrun.sim)
  * reaching objects through sys.modules, gc, globals(), or by reading files
  * objects passed in by the caller (e.g. if the web layer handed a Quake object
    to a server function, no import would be needed at all)
  * code executed with exec/eval
Those are prevented by code review and by the separate runtime test planned in
the blueprint (the server is re-run on reports saved to JSON and must give an
identical estimate). Python offers no reliable in-process sandbox, so we do not
claim one.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "outrun" / "server"
FORBIDDEN = ("outrun.sim", "outrun.evaluation")


class UnresolvableImport(Exception):
    """A relative import that goes above the top-level package."""


def module_package(path: Path, root: Path = REPO_ROOT) -> str:
    """Return the package a file belongs to, as Python sees it.

    outrun/server/locator.py   -> "outrun.server"
    outrun/server/__init__.py  -> "outrun.server"
    outrun/server/sub/x.py     -> "outrun.server.sub"
    """
    parts = list(path.resolve().relative_to(root).with_suffix("").parts)
    return ".".join(parts[:-1])  # drop the module name (or "__init__")


def resolve_relative(module: str | None, level: int, package: str) -> str:
    """Turn a relative import into an absolute module name.

    level 1 (`.`) = the package itself, level 2 (`..`) = its parent, and so on.
    """
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    if keep < 1:
        raise UnresolvableImport(
            f"relative import with {level} dot(s) goes above package '{package}'"
        )
    base = ".".join(parts[:keep])
    return f"{base}.{module}" if module else base


def imported_modules(source: str, package: str, filename: str = "<source>"):
    """Yield every module name the file's import statements could load."""
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = resolve_relative(node.module, node.level, package)
            else:
                base = node.module
            yield base
            for alias in node.names:
                if alias.name == "*":
                    yield f"{base}.*"  # star import: judged by is_forbidden
                else:
                    # `from base import name`: name may be a submodule (base.name)
                    yield f"{base}.{alias.name}"


def is_forbidden(module: str) -> bool:
    if module.endswith(".*"):
        # `from pkg import *` is forbidden if pkg is forbidden itself or is a
        # parent of a forbidden package (e.g. `from outrun import *`).
        pkg = module[:-2]
        return any(pkg == f or pkg.startswith(f + ".") or f.startswith(pkg + ".")
                   for f in FORBIDDEN)
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def forbidden_imports(source: str, package: str = "outrun.server") -> list[str]:
    """Forbidden modules imported by `source`. An unresolvable relative import
    is also reported, because we cannot prove it is safe."""
    try:
        return sorted({m for m in imported_modules(source, package) if is_forbidden(m)})
    except UnresolvableImport as err:
        return [f"<unresolvable: {err}>"]


# --------------------------------------------------------------------------
# The real check on the real server files
# --------------------------------------------------------------------------

def test_server_files_exist():
    assert list(SERVER_DIR.rglob("*.py")), "outrun/server has no Python files"


def test_server_never_imports_sim_or_evaluation():
    offenders = []
    for path in sorted(SERVER_DIR.rglob("*.py")):
        found = forbidden_imports(path.read_text(encoding="utf-8"), module_package(path))
        offenders += [f"{path.relative_to(REPO_ROOT)}: {m}" for m in found]
    assert not offenders, "Data wall broken: " + ", ".join(offenders)


# --------------------------------------------------------------------------
# Regression tests for the checker itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source, expected",
    [
        # the four forms the review found missing
        ("from outrun import sim", "outrun.sim"),
        ("from outrun import evaluation", "outrun.evaluation"),
        ("from .. import sim", "outrun.sim"),
        ("from .. import evaluation", "outrun.evaluation"),
        # other absolute forms
        ("import outrun.sim", "outrun.sim"),
        ("import outrun.sim as s", "outrun.sim"),
        ("import outrun.evaluation.metrics", "outrun.evaluation.metrics"),
        ("from outrun.sim import world", "outrun.sim"),
        ("from outrun.sim.world import Quake", "outrun.sim.world"),
        ("from outrun.sim import *", "outrun.sim"),
        ("from outrun import web, sim", "outrun.sim"),
        ("from outrun import sim as hidden", "outrun.sim"),
        # other relative forms
        ("from ..sim import reports", "outrun.sim.reports"),
        ("from ..evaluation.metrics import compare", "outrun.evaluation.metrics"),
        ("from ..sim.world import Quake", "outrun.sim.world"),
    ],
)
def test_checker_catches_forbidden_import(source, expected):
    assert expected in forbidden_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    from .. import sim\n",
        "def f():\n    from outrun import evaluation\n",
        "class C:\n    def m(self):\n        import outrun.sim\n",
        "try:\n    from outrun import sim\nexcept ImportError:\n    pass\n",
        "if True:\n    from ..evaluation import metrics\n",
        "x = 1\nfor _ in range(1):\n    from ..sim import world\n",
    ],
)
def test_checker_sees_imports_inside_blocks(source):
    assert forbidden_imports(source), f"missed an import in:\n{source}"


@pytest.mark.parametrize(
    "source",
    [
        "import math",
        "from collections import deque",
        "from . import locator",
        "from .locator import solve",
        "from outrun import server",
        "from outrun.server import decide",
        "from outrun import __version__",
        "import outrun",                        # allowed; see LIMITATIONS
        "from outrun import simulation_notes",  # not outrun.sim: no prefix false alarm
        "from outrun import evaluations",       # not outrun.evaluation
    ],
)
def test_checker_allows_safe_imports(source):
    assert forbidden_imports(source) == []


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from outrun import *", "outrun.*"),
        ("from .. import *", "outrun.*"),                   # same thing, relative
        ("def f():\n    from outrun import *\n", "outrun.*"),
        ("from outrun.sim import *", "outrun.sim.*"),
        ("from outrun.evaluation import *", "outrun.evaluation.*"),
    ],
)
def test_checker_rejects_star_import_that_can_expose_forbidden_modules(source, expected):
    assert expected in forbidden_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "from math import *",
        "from . import *",               # outrun.server itself
        "from outrun.server import *",
        "from outrun.web import *",      # sibling package, not a parent of sim/evaluation
    ],
)
def test_checker_allows_safe_star_imports(source):
    assert forbidden_imports(source) == []


def test_relative_import_resolves_from_deeper_subpackage():
    # In outrun/server/sub/x.py, ".." is outrun.server, "..." is outrun.
    assert forbidden_imports("from ... import sim", "outrun.server.sub") == ["outrun.sim"]
    assert forbidden_imports("from .. import sim", "outrun.server.sub") == []  # outrun.server.sim


def test_relative_import_above_top_level_is_reported():
    result = forbidden_imports("from .... import anything", "outrun.server")
    assert len(result) == 1 and result[0].startswith("<unresolvable")


def test_module_package_from_paths():
    root = REPO_ROOT
    assert module_package(root / "outrun/server/locator.py") == "outrun.server"
    assert module_package(root / "outrun/server/__init__.py") == "outrun.server"
    assert module_package(root / "outrun/server/sub/x.py") == "outrun.server.sub"


def test_checker_on_a_real_file_on_disk(tmp_path):
    """End to end on a file: path -> package -> imports, function-level import."""
    pkg = tmp_path / "outrun" / "server"
    pkg.mkdir(parents=True)
    bad = pkg / "bad.py"
    bad.write_text("def sneaky():\n    from .. import sim\n", encoding="utf-8")
    package = module_package(bad, root=tmp_path)
    assert package == "outrun.server"
    assert forbidden_imports(bad.read_text(encoding="utf-8"), package) == ["outrun.sim"]
