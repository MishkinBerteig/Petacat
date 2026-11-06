"""The seeder writes every configuration table, and the suite keeps no seeder of its own.

The database is loaded from the seed files only when it is empty (C2); there is no
re-seed, so these guard the single load path.  They need SQLAlchemy, which the venv
provides via `pip install -e ".[dev]"`.
"""

import pytest
from tests.support import standard_names

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")


def test_configuration_tables_exclude_runtime_tables_and_help_topics():
    """``server.models.run`` shares the declarative ``Base`` with the metadata models, so
    the set of configuration tables must come from the metadata module alone."""
    from server.services.standard_configuration import configuration_table_names

    names = configuration_table_names()
    runtime = {
        "runs", "trace_events", "answer_descriptions",
        "snag_descriptions", "training_mode_sessions", "training_mode_session_problems", "training_mode_session_runs",
        "training_memory_merges", "training_mode_session_memory_snapshots", "configuration_state",
    }
    assert not (names & runtime), f"runtime tables counted as configuration: {names & runtime}"
    assert "help_topics" not in names, "help topics are upserted, not part of the load"
    assert "slipnet_link_defs" in names
    assert "codelet_type_defs" in names


def test_every_trace_event_type_the_engine_emits_is_declared():
    """Every event type the engine records is a row of ``event_types``.

    ``trace_events.event_type`` records the name the run gave the event (it is not a foreign key,
    so a recorded trace survives a rename or removal), but the Admin view lists the event types
    from ``enums.json``: an event type added in code and not there is a role bound to no row —
    which is how ``concept_activation`` first showed up.
    """
    import json
    import os

    from server.engine.metadata import MetadataProvider
    from server.engine.roles import VOCABULARY

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    with open(os.path.join(seed_dir, "enums.json")) as f:
        declared = {row["name"] for row in json.load(f)["event_types"]}

    # The engine records the event types it has a role for (``event_type.*``); the
    # configuration binds each to a row, and that row must exist in ``event_types``.
    meta = MetadataProvider.from_standard_configuration(seed_dir)
    roles = {s.name for s in VOCABULARY if s.name.startswith("event_type.")}
    bound = {b.role: b.name for b in meta.vocabulary_bindings if b.role in roles}
    assert set(bound) == roles, f"event-type roles bound to no row: {sorted(roles - set(bound))}"
    missing = set(bound.values()) - declared
    assert not missing, f"event types missing from enums.json: {sorted(missing)}"


async def test_the_seeder_writes_every_configuration_table():
    """A configuration table that is never written is how a whole seed file goes missing.

    ``posting_rules`` was once on the clear list and on ``BULK_SEED_FILES`` and no code
    path ever inserted a row, so the engine had zero posting rules in production and
    seventeen everywhere else.  The invariant reads both halves off the schema, so a table
    added later is covered the day it is added.
    """
    import os

    from server.services.standard_configuration import (
        configuration_table_names,
        standard_load_ops,
    )

    # The seeder hands its rows to the journal layer as ops (C6); the ops name the tables
    # it addresses, so no database is needed to answer which ones.
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    written = {op["table"] for op in standard_load_ops(seed_dir)}

    expected = set(configuration_table_names())

    missing = expected - written
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
        f"{sorted(constructed)}. Seed through server.services.standard_configuration instead, so the "
        "suite and the application are seeded by the same code."
    )


def test_nothing_fingerprints_the_seed_files_or_reseeds():
    """The database is the source of truth: no fingerprint, no re-seed, no delete path."""
    from server.services import standard_configuration as seeding

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
