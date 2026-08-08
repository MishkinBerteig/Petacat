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


# ──────────────────────────────────────────────────────────────────
# min_shard_capacity
# ──────────────────────────────────────────────────────────────────


async def test_min_shard_capacity_ships_as_twenty_five(db_session):
    """Direction 1: the value moves into the database without moving.

    `PHASE 1 PLAN.md` §0.5 is explicit that `MIN_SHARD_CAPACITY` "must still be 25
    when it becomes a row".  It is a cognition measurement, not a tuning knob: at
    eight shards of twelve on `eqe → qeq; abbba?` the `gave_up` stopping state
    disappeared entirely — 0 in 60 runs against 23 for the serial engine, on that
    problem's most frequent outcome.
    """
    db_meta = await load_metadata_from_db(db_session)

    assert db_meta.get_param("min_shard_capacity") == 25


async def test_min_shard_capacity_bounds_the_shard_count_from_the_database(db_session):
    """Direction 2 — and the reason this phase needs the value to be a row at all.

    The shard count is `max_coderack_size // min_shard_capacity`, 4 at the shipped rack
    of 100.  The plan's *Carried forward: parallelism beyond sharding* sweep cannot vary
    the floor while it is a module constant, so "changing it changes the engine" is the
    assertion that makes that measurement expressible.
    """
    from server.engine.coderack_shards import WorkerShardedCoderack

    db_meta = await load_metadata_from_db(db_session)
    assert WorkerShardedCoderack(db_meta, 8).num_shards == 4

    coarser = db_meta.with_overrides({"min_shard_capacity": 50})
    assert WorkerShardedCoderack(coarser, 8).num_shards == 2

    finer = db_meta.with_overrides({"min_shard_capacity": 10})
    assert WorkerShardedCoderack(finer, 8).num_shards == 8


# ──────────────────────────────────────────────────────────────────
# bottom_up_types
# ──────────────────────────────────────────────────────────────────


async def test_deleting_a_bottom_up_posting_rule_changes_the_run(db_session):
    """Direction 2 for the bottom-up half of the posting rules.

    Until now only the five `top_down` rules were live: `_post_bottom_up_codelets`
    never read `meta.posting_rules` at all, and walked an eleven-string Python list
    instead (`PHASE 1 PLAN.md` §0.2(b)).  So all eleven `bottom_up` rows were editable,
    hashed and displayed while the engine ignored every one of them — deleting them all
    changed nothing.

    `breaker` is the rule to delete because it is posted on every cycle at a probability
    of `temperature / 100`, so its absence is felt from the first cycle rather than only
    once some structure exists.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        delete(PostingRule).where(PostingRule.codelet_type == "breaker")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_the_bottom_up_rules_the_engine_posts_are_the_database_rows(db_session):
    """Direction 1: the eleven types come from the table, in the table's order."""
    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(db_meta)

    assert runner.bottom_up_codelet_types() == [
        "bottom-up-bond-scout",
        "group-scout:whole-string",
        "bottom-up-bridge-scout",
        "important-object-bridge-scout",
        "bottom-up-description-scout",
        "rule-scout",
        "answer-finder",
        "answer-justifier",
        "progress-watcher",
        "jootser",
        "breaker",
    ]


# ──────────────────────────────────────────────────────────────────
# posting_formula
# ──────────────────────────────────────────────────────────────────


async def test_zeroing_every_posting_formula_changes_the_run(db_session):
    """Direction 2, and the measurement `PHASE 1 PLAN.md` §0.1 opens with.

    The plan records that a copy of the seed data with every `posting_formula` set to
    `0.0` produced a **bit-identical** run — same answer, same codelet count, on three
    seeds — because nothing compiled or evaluated the field.  A configuration reading
    "post nothing, ever" ran exactly like the shipped one, while the edit moved the
    config hash and was displayed back through the admin API.

    So this is the assertion that measurement demands: a database in which every rule
    says never to post must not run like the one that says when to.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(update(PostingRule).values(posting_formula="0.0"))
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_changing_one_posting_formula_changes_the_run(db_session):
    """Direction 2, on a single rule rather than all seventeen.

    `breaker` posts at `temperature / 100`, so halving it leaves the rule in place,
    posting, at a different rate — the smallest edit that is still an edit.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "breaker")
        .values(posting_formula="temperature / 200")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_an_unparseable_posting_formula_is_refused_at_load(db_session):
    """A bad formula fails where it can be seen, not mid-run.

    §0.3 names this as the third of the three parts `descriptor_predicate` got and
    `posting_formula` did not: a compile step that raises at load.  Mid-run the same
    fault would surface as one codelet type quietly not posting, which reads as the
    engine exploring differently rather than as a broken configuration.
    """
    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "breaker")
        .values(posting_formula="temperature / ")
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="does not compile"):
        await load_metadata_from_db(db_session)


async def test_a_posting_formula_naming_something_unknown_is_refused(db_session):
    """A formula that names nothing real must not evaluate to "never post"."""
    from server.engine.posting import PostingContext, evaluate_posting_formula

    with pytest.raises(ValueError, match="unknown name"):
        evaluate_posting_formula("no_such_quantity / 100", "breaker", PostingContext(None))


# ──────────────────────────────────────────────────────────────────
# count_formula / count_values
# ──────────────────────────────────────────────────────────────────


async def test_zeroing_every_count_formula_changes_the_run(db_session):
    """Direction 2, the counterpart of §0.1's `posting_formula` measurement.

    The plan set every `count_formula` to `0` and every `count_values` to zero along
    with the rest, and the run came out bit-identical.  A rule saying "post none of
    these" has to mean it.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule).values(count_formula="fixed", count_values={"fixed": 0})
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_changing_one_rules_count_values_changes_the_run(db_session):
    """Direction 2, on one rule's lookup table.

    `bottom-up-bond-scout` posts two, four or six scouts depending on a stochastically
    blurred count of unrelated objects.  Flattening the table to one leaves the rule
    posting, and leaves the blurred draw in place so the random stream is not
    displaced — only the number of codelets that draw produces.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "bottom-up-bond-scout")
        .values(count_values={"few": 1, "some": 1, "many": 1})
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_a_group_scout_count_costs_no_draw_before_any_bond_exists(db_session):
    """Direction 1, on the ordering that the count formula must not disturb.

    `num_ungrouped_objects_based` reads a *stochastically blurred* object tally, which
    costs a draw from the run's random stream.  The switch this replaces checked for
    bonds **first** and returned zero without drawing, because grouping cannot start
    before anything is bonded.  Moving the check after the draw would consume one
    extra number on every early cycle and send the whole run somewhere else — a
    reordering with no visible cause, which is the hardest kind of regression to find.

    So the `none` entry in `count_values` is the no-bonds answer, and reaching it must
    leave the generator untouched.
    """
    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(db_meta)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)

    workspace = runner.ctx.workspace
    for string in workspace.all_strings:
        string.bonds.clear()

    rule = runner.posting_rule_for("group-scout:whole-string")
    before = runner.ctx.rng.call_count

    assert runner._compute_num_to_post(rule) == 0
    assert runner.ctx.rng.call_count == before, "the no-bonds path consumed a draw"


# ──────────────────────────────────────────────────────────────────
# urgency_when_posted / urgency_formula
# ──────────────────────────────────────────────────────────────────


async def test_changing_a_rules_posted_urgency_changes_the_run(db_session):
    """Direction 2 for `urgency_when_posted`.

    Urgency is what the rack's two-stage weighted draw selects on, so raising a scout
    family from low to extremely-high changes which codelets run and in what order
    without changing which are posted.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "bottom-up-bond-scout")
        .values(urgency_when_posted=91)
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_changing_a_rules_urgency_formula_changes_the_run(db_session):
    """Direction 2 for `urgency_formula`, which is the top-down rules' whole urgency.

    A top-down codelet's urgency is its triggering node's conceptual depth times its
    activation.  Flattening the formula to a constant keeps every rule posting the same
    codelets and stops depth and activation deciding which of them runs first.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.direction == "top_down")
        .values(urgency_formula="1")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


# ──────────────────────────────────────────────────────────────────
# condition
# ──────────────────────────────────────────────────────────────────


async def test_changing_a_rules_condition_changes_the_run(db_session):
    """Direction 2 for `condition`.

    `breaker` is unconditional; making it fire only while justifying stops it posting
    at all on a discovery run, without touching its formula, its count or its urgency.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        update(PostingRule)
        .where(PostingRule.codelet_type == "breaker")
        .values(condition="justify_mode")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_a_false_condition_costs_no_draw(db_session):
    """Direction 1, on the ordering — the same property the group-scout count has.

    A condition is checked *before* the posting probability is drawn for, so a rule
    excluded by mode never reaches the generator.  That is what the hardcoded mode
    exclusions did, and it has to stay true: a skipped rule that still drew would
    displace every subsequent decision in the run.
    """
    from dataclasses import replace

    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(db_meta)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)

    rule = replace(runner.posting_rule_for("breaker"), condition="False")
    before = runner.ctx.rng.call_count

    assert runner._rule_condition_holds(rule) is False
    assert runner.ctx.rng.call_count == before, "a refused condition consumed a draw"


# ──────────────────────────────────────────────────────────────────
# initial_codelets
# ──────────────────────────────────────────────────────────────────


async def test_the_opening_population_is_four_per_object_from_the_database(db_session):
    """Direction 1: the shipped configuration posts what the reference posts.

    ``post-initial-codelets`` (``run.ss:275-283``) is ``2N`` rounds of *two* posts —
    **4N** codelets, 36 for `abc/abd/xyz`'s nine objects.
    """
    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(db_meta)
    runner.init_mcat("abc", "abd", "xyz", seed=PROBLEM_SEED)

    assert len(runner.ctx.workspace.all_objects) == 9
    assert runner.ctx.coderack.total_count == 36


async def test_the_opening_population_alternates_the_two_types(db_session):
    """Direction 1, on the ordering, which is not cosmetic.

    The Scheme repeats a *body* containing both posts, so the batch alternates rather
    than running all of one type and then all of the other.  It matters when the batch
    reaches the rack's capacity: `post_deferred` then drops `len(batch) - capacity`
    members **uniformly at random**, and which codelet each drawn index lands on
    depends on the order they were appended in.
    """
    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(db_meta)
    runner.init_mcat("abc", "abd", "xyz", seed=PROBLEM_SEED)

    # The rack bins by urgency, so read the batch the runner built rather than the
    # rack's own ordering: the property is what was appended, in what order.
    batch = runner.build_initial_codelet_batch()
    assert [c.codelet_type for c in batch[:4]] == [
        "bottom-up-bond-scout",
        "bottom-up-bridge-scout",
        "bottom-up-bond-scout",
        "bottom-up-bridge-scout",
    ]
    assert len(batch) == 36


async def test_changing_the_opening_population_changes_the_run(db_session):
    """Direction 2.

    `_post_initial_codelets` hardcoded both types, the round count and the urgency
    tier (`PHASE 1 PLAN.md` §0.2(b)), and the `initial_codelets` block in the seed data
    that states all three was read by nothing.
    """
    from sqlalchemy import update as sql_update

    from server.models.metadata import EngineParam

    shipped = run_outcome(await load_metadata_from_db(db_session))

    await db_session.execute(
        sql_update(EngineParam)
        .where(EngineParam.name == "initial_codelet_rounds")
        .values(value="num_workspace_objects")
    )
    await db_session.commit()

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


# ──────────────────────────────────────────────────────────────────
# Upgrading a database that already exists
# ──────────────────────────────────────────────────────────────────


async def test_seeding_survives_a_column_the_models_no_longer_declare(step0_engine, step0_lock):
    """A configuration change has to reach a database that already exists.

    Startup reconciles *missing* columns onto an older database, and never removed
    stale ones.  So renaming a column on a derived metadata table left the old one in
    place — and a `NOT NULL` column the seeder no longer writes makes every insert into
    that table fail.

    The failure is silent in the direction that matters. `_ensure_db_ready` catches
    everything and logs "DB setup skipped (may not be available)", so the seeding
    transaction rolls back whole and the application starts against **stale or empty**
    metadata with nothing to say the configuration it is serving is not the
    configuration on disk. That is the condition the whole of Step 0 exists to remove,
    reappearing one level down in the machinery that delivers it.

    Derived metadata tables are emptied and rewritten on every re-seed, so dropping a
    column they no longer declare loses nothing. Runtime tables are never touched.
    """
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from server.main import _reconcile_metadata_columns
    from server.models.metadata import Base
    import server.models.run  # noqa: F401
    from server.services.seeding import seed_metadata_from_json

    async with step0_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Stand in for a column that used to exist and has since been renamed away.
        await conn.execute(
            sql_text(
                'ALTER TABLE codelet_pattern_defs '
                'ADD COLUMN "urgency" INTEGER NOT NULL DEFAULT 0'
            )
        )
        await conn.execute(
            sql_text('ALTER TABLE codelet_pattern_defs ALTER COLUMN "urgency" DROP DEFAULT')
        )

    await _reconcile_metadata_columns(step0_engine)

    factory = async_sessionmaker(step0_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await seed_metadata_from_json(session, SEED_DIR)
        await session.commit()

    async with factory() as session:
        meta = await load_metadata_from_db(session)

    assert len(meta.codelet_patterns) == 9
    assert len(meta.posting_rules) == 17


async def test_reconciliation_never_drops_a_column_from_a_runtime_table(step0_engine, step0_lock):
    """Removing stale columns is for the derived tables, and only for those.

    A derived table is emptied and rewritten on every re-seed, so a column it no longer
    declares holds nothing worth keeping. `runs`, `trace_events` and the episodic-memory
    tables hold a user's actual work, and a column there that the models have stopped
    declaring is a migration to be written by hand, not something startup should delete.
    """
    from sqlalchemy import text as sql_text

    from server.main import _reconcile_metadata_columns
    from server.models.metadata import Base
    import server.models.run  # noqa: F401

    async with step0_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sql_text('ALTER TABLE runs ADD COLUMN "retired_column" TEXT')
        )

    await _reconcile_metadata_columns(step0_engine)

    async with step0_engine.connect() as conn:
        result = await conn.execute(
            sql_text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'runs'"
            )
        )
        columns = {row[0] for row in result}

    assert "retired_column" in columns, "a runtime table's column was dropped"


# ──────────────────────────────────────────────────────────────────
# Parameters that existed in the table and that nothing read
# ──────────────────────────────────────────────────────────────────
#
# Each of these shipped in `engine_params` with a value identical to a Python
# literal the engine used instead, so an admin could edit it, see the config hash
# move, see the new value listed back — and change nothing. They are the same
# condition as the posting formulas, found by auditing what the engine reads rather
# than what the plan happened to list.


async def _set_param(session, name: str, value: str) -> None:
    from sqlalchemy import update as sql_update

    from server.models.metadata import EngineParam

    await session.execute(
        sql_update(EngineParam).where(EngineParam.name == name).values(value=value)
    )
    await session.commit()


async def test_changing_max_clamp_period_changes_the_run(db_session):
    """Direction 2 — and this one was half-wired, which is worse than not at all.

    `max_clamp_period` was read at `jootsing.py:132` for the progress-watcher's
    judgement, and *not* at `runner.py`'s clamp-expiry check, which is the call that
    actually ends a clamp. Shortening the parameter shortened the jootser's patience
    and left the clamp running to the old literal 750: half the mechanism moved.

    `xyz` is the probe because it is the problem that snags, and a clamp is the snag
    response.
    """
    shipped = run_outcome(
        await load_metadata_from_db(db_session), CLAMP_PROBLEM, CLAMP_SEED
    )

    await _set_param(db_session, "max_clamp_period", "100")

    changed = run_outcome(
        await load_metadata_from_db(db_session), CLAMP_PROBLEM, CLAMP_SEED
    )

    assert changed != shipped


async def test_changing_the_expiration_period_changes_the_run(db_session):
    """Direction 2. `%expiration-period%` (`workspace.ss:30`) scales the activity
    measure the progress-watcher reads, so it moves every problem."""
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await _set_param(db_session, "expiration_period", "50")

    changed = run_outcome(await load_metadata_from_db(db_session))

    assert changed != shipped


async def test_the_theme_activation_ceiling_comes_from_the_database(db_session):
    """Direction 2, at the mechanism rather than the whole run.

    `max_theme_activation` is the clip both poles of a theme's activation use
    (`themes.ss:34-38`). No run in the sample is sensitive to it — themes rarely
    press against the ceiling on these problems — so asserting on a run would be
    hunting for a seed that happens to notice, which is a guard that stops guarding
    the day the seed changes. Saturation is what the parameter *means*, so that is
    what this asserts.
    """
    from server.engine.themes import Themespace

    async def saturation() -> float:
        meta = await load_metadata_from_db(db_session)
        themespace = Themespace(meta)
        cluster = themespace.clusters[0]
        theme = cluster.themes[0]
        theme.activation = 0
        for _ in range(40):
            themespace.boost_theme(
                cluster.theme_type, cluster.dimension, theme.relation, 100.0
            )
        return theme.activation

    assert await saturation() == 100

    await _set_param(db_session, "max_theme_activation", "40")

    assert await saturation() == 40


async def test_the_activity_measure_reads_both_of_its_parameters(db_session):
    """Direction 2, at the mechanism, for the two constants `get_activity` used.

    `%expiration-period%` and `%num-youngest-structures%` (`workspace.ss:30-31`) are
    the whole of the activity calculation, and the second does not move any sampled
    run on its own — the progress-watcher only asks whether activity is above zero,
    which stays true either way. The number it computes is the observable, so the
    guard is on that.
    """
    from server.engine.runner import EngineRunner

    meta = await load_metadata_from_db(db_session)
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)
    runner.run_mcat(max_steps=600)
    workspace = runner.ctx.workspace
    at = runner.ctx.codelet_count

    shipped = workspace.get_activity(at, meta)

    await _set_param(db_session, "num_youngest_structures", "50")
    widened = await load_metadata_from_db(db_session)
    assert workspace.get_activity(at, widened) != shipped

    await _set_param(db_session, "num_youngest_structures", "3")
    await _set_param(db_session, "expiration_period", "5000")
    stretched = await load_metadata_from_db(db_session)
    assert workspace.get_activity(at, stretched) != shipped


async def test_the_reminding_threshold_reaches_the_memory_from_the_database(db_session):
    """Direction 1 and 2 for `distance_threshold`, at the seam that was broken.

    `EpisodicMemory.find_remindings` has always taken a threshold and
    `tests/seed_unit/test_episodic_memory.py` already covers what different values do
    to it. What no test covered is the *caller*: the reminding site in the
    `report_answer` builtin invoked it with no threshold at all, so the memory fell
    back to its own literal 5.0 and `%distance-threshold%` (`memory.ss:488`) was
    unreachable however the database was edited.

    So the observable is the argument, not the outcome — recording what the engine
    hands the memory is what distinguishes "the parameter is wired" from "the memory
    has a sensible default".
    """
    from server.engine.runner import EngineRunner

    async def threshold_used() -> float | None:
        meta = await load_metadata_from_db(db_session)
        runner = EngineRunner(meta)
        runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)

        seen: list[float] = []
        original = runner.ctx.memory.find_remindings

        def recording(new_desc, distance_threshold=5.0, meta=None):
            seen.append(distance_threshold)
            return original(new_desc, distance_threshold, meta=meta)

        runner.ctx.memory.find_remindings = recording
        runner.run_mcat(max_steps=20_000)
        return seen[0] if seen else None

    assert await threshold_used() == 5.0

    await _set_param(db_session, "distance_threshold", "40")

    assert await threshold_used() == 40


async def test_the_activation_ceiling_binds_everywhere_it_is_written(db_session):
    """Direction 2 for `max_activation`, plus the check that catches a half-wiring.

    The ceiling was written down in eight places — the object graph's flush, the jump
    target, and the flush and jump in each of the three backends — while
    `max_activation` was read at exactly one site that only set initial descriptions.

    Asserting only "the run changed" would have passed with most of those still at
    100: moving the jump window alone changes a run. So the guard also asserts that no
    node finishes above the ceiling, which is what the parameter *means* and what a
    surviving literal violates.
    """
    from server.engine.runner import EngineRunner

    db_meta = await load_metadata_from_db(db_session)
    shipped = run_outcome(db_meta)

    await _set_param(db_session, "max_activation", "80")
    lowered = await load_metadata_from_db(db_session)

    runner = EngineRunner(lowered)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)
    runner.run_mcat(max_steps=20_000)
    workspace = runner.ctx.workspace
    changed = (
        runner.status,
        workspace.answer_string.text if workspace.answer_string else None,
        runner.ctx.codelet_count,
    )

    assert changed != shipped
    peak = max(node.activation for node in runner.ctx.slipnet.nodes.values())
    assert peak <= 80, f"a node reached {peak} under a ceiling of 80"


async def test_activations_stay_floats_whatever_the_parameter_says(db_session):
    """The parameters load as `int`; a node's activation is annotated `float`.

    `ActivationParams.from_metadata` coerces, and this is where that is held. An `int`
    reaching `self.activation = max_activation` would make a node's activation an int
    — which is invisible in arithmetic, since `100 == 100.0`, and visible in a
    state-graph snapshot and in what MLX does with a weak-typed scalar.
    """
    from server.engine.runner import EngineRunner

    await _set_param(db_session, "max_activation", "80")
    meta = await load_metadata_from_db(db_session)

    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=PROBLEM_SEED)
    runner.run_mcat(max_steps=2_000)

    kinds = {type(n.activation).__name__ for n in runner.ctx.slipnet.nodes.values()}
    assert kinds == {"float"}, kinds


async def test_changing_the_workspace_jolt_changes_the_run(db_session):
    """Direction 2 for `workspace_activation`.

    The jolt a codelet pours into a concept it touches is what holds the relevant
    concepts up against decay, and it was a bare `100.0` on the engine's hottest
    activation path with the parameter read nowhere at all.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await _set_param(db_session, "workspace_activation", "40")

    assert run_outcome(await load_metadata_from_db(db_session)) != shipped


async def test_changing_the_full_activation_threshold_changes_the_run(db_session):
    """Direction 2 for `full_activation_threshold`.

    It gates top-down posting and bounds the probabilistic jump's window. The
    parameter was read at one site — the top-down posting loop — while the jump window
    in the object graph and all three backends used the literal 50.
    """
    shipped = run_outcome(await load_metadata_from_db(db_session))

    await _set_param(db_session, "full_activation_threshold", "90")

    assert run_outcome(await load_metadata_from_db(db_session)) != shipped
