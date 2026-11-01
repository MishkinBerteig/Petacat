"""EN8: rules, justify and the rule English read roles, relations and templates.

* G5: every role ``rules.py``, ``justify.py`` and ``rule_english.py`` read is held by the node
  the old literal named; ``rule.dimension_order`` as the ordinal-built tuple orders dimensions as
  the old list did; the stored rule-signature token is unchanged;
* the rule English grammar is the ``rule_english`` template group: an edited template changes the
  sentence, a missing one omits its text;
* the draws of ``abstract_change_descriptions`` come before any role is resolved (``rng`` state);
* B10: the three blanket ``except Exception`` blocks of ``justify.py`` are gone;
* G9: with each role (or relation) the three files read unbound, a run (and a justify run) is built
  and stepped on demo problems with no exception.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from server.engine import rules
from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.rule_english import transcribe_rule_to_english_lines
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.role_table import SINGLE_ROLES

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
RECORDING = Path(__file__).resolve().parents[1] / "seed_unit" / "role_identity_today.json"

#: The roles these three files read.
ROLES_READ = (
    "dimension.direction", "dimension.group_category", "dimension.alphabetic_position",
    "dimension.letter_category", "dimension.length", "dimension.object_category",
    "dimension.string_position", "dimension.bond_facet", "dimension.bond_category",
    "position.whole", "position.single", "direction.left", "direction.right",
    "object.letter", "object.group", "group_category.sameness",
)
RELATIONS_READ = {"identity": "plato-identity", "opposite": "plato-opposite"}


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


@pytest.fixture(scope="module")
def slipnet(meta):
    return Slipnet.from_metadata(meta)


# --- G5 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES_READ)
def test_the_role_is_held_by_the_node_the_old_literal_named(slipnet, role) -> None:
    node = slipnet.nodes[SINGLE_ROLES[role]]
    assert getattr(slipnet.roles, role.replace(".", "_")) is node
    assert role in node.roles


def test_the_dimension_order_tuple_sorts_as_the_old_list_did(slipnet) -> None:
    old = json.loads(RECORDING.read_text())["ordered_lists_in_engine_code"]["rule.dimension_order"]
    order = slipnet.roles.rule_dimension_order
    assert [n.name for n in order] == old
    assert [rules._dim_sort_key(slipnet.nodes[name], order) for name in old] == list(range(len(old)))
    # a dimension that is not listed sorts last
    assert rules._dim_sort_key(slipnet.nodes["plato-bond-category"], order) == len(old)
    assert rules._dim_sort_key(None, order) == len(old)


def test_the_dimension_order_without_a_member_keeps_the_others_in_order() -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-length")))
    order = s.roles.rule_dimension_order
    assert len(order) == 7
    assert [rules._dim_sort_key(n, order) for n in order] == list(range(7))


def test_the_rule_signature_token_is_unchanged(slipnet) -> None:
    group = slipnet.nodes["plato-group"]
    token = "plato-group|string"
    assert rules._descriptor_key(group) == token
    assert rules._descriptor_key("string") == token
    assert rules._descriptor_key(slipnet.nodes["plato-letter"]) == "plato-letter"
    assert rules._descriptor_key(None) is None
    # the caller in answer_comparison asks by the group node's name
    from server.engine.answer_comparison import _collapsed_group_token

    assert _collapsed_group_token("plato-group") == token


def test_a_node_that_plays_no_role_is_matched_by_none(slipnet) -> None:
    from server.engine.slipnet import holds_role

    assert not holds_role(None, "dimension.length")
    assert not holds_role("string", "object.group")
    assert not holds_role(slipnet.nodes["plato-a"], "dimension.length")
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-length")))
    assert not s.roles.dimension_length
    assert not holds_role(s.roles.dimension_length, "dimension.length")


# --- the rule English templates ----------------------------------------------------------


def _english(meta, problem=("abc", "abd", "xyz"), steps=1200, seed=1) -> list[str]:
    """The English of every rule a run builds."""
    runner = EngineRunner(meta)
    lines: list[str] = []
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break
        for ev in runner.ctx.trace.events:
            for structure in ev.structures:
                if isinstance(structure, rules.Rule):
                    lines.extend(transcribe_rule_to_english_lines(structure, meta))
    return lines


def test_the_grammar_is_the_rule_english_template_group(meta) -> None:
    baseline = _english(meta)
    assert any(line.startswith("Change ") for line in baseline)
    edited = dict(meta.commentary_templates)
    section = dict(edited["rule_english"])
    section["change"] = "Alter {dimension} of {scope}{object} into {to}"
    edited["rule_english"] = section
    changed = _english(replace(meta, commentary_templates=edited))
    assert any(line.startswith("Alter ") for line in changed)
    assert not any(line.startswith("Change ") and " of " in line for line in changed)


def test_a_missing_template_omits_its_text_and_raises_nothing(meta) -> None:
    edited = {k: v for k, v in meta.commentary_templates.items() if k != "rule_english"}
    lines = _english(replace(meta, commentary_templates=edited))
    assert all(isinstance(line, str) for line in lines)
    assert not any(line.startswith("Change ") for line in lines)


# --- rng ---------------------------------------------------------------------------------


def _first_reversal_call(meta):
    """Run ``abc -> cba`` until ``abstract_change_descriptions`` is handed a cluster whose
    direction reversal it would abstract; return the call's arguments."""
    seen: dict = {}
    real = rules.abstract_change_descriptions

    def spy(bridges, rng=None, slipnet=None):
        if "args" not in seen and rules._count_strposctgy_opposite_slippages(bridges) == 2:
            seen["args"] = (list(bridges), slipnet)
        return real(bridges, rng=rng, slipnet=slipnet)

    rules.abstract_change_descriptions = spy
    try:
        for seed in range(1, 12):
            runner = EngineRunner(meta)
            with use_backend(gb.BACKEND):
                runner.init_mcat("abc", "cba", "mrrjjj", seed=seed, rng=RNG(seed))
                for _ in range(4000):
                    if "args" in seen or runner.step_mcat().codelet_type is None:
                        break
            if "args" in seen:
                return seen["args"]
    finally:
        rules.abstract_change_descriptions = real
    return None


def test_the_draws_of_abstract_change_descriptions_do_not_depend_on_a_role(meta) -> None:
    """Roles are resolved after the draw, so a configuration without the direction dimension
    (or the opposite relation) draws exactly as many times: it only abstracts no reversal."""
    found = _first_reversal_call(meta)
    if found is None:
        pytest.skip("no reversal cluster arose in the sampled runs")
    bridges, slipnet = found
    reduced = {
        "direction": Slipnet.from_metadata(rc.provider(rc.role_unbound("dimension.direction"))),
        "opposite": Slipnet.from_metadata(rc.provider(rc.node_removed("plato-opposite"))),
    }
    full_rng = RNG(5)
    full = rules.abstract_change_descriptions(bridges, rng=full_rng, slipnet=slipnet)
    for name, s in reduced.items():
        rng = RNG(5)
        got = rules.abstract_change_descriptions(bridges, rng=rng, slipnet=s)
        assert rng.get_state() == full_rng.get_state(), name
        assert len(got) <= len(full), name


def test_resolving_roles_draws_nothing(meta, slipnet) -> None:
    rng = RNG(3)
    state = rng.get_state()
    rules._dimension_order(slipnet)
    rules._dim_sort_key(slipnet.nodes["plato-length"], slipnet.roles.rule_dimension_order)
    rules._descriptor_key(slipnet.nodes["plato-group"])
    assert rng.get_state() == state


# --- B10 ---------------------------------------------------------------------------------


def test_justify_has_no_blanket_except() -> None:
    tree = ast.parse((Path(rules.__file__).with_name("justify.py")).read_text())
    blanket = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler)
        and (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in ("Exception", "BaseException")))
    ]
    assert blanket == []


# --- G9 ----------------------------------------------------------------------------------

G9_STEPS = 900
#: Justify mode starts after a few hundred codelets, once an answer stands.
G9_JUSTIFY_STEPS = 2500


def _step(provider, problem, answer=None, seed=1, steps=G9_STEPS) -> None:
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, answer=answer, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break


def _problems():
    triples, justify = gb.demo_problems()
    return triples, justify


@pytest.mark.slow
@pytest.mark.parametrize("role", ROLES_READ)
def test_g9_role_unbound_builds_rules_and_justifies(role) -> None:
    provider = rc.provider(rc.role_unbound(role))
    triples, justify = _problems()
    for problem in triples[:8]:
        _step(provider, problem)
    for problem, answer in justify[:2]:
        _step(provider, problem, answer=answer, steps=G9_JUSTIFY_STEPS)


@pytest.mark.slow
@pytest.mark.parametrize("name", range(8))
def test_g9_each_rule_dimension_order_member_unbound(name) -> None:
    provider = rc.provider(rc.role_unbound("rule.dimension_order", name))
    triples, justify = _problems()
    for problem in triples[:6]:
        _step(provider, problem)
    for problem, answer in justify[:2]:
        _step(provider, problem, answer=answer, steps=G9_JUSTIFY_STEPS)


@pytest.mark.slow
@pytest.mark.parametrize(
    "relation",
    ["opposite", "identity"],
)
def test_g9_relation_node_removed_builds_rules_and_justifies(relation) -> None:
    provider = rc.provider(rc.node_removed(RELATIONS_READ[relation]))
    triples, justify = _problems()
    for problem in triples[:8]:
        _step(provider, problem)
    for problem, answer in justify[:2]:
        _step(provider, problem, answer=answer, steps=G9_JUSTIFY_STEPS)


@pytest.mark.slow
@pytest.mark.parametrize("relation", sorted(RELATIONS_READ))
def test_g9_relation_row_missing_builds_rules_and_justifies(relation) -> None:
    reduced = rc.standard()
    reduced.documents["theme_relations.json"] = [
        row for row in reduced.documents["theme_relations.json"] if row["name"] != relation
    ]
    provider = rc.provider(reduced)
    triples, justify = _problems()
    for problem in triples[:8]:
        _step(provider, problem)
    for problem, answer in justify[:2]:
        _step(provider, problem, answer=answer, steps=G9_JUSTIFY_STEPS)
