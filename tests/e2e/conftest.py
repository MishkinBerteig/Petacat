"""E2E test fixtures — requires Postgres accessible via TEST_DATABASE_URL.

Petacat runs natively on macOS (WP2.1), so these reach a local Postgres:

  brew services start postgresql@17
  .venv/bin/python -m pytest tests/e2e/ -v

TEST_DATABASE_URL overrides the default below.  It names a separate database on the
same instance as the development one, so a test run cannot touch the Training
Session accumulated in `petacat`.

ALL e2e tests are deterministic: they use fixed seeds and produce
identical results on every run.
"""

import os
import asyncio
import pytest
import httpx

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://petacat:dev@localhost:5432/petacat_test",
)

# Fixed seed for deterministic e2e tests
E2E_SEED = 12345


def _db_available() -> bool:
    """Check if the test DB host is reachable."""
    import socket
    # Parse host and port from the URL
    # URL format: postgresql+asyncpg://user:pass@host:port/dbname
    try:
        parts = TEST_DB_URL.split("@")[1].split("/")[0]
        if ":" in parts:
            host, port = parts.split(":")
            port = int(port)
        else:
            host = parts
            port = 5432
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except Exception:
        return False


# Skip all e2e tests if DB isn't reachable
pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason=f"Test Postgres not reachable at {TEST_DB_URL.rsplit('@', 1)[-1]}. "
           "Start it with: scripts/dev.sh db",
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    from sqlalchemy.pool import NullPool

    # First, ensure the test database exists
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/petacat"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'petacat_test'")
        )
        if result.fetchone() is None:
            await conn.execute(text("CREATE DATABASE petacat_test"))
    await admin_engine.dispose()

    # Use NullPool to avoid connection sharing issues with ASGI transport
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


# Identifies the advisory lock below.  Any constant works as long as every e2e
# session agrees on it; this one is arbitrary and simply unlikely to collide with a
# lock taken by something else on the same instance.
_SCHEMA_LOCK_KEY = 0x7E7ACA7


@pytest.fixture(scope="session")
async def schema_lock(test_engine):
    """Serialise e2e sessions that share ``petacat_test``.

    ``setup_db`` drops and recreates every table.  Two pytest sessions against the
    same database therefore destroy each other's schema mid-run, and the symptom —
    ``relation "runs" does not exist``, raised from whichever tests happened to be
    executing — looks nothing like its cause.  It cost a misdiagnosis: the failure
    first appeared during a free-threaded run that happened to overlap another suite,
    and read as a free-threading defect until two concurrent runs on the *standard*
    build reproduced it exactly.

    A Postgres advisory lock makes the second session wait rather than interleave.
    It is held on a dedicated connection for the whole session because the engine
    uses ``NullPool``: advisory locks belong to a connection, and one taken on a
    connection that is immediately returned would be released at once.
    """
    connection = await test_engine.connect()
    await connection.execute(text("SELECT pg_advisory_lock(:key)"),
                             {"key": _SCHEMA_LOCK_KEY})
    try:
        yield
    finally:
        await connection.execute(text("SELECT pg_advisory_unlock(:key)"),
                                 {"key": _SCHEMA_LOCK_KEY})
        await connection.close()


@pytest.fixture(scope="session")
async def setup_db(test_engine, schema_lock):
    """Create all tables and seed metadata once per session."""
    # Import all models so Base.metadata knows about them
    from server.models.metadata import Base  # noqa
    import server.models.run  # noqa — registers Run, CycleSnapshot, etc. on Base.metadata

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Seed metadata
    from sqlalchemy.pool import NullPool
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await _seed_metadata(session)
        await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_metadata(session: AsyncSession):
    """Insert seed_data into the test DB — through the production seeder.

    This used to be a second copy of ``server/main.py``'s seeding, and the two drifted:
    the copy here wrote ``posting_rules`` and production did not, so the suite measured
    an engine the application could never build and the defect stayed invisible for as
    long as both were maintained by hand.  `PHASE 1 PLAN.md` §0.2(c) is about exactly
    that shape — one concept with two definitions — and requires the duplicate resolved
    rather than re-homed.

    Seeding through the real thing also means a table added to the seeder is seeded
    here the day it is added, instead of the day someone remembers this file.
    """
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

    from server.services.seeding import seed_metadata_from_json, sync_help_topics

    await seed_metadata_from_json(session, seed_dir)
    await session.flush()
    await sync_help_topics(session, seed_dir)


@pytest.fixture(autouse=True)
async def fresh_episodic_memory(test_engine, setup_db):
    """Start every test with an empty Episodic Memory.

    ``_global_memory`` is process-global and deliberately outlives a Run — that is what
    a Training Session *is*.  It used to be harmless to let it accumulate across
    unrelated tests because nothing read it back into cognition.  It is not harmless
    now: ``answer_present`` makes the program refuse to rediscover an answer already in
    memory (``answers.ss:982``), so a test could inherit an answer from whichever test
    happened to run before it and give up instead of solving its own problem.

    ``Metacat/help.txt:31`` puts the same idea the other way round: "resetting a run
    does not erase Metacat's memory", and clearing it is a separate, deliberate act.

    Both places it lives, for the reason ``clear_memory`` touches both: ``GET
    /api/memory`` serves the *rows* while cognition reads ``_global_memory``.  Emptying
    only the object would leave the listing naming answers the live memory no longer
    holds — the same divergence between the two stores that let
    ``/api/memory/compare`` resolve an id to the wrong answer, reproduced inside the
    test suite.
    """
    from server.models.run import AnswerDescriptionRow, SnagDescriptionRow
    from server.services.run_service import _global_memory

    async def _empty() -> None:
        _global_memory.clear()
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            for table in (AnswerDescriptionRow, SnagDescriptionRow):
                await session.execute(delete(table))
            await session.commit()

    await _empty()
    yield
    await _empty()


@pytest.fixture
async def db_session(test_engine, setup_db):
    """Provide a fresh async session for each test."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def app_client(setup_db, test_engine):
    """Provide an HTTPX async client pointing at the FastAPI app.

    Overrides the DB dependency to use the test database.
    """
    from server.main import app
    from server.db import get_session
    from server.engine.metadata import MetadataProvider
    from server.services.run_service import RunService
    from server.api import runs as runs_module

    seed_dir = os.environ.get(
        "SEED_DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "seed_data"),
    )
    meta = MetadataProvider.from_seed_data(seed_dir)
    run_service = RunService(meta)
    runs_module._run_service = run_service

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_session():
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _test_session

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
