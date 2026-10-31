"""The database-versus-seed-file equivalence harness (work package C0).

``MetadataProvider.from_standard_configuration`` reads the Metacat Standard Configuration
(``seed_data/*.json``, the read-only reference).  ``load_metadata_from_db`` reads a
database that was loaded from those same files.  Under a freshly loaded database,
with no edits, the two providers must be the same value, field for field, including:

* the **order** of every list and every dict (node order and link order fix the float
  accumulation order and which node each ``rng.prob`` draw is spent on);
* the **type** of every number (``5`` against ``5.0``), and ``bool`` against ``int``;
* tuples against lists.

Python's ``==`` cannot say any of that (``1 == 1.0``, ``True == 1``, and dict equality
ignores order), so this module walks both values and reports each difference by path.

Reusable: every later package that touches a loader or adds a table re-runs
``tests/integration/test_db_seed_equivalence.py``, which is built on these helpers.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Iterator

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED_DIR = os.path.join(REPO_ROOT, "seed_data")

#: The default URL of the scratch database the harness loads.  It is deliberately not
#: ``petacat_test`` (the e2e layer's, which holds an advisory lock for its session) nor
#: ``petacat`` (the development database).
DEFAULT_HARNESS_DB_URL = "postgresql+asyncpg://petacat:dev@localhost:5432/petacat_c0"

#: The advisory-lock key the harness takes on its scratch database, so two pytest
#: sessions cannot drop each other's tables.
HARNESS_LOCK_KEY = 0x7E7ACC0


def deep_differences(
    seed: Any, db: Any, path: str = "", *, limit: int = 400, ordered: bool = True
) -> list[str]:
    """Every place *seed* and *db* differ, as readable lines (``[]`` when identical).

    ``ordered=False`` ignores dict key order (list order still counts); it exists for
    comparing a raw JSONB column against the file it came from.
    """
    out: list[str] = []
    for line in _walk(seed, db, path, ordered):
        out.append(line)
        if len(out) >= limit:
            out.append("... (truncated)")
            break
    return out


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 90 else text[:87] + "..."


def _walk(a: Any, b: Any, path: str, ordered: bool = True) -> Iterator[str]:
    where = path or "<root>"
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        if type(a) is not type(b):
            yield f"{where}: type {type(a).__name__} != {type(b).__name__}"
            return
        for f in dataclasses.fields(a):
            yield from _walk(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}", ordered)
        return
    if type(a) is not type(b):
        yield f"{where}: type {type(a).__name__} {_short(a)} != {type(b).__name__} {_short(b)}"
        return
    if isinstance(a, dict):
        ka, kb = list(a), list(b)
        if set(ka) != set(kb):
            only_a = [k for k in ka if k not in b]
            only_b = [k for k in kb if k not in a]
            yield f"{where}: keys differ; only in seed {only_a[:8]}, only in db {only_b[:8]}"
        elif ordered and ka != kb:
            first = next(i for i, (x, y) in enumerate(zip(ka, kb)) if x != y)
            yield (
                f"{where}: key ORDER differs at position {first} "
                f"(seed {ka[first]!r}, db {kb[first]!r})"
            )
        for k in ka:
            if k in b:
                yield from _walk(a[k], b[k], f"{path}[{k!r}]", ordered)
        return
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            yield f"{where}: length {len(a)} != {len(b)}"
            return
        for i, (x, y) in enumerate(zip(a, b)):
            yield from _walk(x, y, f"{path}[{i}]", ordered)
        return
    if isinstance(a, (set, frozenset)):
        if a != b:
            yield f"{where}: sets differ; only seed {sorted(a - b)[:8]}, only db {sorted(b - a)[:8]}"
        return
    if isinstance(a, float):
        # repr distinguishes 0.0 from -0.0 and shows every digit; NaN != NaN otherwise.
        if repr(a) != repr(b):
            yield f"{where}: {a!r} != {b!r}"
        return
    if a != b:
        yield f"{where}: {_short(a)} != {_short(b)}"


def provider_differences(seed_provider: Any, db_provider: Any) -> dict[str, list[str]]:
    """Differences grouped by provider field (an empty dict means the providers agree)."""
    out: dict[str, list[str]] = {}
    for f in dataclasses.fields(seed_provider):
        found = deep_differences(
            getattr(seed_provider, f.name), getattr(db_provider, f.name), f.name
        )
        if found:
            out[f.name] = found
    return out


# ---------------------------------------------------------------------------
# The scratch database
# ---------------------------------------------------------------------------


def harness_db_url() -> str:
    return os.environ.get("C0_HARNESS_DATABASE_URL", DEFAULT_HARNESS_DB_URL)


async def ensure_database(url: str) -> None:
    """Create the scratch database on the instance if it is missing."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    name = url.rsplit("/", 1)[1]
    admin = create_async_engine(
        url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with admin.connect() as conn:
            found = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            if found.fetchone() is None:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


async def load_fresh_database(engine: Any, seed_dir: str = SEED_DIR) -> None:
    """Drop and recreate every table, then load the seed files into the empty database.

    The same call sequence as ``tests/e2e/conftest.py``'s ``setup_db``: the production
    seeder, once, into empty tables.
    """
    import server.models.run  # noqa: F401 -- registers the runtime tables
    import server.models.training  # noqa: F401
    from server.models.metadata import Base
    from server.services.seeding import seed_metadata_from_json
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await seed_metadata_from_json(session, seed_dir)
        await session.commit()


# ---------------------------------------------------------------------------
# One load per pytest process, shared by every test file of the harness
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FreshDatabase:
    """What a freshly loaded database holds, read back."""

    #: ``load_metadata_from_db`` on the freshly loaded database.
    provider: Any
    #: Every derived metadata table, as ``{table name: [row as {column: value}]}``,
    #: each ordered by primary key, read straight from the database (not via the loader).
    tables: dict[str, list[dict[str, Any]]]


_FRESH: FreshDatabase | None = None


def database_reachable() -> bool:
    import socket

    try:
        authority = harness_db_url().split("@")[1].split("/")[0]
        host, _, port = authority.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
        return True
    except Exception:
        return False


async def _read_tables(engine: Any) -> dict[str, list[dict[str, Any]]]:
    import inspect

    from server.models import metadata as models
    from server.services.seeding import _derived_names
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    classes = {
        cls.__tablename__: cls
        for _, cls in inspect.getmembers(models, inspect.isclass)
        if getattr(cls, "__module__", "") == models.__name__
        and hasattr(cls, "__tablename__")
        and cls.__tablename__ in _derived_names()
    }
    out: dict[str, list[dict[str, Any]]] = {}
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for name, cls in sorted(classes.items()):
            keys = [c.name for c in cls.__table__.primary_key.columns]
            rows = (
                await session.execute(
                    select(cls).order_by(*[cls.__table__.c[k] for k in keys])
                )
            ).scalars()
            out[name] = [
                {
                    attr.key: getattr(row, attr.key)
                    for attr in cls.__mapper__.column_attrs
                }
                for row in rows
            ]
    return out


async def _load_and_read() -> FreshDatabase:
    from server.services.metadata_service import load_metadata_from_db
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    url = harness_db_url()
    await ensure_database(url)
    engine = create_async_engine(url, poolclass=NullPool)
    lock = await engine.connect()
    await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": HARNESS_LOCK_KEY})
    try:
        await load_fresh_database(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            provider = await load_metadata_from_db(session)
        tables = await _read_tables(engine)
    finally:
        await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": HARNESS_LOCK_KEY})
        await lock.close()
        await engine.dispose()
    return FreshDatabase(provider=provider, tables=tables)


def fresh_database() -> FreshDatabase:
    """Empty database, loaded from the seed files, no edits; read back once per process."""
    import asyncio

    global _FRESH
    if _FRESH is None:
        _FRESH = asyncio.run(_load_and_read())
    return _FRESH


def seed_provider() -> Any:
    """A new provider built from the seed files (the reference)."""
    from server.engine.metadata import MetadataProvider

    return MetadataProvider.from_standard_configuration(SEED_DIR)


# ---------------------------------------------------------------------------
# Run equivalence
# ---------------------------------------------------------------------------

#: The lockstep corpus' problems (``tests/lockstep/traces/<initial>-<modified>-<target>``)
#: and a few demo problems.  Modest on purpose; a package that adds fields widens it
#: here and every file that uses it follows.
LOCKSTEP_PROBLEMS: tuple[tuple[str, str, str, str | None], ...] = (
    ("abc", "abd", "xyz", None),
    ("abc", "abd", "ijk", None),
    ("abc", "abd", "mrrjjj", None),
    ("abc", "cba", "mrrjjj", None),
    ("aabc", "aabd", "ijkk", None),
    ("abc", "abd", "ijk", "ijl"),  # a justification run
)
RUN_SEEDS: tuple[int, ...] = (1, 2)
RUN_MAX_STEPS = 1200


def run_signature(meta: Any, problem: tuple, seed: int, max_steps: int = RUN_MAX_STEPS) -> dict:
    """What a Metacat Mode run left behind, for comparing two providers.

    Answer, codelet count, number of draws from the run's random stream, final
    temperature, the final status, and two hashes: one over every trace event, codelet
    step and structure change the sink saw, and one over the final shared state.
    """
    import hashlib

    from server.engine.runner import EngineRunner
    from server.parallel.speculative.compare import RecordingSink
    from server.parallel.speculative.fingerprint import combined

    initial, modified, target, answer = problem
    sink = RecordingSink()
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, answer, seed=seed, sink=sink)
    result = runner.run_mcat(max_steps)
    ctx = runner.ctx
    trace = repr((sink.steps, sink.structures, sink.events, sink.answers, sink.calls))
    final = ctx.workspace.answer_string
    return {
        "status": result.status,
        "answers": list(result.answers),
        "answer_text": final.text if final else "",
        "codelet_count": ctx.codelet_count,
        "rng_calls": ctx.rng.call_count,
        "temperature": repr(float(ctx.temperature.value)),
        "trace_hash": hashlib.sha256(trace.encode()).hexdigest(),
        "state_hash": combined(ctx),
    }
