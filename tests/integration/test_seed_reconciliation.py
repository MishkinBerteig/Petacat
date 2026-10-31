"""The seeder writes every configuration table, and the suite keeps no seeder of its own.

The database is loaded from the seed files only when it is empty (C2); there is no
re-seed, so these guard the single load path.  They need SQLAlchemy, which the venv
provides via `pip install -e ".[dev]"`.
"""

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")


def test_configuration_tables_exclude_runtime_tables_and_help_topics():
    """``server.models.run`` shares the declarative ``Base`` with the metadata models, so
    the set of configuration tables must come from the metadata module alone."""
    from server.services.seeding import configuration_table_names

    names = configuration_table_names()
    runtime = {
        "runs", "trace_events", "cycle_snapshots", "answer_descriptions",
        "snag_descriptions", "trainings", "training_problems", "training_runs",
        "training_memory_merges", "configuration_state",
    }
    assert not (names & runtime), f"runtime tables counted as configuration: {names & runtime}"
    assert "help_topics" not in names, "help topics are upserted, not part of the load"
    assert "slipnet_link_defs" in names
    assert "codelet_type_defs" in names


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


async def test_the_seeder_writes_every_configuration_table():
    """A configuration table that is never written is how a whole seed file goes missing.

    ``posting_rules`` was once on the clear list and on ``BULK_SEED_FILES`` and no code
    path ever inserted a row, so the engine had zero posting rules in production and
    seventeen everywhere else.  The invariant reads both halves off the schema, so a table
    added later is covered the day it is added.
    """
    import os

    from server.services.seeding import (
        configuration_table_names,
        seed_metadata_from_json,
    )

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    session = _RecordingSession()
    await seed_metadata_from_json(session, seed_dir)

    expected = set(configuration_table_names())

    missing = expected - session.written
    assert not missing, (
        "the seeder owns these configuration tables but writes no row into them: "
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


def test_nothing_fingerprints_the_seed_files_or_reseeds():
    """The database is the source of truth: no fingerprint, no re-seed, no delete path."""
    from server.services import seeding

    assert not hasattr(seeding, "SEED_FINGERPRINT_PARAM")
    assert not hasattr(seeding, "seed_data_fingerprint")
    assert not hasattr(seeding, "derived_metadata_tables")


def test_slipnet_node_model_carries_the_descriptor_predicate():
    """The predicate is knowledge about a concept, so the DB mirrors the JSON.

    ``create_all`` never alters an existing table; a database that predates a schema
    change is cleared, not upgraded (C2).
    """
    from server.models.metadata import SlipnetNodeDef

    assert "descriptor_predicate" in SlipnetNodeDef.__table__.columns
