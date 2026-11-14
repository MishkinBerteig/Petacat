"""C6: the table registry (configuration plan 3.12.2), built by model introspection."""

from __future__ import annotations

import dataclasses

import pytest

from server.services import config_registry as reg


def test_the_registry_has_every_addressable_table_and_no_enum_or_help_topic():
    assert set(reg.REGISTRY) == {
        "slipnet_node_defs", "slipnet_link_defs", "slipnet_layout", "theme_dimension_defs",
        "theme_relations", "slipnet_node_roles", "codelet_type_defs", "codelet_type_roles",
        "posting_rules", "codelet_pattern_defs", "engine_params", "formula_coefficients",
        "urgency_levels", "demo_problems", "commentary_templates",
        "initial_description_rules", "initial_activation_rules",
        "input_character_ranges", "input_lowering_ranges", "link_types",
    }
    # The 12 enum lookup tables of the first vocabulary (``link_types`` left them: it is addressable
    # by the change API), and the five stage 4 added: the
    # string kinds, rule scopes and failure kinds the engine names, and the clamp types and
    # progress focuses it reads (all of them have a ``name`` key and the four enum columns).
    assert set(reg.ENUM_REGISTRY) == {
        "run_statuses", "event_types", "bridge_types", "bridge_orientations", "clause_types",
        "rule_types", "theme_types", "proposal_levels", "codelet_families",
        "codelet_phases", "posting_directions", "param_value_types",
        "string_kinds", "rule_scopes", "failure_kinds", "clamp_types", "progress_focuses",
    }
    assert len(reg.ENUM_REGISTRY) == 17
    assert "help_topics" not in reg.LAYER_REGISTRY
    assert set(reg.LAYER_REGISTRY) == set(reg.REGISTRY) | set(reg.ENUM_REGISTRY)
    assert set(reg.LAYER_REGISTRY) == set(reg.configuration_table_names())


def test_a_table_spec_is_a_frozen_dataclass_with_the_agreed_fields():
    spec = reg.REGISTRY["slipnet_link_defs"]
    assert dataclasses.is_dataclass(spec)
    assert [f.name for f in dataclasses.fields(spec)] == [
        "name", "model", "key", "order", "code_columns", "json_columns",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "x"  # type: ignore[misc]
    assert spec.key == ("from_node", "to_node", "link_type", "label_node")
    assert spec.order == ("sort_order",)
    assert isinstance(spec.code_columns, frozenset) and isinstance(spec.json_columns, frozenset)


def test_keys_order_code_and_json_columns():
    r = reg.REGISTRY
    assert r["slipnet_node_roles"].key == ("role", "ordinal")
    assert r["posting_rules"].key == ("rule_key",)
    assert r["codelet_pattern_defs"].key == ("pattern_name", "codelet_type")
    assert r["codelet_pattern_defs"].order == ("ordinal",)
    assert r["demo_problems"].order == ()
    assert r["codelet_type_defs"].code_columns == {"execute_body"}
    assert r["slipnet_node_defs"].code_columns == {"descriptor_predicate"}
    assert r["posting_rules"].code_columns == {
        "urgency_formula", "posting_formula", "count_formula", "condition",
    }
    assert r["posting_rules"].json_columns == {"count_values", "triggering_slipnodes"}
    assert r["commentary_templates"].json_columns == {"template_data"}
    assert r["theme_dimension_defs"].json_columns == {"valid_relations"}
    for spec in reg.LAYER_REGISTRY.values():
        columns = set(spec.columns)
        assert set(spec.key) <= columns and set(spec.order) <= columns
        assert spec.code_columns <= columns and spec.json_columns <= columns


def test_a_null_label_is_read_as_the_empty_string_and_the_surrogate_id_is_not_stored():
    spec = reg.REGISTRY["slipnet_link_defs"]
    key = spec.key_of({"from_node": "a", "to_node": "b", "link_type": "t", "label_node": None})
    assert key["label_node"] == ""
    assert spec.key_tuple({"from_node": "a", "to_node": "b", "link_type": "t"}) == ("a", "b", "t", "")
    assert spec.surrogate == "id" and "id" not in spec.stored_columns
    assert reg.REGISTRY["engine_params"].surrogate is None
    assert reg.REGISTRY["slipnet_node_roles"].surrogate is None  # composite key, no id


def test_a_configuration_table_without_a_declared_key_stops_the_registry_building(monkeypatch):
    monkeypatch.delitem(reg._NATURAL_KEYS, "engine_params")
    with pytest.raises(RuntimeError, match="engine_params"):
        reg._build()
