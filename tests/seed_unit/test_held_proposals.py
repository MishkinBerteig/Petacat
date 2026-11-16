"""Changes to a run's Slipnet held for an instantiator (increment 4, stage A).

``propose_ops(ops, built_by=..., urgency=...)`` holds the ops of one link for an instantiator and posts it; the
instantiator calls ``take_proposed_ops`` and builds what it took with ``apply_ops`` or fizzles.  Held changes are
grouped by target (the link: ``from``, ``to``, ``type``, ``label``) and composed as ``propose_ops`` composes
(an identical op once, ``adjust`` summed, ``scale`` multiplied); at most one instantiator waits per target;
the next proposal after one left the Coderack unrun posts a new one; what is still held when the turn ends is
dropped and is never in the run's outcome; a plain ``propose_ops`` is unchanged.
"""

from __future__ import annotations

import pytest

from server.engine.codelet_dsl.builtins import apply_ops, propose_ops, take_proposed_ops
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb
from tests.support import proposing_configuration as pc
from tests.support.instantiators import on_rack, run_instantiators

pytestmark = pytest.mark.numeric_matrix

A, B, C, D = "plato-a", "plato-b", "plato-c", "plato-d"
ADJ = "plato-adjacent"
KIND = "adjacent-instantiator"
BUILT = "pair-instantiator"


@pytest.fixture(scope="module")
def base():
    return cd.provider(tb.resolve_base().document)


@pytest.fixture(scope="module")
def always():
    """The Base plus an instantiator that builds what it takes with no evidence to check."""
    return pc.instantiating_provider()


def fresh(meta, problem=("ace", "ace", "ace")):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, None, seed=1)
    return runner


def link(frm, to, length=40):
    return {"op": "add_link", "from": frm, "to": to, "type": "adjacent", "label": ADJ, "fixed": True, "length": length}


def scale(frm, to, factor):
    return {"op": "scale", "table": "slipnet_link_defs", "key": {
        "from_node": frm, "to_node": to, "link_type": "adjacent", "label_node": ADJ},
        "field": "link_length", "factor": factor}


def adjust(frm, to, by):
    return {"op": "adjust", "table": "slipnet_link_defs", "key": {
        "from_node": frm, "to_node": to, "link_type": "adjacent", "label_node": ADJ},
        "field": "link_length", "by": by}


def propose(ctx, ops, urgency=70, built_by=KIND):
    propose_ops(ctx, ops, built_by=built_by, urgency=urgency)


def held(ctx, frm=A, to=C, built_by=KIND):
    return ctx.held_proposals.get((built_by, "link", frm, to, "adjacent", ADJ))


# -- holding ------------------------------------------------------------------------------------------------------


def test_a_proposal_for_an_instantiator_changes_nothing_in_the_run_and_records_nothing(base):
    ctx = fresh(base).ctx
    draws = ctx.rng.call_count
    propose(ctx, [link(A, C), scale(A, C, 0.5)])
    assert ctx.proposals == [] and ctx.slipnet.find_link(A, C, "adjacent", ADJ) is None
    assert ctx.rng.call_count == draws  # nothing was drawn: the Coderack was not full
    assert held(ctx)["ops"] == [link(A, C), scale(A, C, 0.5)]


def test_the_urgency_is_the_one_the_proposer_supplies_and_the_codelet_carries_its_target(base):
    runner = fresh(base)
    propose(runner.ctx, [link(A, C), scale(A, C, 0.5)], urgency=base.get_urgency("high"))
    (codelet,) = on_rack(runner, KIND)
    assert codelet.urgency == base.get_urgency("high") and codelet.codelet_type == KIND
    assert codelet.arguments == {"held": (KIND, "link", A, C, "adjacent", ADJ)}
    assert held(runner.ctx)["codelet"] is codelet


def test_proposals_for_one_target_accumulate_as_propose_ops_composes_and_post_one_instantiator(base):
    runner = fresh(base)
    ctx = runner.ctx
    for _ in range(5):
        propose(ctx, [link(A, C, 90.06), scale(A, C, 0.9)])
    propose(ctx, [adjust(A, C, 1), adjust(A, C, 2)])
    entry = held(ctx)
    assert entry["ops"][0] == link(A, C, 90.06)  # an identical op once
    assert entry["ops"][1]["factor"] == pytest.approx(0.9 ** 5)  # the scales multiplied, in call order
    assert entry["ops"][2] == adjust(A, C, 3)  # the adjusts summed
    assert len(entry["ops"]) == 3 and len(ctx.held_proposals) == 1
    assert len(on_rack(runner, KIND)) == 1 and ctx.proposals == []


def test_another_target_has_its_own_entry_and_its_own_instantiator(base):
    runner = fresh(base)
    propose(runner.ctx, [link(A, C), scale(A, C, 0.5)])
    propose(runner.ctx, [link(C, "plato-e"), scale(C, "plato-e", 0.5)])
    propose(runner.ctx, [link(C, A), scale(C, A, 0.5)])  # the reverse is another link
    assert len(runner.ctx.held_proposals) == 3
    assert [c.arguments["held"][2:4] for c in on_rack(runner, KIND)] == [(A, C), (C, "plato-e"), (C, A)]
    # the same ops for another kind of instantiator is another entry as well
    propose(runner.ctx, [link(A, C)], built_by="category-instantiator")
    assert len(runner.ctx.held_proposals) == 4 and len(on_rack(runner, "category-instantiator")) == 1


def test_after_an_instantiator_left_the_coderack_unrun_the_next_proposal_posts_a_new_one(base):
    runner = fresh(base)
    ctx = runner.ctx
    propose(ctx, [link(A, C), scale(A, C, 0.5)])
    (first,) = on_rack(runner, KIND)
    for evict in ("one", "flush"):
        # evicted, or flushed with the rest of the rack (as a snag's restart does): the held ops stay
        if evict == "one":
            rack = ctx.coderack
            rack._bin_of(first).remove(first)
            rack._total_count -= 1
        else:
            ctx.coderack.clear()
        assert on_rack(runner, KIND) == [] and held(ctx)["ops"]
        propose(ctx, [link(A, C), scale(A, C, 0.5)])
        (again,) = on_rack(runner, KIND)
        assert again is not first and held(ctx)["codelet"] is again
        first = again
    assert held(ctx)["ops"][1]["factor"] == pytest.approx(0.5 ** 3)  # everything proposed is still held, composed
    propose(ctx, [scale(A, C, 0.5)])  # one is waiting: no second
    assert len(on_rack(runner, KIND)) == 1


def test_a_proposal_that_is_not_one_links_ops_is_refused_whole(base):
    ctx = fresh(base).ctx
    bad = [
        ([], "needs ops"),
        ([link(A, C), link(A, D)], "two"),
        ([link(A, C), scale(A, D, 0.5)], "two"),
        ([{"op": "add_node", "name": "x", "fields": {}}], "add_node"),
        ([{"op": "add_trigger", "rule_key": "x", "node": A}], "one link"),
        ([{"op": "adjust", "table": "slipnet_node_defs", "key": {"name": A}, "field": "noticings", "by": 1}], "one link"),
        ([{**scale(A, C, 0.5), "field": "fixed_length"}], "one link"),
        ([{"op": "add_link", "from": A, "to": C}], "one link"),
        ([{"op": "add_link", "from": A, "to": 5, "type": "adjacent"}], "one link"),
        ("nope", None),
    ]
    for ops, why in bad:
        with pytest.raises((ValueError, TypeError), match=why):
            propose(ctx, ops)
    for kwargs, why in (({"built_by": "no-such-type", "urgency": 5}, "codelet type"),
                        ({"built_by": KIND, "urgency": None}, "urgency"),
                        ({"built_by": KIND, "urgency": "high"}, "urgency"),
                        ({"built_by": "", "urgency": 5}, "codelet type"),
                        ({"built_by": None, "urgency": 5}, "urgency goes with built_by")):
        with pytest.raises(ValueError, match=why):
            propose_ops(ctx, [link(A, C)], **kwargs)
    assert ctx.held_proposals == {} and ctx.proposals == []


def test_a_plain_propose_ops_is_unchanged_and_never_holds(base):
    runner = fresh(base)
    ctx = runner.ctx
    propose_ops(ctx, [link(A, C), scale(A, C, 0.5), adjust(A, C, 1)])
    propose_ops(ctx, [link(A, C), scale(A, C, 0.5), adjust(A, C, 2)])
    assert ctx.proposals == [link(A, C), scale(A, C, 0.25), adjust(A, C, 3)]
    assert ctx.held_proposals == {} and on_rack(runner, KIND) == []
    with pytest.raises(ValueError, match="built_by"):
        propose_ops(ctx, [link(A, C)], urgency=5)
    with pytest.raises(ValueError, match="apply_ops"):
        propose_ops(ctx, [{"op": "add_node", "name": "x", "fields": {}}])


# -- taking -------------------------------------------------------------------------------------------------------


def test_an_instantiator_takes_everything_held_for_its_target_and_nothing_stays_held(base):
    runner = fresh(base)
    ctx = runner.ctx
    propose(ctx, [link(A, C), scale(A, C, 0.5)])
    propose(ctx, [link(C, "plato-e"), scale(C, "plato-e", 0.5)])
    target = (KIND, "link", A, C, "adjacent", ADJ)
    taken = take_proposed_ops(ctx, target)
    assert taken == [link(A, C), scale(A, C, 0.5)] and held(ctx) is None
    assert take_proposed_ops(ctx, target) == []  # nothing is left
    assert take_proposed_ops(ctx, list(target)) == [] and take_proposed_ops(ctx, None) == []
    assert take_proposed_ops(ctx, "plato-a") == []
    assert held(ctx, C, "plato-e") is not None  # another target's is untouched
    assert ctx.proposals == []  # taking records nothing: building does
    taken[0]["length"] = 1
    assert take_proposed_ops(ctx, (KIND, "link", C, "plato-e", "adjacent", ADJ))[0]["length"] == 40  # private copies


def test_what_an_instantiator_takes_and_builds_is_recorded_for_the_session_and_composes_across_builds(always):
    runner = fresh(always)
    ctx = runner.ctx
    propose(ctx, built_by=BUILT, ops=[link(A, C, 90), scale(A, C, 0.5)])
    run_instantiators(runner, BUILT)
    assert held(ctx, built_by=BUILT) is None
    assert ctx.slipnet.find_link(A, C, "adjacent", ADJ).link_length() == 45
    assert ctx.proposals == [link(A, C, 90), scale(A, C, 0.5)]
    # a later proposal for the same target posts a new instantiator (the first ran), and composes into the record
    propose(ctx, built_by=BUILT, ops=[link(A, C, 90), scale(A, C, 0.5)])
    assert len(on_rack(runner, BUILT)) == 1
    run_instantiators(runner, BUILT)
    assert ctx.proposals == [link(A, C, 90), scale(A, C, 0.25)]
    assert ctx.slipnet.find_link(A, C, "adjacent", ADJ).link_length() == 22.5


def test_apply_ops_by_the_taker_may_be_refused_and_the_run_is_left_unchanged(always):
    ctx = fresh(always).ctx
    propose(ctx, built_by=BUILT, ops=[link(A, C, 90), scale(A, C, 1e308)])
    propose(ctx, built_by=BUILT, ops=[scale(A, C, 1e308)])
    taken = take_proposed_ops(ctx, (BUILT, "link", A, C, "adjacent", ADJ))
    with pytest.raises(ValueError, match="finite"):
        apply_ops(ctx, taken)
    assert ctx.slipnet.find_link(A, C, "adjacent", ADJ) is None and ctx.proposals == []


# -- the end of the turn ---------------------------------------------------------------------------------------------


def test_what_is_still_held_at_the_end_of_the_turn_is_dropped_and_not_in_the_outcome(always):
    from server.services.training_mode_session_executor import SessionTask, run_task

    runner = fresh(always)
    ctx = runner.ctx
    propose(ctx, built_by=BUILT, ops=[link(A, C, 90), scale(A, C, 0.5)])
    propose(ctx, built_by=BUILT, ops=[link(C, "plato-e", 90), scale(C, "plato-e", 0.5)])
    run_instantiators(runner, BUILT)  # both are built ...
    propose(ctx, built_by=BUILT, ops=[link(C, "plato-e", 90), scale(C, "plato-e", 0.5)])  # ... and this one is still held
    assert held(ctx, C, "plato-e", built_by=BUILT) is not None
    assert ctx.proposals == [link(A, C, 90), scale(A, C, 0.5), link(C, "plato-e", 90), scale(C, "plato-e", 0.5)]
    # a whole run's outcome carries ctx.proposals, never the held entries
    task = SessionTask("ace", "ace", "ace", None, 1, 700, None, "off")
    outcome = run_task(task, always)
    assert not outcome.error
    assert any(p["op"] == "scale" for p in outcome.proposals)
    assert not hasattr(outcome, "held_proposals")
