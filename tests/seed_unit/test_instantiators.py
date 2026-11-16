"""The v2.0 Base's three instantiators: ``adjacent-instantiator``, ``category-instantiator`` and ``instance-of-instantiator``.

``consolidator`` proposes a change to the run's Slipnet; the instantiator posted for it takes everything held for
its link, checks the evidence, and builds it with ``apply_ops`` (the run's own Slipnet has the link at once and the
session is told) or fizzles (what it took is dropped).  The evidence of ``adjacent-instantiator`` is a built
``adjacent`` bond in the Workspace between two single symbols whose letter-category descriptions are the link's
``from`` and ``to``, ``from`` on the left; of the other two, that the Workspace still holds the symbol and the run's
Slipnet still lacks the link.  None of them draws a random number.
"""

from __future__ import annotations

import pytest

from server.engine.bonds import Bond
from server.engine.coderack import Codelet
from server.engine.codelet_dsl.builtins import links_of
from server.engine.groups import Group
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve
from tests.support.instantiators import INSTANTIATORS, on_rack, run_instantiators

pytestmark = pytest.mark.numeric_matrix

ONE, TWO, THREE = "plato-cp-0031", "plato-cp-0032", "plato-cp-0033"
ADJ, LC = "plato-adjacent", "plato-letter-category"


def node_op(ch):
    return {"op": "add_node", "name": "plato-cp-%04x" % ord(ch), "fields": {
        "short_name": ch, "glyph": ch, "plain_name": ch, "article_an": False, "conceptual_depth": 10}}


@pytest.fixture(scope="module")
def document():
    doc = tb.resolve_base().document
    ops, _ = resolve(doc, {"ops": [node_op(c) for c in "123"]})
    return cd.apply_resolved(doc, ops)


@pytest.fixture(scope="module")
def meta(document):
    return cd.provider(document)


def runner_for(meta, problem=("12", "12", "123")):
    r = EngineRunner(meta)
    r.init_mcat(*problem, None, seed=1)
    return r


def string_of(r, name="initial"):
    return {"initial": r.ctx.workspace.initial_string, "modified": r.ctx.workspace.modified_string,
            "target": r.ctx.workspace.target_string}[name]


def bond_between(r, string, i, j, category=ADJ):
    nodes = r.ctx.slipnet.nodes
    letters = [o for o in string.objects if o.left_string_pos in (i, j)]
    a, b = sorted(letters, key=lambda o: o.left_string_pos)
    if i > j:
        a, b = b, a
    lc = r.ctx.slipnet.roles.dimension_letter_category
    bond = Bond(a, b, nodes[category], lc, a.get_descriptor_for(lc), b.get_descriptor_for(lc),
                nodes["plato-right"] if i < j else nodes["plato-left"])
    string.add_bond(bond)
    return bond


def notice(r, name):
    """Run ``consolidator`` on the node and leave the instantiators it posted on the Coderack."""
    r._execute_codelet(Codelet("consolidator", 50, arguments={"slipnode": r.ctx.slipnet.nodes[name]}))


def ops_of(r, kind):
    return [p for p in r.ctx.proposals if p["op"] == kind]


def link_of(r, frm, to, kind="adjacent", label=ADJ):
    return r.ctx.slipnet.find_link(frm, to, kind, label)


def types_on_rack(r):
    return [c.codelet_type for c in on_rack(r)]


# -- the posting: consolidator posts one instantiator for each link --------------------------------------------------


def test_consolidator_posts_one_instantiator_for_each_link_it_proposes_however_often_it_notices(meta):
    r = runner_for(meta)
    bond_between(r, string_of(r), 0, 1)
    for _ in range(4):
        notice(r, ONE)
        notice(r, TWO)
    assert types_on_rack(r).count("adjacent-instantiator") == 1  # the pair 1 to 2, noticed eight times
    assert len(r.ctx.held_proposals) == 1
    (entry,) = r.ctx.held_proposals.values()
    assert [o["op"] for o in entry["ops"]] == ["add_link", "scale"]
    assert entry["ops"][1]["factor"] == pytest.approx((1 - 0.0625 / 90) ** 8)
    # nothing was built, so only the counts are recorded for the next turn
    assert {p["op"] for p in r.ctx.proposals} == {"adjust"} and link_of(r, ONE, TWO) is None


def test_each_instantiator_is_posted_at_the_high_urgency_level_whatever_urgency_consolidator_ran_at(document):
    for urgency in (7, 31):
        r = runner_for(over_threshold(document), ("12", "12", "12"))
        bond_between(r, string_of(r), 0, 1)
        r._execute_codelet(Codelet("consolidator", urgency, arguments={"slipnode": r.ctx.slipnet.nodes[ONE]}))
        posted = on_rack(r)
        assert sorted(c.codelet_type for c in posted) == [
            "adjacent-instantiator", "category-instantiator", "instance-of-instantiator"]
        assert [c.urgency for c in posted] == [r.ctx.meta.get_urgency("high")] * 3


def test_consolidator_is_posted_in_metacats_top_down_form(meta):
    rule = next(r for r in meta.posting_rules if r.codelet_type == "consolidator")
    assert (rule.urgency_formula, rule.posting_formula) == ("conceptual_depth * activation / 100", "average_unhappiness / 100")


# -- adjacent-instantiator --------------------------------------------------------------------------------------------


def test_adjacent_instantiator_builds_when_the_bond_is_still_in_the_workspace(meta):
    r = runner_for(meta)
    bond_between(r, string_of(r), 0, 1)
    notice(r, ONE)
    notice(r, TWO)
    draws = r.ctx.rng.call_count
    assert run_instantiators(r)  # it ran
    assert r.ctx.rng.call_count == draws
    link = link_of(r, ONE, TWO)
    assert link is not None and link.label_node is r.ctx.slipnet.nodes[ADJ] and link in r.ctx.slipnet.nodes[ONE].lateral_links
    assert link.link_length() == pytest.approx(90 * (1 - 0.0625 / 90))  # (L / r) * r ** 2 = L r
    assert [o["from"] for o in ops_of(r, "add_link")] == [ONE] and len(ops_of(r, "scale")) == 1
    assert r.ctx.held_proposals == {}
    # the reverse link was never proposed
    assert link_of(r, TWO, ONE) is None


def test_adjacent_instantiator_fizzles_when_the_bond_was_broken_and_drops_what_it_took(meta):
    r = runner_for(meta)
    s = string_of(r)
    bond = bond_between(r, s, 0, 1)
    notice(r, ONE)
    s.remove_bond(bond)  # the bond is gone by the time the instantiator runs
    draws = r.ctx.rng.call_count
    run_instantiators(r)
    assert r.ctx.rng.call_count == draws
    assert link_of(r, ONE, TWO) is None and r.ctx.held_proposals == {}
    assert ops_of(r, "add_link") == [] and ops_of(r, "scale") == []
    assert len(ops_of(r, "adjust")) == 1  # the count still goes to the next turn


def test_adjacent_instantiator_fizzles_when_no_bond_joins_those_two_symbols_in_that_order(meta):
    r = runner_for(meta, ("123", "123", "123"))
    bond_between(r, string_of(r), 1, 2)  # 2 to 3 only
    notice(r, TWO)
    (entry,) = r.ctx.held_proposals.values()
    # the evidence is for the link 2 to 3; a bond of the opposite direction (right to left) is not the same
    # link: it reads left to right too, so the link is the same.  Ask for 3 to 2 and it fizzles.
    reverse = [dict(o) for o in entry["ops"]]
    reverse[0].update({"from": THREE, "to": TWO})
    reverse[1]["key"] = {**reverse[1]["key"], "from_node": THREE, "to_node": TWO}
    from server.engine.codelet_dsl.builtins import propose_ops

    propose_ops(r.ctx, reverse, built_by="adjacent-instantiator", urgency=70)
    run_instantiators(r)
    assert link_of(r, THREE, TWO) is None and link_of(r, TWO, THREE) is not None


def test_adjacent_instantiator_fizzles_for_a_bond_with_a_group_at_an_end_and_for_another_category(meta):
    # the consolidator proposes nothing for a successor bond; a held proposal for one would fizzle too
    r = runner_for(meta)
    bond_between(r, string_of(r), 0, 1, "plato-successor")
    notice(r, ONE)
    assert r.ctx.held_proposals == {}
    # a proposal for the pair, with only a successor bond joining it in the Workspace
    from server.engine.codelet_dsl.builtins import propose_ops

    ratio = 1 - 0.0625 / 90
    propose_ops(r.ctx, [
        {"op": "add_link", "from": ONE, "to": TWO, "type": "adjacent", "label": ADJ, "fixed": True, "length": 90 / ratio},
        {"op": "scale", "table": "slipnet_link_defs", "key": {
            "from_node": ONE, "to_node": TWO, "link_type": "adjacent", "label_node": ADJ},
         "field": "link_length", "factor": ratio}], built_by="adjacent-instantiator", urgency=70)
    run_instantiators(r)
    assert link_of(r, ONE, TWO) is None and r.ctx.held_proposals == {}


def test_adjacent_instantiator_builds_a_link_the_run_already_has_by_scaling_it(meta, document):
    base = cd.provider(document)
    ops, _ = resolve(document, {"ops": [{"op": "add_link", "from": ONE, "to": TWO, "type": "adjacent", "label": ADJ,
                                         "fixed": True, "length": 50}]})
    started = cd.provider(cd.apply_resolved(document, ops))
    r = runner_for(started)
    assert link_of(r, ONE, TWO).link_length() == 50
    bond_between(r, string_of(r), 0, 1)
    notice(r, ONE)
    run_instantiators(r)
    assert link_of(r, ONE, TWO).link_length() == pytest.approx(50 * (1 - 0.0625 / 90))
    assert base is not started


def adjacent_proposal_with(meta, *other_links):
    """A run holding a built adjacent bond 1 to 2 and the given other links already in its Slipnet; consolidator proposes the
    pair's adjacent link and its instantiator runs.  Returns the runner."""
    from server.engine.codelet_dsl.builtins import apply_ops

    r = runner_for(meta)
    bond_between(r, string_of(r), 0, 1)
    if other_links:
        apply_ops(r.ctx, list(other_links))
    notice(r, ONE)
    run_instantiators(r, "adjacent-instantiator")
    return r


def other(frm, to, kind="lateral", label="plato-successor", length=40):
    op = {"op": "add_link", "from": frm, "to": to, "type": kind, "fixed": True, "length": length}
    if label:
        op["label"] = label
    return op


def test_adjacent_instantiator_fizzles_when_another_link_joins_the_pair_in_either_direction(meta):
    for links in ([other(ONE, TWO)], [other(TWO, ONE)], [other(ONE, TWO, "category", None)],
                  [other(TWO, ONE, "category", None)], [other(ONE, TWO, "instance", None)],
                  [other(ONE, TWO, "property", None)]):
        r = adjacent_proposal_with(meta, *links)
        assert link_of(r, ONE, TWO) is None and link_of(r, TWO, ONE) is None, links
        assert [p for p in r.ctx.proposals if p["op"] in ("scale",)] == [], links
        assert all(p["type"] != "adjacent" for p in r.ctx.proposals if p["op"] == "add_link"), links
        assert r.ctx.held_proposals == {}, links  # what it took is dropped


def test_adjacent_instantiator_still_builds_and_strengthens_when_only_its_own_link_joins_the_pair(meta):
    own = other(ONE, TWO, "adjacent", ADJ, 50)
    r = adjacent_proposal_with(meta, own)
    assert link_of(r, ONE, TWO).link_length() == pytest.approx(50 * (1 - 0.0625 / 90))
    # an unrelated link of another pair does not matter
    r = adjacent_proposal_with(meta, other(ONE, THREE), other(THREE, TWO))
    assert link_of(r, ONE, TWO) is not None


def test_a_link_that_arrives_between_the_first_build_and_a_later_noticing_stops_the_later_build(meta):
    from server.engine.codelet_dsl.builtins import apply_ops

    r = runner_for(meta)
    bond_between(r, string_of(r), 0, 1)
    notice(r, ONE)
    run_instantiators(r, "adjacent-instantiator")
    built = link_of(r, ONE, TWO).link_length()
    apply_ops(r.ctx, [other(TWO, ONE, "category", None)])
    notice(r, ONE)
    run_instantiators(r, "adjacent-instantiator")
    assert link_of(r, ONE, TWO).link_length() == built  # the second noticing's change was dropped


# -- category-instantiator and instance-of-instantiator ----------------------------------------------------------------


def over_threshold(document, node=ONE, count=40):
    ops, _ = resolve(document, {"ops": [{"op": "adjust", "table": "slipnet_node_defs", "key": {"name": node},
                                         "field": "noticings", "by": count}]})
    return cd.provider(cd.apply_resolved(document, ops))


def test_category_and_instance_of_instantiators_build_when_the_symbol_is_there_and_the_link_is_missing(document):
    r = runner_for(over_threshold(document), ("1", "1", "1"))
    notice(r, ONE)
    assert sorted(types_on_rack(r)) == ["category-instantiator", "instance-of-instantiator"]
    draws = r.ctx.rng.call_count
    assert len(run_instantiators(r)) == 2
    assert r.ctx.rng.call_count == draws
    one, lc = r.ctx.slipnet.nodes[ONE], r.ctx.slipnet.nodes[LC]
    assert [l.to_node for l in links_of(r.ctx, one, "category")] == [lc] and one.category is lc
    assert [l.link_length() for l in links_of(r.ctx, one, "category")] == [20]
    assert [l.link_length() for l in links_of(r.ctx, lc, "instance") if l.to_node is one] == [97]
    assert [(o["from"], o["to"], o["type"], o["length"]) for o in ops_of(r, "add_link")] == [
        (ONE, LC, "category", 20), (LC, ONE, "instance", 97)]
    assert r.ctx.held_proposals == {}


def test_they_fizzle_when_the_symbol_is_no_longer_in_the_workspace(document):
    r = runner_for(over_threshold(document), ("1", "1", "1"))
    notice(r, ONE)
    for s in (string_of(r, "initial"), string_of(r, "modified"), string_of(r, "target")):
        for o in list(s.objects):
            lc = r.ctx.slipnet.roles.dimension_letter_category
            o.descriptions = [d for d in o.descriptions if d.description_type is not lc]  # no longer described
    run_instantiators(r)
    one, lc = r.ctx.slipnet.nodes[ONE], r.ctx.slipnet.nodes[LC]
    assert one.category_links == [] and not any(l.to_node is one for l in lc.instance_links)
    assert ops_of(r, "add_link") == [] and r.ctx.held_proposals == {}


def test_they_fizzle_when_the_run_already_has_the_link(document):
    r = runner_for(over_threshold(document), ("1", "1", "1"))
    notice(r, ONE)
    from server.engine.codelet_dsl.builtins import apply_ops

    # another instantiator (or a seed link) has made both links in the meantime
    apply_ops(r.ctx, [{"op": "add_link", "from": ONE, "to": LC, "type": "category", "fixed": True, "length": 20},
                      {"op": "add_link", "from": LC, "to": ONE, "type": "instance", "fixed": True, "length": 97}])
    recorded = list(r.ctx.proposals)
    run_instantiators(r)
    assert r.ctx.proposals == recorded and r.ctx.held_proposals == {}
    assert len(r.ctx.slipnet.nodes[ONE].category_links) == 1


def test_a_seed_letter_has_both_links_so_nothing_is_proposed_for_it(document):
    r = runner_for(over_threshold(document, "plato-a", 99), ("a", "a", "a"))
    notice(r, "plato-a")
    assert [t for t in types_on_rack(r) if t in INSTANTIATORS] == [] and r.ctx.held_proposals == {}


def test_the_instantiators_have_no_posting_rule_and_are_meta_builders(meta):
    for name in INSTANTIATORS:
        spec = meta.codelet_specs[name]
        assert (spec.family, spec.phase) == ("meta", "builder")
        assert all(rule.codelet_type != name for rule in meta.posting_rules)
