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


def test_slipnet_node_model_carries_the_descriptor_predicate():
    """The predicate is knowledge about a concept, so the DB mirrors the JSON.

    ``create_all`` never alters an existing table, which is why startup also
    reconciles missing columns additively.
    """
    from server.models.metadata import SlipnetNodeDef

    assert "descriptor_predicate" in SlipnetNodeDef.__table__.columns
