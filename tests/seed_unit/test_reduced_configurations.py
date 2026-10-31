"""The reduced-configuration fixture generator (EN0; the engine is not run on these yet).

Well-formedness of every reduced configuration: nothing left that names a removed node or
codelet type (code that cannot be rewritten is reported as ``dangling``, not left silently),
the cascade removed what the plan's rules (3.12.5) say, and a provider loads from each.
"""

from __future__ import annotations

import pytest

from tests.support import configuration_cascade as cascade
from tests.support import reduced_configurations as rc
from tests.support.role_table import (
    CODELET_ROLES, LETTER_NODES, NUMBER_NODES, ORDERED_ROLES, SINGLE_ROLES,
)


def _assert_well_formed(r: rc.Reduced) -> None:
    left = cascade.dangling_node_references(r.documents, r.removed_nodes)
    assert not left, f"{r.name}: still names a removed node: {left[:5]}"
    left = cascade.dangling_codelet_references(r.documents, r.removed_codelet_types)
    assert not left, f"{r.name}: still names a removed codelet type: {left[:5]}"
    names = set(cascade.node_names(r.documents))
    for link in r.documents["slipnet_links.json"]:
        for end in ("from_node", "to_node"):
            assert link[end] in names, f"{r.name}: link end {link[end]} is not a node"
        assert link.get("label_node") in names | {None}
    assert set(r.documents["slipnet_layout.json"]["node_positions"]) <= names
    for row in r.documents["theme_dimensions.json"]["dimensions"]:
        assert row["slipnet_node"] in names
    ctypes = set(cascade.codelet_type_names(r.documents))
    for rule in r.documents["posting_rules.json"]["posting_rules"]:
        assert rule["codelet_type"] in ctypes
        assert set(rule.get("triggering_slipnodes") or []) <= names
    for entries in r.documents["posting_rules.json"]["codelet_patterns"].values():
        assert {e[0] for e in entries} <= ctypes


def test_standard_documents_are_well_formed_and_unchanged() -> None:
    r = rc.standard()
    _assert_well_formed(r)
    assert len(cascade.node_names(r.documents)) == 59
    assert r.report.cascaded == []


def test_loading_documents_gives_independent_copies() -> None:
    a, b = cascade.load_documents(), cascade.load_documents()
    cascade.remove_node(a, "plato-a")
    assert "plato-a" in cascade.node_names(b)


def test_node_removal_cascades_what_the_plan_lists() -> None:
    r = rc.node_removed("plato-opposite")
    _assert_well_formed(r)
    assert "plato-opposite" not in cascade.node_names(r.documents)
    # the opposite sliplinks are labelled by the relation, so they go with it
    assert r.report.count("slipnet_links") >= 2
    assert any("label" in cause for t, _, cause in r.report.cascaded if t == "slipnet_links")
    assert "plato-opposite" not in r.documents["engine_params.json"]["intrinsic_link_lengths"]
    assert "plato-opposite" not in r.documents["slipnet_layout.json"]["node_positions"]


def test_dimension_removal_reaches_every_table_that_names_it() -> None:
    r = rc.node_removed("plato-string-position-category")
    _assert_well_formed(r)
    params = r.documents["engine_params.json"]
    assert "plato-string-position-category" not in params["top_down_slipnodes"]
    assert "plato-string-position-category" not in params["initially_clamped_slipnodes"]
    assert "plato-string-position-category" not in params["theme_dimension_labels"]
    assert "plato-string-position-category" not in params["rule_english_dimension_phrases"]
    tables = {t for t, _, _ in r.report.cascaded}
    assert {"theme_dimensions", "theme_dimensions.answer_description_theme_types",
            "engine_params.top_down_slipnodes", "engine_params.initially_clamped_slipnodes"} <= tables
    # code that names it cannot be rewritten: it is listed, not hidden
    assert r.report.dangling


def test_trigger_removal() -> None:
    r = rc.node_removed("plato-left")
    _assert_well_formed(r)
    assert "posting_rules.triggering_slipnodes" in {t for t, _, _ in r.report.cascaded}


def test_removing_a_missing_node_is_refused() -> None:
    with pytest.raises(KeyError):
        rc.node_removed("plato-not-a-node")


def test_letter_removal_reports_the_demos_that_use_the_letter() -> None:
    r = rc.letter_removed("q")
    _assert_well_formed(r)
    assert r.removed_nodes == ["plato-q"]
    assert any(t == "demo_problems" for t, _, _ in r.report.dangling)


def test_a_d_w_z_alphabet_keeps_exactly_those_letters() -> None:
    r = rc.a_d_w_z()
    _assert_well_formed(r)
    kept = {n for n in cascade.node_names(r.documents) if n in LETTER_NODES}
    assert kept == {f"plato-{c}" for c in "abcdwxyz"}
    assert len(cascade.node_names(r.documents)) == 59 - 18
    # the chain is broken between d and w: no successor link joins them
    assert not any(l["from_node"] == "plato-d" and l["to_node"] == "plato-w"
                   for l in r.documents["slipnet_links.json"])


def test_ladder_with_a_gap_leaves_four_numbers() -> None:
    r = rc.ladder_with_gap()
    _assert_well_formed(r)
    kept = [n for n in cascade.node_names(r.documents) if n in NUMBER_NODES]
    assert kept == ["plato-one", "plato-two", "plato-four", "plato-five"]


def test_codelet_role_removal_cascades_rules_and_patterns() -> None:
    r = rc.role_unbound("evaluator.bond")
    _assert_well_formed(r)
    assert "bond-evaluator" not in cascade.codelet_type_names(r.documents)
    tables = {t for t, _, _ in r.report.cascaded}
    assert {"codelet_types", "codelet_patterns"} <= tables


def test_initial_codelet_type_removal_edits_the_parameter_list() -> None:
    docs = cascade.load_documents()
    report = cascade.remove_codelet_type(docs, "bottom-up-bond-scout")
    assert "engine_params.initial_codelet_types" in {t for t, _, _ in report.cascaded}
    assert "bottom-up-bond-scout" not in docs["engine_params.json"]["initial_codelet_types"]


def test_every_role_removal_is_well_formed() -> None:
    count = 0
    for r in rc.all_single_role_removals():
        _assert_well_formed(r)
        count += 1
    assert count == len(SINGLE_ROLES) + sum(len(v) for v in ORDERED_ROLES.values()) + len(CODELET_ROLES)


def test_every_node_removal_is_well_formed() -> None:
    count = 0
    for r in rc.all_node_removals():
        _assert_well_formed(r)
        count += 1
    assert count == 59


def test_a_provider_loads_from_a_reduced_configuration() -> None:
    meta = rc.provider(rc.a_d_w_z())
    assert len(meta.slipnet_node_specs) == 59 - 18
    assert "plato-e" not in meta.slipnet_node_specs
    assert len(rc.provider(rc.standard()).slipnet_node_specs) == 59
