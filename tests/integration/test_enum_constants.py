"""Verify the engine's names match the rows of seed_data/enums.json.

The run statuses are the engine's own constants and are pinned to their rows.  Every other name
the engine uses is a role, bound to a row (``role`` column): each vocabulary table's rows are the
roles' bindings.  The seed's link types, codelet families and phases, and posting directions cover
every use in the other seed files, and the structure of ``enums.json`` is fixed.
"""

import json
import os

import pytest

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def enums_data():
    with open(os.path.join(SEED_DIR, "enums.json")) as f:
        return json.load(f)


def _names(enums_data, table):
    """Extract the set of name values from an enum table in the seed data."""
    return {row["name"] for row in enums_data[table]}


# ── Run statuses ──

def test_run_status_constants_match_seed(enums_data):
    from server.engine.runner import (
        STATUS_INITIALIZED, STATUS_RUNNING, STATUS_PAUSED,
        STATUS_ANSWER_FOUND, STATUS_HALTED, STATUS_GAVE_UP,
    )
    expected = _names(enums_data, "run_statuses")
    constants = {
        STATUS_INITIALIZED, STATUS_RUNNING, STATUS_PAUSED,
        STATUS_ANSWER_FOUND, STATUS_HALTED, STATUS_GAVE_UP,
    }
    assert constants == expected


# ── The vocabulary: every enum table the engine names rows of ──
#
# The engine holds no constant for any of these names (``tests/architecture/test_vocabulary_literals.py``
# fails on one).  Each table's rows carry a ``role`` that binds one to a concept the engine owns,
# and the provider resolves the bindings once (``meta.vocabulary_bindings``).  These tests pin the
# seed rows: the old pin of the engine's constants against the rows, now stated on the bindings.

#: The tables whose rows were equal, as a set of names, to the engine's constants before the
#: vocabulary was read from the database: every row of each is bound to a role.
BOUND_ENTIRELY = (
    "event_types", "bridge_types", "bridge_orientations", "clause_types", "rule_types",
    "theme_types", "proposal_levels", "string_kinds", "rule_scopes", "failure_kinds",
    "clamp_types", "posting_directions",
)


@pytest.fixture(scope="module")
def bindings():
    from server.engine.metadata import MetadataProvider

    return MetadataProvider.from_standard_configuration(SEED_DIR).vocabulary_bindings


@pytest.mark.parametrize("table", BOUND_ENTIRELY)
def test_every_row_of_a_vocabulary_table_is_bound_to_a_role(enums_data, bindings, table):
    """The seed rows of the table and the rows the roles are bound to are the same names, and the
    roles are the table's own (``roles.VOCABULARY``)."""
    from server.engine.roles import VOCABULARY

    bound = [b for b in bindings if b.table == table]
    assert {b.name for b in bound} == _names(enums_data, table)
    assert {b.role for b in bound} == {s.name for s in VOCABULARY if s.table == table}
    assert len(bound) == len({b.role for b in bound}), "a role is bound twice"


def test_every_event_type_row_is_an_event_type_the_engine_records(enums_data, bindings):
    """A role bound to no row would leave the engine recording events under no configured name, so
    each of the 7 roles has a row.  The 7 are the Scheme's Trace kinds (``make-generic-event`` in
    ``trace.ss``: answer, clamp, concept-activation, concept-mapping, group, rule, snag), and each
    is recorded by the engine and read back by it."""
    roles = {b.role for b in bindings if b.table == "event_types"}
    assert len(roles) == 7 == len(_names(enums_data, "event_types"))
    assert set(_names(enums_data, "event_types")) == {
        "group_built", "rule_built", "answer_found", "snag", "clamp_start",
        "concept_mapping_built", "concept_activation",
    }


def test_theme_relations_are_bound(bindings):
    """The five relations the engine names are rows of ``theme_relations``."""
    assert {b.role for b in bindings if b.table == "theme_relations"} == {
        "theme_relation.identity", "theme_relation.opposite", "theme_relation.successor",
        "theme_relation.predecessor", "theme_relation.diff",
    }


# ── Link types ──

def test_link_types_match_seed(enums_data):
    """Verify seed link_type values cover all types used in slipnet_links.json."""
    with open(os.path.join(SEED_DIR, "slipnet_links.json")) as f:
        links = json.load(f)
    used_types = {lk["link_type"] for lk in links}
    valid_types = _names(enums_data, "link_types")
    assert used_types <= valid_types, f"Unknown link types: {used_types - valid_types}"


# ── Codelet families and phases ──

def test_codelet_families_match_seed(enums_data):
    """Verify seed codelet_families cover all families used in codelet_types.json."""
    with open(os.path.join(SEED_DIR, "codelet_types.json")) as f:
        codelets = json.load(f)
    used_families = {c["family"] for c in codelets}
    valid_families = _names(enums_data, "codelet_families")
    assert used_families <= valid_families, f"Unknown families: {used_families - valid_families}"


def test_codelet_phases_match_seed(enums_data):
    """Verify seed codelet_phases cover all phases used in codelet_types.json."""
    with open(os.path.join(SEED_DIR, "codelet_types.json")) as f:
        codelets = json.load(f)
    used_phases = {c["phase"] for c in codelets}
    valid_phases = _names(enums_data, "codelet_phases")
    assert used_phases <= valid_phases, f"Unknown phases: {used_phases - valid_phases}"


# ── Posting directions ──

def test_posting_directions_match_seed(enums_data):
    """Verify seed posting_directions cover all directions used in posting_rules.json."""
    with open(os.path.join(SEED_DIR, "posting_rules.json")) as f:
        data = json.load(f)
    used_dirs = {pr["direction"] for pr in data.get("posting_rules", [])}
    valid_dirs = _names(enums_data, "posting_directions")
    assert used_dirs <= valid_dirs, f"Unknown directions: {used_dirs - valid_dirs}"


# ── Param value types ──

def test_param_value_types_match_seed(enums_data):
    valid_types = _names(enums_data, "param_value_types")
    assert {"int", "float", "bool", "string", "json", "rational"} <= valid_types


# ── Seed data structure ──

def test_all_enum_tables_present(enums_data):
    """Verify enums.json contains every enum table of the registry (17: the 12 of the first
    vocabulary, and the string kinds, rule scopes, failure kinds, clamp types and progress
    focuses stage 4 added) and ``link_types``, which the change API addresses and which is
    therefore no longer an enum table (the file still holds its five Standard rows)."""
    from server.services.config_registry import ENUM_REGISTRY

    expected_tables = {
        "run_statuses", "event_types", "bridge_types", "bridge_orientations",
        "clause_types", "rule_types", "theme_types", "proposal_levels",
        "link_types", "codelet_families", "codelet_phases",
        "posting_directions", "param_value_types",
        "string_kinds", "rule_scopes", "failure_kinds", "clamp_types", "progress_focuses",
    }
    assert set(enums_data.keys()) == expected_tables == set(ENUM_REGISTRY) | {"link_types"}
    assert len(expected_tables) == 18 and len(ENUM_REGISTRY) == 17


def test_enum_rows_have_required_fields(enums_data):
    """Every enum row must have name, display_label, sort_order, description."""
    for table_name, rows in enums_data.items():
        assert len(rows) > 0, f"Table '{table_name}' is empty"
        for row in rows:
            assert "name" in row, f"Missing 'name' in {table_name}"
            assert "display_label" in row, f"Missing 'display_label' in {table_name}"
            assert "sort_order" in row, f"Missing 'sort_order' in {table_name}"
            assert "description" in row, f"Missing 'description' in {table_name}"


def test_enum_names_are_unique_within_tables(enums_data):
    """Names must be unique within each enum table."""
    for table_name, rows in enums_data.items():
        names = [r["name"] for r in rows]
        assert len(names) == len(set(names)), f"Duplicate names in {table_name}"
