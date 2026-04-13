"""Tests for MetadataProvider loading from seed_data/."""

import os
import pytest
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_loads_slipnet_nodes(meta):
    assert len(meta.slipnet_node_specs) == 59
    assert "plato-a" in meta.slipnet_node_specs
    assert "plato-successor" in meta.slipnet_node_specs
    assert meta.slipnet_node_specs["plato-a"].conceptual_depth == 10
    assert meta.slipnet_node_specs["plato-sameness"].conceptual_depth == 80


def test_loads_slipnet_links(meta):
    assert len(meta.slipnet_link_specs) > 200


def test_loads_codelet_types(meta):
    assert len(meta.codelet_specs) == 27
    assert "bottom-up-bond-scout" in meta.codelet_specs
    assert "breaker" in meta.codelet_specs
    spec = meta.get_codelet_spec("bottom-up-bond-scout")
    assert spec.family == "bond"
    assert spec.phase == "scout"
    assert spec.default_urgency == 35


def test_loads_urgency_levels(meta):
    assert meta.get_urgency("extremely_low") == 7
    assert meta.get_urgency("low") == 35
    assert meta.get_urgency("extremely_high") == 91


def test_loads_engine_params(meta):
    assert meta.get_param("max_activation") == 100
    assert meta.get_param("update_cycle_length") == 15
    assert meta.get_param("max_coderack_size") == 100
    assert meta.get_param("full_activation_threshold") == 50


def test_loads_formula_coefficients(meta):
    assert meta.get_formula_coeff("temp_exponent_base") == 0.5
    assert meta.get_formula_coeff("temp_exponent_scale") == 30.0
    assert meta.get_formula_coeff("unhappiness_weight") == 70.0


def test_loads_posting_rules(meta):
    assert len(meta.posting_rules) > 0
    bond_scout_rules = [
        r for r in meta.posting_rules if r.codelet_type == "bottom-up-bond-scout"
    ]
    assert len(bond_scout_rules) == 1


def test_loads_demo_problems(meta):
    assert len(meta.demo_problems) > 0
    run7 = [d for d in meta.demo_problems if d.name == "run7"]
    assert len(run7) == 1
    assert run7[0].initial == "abc"
    assert run7[0].modified == "abd"
    assert run7[0].target == "xyz"
    assert run7[0].seed == 3852097033


def test_loads_theme_dimensions(meta):
    assert len(meta.theme_dimensions) == 9
    dir_dim = [d for d in meta.theme_dimensions if d.slipnet_node == "plato-direction-category"]
    assert len(dir_dim) == 1
    assert "identity" in dir_dim[0].valid_relations
    assert "opposite" in dir_dim[0].valid_relations


def test_loads_slipnet_layout(meta):
    assert len(meta.slipnet_layout) == 59
    assert meta.slipnet_layout["plato-a"] == (2, 0)
    assert meta.slipnet_layout["plato-identity"] == (1, 0)


def test_loads_codelet_patterns(meta):
    assert "rule-codelet-pattern" in meta.codelet_patterns
    rule_pattern = meta.codelet_patterns["rule-codelet-pattern"]
    assert len(rule_pattern) == 3
    assert rule_pattern[0] == ("rule-scout", 77)


def test_get_param_default(meta):
    assert meta.get_param("nonexistent", 42) == 42


def test_fixed_length_false_loaded_correctly(meta):
    """Links with explicit fixed_length: false should load as fixed_length=False."""
    # Lateral links between letters have fixed_length: false in the JSON
    letter_links = [
        lk for lk in meta.slipnet_link_specs
        if lk.from_node == "plato-a" and lk.to_node == "plato-b"
        and lk.link_type == "lateral"
    ]
    assert len(letter_links) == 1
    assert letter_links[0].fixed_length is False
    assert letter_links[0].label_node == "plato-successor"


def test_fixed_length_with_link_length_loaded_correctly(meta):
    """Links with explicit link_length (no fixed_length key) should be fixed."""
    instance_links = [
        lk for lk in meta.slipnet_link_specs
        if lk.from_node == "plato-letter-category" and lk.to_node == "plato-a"
    ]
    assert len(instance_links) == 1
    assert instance_links[0].fixed_length is True
    assert instance_links[0].link_length == 97


def test_spreading_activation_threshold_param(meta):
    """Spreading activation threshold should default to 100."""
    assert meta.get_param("spreading_activation_threshold") == 100


def test_loads_enum_values(meta):
    """MetadataProvider should load enum_values from enums.json."""
    assert len(meta.enum_values) == 14
    assert "run_statuses" in meta.enum_values
    assert "event_types" in meta.enum_values
    assert "bridge_types" in meta.enum_values
    assert "proposal_levels" in meta.enum_values
    assert "initialized" in meta.enum_values["run_statuses"]
    assert "bond_built" in meta.enum_values["event_types"]
    assert "top" in meta.enum_values["bridge_types"]
    assert "proposed" in meta.enum_values["proposal_levels"]


def test_enum_values_match_expected_counts(meta):
    """Each enum table should have the expected number of values."""
    assert len(meta.enum_values["run_statuses"]) == 6
    assert len(meta.enum_values["event_types"]) == 16
    assert len(meta.enum_values["bridge_types"]) == 3
    assert len(meta.enum_values["bridge_orientations"]) == 2
    assert len(meta.enum_values["clause_types"]) == 3
    assert len(meta.enum_values["rule_types"]) == 2
    assert len(meta.enum_values["theme_types"]) == 3
    assert len(meta.enum_values["proposal_levels"]) == 3
    assert len(meta.enum_values["link_types"]) == 5
    assert len(meta.enum_values["codelet_families"]) == 8
    assert len(meta.enum_values["codelet_phases"]) == 4
    assert len(meta.enum_values["posting_directions"]) == 3
    assert len(meta.enum_values["param_value_types"]) == 5
    assert len(meta.enum_values["demo_modes"]) == 2
