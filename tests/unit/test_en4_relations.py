"""EN4: relations come from the ``theme_relations`` table, not from node names.

* G5: the relation nodes found through ``slipnet.relation`` are the nodes the old literals
  named; ``answer.description_dimension`` gives the five answer-description dimensions in
  today's order;
* the bridge-type spellings (B3), the ``diff`` abstractness (from data) and the `None`-label
  hazard (A R02);
* G9: with a relation's row removed, or its node removed, a run is built and stepped on the
  demo problems with no exception.
"""

from __future__ import annotations

import copy
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.roles import absent
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet, opposite_node
from server.engine.themes import Themespace, relation_name_for_label
from tests.support.standard_names import RELATION_DIFFERENT
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
#: Today's literals, recorded for the identity comparison (G5).
RELATION_NODES = {
    "identity": "plato-identity",
    "opposite": "plato-opposite",
    "successor": "plato-successor",
    "predecessor": "plato-predecessor",
}
ANSWER_DIMENSIONS_TODAY = (
    "plato-alphabetic-position-category",
    "plato-string-position-category",
    "plato-direction-category",
    "plato-group-category",
    "plato-bond-facet",
)


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


@pytest.fixture(scope="module")
def slipnet(meta):
    return Slipnet.from_metadata(meta)


# --- G5 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("relation", sorted(RELATION_NODES))
def test_a_relation_is_the_node_the_old_literal_named(slipnet, relation) -> None:
    assert slipnet.relation(relation) is slipnet.nodes[RELATION_NODES[relation]]
    assert slipnet.nodes[RELATION_NODES[relation]].relation == relation
    assert relation_name_for_label(slipnet.nodes[RELATION_NODES[relation]]) == relation


def test_diff_has_no_node_and_an_unlabelled_link_is_diff(slipnet) -> None:
    assert not slipnet.relation(RELATION_DIFFERENT)
    assert relation_name_for_label(None) == RELATION_DIFFERENT
    assert relation_name_for_label(slipnet.nodes["plato-sameness"]) == RELATION_DIFFERENT


def test_the_answer_description_dimensions_keep_todays_order(slipnet) -> None:
    got = tuple(n.name for n in slipnet.roles.answer_description_dimension)
    assert got == ANSWER_DIMENSIONS_TODAY


def test_get_related_node_by_relation_name_equals_by_node(slipnet) -> None:
    for name in ("plato-succgrp", "plato-predgrp", "plato-right", "plato-left", "plato-leftmost"):
        node = slipnet.nodes[name]
        assert node.get_related_node("opposite") is node.get_related_node(
            slipnet.nodes["plato-opposite"]
        )
        assert node.get_related_node("identity") is node


# --- B3 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["top", "top-bridge", "top_bridge"])
def test_every_top_spelling_is_the_top_bridge_theme_type(spelling, meta) -> None:
    v = meta.vocabulary
    assert Themespace(meta).theme_type_for_bridge_type(spelling) == v.theme_type_top_bridge


def test_the_other_bridge_types_and_unknown_spellings(meta) -> None:
    v = meta.vocabulary
    themespace = Themespace(meta)
    assert themespace.theme_type_for_bridge_type("bottom-bridge") == v.theme_type_bottom_bridge
    assert themespace.theme_type_for_bridge_type("vertical") == v.theme_type_vertical_bridge
    assert themespace.theme_type_for_bridge_type("sideways") == "sideways"


# --- the diff abstractness ---------------------------------------------------------------


def test_abstractness_comes_from_the_theme_relations_rows(meta) -> None:
    from dataclasses import replace

    from server.engine.answers import _relation_abstractness, _theme_abstractness

    assert _relation_abstractness("identity", meta) == 0.0
    assert _relation_abstractness("diff", meta) == 50.0
    depth = meta.slipnet_node_specs["plato-opposite"].conceptual_depth
    assert _relation_abstractness("opposite", meta) == float(depth)
    # an edited row is read, not a constant
    rows = tuple(
        replace(r, abstractness=70) if r.name == "diff" else r for r in meta.theme_relations
    )
    edited = replace(meta, theme_relations=rows)
    assert _relation_abstractness("diff", edited) == 70.0
    # no row at all: the coefficient
    bare = replace(meta, theme_relations=())
    assert _relation_abstractness("diff", bare) == meta.formula_coefficients[
        "theme_relation_default_abstractness"
    ]
    assert _theme_abstractness("plato-direction-category", "diff", meta) == round(
        (meta.slipnet_node_specs["plato-direction-category"].conceptual_depth + 50.0) / 2.0
    )


# --- absence ----------------------------------------------------------------------------


def _without_row(relation: str) -> rc.Reduced:
    r = rc.standard()
    r.documents["theme_relations.json"] = [
        row for row in r.documents["theme_relations.json"] if row["name"] != relation
    ]
    return r


@pytest.mark.parametrize("relation", sorted(RELATION_NODES))
def test_a_missing_row_makes_the_relation_unavailable(relation) -> None:
    s = Slipnet.from_metadata(rc.provider(_without_row(relation)))
    token = s.relation(relation)
    assert not token
    assert token is absent("relation." + relation)
    assert s.nodes[RELATION_NODES[relation]].relation is None
    assert relation_name_for_label(s.nodes[RELATION_NODES[relation]]) == RELATION_DIFFERENT
    # the other relations are untouched
    for other in set(RELATION_NODES) - {relation}:
        assert s.relation(other)


@pytest.mark.parametrize("relation", sorted(RELATION_NODES))
def test_a_removed_relation_node_makes_the_relation_unavailable(relation) -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed(RELATION_NODES[relation])))
    assert not s.relation(relation)
    assert RELATION_NODES[relation] not in s.nodes


def test_without_opposite_a_flip_is_the_identity_and_no_node_is_misread() -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-opposite")))
    right = s.nodes["plato-right"]
    assert opposite_node(right) is right
    assert right.get_related_node("opposite") is None
    # a missing (None) label is never the absent opposite
    assert None is not s.relation("opposite")
    assert not s.relation("opposite")


def test_without_identity_a_node_against_itself_has_no_label() -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-identity")))
    node = s.nodes["plato-right"]
    assert s.get_label(node, node) is None


def test_the_clamp_pin_of_an_opposite_theme_needs_the_opposite_relation(slipnet) -> None:
    from server.engine.trace import get_associated_concept_pattern

    pattern = {
        "type": "vertical_bridge",
        "entries": [
            {"dimension": "plato-direction-category", "relation": "opposite", "activation": 100.0}
        ],
    }
    with_it = get_associated_concept_pattern(pattern, slipnet)["entries"]
    assert {"node": "plato-opposite", "activation": 100.0} in with_it
    bare = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-opposite")))
    without = get_associated_concept_pattern(pattern, bare)["entries"]
    assert [e["node"] for e in without] == ["plato-direction-category"]


def test_the_answer_description_dimensions_lose_a_removed_dimension() -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-direction-category")))
    names = [n.name for n in s.roles.answer_description_dimension]
    assert names == [n for n in ANSWER_DIMENSIONS_TODAY if n != "plato-direction-category"]


# --- G9 ---------------------------------------------------------------------------------

G9_STEPS = 150


def _step(provider, problem, seed=1, steps=G9_STEPS) -> None:
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break


def _demo_problems():
    triples, _ = gb.demo_problems()
    return triples


@pytest.mark.slow
@pytest.mark.parametrize("relation", sorted(RELATION_NODES))
def test_g9_relation_row_missing_runs_on_every_demo_problem(relation) -> None:
    provider = rc.provider(_without_row(relation))
    for problem in _demo_problems():
        _step(provider, problem)


@pytest.mark.slow
@pytest.mark.parametrize("relation", sorted(RELATION_NODES))
def test_g9_relation_node_removed_runs(relation) -> None:
    provider = rc.provider(rc.node_removed(RELATION_NODES[relation]))
    for problem in _demo_problems()[:6]:
        _step(provider, problem)
