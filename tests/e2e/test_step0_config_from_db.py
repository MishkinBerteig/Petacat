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

#: A second problem, for the values `mrrjjj` cannot see.
#:
#: `mrrjjj` at seed 42 reaches its answer without ever snagging, so it never clamps and
#: is *insensitive* to `codelet_patterns` — measured: identical at 777 codelets with the
#: patterns present and with them all removed.  A guard test on that problem would have
#: passed against an engine holding no patterns at all, which is the failure the whole
#: file exists to detect.
#:
#: `abc → abd; xyz` is the standard snagging problem: `z` has no successor, so the run
#: hits the snag, clamps, and the patterns decide what the clamp pins.  Seed 42 rather
#: than the cheaper seed 7 because it separated the configurations on *both* engines the
#: database could be while the predicates were still being lost in the loader:
#:
#:   with descriptor predicates:  answer_found xyz 17284 → gave_up 17283
#:   without them:                gave_up 3113          → gave_up 2537
#:
#: Seed 7 separated them only on the first, so a guard built on it would have stopped
#: discriminating the moment the predicates were wired up — silently, which is the one
#: way a guard test fails that nothing reports.
CLAMP_PROBLEM = ("abc", "abd", "xyz")
CLAMP_SEED = 42

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


def run_outcome(
    meta: MetadataProvider,
    problem: tuple[str, str, str] = PROBLEM,
    seed: int = PROBLEM_SEED,
) -> tuple[str, str | None, int]:
    """One run's stopping state: `(status, answer, codelets)`.

    The triple §0.4 names — "the assertion has to be on the run — status, answer,
    codelet count".  Both configurations run in this process on this session's
    numeric backend, so the comparison is between the two metadata providers and
    nothing else.

    *problem* is a parameter because no single problem is sensitive to every
    configuration value; each guard has to pick one its value can actually move.
    """
    from server.engine.runner import EngineRunner

    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=seed)
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


async def test_database_configuration_reproduces_the_seed_data_run(
    db_session, seed_meta
):
    """Direction 1, whole: the database configuration *is* the engine the oracle measured.

    The capstone for §0's first half.  It was a strict xfail through the two increments
    that made it true — the database lost `codelet_patterns` to a table that did not
    exist and `descriptor_predicate` to a loader that did not select it — and strict so
    that it could not start passing unnoticed.  It passes now, on both problems.

    What it does *not* say is that every value the engine reads comes from the database:
    the values still hardcoded in Python (`PHASE 1 PLAN.md` §0.2(a) and (b)) are equal
    on both sides of this comparison precisely because neither side reads them.  This
    asserts that nothing is lost in transit, which is the half that was broken.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert run_outcome(db_meta) == run_outcome(seed_meta)
    assert run_outcome(db_meta, CLAMP_PROBLEM, CLAMP_SEED) == run_outcome(
        seed_meta, CLAMP_PROBLEM, CLAMP_SEED
    )


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


# ──────────────────────────────────────────────────────────────────
# codelet_patterns
# ──────────────────────────────────────────────────────────────────


async def test_production_seeding_writes_every_codelet_pattern(db_session, seed_meta):
    """Direction 1, at the table.

    The nine named patterns live in `posting_rules.json` beside the rules, and had no
    table to be written into: `load_metadata_from_db` built `codelet_patterns` as an
    empty dict with a comment saying the patterns were "stored inline in seed_data".
    They are the engine's clamps — a jootser's response to a repeated snag, and the
    whole of justify mode's opening — so an empty dict is not a missing convenience.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert db_meta.codelet_patterns == seed_meta.codelet_patterns


async def test_codelet_pattern_entries_keep_their_order(db_session, seed_meta):
    """A pattern is an ordered list of clamps, and it round-trips as one."""
    db_meta = await load_metadata_from_db(db_session)

    assert list(db_meta.codelet_patterns) == list(seed_meta.codelet_patterns)
    for name, entries in seed_meta.codelet_patterns.items():
        assert db_meta.codelet_patterns[name] == entries, name


async def test_database_codelet_patterns_drive_the_run_identically(
    db_session, seed_meta
):
    """Direction 1, at the run, for this field alone."""
    from dataclasses import replace

    db_meta = await load_metadata_from_db(db_session)
    with_seed_patterns = replace(db_meta, codelet_patterns=seed_meta.codelet_patterns)

    assert run_outcome(db_meta, CLAMP_PROBLEM, CLAMP_SEED) == run_outcome(
        with_seed_patterns, CLAMP_PROBLEM, CLAMP_SEED
    )


async def test_emptying_the_bottom_up_codelet_pattern_changes_the_run(db_session):
    """Direction 2.

    `bottom-up-codelet-pattern` is what `jootsing.py:429` clamps when the jootser
    decides the run is stuck in one way of seeing the problem.  Deleting its entries
    leaves the pattern named and empty, so the clamp still fires and pins nothing —
    which is precisely the state an unwired `codelet_patterns` left the engine in.
    """
    from server.models.metadata import CodeletPatternDef

    shipped = run_outcome(
        await load_metadata_from_db(db_session), CLAMP_PROBLEM, CLAMP_SEED
    )

    await db_session.execute(
        delete(CodeletPatternDef).where(
            CodeletPatternDef.pattern_name == "bottom-up-codelet-pattern"
        )
    )
    await db_session.commit()

    changed = run_outcome(
        await load_metadata_from_db(db_session), CLAMP_PROBLEM, CLAMP_SEED
    )

    assert changed != shipped


# ──────────────────────────────────────────────────────────────────
# descriptor_predicate
# ──────────────────────────────────────────────────────────────────


async def test_the_loader_reads_back_every_descriptor_predicate(db_session, seed_meta):
    """Direction 1, at the column.

    `slipnet_node_defs.descriptor_predicate` has had a column since the field was
    added, startup reconciles it onto databases that predate it, and the seeder writes
    it.  `load_metadata_from_db` built its `SlipnodeSpec` from three columns and never
    selected the fourth, so all fourteen predicates were dropped on the way back —
    the plan's §0.3 case exactly, where a value gets the column and the loader and not
    the thing that reads it.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert db_meta.slipnet_node_specs == seed_meta.slipnet_node_specs


async def test_database_descriptor_predicates_drive_the_run_identically(
    db_session, seed_meta
):
    """Direction 1, at the run, for this field alone."""
    from dataclasses import replace

    db_meta = await load_metadata_from_db(db_session)
    with_seed_nodes = replace(db_meta, slipnet_node_specs=seed_meta.slipnet_node_specs)

    assert run_outcome(db_meta) == run_outcome(with_seed_nodes)


async def test_changing_a_descriptor_predicate_changes_the_run(db_session):
    """Direction 2.

    A predicate decides when a node validly describes an object.  Making
    `plato-leftmost`'s never hold stops the leftmost object of every string being
    described as leftmost, without removing a node, a link or a codelet — an edit with
    nowhere to hide except in behaviour.  It takes `mrrjjj` from 777 codelets to 898.

    `plato-leftmost` rather than a node higher up the list because most of them are
    *insensitive* on this problem: falsifying `plato-whole`, `plato-letter`,
    `plato-group`, `plato-single` or `plato-three` each leave the run at exactly 777.
    A predicate that is never consulted proves nothing about whether predicates are
    read.
    """
    from server.models.metadata import SlipnetNodeDef

    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(SlipnetNodeDef)
        .where(SlipnetNodeDef.name == "plato-leftmost")
        .values(descriptor_predicate="False")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_the_export_carries_the_descriptor_predicates(db_session):
    """The value has to come *back out* as an editable field, not only go in.

    §0's requirement is bi-directional: a value carried JSON → DB → runtime and back
    out as something an admin can edit.  The predicate had none of the second half —
    it appeared in no admin response, no request model and no export, so the one way
    to change it was to edit the seed file and re-seed, which is the state the whole
    of Step 0 is moving away from.

    Asserted against the database rather than over HTTP because this module owns its
    own database; `tests/e2e/test_api_extended.py` covers the export endpoint itself.
    """
    from sqlalchemy import select

    from server.models.metadata import SlipnetNodeDef

    result = await db_session.execute(
        select(SlipnetNodeDef).where(SlipnetNodeDef.descriptor_predicate.isnot(None))
    )
    with_predicates = {r.name: r.descriptor_predicate for r in result.scalars()}

    assert len(with_predicates) == 14
    assert with_predicates["plato-leftmost"] == (
        "not string_spanning_group(obj) and position_in_string(obj, 'leftmost')"
    )
