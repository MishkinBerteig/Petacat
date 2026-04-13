"""Verify engine string constants match the values in seed_data/enums.json.

These tests ensure that every Python constant used in place of the former
Enum classes has a corresponding entry in the seed data that gets loaded
into the DB lookup tables.
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


# ── Event types ──

def test_event_type_constants_match_seed(enums_data):
    from server.engine.trace import (
        BOND_BUILT, BOND_BROKEN, GROUP_BUILT, GROUP_BROKEN,
        BRIDGE_BUILT, BRIDGE_BROKEN, RULE_BUILT, RULE_BROKEN,
        DESCRIPTION_BUILT, ANSWER_FOUND, SNAG, CLAMP_START,
        CLAMP_END, JOOTSING, THEME_ACTIVATED, CONCEPT_MAPPING_BUILT,
    )
    expected = _names(enums_data, "event_types")
    constants = {
        BOND_BUILT, BOND_BROKEN, GROUP_BUILT, GROUP_BROKEN,
        BRIDGE_BUILT, BRIDGE_BROKEN, RULE_BUILT, RULE_BROKEN,
        DESCRIPTION_BUILT, ANSWER_FOUND, SNAG, CLAMP_START,
        CLAMP_END, JOOTSING, THEME_ACTIVATED, CONCEPT_MAPPING_BUILT,
    }
    assert constants == expected


# ── Bridge types ──

def test_bridge_type_constants_match_seed(enums_data):
    from server.engine.bridges import BRIDGE_TOP, BRIDGE_BOTTOM, BRIDGE_VERTICAL
    expected = _names(enums_data, "bridge_types")
    assert {BRIDGE_TOP, BRIDGE_BOTTOM, BRIDGE_VERTICAL} == expected


# ── Bridge orientations ──

def test_bridge_orientation_constants_match_seed(enums_data):
    from server.engine.bridges import ORIENTATION_HORIZONTAL, ORIENTATION_VERTICAL
    expected = _names(enums_data, "bridge_orientations")
    assert {ORIENTATION_HORIZONTAL, ORIENTATION_VERTICAL} == expected


# ── Clause types ──

def test_clause_type_constants_match_seed(enums_data):
    from server.engine.rules import CLAUSE_INTRINSIC, CLAUSE_EXTRINSIC, CLAUSE_VERBATIM
    expected = _names(enums_data, "clause_types")
    assert {CLAUSE_INTRINSIC, CLAUSE_EXTRINSIC, CLAUSE_VERBATIM} == expected


# ── Rule types ──

def test_rule_type_constants_match_seed(enums_data):
    from server.engine.rules import RULE_TOP, RULE_BOTTOM
    expected = _names(enums_data, "rule_types")
    assert {RULE_TOP, RULE_BOTTOM} == expected


# ── Theme types ──

def test_theme_type_constants_match_seed(enums_data):
    from server.engine.themes import (
        THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE, ALL_THEME_TYPES,
    )
    expected = _names(enums_data, "theme_types")
    assert {THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE} == expected
    assert set(ALL_THEME_TYPES) == expected


# ── Proposal levels ──

def test_proposal_level_constants_match_seed(enums_data):
    from server.engine.workspace_structures import WorkspaceStructure
    expected = _names(enums_data, "proposal_levels")
    assert {WorkspaceStructure.PROPOSED, WorkspaceStructure.EVALUATED, WorkspaceStructure.BUILT} == expected


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
    assert {"int", "float", "bool", "string", "json"} <= valid_types


# ── Demo modes ──

def test_demo_modes_match_seed(enums_data):
    """Verify seed demo_modes cover all modes used in demo_problems.json."""
    with open(os.path.join(SEED_DIR, "demo_problems.json")) as f:
        demos = json.load(f)
    used_modes = {d["mode"] for d in demos}
    valid_modes = _names(enums_data, "demo_modes")
    assert used_modes <= valid_modes, f"Unknown modes: {used_modes - valid_modes}"


# ── Seed data structure ──

def test_all_14_enum_tables_present(enums_data):
    """Verify enums.json contains all 14 expected tables."""
    expected_tables = {
        "run_statuses", "event_types", "bridge_types", "bridge_orientations",
        "clause_types", "rule_types", "theme_types", "proposal_levels",
        "link_types", "codelet_families", "codelet_phases",
        "posting_directions", "param_value_types", "demo_modes",
    }
    assert set(enums_data.keys()) == expected_tables


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
