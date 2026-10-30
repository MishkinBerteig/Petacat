"""The parallel subsystem is a plugin: the engine never imports it, and Petacat runs without it.

``server/parallel/`` holds everything that spreads Petacat across cores — the swarm of
processes, the speculative executor, free-running.  The user's requirement is that it be
*completely detachable*: the main Petacat runs single-threaded, as Metacat does, and must
keep doing so with the plugin deleted.  Two properties make that true, and each is held
here rather than by discipline:

1. **No engine module names ``server.parallel``.**  Checked statically with ``ast``, the same
   way ``test_engine_purity`` keeps the database layer out, so a docstring mentioning the
   package does not trip it and an import hidden in a function body does.
2. **A serial run, and the service layer, work with the package unimportable.**  Checked in a
   fresh interpreter whose import system refuses ``server.parallel``, so "it would work" is
   replaced by "it ran".
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE_DIR = os.path.join(REPO_ROOT, "server", "engine")
PLUGIN_ROOT = "server.parallel"


def _imported_modules(path: str) -> list[tuple[int, str]]:
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
            # ``from server import parallel`` names the plugin through its alias.
            found.extend(
                (node.lineno, f"{node.module}.{alias.name}") for alias in node.names
            )
    return found


def test_no_engine_module_imports_the_parallel_plugin() -> None:
    offenders = []
    for root, _dirs, files in os.walk(ENGINE_DIR):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            for line, module in _imported_modules(path):
                if module == PLUGIN_ROOT or module.startswith(PLUGIN_ROOT + "."):
                    offenders.append(f"{os.path.relpath(path, REPO_ROOT)}:{line} imports {module}")
    assert not offenders, (
        "server/engine/ must never import the parallel plugin — it is detachable, and "
        "the engine is the single-threaded reference it is measured against:\n  "
        + "\n  ".join(offenders)
    )


_BLOCK_PLUGIN = r"""
import importlib.abc, sys

class _Detached(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "server.parallel" or name.startswith("server.parallel."):
            raise ImportError(f"{name} is detached for this test")
        return None

sys.meta_path.insert(0, _Detached())
"""


def _run_detached(body: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PETACAT_NUMERIC_BACKEND", "off")
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_PLUGIN + body],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=300,
    )


def test_a_serial_run_completes_with_the_plugin_detached() -> None:
    completed = _run_detached(
        r"""
import os
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

meta = MetadataProvider.from_seed_data(os.path.join(os.getcwd(), "seed_data"))
runner = EngineRunner(meta)
runner.init_mcat("abc", "abd", "xyz", seed=7)
result = runner.run_mcat(max_steps=20000)
assert "server.parallel" not in sys.modules
print("STATUS", runner.status, result.codelet_count)
"""
    )
    assert completed.returncode == 0, completed.stderr
    assert "STATUS" in completed.stdout


def test_the_run_service_imports_and_falls_back_to_serial_when_detached() -> None:
    completed = _run_detached(
        r"""
import server.services.run_service as rs
assert rs._parallel is None, "the service layer should see the plugin as absent"
print("OK")
"""
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout
