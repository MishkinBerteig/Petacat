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


#: A database of this module's own, created on demand like ``petacat_step0`` (ruling 62).  The test
#: drops and re-creates its schema, so it must never be pointed at ``petacat_test`` or at whatever
#: ``TEST_DATABASE_URL`` names: the e2e layer holds those under an advisory lock.
#: ``DETACHED_DATABASE_NAME`` may rename it (it must still start ``petacat_detached``), so two sessions
#: run side by side can each have one.
DETACHED_DB_NAME = os.environ.get("DETACHED_DATABASE_NAME", "petacat_detached")
assert DETACHED_DB_NAME.startswith("petacat_detached"), DETACHED_DB_NAME
_SHARED_DEFAULT = "postgresql+asyncpg://petacat:dev@localhost:5432/petacat_test"


def _server_url() -> str:
    """The Postgres server the tests use, without a database name."""
    return os.environ.get("TEST_DATABASE_URL", _SHARED_DEFAULT).rsplit("/", 1)[0]


def _detached_database_url() -> str | None:
    """The URL of ``petacat_detached``, creating the database if it is not there; ``None`` when the
    server is not reachable.  Refuses a name that is the shared test database."""
    import asyncio

    shared = os.environ.get("TEST_DATABASE_URL", _SHARED_DEFAULT).rsplit("/", 1)[1]
    assert DETACHED_DB_NAME not in (shared, "petacat_test"), (
        "this test's database must not be the shared test database")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def create() -> bool:
        engine = create_async_engine(_server_url() + "/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                found = await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": DETACHED_DB_NAME})
                if found.fetchone() is None:
                    await conn.execute(text(f'CREATE DATABASE "{DETACHED_DB_NAME}"'))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    return _server_url() + "/" + DETACHED_DB_NAME if asyncio.run(create()) else None


def _run_detached(body: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    url = _detached_database_url()
    if url is not None:
        env["DETACHED_DATABASE_URL"] = url
    else:
        env.pop("DETACHED_DATABASE_URL", None)
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


def test_sessions_run_serially_in_one_child_when_the_plugin_is_detached() -> None:
    """The Training Mode Session service is core: with ``server.parallel`` unimportable it chooses the
    serial executor, and the runs it produces equal the plugin's in-process reference.

    This needs the test Postgres (the Training Mode Session is database-backed); without it only the
    executor itself is checked.
    """
    import json

    completed = _run_detached(
        r"""
import asyncio, json, os, sys
from server.engine.metadata import MetadataProvider
from server.services.training_mode_session_executor import SerialExecutor, SessionTask, create_executor

meta = MetadataProvider.from_standard_configuration(os.path.join(os.getcwd(), "seed_data"))
executor = create_executor()
assert executor.kind == "serial" and isinstance(executor, SerialExecutor), executor
problems = [("abc", "abd", "ijk"), ("abc", "abd", "xyz")]
out = {}

# The executor alone.
tasks = [SessionTask(i, m, t, None, seed, 300, None, "off") for (i, m, t) in problems for seed in (1, 2)]
for task in tasks:
    o = executor.submit([task], meta).result(timeout=300)[0]
    out[f"exec/{task.target}/{task.seed}"] = [o.status, o.answer, o.codelets]
executor.close()

# The whole service, when this module's own database is reachable.
async def service():
    import socket
    url = os.environ.get("DETACHED_DATABASE_URL")
    if not url:
        return
    # the schema is dropped below: refuse the shared test database, whatever the environment says
    name = url.rsplit("/", 1)[1]
    shared = os.environ.get("TEST_DATABASE_URL", "").rsplit("/", 1)[-1]
    assert name.startswith("petacat_detached") and name not in ("petacat_test", shared), name
    try:
        host_port = url.split("@")[1].split("/")[0]
        host, _, port = host_port.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
    except Exception:
        return
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from server.services.training_mode_session_service import TrainingModeSessionService

    engine = create_async_engine(url, poolclass=NullPool)
    # A session has its own configuration, created from the global one, so the service needs the
    # whole schema and the Metacat Standard Configuration loaded: prepare the test database as
    # the e2e fixtures do (the database outlives schema changes, and they drop it when done).
    from sqlalchemy import text
    from server.models.metadata import Base
    import server.models.run  # noqa: F401
    from server.models import training_mode_session as tr
    from server.services.standard_configuration import seed_metadata_from_json, sync_help_topics

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    prep = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with prep() as s:
        seed_dir = os.path.join(os.getcwd(), "seed_data")
        await seed_metadata_from_json(s, seed_dir)
        await s.flush()
        await sync_help_topics(s, seed_dir)
        await s.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    svc = TrainingModeSessionService(factory, lambda: meta, executor=create_executor())
    await svc.start()
    try:
        made = await svc.create_session(
            name="detached", settings={"seeds_per_problem": 2, "max_codelets": 300, "backend": "off"},
            problems=[{"initial": i, "modified": m, "target": t} for (i, m, t) in problems])
        tid = made["session"]["id"]
        await svc.start_session(tid)
        for _ in range(600):
            if (await svc.summary(tid))["activity"] == "idle":
                break
            await asyncio.sleep(0.2)
        assert (await svc.summary(tid))["activity"] == "idle"
        assert svc.executor_info()["kind"] == "serial"
        for pid, (_, _, t) in zip(made["problem_ids"], problems):
            for r in await svc.problem_runs(tid, pid):
                out[f"svc/{t}/{r['seed']}"] = [r["status"], r["answer"], r["codelets"]]
    finally:
        await svc.stop()
        async with factory() as s:
            await s.execute(delete(tr.TrainingModeSession).where(tr.TrainingModeSession.name == "detached"))
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
    # The Training Mode Session's runs share one Episodic Memory (a run after the first starts from what the
    # earlier ones left), so only the executor's memory-free runs have a plugin reference.
    assert any(k.startswith("svc/") for k in out)
    out = {k: v for k, v in out.items() if k.startswith("exec/")}

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


def test_this_module_never_names_the_shared_test_database() -> None:
    """A guard (ruling 62): the only database this file passes to its child is ``petacat_detached``,
    and nothing here reads ``TEST_DATABASE_URL`` for the database to wipe."""
    import re

    source = open(__file__).read()
    assert DETACHED_DB_NAME.startswith("petacat_detached")
    # the child reads DETACHED_DATABASE_URL only; the shared URL appears only to be refused
    child = source.split('async def service():', 1)[1].split('asyncio.run(service())', 1)[0]
    assert 'os.environ.get("DETACHED_DATABASE_URL")' in child
    assert not re.search(r'os\.environ\.get\("TEST_DATABASE_URL"\s*,\s*"postgresql', child)
    assert "drop_all" in child and 'name.startswith("petacat_detached")' in child
