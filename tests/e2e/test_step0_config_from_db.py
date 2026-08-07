"""Step 0 guard tests — configuration the engine reads comes from the database.

`PHASE 1 PLAN.md` §0.4 sets the bar these tests have to clear.  A test that only
checks a value round-trips JSON → DB → `MetadataProvider` is not a guard test,
because every value in `seed_data/` already passes that.  Each one here asserts
**both** directions:

1. the shipped database value reproduces today's behaviour exactly, and
2. **a changed database value changes the run.**

Only the second distinguishes *wired* from *stored*, and it is the one that would
have caught the state these tests were written against: `server/main.py` seeds
twelve bulk JSON files and `posting_rules.json` is not among the tables it writes,
so the production database held **zero** posting rules while the admin API listed,
exported and imported them.

The comparison is against `MetadataProvider.from_seed_data`, which is what
`scripts/compare_to_metacat.py` and the whole of `tests/module/` run on.  That path
is the reference here: it is the engine the oracle in `ORACLE-COMPARISON.md`
measured, so "the database reproduces it" is the statement worth making.

**Why this module owns a database.**  These tests mutate metadata rows to make the
second assertion, and `tests/e2e/conftest.py::setup_db` seeds `petacat_test` once
per session for every other e2e module to share.  Mutating that mid-session would
hand later tests a configuration they did not ask for, so this file creates and
drops `petacat_step0` of its own.  It also seeds through the **production** seeder
rather than the conftest's copy, because which of the two runs is exactly the
question — the conftest seeds posting rules and production did not, and that
divergence is what kept the defect invisible.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from server.engine.metadata import MetadataProvider
from server.models.metadata import PostingRule
from server.services.metadata_service import load_metadata_from_db

from .conftest import TEST_DB_URL, _db_available

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: A database of this module's own, so mutating metadata cannot reach the session
#: `petacat_test` that every other e2e module shares.
STEP0_DB_NAME = "petacat_step0"
STEP0_DB_URL = TEST_DB_URL.rsplit("/", 1)[0] + "/" + STEP0_DB_NAME

#: Distinct from the conftest's key: this database is not `petacat_test`, so the two
#: locks guard different things and must not serialise against each other.
_SCHEMA_LOCK_KEY = 0x57E70

#: One short problem, run three ways.  `abc → abd; mrrjjj` at seed 42 answers
#: `mrrkkk` in 777 codelets on the shipped configuration and `mrrjjk` in 691 with the
#: posting rules gone, so it separates the two configurations on *both* the answer
#: and the codelet count — and it is quick enough to run several times per test.
PROBLEM = ("abc", "abd", "mrrjjj")
PROBLEM_SEED = 42

pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Test Postgres not reachable; start it with scripts/dev.sh db",
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def step0_engine():
    """An engine on `petacat_step0`, created if it is not there yet."""
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/petacat"
    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": STEP0_DB_NAME},
        )
        if result.fetchone() is None:
            await conn.execute(text(f'CREATE DATABASE "{STEP0_DB_NAME}"'))
    await admin_engine.dispose()

    engine = create_async_engine(STEP0_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def step0_lock(step0_engine):
    """Serialise concurrent sessions, for the reason the conftest's lock exists."""
    connection = await step0_engine.connect()
    await connection.execute(
        text("SELECT pg_advisory_lock(:key)"), {"key": _SCHEMA_LOCK_KEY}
    )
    try:
        yield
    finally:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": _SCHEMA_LOCK_KEY}
        )
        await connection.close()


@pytest.fixture
async def db_session(step0_engine, step0_lock):
    """A database seeded by the **production** seeder, rebuilt for every test.

    Rebuilt per test rather than per module because these tests edit metadata rows,
    and a test that changes a posting rule must not decide what the next one loads.
    """
    from server.models.metadata import Base
    import server.models.run  # noqa: F401 — registers the runtime tables
    from server.services.seeding import seed_metadata_from_json

    async with step0_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        step0_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await seed_metadata_from_json(session, SEED_DIR)
        await session.commit()

    async with factory() as session:
        yield session


@pytest.fixture(scope="module")
def seed_meta():
    """The configuration the oracle and `tests/module/` measure."""
    return MetadataProvider.from_seed_data(SEED_DIR)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def run_outcome(meta: MetadataProvider) -> tuple[str, str | None, int]:
    """One run's stopping state: `(status, answer, codelets)`.

    The triple §0.4 names — "the assertion has to be on the run — status, answer,
    codelet count".  Both configurations run in this process on this session's
    numeric backend, so the comparison is between the two metadata providers and
    nothing else.
    """
    from server.engine.runner import EngineRunner

    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)
    runner.run_mcat(max_steps=20_000)
    workspace = runner.ctx.workspace
    answer = workspace.answer_string.text if workspace.answer_string else None
    return runner.status, answer, runner.ctx.codelet_count


# ──────────────────────────────────────────────────────────────────
# posting_rules
# ──────────────────────────────────────────────────────────────────


async def test_production_seeding_writes_every_posting_rule(db_session, seed_meta):
    """Direction 1, at the table: production seeds what the seed file holds.

    `posting_rules.json` is in `main.py`'s `_BULK_SEED_FILES`, so editing it
    re-fingerprints and re-seeds the database — while the seeder wrote no
    `PostingRule` row at all.  The file counted towards the hash of a table it never
    filled.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert db_meta.posting_rules == seed_meta.posting_rules


async def test_posting_rules_load_in_seed_file_order(db_session, seed_meta):
    """Order is part of the value, not a detail of the query.

    Every rule the engine consults costs a draw from the run's random stream, so two
    orderings of the same seventeen rules are two different engines.  `select()`
    without an `ORDER BY` promises nothing, which makes the ordering a property to
    assert rather than to rely on.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert [r.codelet_type for r in db_meta.posting_rules] == [
        r.codelet_type for r in seed_meta.posting_rules
    ]


async def test_database_posting_rules_drive_the_run_identically(db_session, seed_meta):
    """Direction 1, at the run, for this field alone.

    Holding everything else at the database's values and swapping only
    `posting_rules` isolates the field under test.  Comparing whole providers
    instead would fold in every *other* value the database is still losing, and a
    per-value guard test has to be able to fail for its own reason.
    """
    from dataclasses import replace

    db_meta = await load_metadata_from_db(db_session)
    with_seed_rules = replace(db_meta, posting_rules=seed_meta.posting_rules)

    assert run_outcome(db_meta) == run_outcome(with_seed_rules)


@pytest.mark.xfail(
    strict=True,
    reason="Step 0 in progress: the database still loses codelet_patterns (no table "
    "exists) and descriptor_predicate (the loader does not select it). This is the "
    "capstone assertion for §0 — when it passes, the database configuration and the "
    "seed data are the same engine, and it is strict so it cannot pass unnoticed.",
)
async def test_database_configuration_reproduces_the_seed_data_run(
    db_session, seed_meta
):
    """Direction 1, whole: the database configuration *is* the engine the oracle measured."""
    db_meta = await load_metadata_from_db(db_session)

    assert run_outcome(db_meta) == run_outcome(seed_meta)


async def test_removing_the_top_down_posting_rules_changes_the_run(db_session):
    """Direction 2 — the assertion that separates wired from stored.

    The five `top_down` rules are the ones `runner.py:1286-1291` reads, so deleting
    them is the smallest edit whose effect the engine cannot hide.  A run that comes
    out unchanged means the database is decoration.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        delete(PostingRule).where(PostingRule.direction == "top_down")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_changing_a_triggering_slipnode_changes_the_run(db_session):
    """Direction 2, on a single field rather than whole rows.

    `triggering_slipnodes` decides which activated concept posts which scout.  Pointing
    the category bond scout at a node that never reaches threshold silences it without
    removing anything, which is the edit an admin would actually make.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "top-down-bond-scout:category")
        .values(triggering_slipnodes=["plato-nonexistent-node"])
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped
