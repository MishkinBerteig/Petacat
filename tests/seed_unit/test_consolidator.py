"""The v2.0 Base's ``consolidator``: what one run of the body proposes for one noticing of a symbol.

A run of the body is one noticing of the node that triggered it.  The count goes to the next turn
(``ctx.proposals``); each link is proposed for an instantiator and held, and what an instantiator builds
is recorded in ``ctx.proposals`` too.  The tests build a Workspace by hand (the Base with the nodes of
``1``, ``2`` and ``3``, as a Training Mode Session keeps them), put bonds in it, run the codelet and then the
instantiators it posted (``notice``), and read ``ctx.proposals``; and they land the proposals in a live
configuration the way the in-worker learner does, so that the link lengths over several noticings are the
configuration's.
"""

from __future__ import annotations

import pytest

from server.engine.bonds import Bond
from server.engine.coderack import Codelet
from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService
from server.services.training_mode_session_executor import SessionOutcome
from tests.support.instantiators import run_instantiators

pytestmark = pytest.mark.numeric_matrix

ONE, TWO, THREE = "plato-cp-0031", "plato-cp-0032", "plato-cp-0033"
ADJ = "plato-adjacent"


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


def runner_for(meta, problem=("12", "12", "123"), seed=1):
    r = EngineRunner(meta)
    r.init_mcat(*problem, None, seed=seed)
    return r


def string_of(r, name):
    return {"initial": r.ctx.workspace.initial_string, "modified": r.ctx.workspace.modified_string,
            "target": r.ctx.workspace.target_string}[name]


def bond_between(r, string, i, j, category=ADJ):
    """A built bond from the letter at position ``i`` to the one at ``j`` (neighbours), of the named category."""
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


def notice(r, name, build=True):
    """Run ``consolidator`` on a node, then (unless ``build`` is false) the instantiators it posted, and return
    what the run has recorded for the session: the count, and the links the instantiators built."""
    r._execute_codelet(Codelet("consolidator", 50, arguments={"slipnode": r.ctx.slipnet.nodes[name]}))
    if build:
        run_instantiators(r)
    return [dict(p) for p in r.ctx.proposals]


def adjust_of(ops, table, name):
    return [o["by"] for o in ops if o["op"] == "adjust" and o["table"] == table and
            (o["key"].get("name") == name or o["key"].get("from_node") == name)]


L, S = 90, 0.0625   # adjacent_link_length and adjacent_link_step in the v2.0 Base
R = 1 - S / L       # the ratio each noticing multiplies the pair's link by: r = 1 - s / L


def pair_ops(frm, to, noticings=1, ratio=R, length=L):
    """The pair-link ops of ``noticings`` noticings in one run: one ``add_link`` at L / r (the identical
    ``add_link`` is recorded once) and one ``scale`` whose factor is r multiplied in once per noticing."""
    factor = ratio
    for _ in range(noticings - 1):
        factor = factor * ratio
    return [{"op": "add_link", "from": frm, "to": to, "type": "adjacent", "label": ADJ, "fixed": True,
             "length": length / ratio},
            {"op": "scale", "table": "slipnet_link_defs", "key": {
                "from_node": frm, "to_node": to, "link_type": "adjacent", "label_node": ADJ},
             "field": "link_length", "factor": factor}]


COUNT = lambda name, by=1: {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": name},  # noqa: E731
                            "field": "noticings", "by": by}


# -- the body --------------------------------------------------------------------------------------------


def test_a_node_the_workspace_does_not_hold_fizzles_and_proposes_nothing(meta):
    r = runner_for(meta, ("12", "12", "12"))
    assert notice(r, THREE) == [] and notice(r, "plato-a") == []  # primed, not noticed
    assert r.ctx.proposals == []


def test_a_lone_symbol_counts_and_writes_no_link(meta):
    r = runner_for(meta, ("1", "1", "1"))
    assert notice(r, ONE) == [COUNT(ONE)]


def test_an_adjacent_bond_proposes_the_labelled_link_in_reading_order_from_either_end(meta):
    r = runner_for(meta)
    bond_between(r, string_of(r, "initial"), 0, 1)
    assert notice(r, ONE) == [COUNT(ONE), *pair_ops(ONE, TWO)]
    r = runner_for(meta)
    bond_between(r, string_of(r, "initial"), 1, 0)  # a bond from right to left: the link still reads left to right
    assert notice(r, TWO) == [COUNT(TWO), *pair_ops(ONE, TWO)]


def test_a_pair_seen_from_both_ends_counts_twice(meta):
    r = runner_for(meta)
    bond_between(r, string_of(r, "initial"), 0, 1)
    notice(r, ONE)
    ops = notice(r, TWO)
    assert ops == [COUNT(ONE), *pair_ops(ONE, TWO, noticings=2), COUNT(TWO)]


def test_a_pair_seen_twice_in_the_workspace_counts_twice_from_one_end(meta):
    r = runner_for(meta)
    bond_between(r, string_of(r, "initial"), 0, 1)
    bond_between(r, string_of(r, "modified"), 0, 1)
    assert notice(r, ONE) == [COUNT(ONE), *pair_ops(ONE, TWO, noticings=2)]


def test_it_goes_through_the_bonds_in_the_workspaces_order_and_draws_no_random_number(meta):
    r = runner_for(meta, ("123", "123", "123"))
    s = string_of(r, "initial")
    bond_between(r, s, 0, 1)
    bond_between(r, s, 1, 2)
    draws = r.ctx.rng.call_count
    ops = notice(r, TWO)
    assert r.ctx.rng.call_count == draws
    # the newest bond heads the string's list: 2-3, then 1-2
    assert ops == [COUNT(TWO), *pair_ops(TWO, THREE), *pair_ops(ONE, TWO)]


def test_a_bond_with_a_group_at_either_end_proposes_no_link(meta):
    r = runner_for(meta, ("113", "113", "113"))
    s = string_of(r, "initial")
    letters = [o for o in s.objects if o.left_string_pos in (0, 1)]
    nodes, lc = r.ctx.slipnet.nodes, r.ctx.slipnet.roles.dimension_letter_category
    group = Group(s, nodes["plato-samegrp"], lc, None, letters, [])
    s.add_group(group)
    three = [o for o in s.objects if o.left_string_pos == 2 and type(o).__name__ == "Letter"][0]
    # the group even carries a letter-category description of the symbol, so only its being a group stops the link
    group.add_description(Description(group, lc, nodes[ONE]))
    bond = Bond(group, three, nodes[ADJ], lc, nodes[ONE], nodes[THREE], nodes["plato-right"])
    s.add_bond(bond)
    assert notice(r, ONE) == [COUNT(ONE)]  # the symbol is there and counts; the bond writes nothing
    assert notice(r, THREE) == [COUNT(ONE), COUNT(THREE)]


def test_a_bond_whose_end_has_no_letter_category_description_proposes_nothing(meta):
    r = runner_for(meta)
    s = string_of(r, "initial")
    bond_between(r, s, 0, 1)
    two = [o for o in s.objects if o.left_string_pos == 1][0]
    lc = r.ctx.slipnet.roles.dimension_letter_category
    two.descriptions = [d for d in two.descriptions if d.description_type is not lc]
    assert notice(r, ONE) == [COUNT(ONE)]


def test_a_successor_or_sameness_bond_proposes_nothing(meta):
    for category in ("plato-successor", "plato-sameness"):
        r = runner_for(meta)
        bond_between(r, string_of(r, "initial"), 0, 1, category)
        assert notice(r, ONE) == [COUNT(ONE)], category


def test_a_bond_of_a_symbol_to_itself_proposes_nothing(meta):
    r = runner_for(meta, ("11", "11", "11"))
    bond_between(r, string_of(r, "initial"), 0, 1)
    assert notice(r, ONE) == [COUNT(ONE)]


def test_category_and_instance_links_are_proposed_only_at_or_past_the_threshold_and_only_when_missing(document):
    def at(count, doc=document):
        ops, _ = resolve(doc, {"ops": [{"op": "adjust", "table": "slipnet_node_defs", "key": {"name": ONE},
                                        "field": "noticings", "by": count}]}) if count else ([], None)
        return cd.provider(cd.apply_resolved(doc, ops))

    wanted = [{"op": "add_link", "from": ONE, "to": "plato-letter-category", "type": "category", "fixed": True,
               "length": 20},
              {"op": "add_link", "from": "plato-letter-category", "to": ONE, "type": "instance", "fixed": True,
               "length": 97}]
    assert notice(runner_for(at(39), ("1", "1", "1")), ONE) == [COUNT(ONE)]  # one short of the threshold
    assert notice(runner_for(at(40), ("1", "1", "1")), ONE) == [COUNT(ONE), *wanted]
    assert notice(runner_for(at(500), ("1", "1", "1")), ONE) == [COUNT(ONE), *wanted]
    # a seed letter has both links: nothing is proposed for it however often it was noticed
    far = cd.provider(cd.apply_resolved(document, resolve(document, {"ops": [
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "field": "noticings",
         "by": 99}]})[0]))
    assert notice(runner_for(far, ("a", "a", "a")), "plato-a") == [COUNT("plato-a")]
    # only the missing one is proposed
    half, _ = resolve(document, {"ops": [
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": ONE}, "field": "noticings", "by": 40},
        {"op": "add_link", "from": ONE, "to": "plato-letter-category", "type": "category", "fixed": True,
         "length": 20}]})
    only = notice(runner_for(cd.provider(cd.apply_resolved(document, half)), ("1", "1", "1")), ONE)
    assert only == [COUNT(ONE), wanted[1]]


def test_the_threshold_and_the_lengths_are_read_from_parameters(document):
    ops, _ = resolve(document, {"ops": [
        {"op": "set_param", "name": "consolidation_threshold", "to": 0},
        {"op": "set_param", "name": "symbol_category_link_length", "to": 11},
        {"op": "set_param", "name": "symbol_instance_link_length", "to": 12},
        {"op": "set_param", "name": "adjacent_link_length", "to": 70},
        {"op": "set_param", "name": "adjacent_link_step", "to": 0.5, "value_type": "float"}]})
    meta = cd.provider(cd.apply_resolved(document, ops))
    r = runner_for(meta)
    bond_between(r, string_of(r, "initial"), 0, 1)
    got = notice(r, ONE)
    ratio = 1 - 0.5 / 70
    assert [o["length"] for o in got if o["op"] == "add_link"] == [70 / ratio, 11, 12]
    assert [o["factor"] for o in got if o["op"] == "scale" and o["field"] == "link_length"] == [ratio]
    assert 70 / ratio == pytest.approx(70.5, rel=1e-4) and ratio == pytest.approx(1 - 0.5 / 70)


def test_the_first_noticing_leaves_the_link_at_exactly_90_and_a_step_is_one_sixteenth_of_the_way_there():
    """``add_link`` at L / r and a ``scale`` by r: (L / r) * r is exactly 90.0 for L = 90 and s = 1/16 (so the
    configuration stores the whole number 90), and the first later step is s: 90 - 90 * r = s up to float rounding."""
    assert R == 0.9993055555555556 and L / R == 90.06254343293953 and (L / R) * R == 90.0
    assert L - L * R == pytest.approx(S, rel=1e-12)


# -- landing: the configuration's lengths over several noticings ------------------------------------------


def fake(ops, seed=1):
    return SessionOutcome(seed=seed, status="answer_found", answer="x", answers=["x"], codelets=1, seconds=0.0,
                          stopping_state="answer_found:x", proposals=ops)


def land(config, ops, run):
    batch = TrainingModeSessionService._proposal_batch(fake(ops))
    return config.finish_run(memory_merge=lambda: None, batch=batch, run=(run, run), started_revision=0,
                             learner=IN_WORKER_LEARNER)


def test_the_labelled_link_is_90_at_the_first_noticing_and_a_ratio_shorter_for_each_after(document, meta):
    config = LiveConfiguration(document, configuration_id=0, revision=0, episode_version=0)
    key = (ONE, TWO, "adjacent", ADJ)
    lengths = []
    for run in range(1, 6):
        r = runner_for(meta)
        bond_between(r, string_of(r, "initial"), 0, 1)
        land(config, notice(r, ONE), run)
        lengths.append(config.document.tables["slipnet_link_defs"][key]["link_length"])
    assert config.diagnostics == []
    # one noticing per run: each run multiplies the stored length by r, so the lengths are exactly
    # the float products 90, 90 r, 90 r r, ... (and within rounding of 90 * r ** (N - 1)), never 0 or below
    want = [float(L)]
    for _ in range(4):
        want.append(want[-1] * R)
    assert lengths == want and lengths[0] == 90 and type(lengths[0]) is int
    assert lengths == pytest.approx([L * R ** n for n in range(5)], rel=1e-12)
    assert all(0 < n < 90.0001 for n in lengths) and lengths == sorted(lengths, reverse=True)
    assert config.document.tables["slipnet_node_defs"][(ONE,)]["noticings"] == 5
    link = config.document.tables["slipnet_link_defs"][key]
    assert link["label_node"] == ADJ and link["fixed_length"] is True
    # nothing else was written: no successor, no category or instance link, no other link at all
    base = document.tables["slipnet_link_defs"]
    assert [k for k in config.document.tables["slipnet_link_defs"] if k not in base] == [key]
    assert {k for k, v in config.document.tables["slipnet_node_defs"].items() if v["conceptual_depth"] !=
            document.tables["slipnet_node_defs"][k]["conceptual_depth"]} == set()


def test_a_pair_noticed_from_both_ends_in_one_run_and_the_same_pair_in_another_add_up(document, meta):
    config = LiveConfiguration(document, configuration_id=0, revision=0, episode_version=0)
    for run in (1, 2):
        r = runner_for(meta)
        bond_between(r, string_of(r, "initial"), 0, 1)
        notice(r, ONE)
        land(config, notice(r, TWO), run)
    # four noticings of the pair: 90 * r ** 3 (the run's two scales are multiplied into one, so the last
    # bits can differ from four sequential multiplications; the test allows 1e-12 of relative error)
    got = config.document.tables["slipnet_link_defs"][(ONE, TWO, "adjacent", ADJ)]["link_length"]
    assert got == pytest.approx(L * R ** 3, rel=1e-12)
