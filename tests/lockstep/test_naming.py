"""Canonical names (spec §4, DECISIONS.md): plain values, then every kind of object a
finished run holds."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.lockstep.faithful import run_faithful
from tests.lockstep.naming import name_of
from tests.lockstep.tracing_rng import TracingRNG

pytestmark = pytest.mark.lockstep


# -- plain values -----------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [
    (3, "3"), (3.0, "3"), (0.5, "0.5"), (-2, "-2"), (1e-05, "1e-05"),
    (True, "true"), (False, "false"), (None, "-"),
    ("letter-category", "letter-category"),
    ((1, 2), "(1,2)"), ([True, "x", 0.25], "(true,x,0.25)"),
    (("top", ("a", "b")), "(top,(a,b))"),
])
def test_plain_values_are_named_by_value(value, expected):
    assert name_of(value) == expected


def test_an_unnameable_thing_becomes_a_question_mark_name_instead_of_crashing():
    class Odd:
        def __repr__(self):
            raise RuntimeError("no repr either")

    assert name_of(Odd()) == "?odd:unprintable"
    assert name_of(object()).startswith("?object:")
    assert name_of({"a": 1}).startswith("?dict:")


# -- objects, from a real run -------------------------------------------------------


@pytest.fixture(scope="module")
def finished():
    outcome = run_faithful(("abc", "abd", "xyz"), 1, 700, TracingRNG(1))
    assert outcome.runner is not None
    return outcome.runner.ctx


def test_letters_strings_and_slipnet_nodes_in_the_opening_state(finished):
    ws = finished.workspace
    assert [name_of(s) for s in ws.all_strings][:3] == ["string(i)", "string(m)", "string(t)"]
    letters = [name_of(o) for o in ws.all_objects if o.span == 1]
    assert letters[:3] == ["i.0", "i.1", "i.2"]
    assert {"m.0", "t.2"} <= set(letters)
    assert name_of(finished.slipnet.nodes["plato-successor"]) == "successor"
    assert name_of(finished.slipnet.nodes["plato-letter-category"]) == "letter-category"
    assert not any(name_of(n).startswith("plato-") for n in finished.slipnet.nodes.values())


def test_descriptions_are_named_with_object_type_and_descriptor(finished):
    names = {name_of(d) for o in finished.workspace.all_objects for d in o.descriptions}
    assert "desc(i.0,letter-category,a)" in names
    assert "desc(t.2,string-position-category,rightmost)" in names


PATTERNS = {
    "bond": re.compile(r"^bond\([imta]\.\d+,[imta]\.\d+,[a-z-]+,[a-z-]+\)$"),
    "bridge": re.compile(r"^bridge\((top|bottom|vertical),.+,.+\)$"),
    "group": re.compile(r"^group\([imta]\.\d+-\d+,[a-z-]+,[a-z-]+,[a-z-]+\)$"),
    "cm": re.compile(r"^cm\([a-z-]+,[a-z0-9-]+,[a-z-]+,[a-z0-9-]+\)$"),
}


def test_every_structure_the_run_built_has_a_canonical_name(finished):
    ws = finished.workspace
    seen = {kind: [] for kind in PATTERNS}
    for s in ws.all_strings:
        seen["bond"] += [name_of(b) for b in s.bonds]
        seen["group"] += [name_of(g) for g in s.groups]
    for b in ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges:
        seen["bridge"].append(name_of(b))
        seen["cm"] += [name_of(cm) for cm in b.concept_mappings]
    assert seen["bond"] and seen["bridge"], "the run must have built something to name"
    for kind, names in seen.items():
        for name in names:
            assert PATTERNS[kind].match(name), f"{kind} name {name!r}"
            assert "?" not in name and "plato" not in name


def test_a_directionless_bond_lists_its_ends_left_to_right(finished):
    from server.engine.bonds import Bond

    sameness = [b for s in finished.workspace.all_strings for b in s.bonds
                if b.direction is None]
    if not sameness:  # abc/abd/xyz need not build one; build the reversed case by hand
        letters = finished.workspace.initial_string.objects
        node = finished.slipnet.nodes["plato-sameness"]
        facet = finished.slipnet.nodes["plato-letter-category"]
        bond = Bond(letters[2], letters[1], node, facet, None, None, None)
        assert name_of(bond) == "bond(i.1,i.2,sameness,letter-category)"
    else:
        for b in sameness:
            a, z = name_of(b).split("(")[1].split(",")[:2]
            assert int(a.split(".")[1]) < int(z.split(".")[1])


def test_codelets_bins_and_themes(finished):
    from server.engine.coderack import Codelet
    from server.engine.themes import Theme

    scout = Codelet("bottom-up-bond-scout", 10)
    assert name_of(scout) == "bottom-up-bond-scout"
    node = finished.slipnet.nodes["plato-successor"]
    assert name_of(Codelet("top-down-bond-scout:category", 10,
                           arguments={"slipnode": node})) == \
        "top-down-bond-scout:category(successor)"
    bond = next(b for s in finished.workspace.all_strings for b in s.bonds)
    assert name_of(Codelet("bond-evaluator", 5, arguments={"structure": bond})) == \
        f"bond-evaluator({name_of(bond)})"
    assert name_of(finished.coderack.bins[3]) == "bin3"
    assert name_of(Theme("top_bridge", "plato-letter-category", "identity")) == \
        "theme(top-bridge,letter-category,identity)"
    assert name_of(Theme("vertical_bridge", "plato-length", "diff")) == \
        "theme(vertical-bridge,length,different)"
    assert name_of(Theme("top_bridge", "plato-length", None)) == \
        "theme(top-bridge,length,different)"


def test_rules_are_written_in_metacats_clause_grammar():
    from server.engine.rules import Rule, RuleChange, RuleClause

    class N:  # the two things a slipnet node must have to be a node
        conceptual_depth = 0

        def __init__(self, name):
            self.name = name

    letter_cat, successor, rightmost = N("plato-letter-category"), N("plato-successor"), N("plato-rightmost")
    letter, pos_cat = N("plato-letter"), N("plato-string-position-category")
    clause = RuleClause(
        "intrinsic", object_description=(letter, pos_cat, rightmost),
        changes=[RuleChange(dimension=letter_cat, relation=successor, referent="self")],
    )
    rule = Rule("top", [clause])
    assert name_of(rule) == (
        "rule(top,((intrinsic ((letter string-position-category rightmost)) "
        "((self letter-category successor)))))"
    )
    ext = RuleClause("extrinsic", extrinsic_objects=[(letter, pos_cat, rightmost)] * 2,
                     dimensions=[letter_cat])
    assert name_of(Rule("bottom", [ext])) == (
        "rule(bottom,((extrinsic ((letter string-position-category rightmost) "
        "(letter string-position-category rightmost)) (letter-category))))"
    )
    assert name_of(Rule("top", [])) == "rule(top,())"


# -- the opening state against Metacat's names ------------------------------------

OPENING = Path(__file__).parent / "metacat" / "opening-names.abc-abd-xyz.json"


@pytest.mark.skipif(not OPENING.exists(), reason="Metacat's opening-state names not recorded")
def test_the_opening_state_names_match_metacats():
    """Spec §10.2: both engines name every letter, description and slipnet node in the
    opening state, and the two lists must be identical.  (Metacat's list leaves out
    the three ``string(...)`` names, which are checked above.)"""
    from server.engine.numeric.backend import use_backend
    from server.engine.runner import EngineRunner
    from tests.lockstep.faithful import _metadata

    runner = EngineRunner(_metadata())
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, rng=TracingRNG(1))
    ctx = runner.ctx
    names = {name_of(n) for n in ctx.slipnet.nodes.values()}
    for o in ctx.workspace.all_objects:
        names.add(name_of(o))
        names.update(name_of(d) for d in o.descriptions)
    assert names == set(json.loads(OPENING.read_text()))
