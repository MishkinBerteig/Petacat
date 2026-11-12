"""The Training Mode Base Configuration (``training_base/``) is Training Mode's alone.

Only ``services/configurations.py`` (session creation, and the Admin view's comparison, which asks it
for the resolved Base) imports ``server.services.training_base``, and it imports it lazily.  Nothing on Metacat Mode's run path does:
not ``server/engine/``, not ``server/parallel/``, not ``RunService``, the sinks or Review.  A fresh
interpreter that imports Metacat Mode's run path does not load the module, and no file there
names the folder.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"

IMPORTERS = {"services/configurations.py"}

RUN_PATH = [
    "server.engine.runner", "server.parallel.swarm", "server.services.run_service",
    "server.services.sinks", "server.services.review_service", "server.api.runs", "server.api.swarm",
]


def _imports_training_base(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        if any(n == "server.services.training_base" or n.endswith(".training_base") for n in names):
            lines.append(node.lineno)
    return lines


def test_only_the_configurations_service_imports_it():
    found = {}
    for path in sorted(SERVER.rglob("*.py")):
        rel = path.relative_to(SERVER).as_posix()
        if rel == "services/training_base.py":
            continue
        lines = _imports_training_base(ast.parse(path.read_text()))
        if lines:
            found[rel] = lines
    assert set(found) == IMPORTERS, found


def test_those_imports_are_inside_functions_so_importing_them_loads_nothing():
    for rel in IMPORTERS:
        tree = ast.parse((SERVER / rel).read_text())
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert not _imports_training_base(ast.Module(body=top_level, type_ignores=[])), rel


def test_the_engine_and_the_parallel_plugin_never_name_the_folder():
    for rel_dir in ("engine", "parallel"):
        for path in sorted((SERVER / rel_dir).rglob("*.py")):
            assert "training_base" not in path.read_text(), path


def test_importing_the_metacat_mode_run_path_does_not_load_the_module():
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in RUN_PATH)
        + "assert 'server.services.training_base' not in sys.modules, 'loaded'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    assert done.returncode == 0, done.stderr
