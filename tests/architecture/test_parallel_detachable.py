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

meta = MetadataProvider.from_standard_configuration(os.path.join(os.getcwd(), "seed_data"))
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


def test_trainings_run_serially_in_one_child_when_the_plugin_is_detached() -> None:
    """The Training service is core: with ``server.parallel`` unimportable it chooses the
    serial executor, and the runs it produces equal the plugin's in-process reference.

    This needs the test Postgres (the Training is database-backed); without it only the
    executor itself is checked.
    """
    import json

    completed = _run_detached(
        r"""
import asyncio, json, os, sys
from server.engine.metadata import MetadataProvider
from server.services.training_executor import SerialExecutor, TrainingTask, create_executor

meta = MetadataProvider.from_standard_configuration(os.path.join(os.getcwd(), "seed_data"))
executor = create_executor()
assert executor.kind == "serial" and isinstance(executor, SerialExecutor), executor
problems = [("abc", "abd", "ijk"), ("abc", "abd", "xyz")]
out = {}

# The executor alone.
tasks = [TrainingTask(i, m, t, None, seed, 300, None, "off") for (i, m, t) in problems for seed in (1, 2)]
for task in tasks:
    o = executor.submit([task], meta).result(timeout=300)[0]
    out[f"exec/{task.target}/{task.seed}"] = [o.status, o.answer, o.codelets]
executor.close()

# The whole service, when the test database is reachable.
async def service():
    import socket
    url = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://petacat:dev@localhost:5432/petacat_test")
    try:
        host_port = url.split("@")[1].split("/")[0]
        host, _, port = host_port.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
    except Exception:
        return
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from server.models.metadata import Base
    from server.models import training as tr
    from server.services.training_service import TrainingService

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[
            tr.Training.__table__, tr.TrainingProblem.__table__, tr.TrainingRun.__table__,
            tr.TrainingMemoryMerge.__table__]))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    svc = TrainingService(factory, lambda: meta, executor=create_executor())
    await svc.start()
    try:
        made = await svc.create_training(
            name="detached", settings={"memory": "independent", "seeds_per_problem": 2,
                                       "max_codelets": 300, "backend": "off"},
            problems=[{"initial": i, "modified": m, "target": t} for (i, m, t) in problems])
        tid = made["training"]["id"]
        await svc.close(tid)
        for _ in range(600):
            if (await svc.summary(tid))["state"] == "finished":
                break
            await asyncio.sleep(0.2)
        assert (await svc.summary(tid))["state"] == "finished"
        assert svc.executor_info()["kind"] == "serial"
        for pid, (_, _, t) in zip(made["problem_ids"], problems):
            for r in await svc.problem_runs(tid, pid):
                out[f"svc/{t}/{r['seed']}"] = [r["status"], r["answer"], r["codelets"]]
    finally:
        await svc.stop()
        async with factory() as s:
            await s.execute(delete(tr.Training).where(tr.Training.name == "detached"))
            await s.commit()
        await engine.dispose()

asyncio.run(service())
assert "server.parallel" not in sys.modules
print("RESULT", json.dumps(out))
"""
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    out = json.loads(completed.stdout.split("RESULT ", 1)[1])
    assert any(k.startswith("exec/") for k in out)

    # The plugin's in-process reference (a fresh interpreter, plugin present) gives the
    # same runs, run for run.
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    reference = subprocess.run(
        [sys.executable, "-c", r"""
import json, sys
from server.engine.metadata import MetadataProvider
from server.parallel.swarm import SEED_DIR, RunTask, run_inprocess
meta = MetadataProvider.from_standard_configuration(SEED_DIR)
keys = json.loads(sys.argv[1])
out = {}
for key in keys:
    _, target, seed = key.split("/")
    want = run_inprocess(RunTask("abc", "abd", target, None, int(seed), 300, backend="off"), meta)
    out[key] = [want.status, want.answer, want.codelets]
print("RESULT", json.dumps(out))
""", json.dumps(sorted(out))],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=300,
    )
    assert reference.returncode == 0, reference.stderr[-3000:]
    want = json.loads(reference.stdout.split("RESULT ", 1)[1])
    assert out == want
