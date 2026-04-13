"""Tests for metadata seeding — verifies seed_data/ JSON files are well-formed
and the MetadataProvider round-trip works correctly.

These tests don't require Postgres — they use from_seed_data().
"""

import os
import json
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_all_seed_files_valid_json():
    """Every JSON file in seed_data/ should parse without errors."""
    for filename in os.listdir(SEED_DIR):
        if filename.endswith(".json"):
            path = os.path.join(SEED_DIR, filename)
            with open(path) as f:
                data = json.load(f)
            assert data is not None, f"{filename} parsed to None"


def test_node_count(meta):
    assert len(meta.slipnet_node_specs) == 59


def test_link_count(meta):
    assert len(meta.slipnet_link_specs) > 200


def test_codelet_count(meta):
    assert len(meta.codelet_specs) == 27


def test_all_codelets_have_execute_body(meta):
    """Every codelet type should have non-empty execute_body."""
    for name, spec in meta.codelet_specs.items():
        assert spec.execute_body.strip(), f"Codelet '{name}' has empty execute_body"


def test_all_codelets_compile(meta):
    """Every codelet execute_body should compile as valid Python."""
    interpreter = CodeletInterpreter(builtins=get_builtins())
    for name, spec in meta.codelet_specs.items():
        compiled = interpreter.compile(spec.execute_body, name=name)
        assert not compiled.is_empty, f"Codelet '{name}' failed to compile"


def test_urgency_levels_complete(meta):
    expected = {"extremely_low", "very_low", "low", "medium", "high", "very_high", "extremely_high"}
    assert set(meta.urgency_levels.keys()) == expected


def test_theme_dimensions_count(meta):
    assert len(meta.theme_dimensions) == 9


def test_demo_problems_have_seeds(meta):
    for demo in meta.demo_problems:
        assert demo.seed > 0, f"Demo '{demo.name}' has no seed"


def test_slipnet_layout_matches_nodes(meta):
    """Every node in the layout should exist in slipnet_node_specs."""
    for node_name in meta.slipnet_layout:
        assert node_name in meta.slipnet_node_specs, f"Layout node '{node_name}' not in node specs"


def test_codelet_patterns_reference_valid_types(meta):
    """Every codelet type in patterns should exist in codelet_specs."""
    for pattern_name, entries in meta.codelet_patterns.items():
        for codelet_type, urgency in entries:
            assert codelet_type in meta.codelet_specs, (
                f"Pattern '{pattern_name}' references unknown type '{codelet_type}'"
            )


def test_posting_rules_reference_valid_types(meta):
    """Every codelet type in posting rules should exist in codelet_specs."""
    for rule in meta.posting_rules:
        assert rule.codelet_type in meta.codelet_specs, (
            f"Posting rule references unknown type '{rule.codelet_type}'"
        )


def test_formula_coefficients_not_empty(meta):
    assert len(meta.formula_coefficients) > 50
