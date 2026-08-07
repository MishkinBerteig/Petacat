"""The DB copy of the metadata must track the seed files without eating runtime data.

These guard the startup reconciliation in ``server.main``.  They need SQLAlchemy,
which the venv provides via `pip install -e ".[dev]"`.
"""

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")


def test_clearing_derived_metadata_never_touches_runtime_tables():
    """``server.models.run`` shares the declarative ``Base`` with the metadata
    models, so walking ``Base.metadata`` wholesale would sweep up a user's runs,
    trace events, snapshots and episodic memory and delete them.
    """
    from server.main import _derived_metadata_tables

    names = {t.name for t in _derived_metadata_tables()}
    runtime = {
        "runs",
        "trace_events",
        "cycle_snapshots",
        "answer_descriptions",
        "snag_descriptions",
    }
    assert not (names & runtime), f"runtime tables would be cleared: {names & runtime}"
    assert "help_topics" not in names, "help topics are upserted, not cleared"
    # And it is actually doing something.
    assert "slipnet_link_defs" in names
    assert "codelet_type_defs" in names


def test_tables_that_runtime_data_points_at_are_protected():
    """``runs.status`` and ``trace_events.event_type`` are foreign keys onto enum
    tables, so those rows cannot be cleared while runs exist — Postgres refuses.
    They are seeded insert-if-missing instead.
    """
    from server.main import _derived_metadata_tables, _protected_enum_tables

    protected = _protected_enum_tables()
    assert {"run_statuses", "event_types"} <= protected

    cleared = {t.name for t in _derived_metadata_tables()}
    assert not (cleared & protected)


def test_every_trace_event_type_the_engine_emits_is_declared():
    """``trace_events.event_type`` is a foreign key onto ``event_types``.

    An event type added in code but not in ``enums.json`` makes persisting that
    event fail with a foreign-key violation at runtime — which is how
    ``concept_activation`` first showed up.
    """
    import json
    import os

    from server.engine import trace as trace_module

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    with open(os.path.join(seed_dir, "enums.json")) as f:
        declared = {row["name"] for row in json.load(f)["event_types"]}

    emitted = {
        value
        for name, value in vars(trace_module).items()
        if name.isupper() and isinstance(value, str) and not name.startswith("_")
    }
    # Only the event-type constants matter; they are exactly the ones the trace
    # records, and each must have an enum row.
    event_types = {
        trace_module.BOND_BUILT, trace_module.BOND_BROKEN,
        trace_module.GROUP_BUILT, trace_module.GROUP_BROKEN,
        trace_module.BRIDGE_BUILT, trace_module.BRIDGE_BROKEN,
        trace_module.RULE_BUILT, trace_module.RULE_BROKEN,
        trace_module.DESCRIPTION_BUILT, trace_module.ANSWER_FOUND,
        trace_module.SNAG, trace_module.CLAMP_START, trace_module.CLAMP_END,
        trace_module.JOOTSING, trace_module.THEME_ACTIVATED,
        trace_module.CONCEPT_MAPPING_BUILT, trace_module.CONCEPT_ACTIVATION,
    }
    assert event_types <= emitted  # sanity: we listed real constants
    missing = event_types - declared
    assert not missing, f"event types missing from enums.json: {sorted(missing)}"


class _RecordingSession:
    """Enough of an ``AsyncSession`` to record what the seeder writes.

    No database: the question is which tables the seeder *addresses*, and running it
    against a recorder answers that without a Postgres and without the answer
    depending on one being seeded a particular way.
    """

    def __init__(self):
        self.written: set[str] = set()

    def add(self, row) -> None:
        self.written.add(type(row).__tablename__)

    async def flush(self) -> None:
        pass

    async def execute(self, _statement):
        class _Result:
            def scalars(self):
                return self

            def all(self):
                return []

        return _Result()


async def test_the_seeder_refills_every_table_it_empties():
    """A cleared table that is never refilled is how a whole seed file goes missing.

    ``_derived_metadata_tables`` is the list startup ``DELETE``s before re-seeding, so
    every name on it is a table the seeder has undertaken to write.  ``posting_rules``
    was on that list and on ``BULK_SEED_FILES`` — cleared on every seed-data change,
    counted in the fingerprint, exposed for editing and export through the admin API —
    and no code path ever inserted a row.  The engine consequently had zero posting
    rules in production and seventeen everywhere else.

    Stated this way the invariant needs no file-to-table mapping to maintain: it reads
    both halves off the schema, so a table added later is covered the day it is added.
    """
    import os

    from server.services.seeding import (
        derived_metadata_tables,
        protected_enum_tables,
        seed_metadata_from_json,
    )

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    session = _RecordingSession()
    await seed_metadata_from_json(session, seed_dir, fingerprint="test")

    emptied = {t.name for t in derived_metadata_tables()}
    # The protected enum tables are never emptied, but they are seeded
    # insert-if-missing, so they are written too and belong in the expectation.
    expected = emptied | protected_enum_tables()

    missing = expected - session.written
    assert not missing, (
        "the seeder empties or owns these tables but writes no row into them: "
        f"{sorted(missing)}"
    )


def test_the_test_suite_does_not_keep_a_seeder_of_its_own():
    """One seeder, so the suite cannot measure an engine production cannot build.

    ``tests/e2e/conftest.py`` grew a second copy of the startup seeding, and the two
    drifted apart in the direction that hides a defect rather than reveals one: the
    copy here wrote ``posting_rules``, production wrote none, and every e2e test
    therefore passed against a configuration the application never had.  Nothing
    contradicted it, because the only place the difference showed was a database
    neither the suite nor the developer looked at.

    The check is on instantiation rather than on imports: the conftest legitimately
    *names* the models for its `drop_all`/`create_all` and cleanup, and what must not
    come back is it constructing rows to insert.
    """
    import ast
    from pathlib import Path

    from server.models import metadata as metadata_models

    model_names = {
        name
        for name in dir(metadata_models)
        if isinstance(getattr(metadata_models, name), type)
        and hasattr(getattr(metadata_models, name), "__tablename__")
    }

    conftest = Path(__file__).resolve().parents[1] / "e2e" / "conftest.py"
    tree = ast.parse(conftest.read_text(encoding="utf-8"))

    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in model_names
    }

    assert not constructed, (
        "tests/e2e/conftest.py constructs metadata rows itself: "
        f"{sorted(constructed)}. Seed through server.services.seeding instead, so the "
        "suite and the application are seeded by the same code."
    )


def test_the_fingerprint_covers_the_seeder_and_not_only_the_seed_files():
    """A fix to the seeder has to reach databases that already exist.

    Startup re-seeds only when the fingerprint moves.  With the digest taken over the
    seed files alone, teaching the seeder to write a table it had been skipping
    changed nothing anywhere: the files were untouched, the fingerprints matched, and
    every existing database kept its empty table.  Hashing this module's source too
    is what makes a code fix take effect on the next restart.
    """
    import os

    from server.services import seeding

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    before = seeding.seed_data_fingerprint(seed_dir)

    original = seeding.__file__
    try:
        # Point the digest at a different file, standing in for an edited seeder.
        seeding.__file__ = os.path.join(seed_dir, "enums.json")
        after = seeding.seed_data_fingerprint(seed_dir)
    finally:
        seeding.__file__ = original

    assert after != before, "the seeder's own source does not move the fingerprint"
    assert seeding.seed_data_fingerprint(seed_dir) == before, "digest is not stable"


def test_slipnet_node_model_carries_the_descriptor_predicate():
    """The predicate is knowledge about a concept, so the DB mirrors the JSON.

    ``create_all`` never alters an existing table, which is why startup also
    reconciles missing columns additively.
    """
    from server.models.metadata import SlipnetNodeDef

    assert "descriptor_predicate" in SlipnetNodeDef.__table__.columns
