"""``propose_ops`` and ``noticings``: the two builtins a v2.0 Base body uses to leave a change for the
session's configuration and to read how often a node has been noticed.

``propose_ops`` records change-API ops in the run's ``proposals`` (the list ``apply_ops`` writes), in call
order, and changes nothing in the run.  It refuses ``add_node``, records an identical op once, and adds
repeated ``adjust`` ops on the same ``(table, key, field)`` into the first one.  It draws no random number.
``noticings`` reads the configuration as the run started it.  The same seed gives the same run, proposals
included, on ``off``, ``python`` and ``numpy``.
"""

from __future__ import annotations

import copy
import json

import pytest

from server.engine.codelet_dsl.builtins import apply_ops, get_builtins, noticings, propose_ops
from server.engine.numeric.backend import use_backend
from server.engine.roles import absent
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve
from server.services.training_mode_session_executor import SessionTask, outcome_fingerprint, run_task

pytestmark = pytest.mark.numeric_matrix

KEY = {"from_node": "plato-a", "to_node": "plato-b", "link_type": "adjacent", "label_node": ""}
ADD_LINK = {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True, "length": 90.125}


def adjust(by, key=None, table="slipnet_link_defs", field="link_length"):
    return {"op": "adjust", "table": table, "key": dict(KEY if key is None else key), "field": field, "by": by}


@pytest.fixture(scope="module")
def base():
    return cd.provider(tb.resolve_base().document)


def fresh_ctx(meta, problem=("abc", "abd", "xyz")):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, None, seed=1)
    return runner.ctx


def test_both_builtins_are_in_the_registry():
    assert get_builtins()["propose_ops"] is propose_ops and get_builtins()["noticings"] is noticings


# -- what it records -----------------------------------------------------------------------------------


def test_it_records_ops_in_call_order_as_data(base):
    ctx = fresh_ctx(base)
    other = {"op": "add_trigger", "rule_key": "some-rule", "node": "plato-a"}
    kind = {"op": "add_link_type", "name": "near"}
    propose_ops(ctx, [ADD_LINK, other])
    propose_ops(ctx, [kind])
    assert ctx.proposals == [ADD_LINK, other, kind]
    assert ctx.proposals[0] is not ADD_LINK  # a copy: the body's dict can change afterwards
    # "any other op is accepted as data": the change API checks it when the learner submits it
    propose_ops(ctx, [{"op": "no-such-op", "x": 1}])
    assert ctx.proposals[-1] == {"op": "no-such-op", "x": 1}


def test_it_refuses_add_node_which_goes_through_apply_ops_and_applies_nothing_of_the_call(base):
    ctx = fresh_ctx(base)
    node = {"op": "add_node", "name": "plato-cp-0031", "fields": {"short_name": "1", "conceptual_depth": 10}}
    with pytest.raises(ValueError, match="apply_ops"):
        propose_ops(ctx, [ADD_LINK, node])
    assert ctx.proposals == []  # the check comes first: not even the op before the bad one is recorded
    for bad in ("add_link", 3, {"no": "op"}, {"op": ""}):
        with pytest.raises(ValueError):
            propose_ops(ctx, [bad])
    assert ctx.proposals == []


def test_an_op_identical_to_one_already_recorded_is_not_recorded_again(base):
    ctx = fresh_ctx(base)
    propose_ops(ctx, [ADD_LINK, ADD_LINK])
    propose_ops(ctx, [copy.deepcopy(ADD_LINK)])
    assert ctx.proposals == [ADD_LINK]
    # a different op with the same name is a different op
    propose_ops(ctx, [{**ADD_LINK, "length": 90}])
    assert len(ctx.proposals) == 2


def test_apply_ops_and_propose_ops_share_one_list_in_call_order(base):
    ctx = fresh_ctx(base, ("1", "1", "1"))
    node = {"op": "add_node", "name": "plato-cp-0031", "fields": {
        "short_name": "1", "glyph": "1", "plain_name": "1", "article_an": False, "conceptual_depth": 10}}
    propose_ops(ctx, [ADD_LINK])
    apply_ops(ctx, [node])
    propose_ops(ctx, [adjust(-0.125)])
    assert [p["op"] for p in ctx.proposals] == ["add_link", "add_node", "adjust"]


# -- summing -------------------------------------------------------------------------------------------


def test_repeated_adjust_ops_on_one_target_are_one_op_kept_where_the_first_was(base):
    ctx = fresh_ctx(base)
    first_node = {"op": "add_link_type", "name": "near"}
    propose_ops(ctx, [first_node, adjust(-0.125), ADD_LINK])
    for _ in range(79):
        propose_ops(ctx, [adjust(-0.125)])
    assert [p["op"] for p in ctx.proposals] == ["add_link_type", "adjust", "add_link"]
    assert ctx.proposals[1]["by"] == -10 and ctx.proposals[1]["by"] + 90 == 80  # 80 steps of 1/8 are exactly 10


def test_eighty_adjusts_of_one_eighth_sum_to_exactly_minus_ten_in_one_call_or_many(base):
    ctx = fresh_ctx(base)
    propose_ops(ctx, [adjust(-0.125) for _ in range(80)])
    assert ctx.proposals == [adjust(-10.0)] and ctx.proposals[0]["by"] == -10
    # the same total on top of a link at 90 is exactly 80
    assert 90 + ctx.proposals[0]["by"] == 80


def test_the_same_target_is_the_same_table_the_same_field_and_the_same_key(base):
    ctx = fresh_ctx(base)
    other_key = {**KEY, "to_node": "plato-c"}
    propose_ops(ctx, [
        adjust(-1), adjust(-1, key=other_key), adjust(-1, field="fixed_length"),
        adjust(-1, table="slipnet_node_defs", key={"name": "plato-a"}, field="noticings"),
        adjust(-1, key={**KEY, "label_node": None}),   # a NULL key part is read as "", as the change API does
        adjust(-2, key=other_key),
        adjust(5, table="slipnet_node_defs", key={"name": "plato-a"}, field="noticings"),
    ])
    assert ctx.proposals == [
        adjust(-2),
        adjust(-3, key=other_key),
        adjust(-1, field="fixed_length"),
        adjust(4, table="slipnet_node_defs", key={"name": "plato-a"}, field="noticings"),
    ]


def test_an_adjust_that_cannot_be_added_is_recorded_as_it_is_for_the_change_api_to_refuse(base):
    ctx = fresh_ctx(base)
    propose_ops(ctx, [adjust(-1), adjust(float("inf")), adjust(10 ** 400), adjust("x")])
    assert [p["by"] for p in ctx.proposals][:1] == [-1] and len(ctx.proposals) == 4
    ints = fresh_ctx(base)
    propose_ops(ints, [adjust(1), adjust(2), adjust(3)])
    assert ints.proposals == [adjust(6)] and isinstance(ints.proposals[0]["by"], int)


def test_an_identical_adjust_counts_each_time_unlike_every_other_identical_op(base):
    ctx = fresh_ctx(base)
    propose_ops(ctx, [adjust(-0.125), adjust(-0.125), ADD_LINK, ADD_LINK])
    assert ctx.proposals == [adjust(-0.25), ADD_LINK]


# -- what it does not touch ---------------------------------------------------------------------------


def test_it_changes_nothing_in_the_run_and_draws_no_random_number(base):
    ctx = fresh_ctx(base)
    meta_before, nodes_before = ctx.meta, list(ctx.slipnet.nodes)
    links_before = sum(len(n.outgoing_links) for n in ctx.slipnet.nodes.values())
    draws, codelets = ctx.rng.call_count, ctx.codelet_count
    objects = list(ctx.workspace.objects) if hasattr(ctx.workspace, "objects") else None
    propose_ops(ctx, [ADD_LINK, adjust(-0.125), {"op": "add_link_type", "name": "near"}])
    assert ctx.meta is meta_before and list(ctx.slipnet.nodes) == nodes_before
    assert sum(len(n.outgoing_links) for n in ctx.slipnet.nodes.values()) == links_before
    assert ctx.rng.call_count == draws and ctx.codelet_count == codelets
    assert objects is None or list(ctx.workspace.objects) == objects
    assert "plato-b" in ctx.slipnet.nodes and not any(
        link.link_type == "adjacent" and link.to_node.name == "plato-b" for link in ctx.slipnet.nodes["plato-a"].outgoing_links)


# -- noticings -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def counted():
    doc = tb.resolve_base().document
    ops = [{"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "field": "noticings", "by": 7},
           {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-successor"}, "field": "noticings", "by": 2}]
    resolved, _ = resolve(doc, {"ops": ops})
    return cd.provider(cd.apply_resolved(doc, resolved))


def test_noticings_reads_the_count_the_configuration_held_when_the_run_started(counted, base):
    ctx = fresh_ctx(counted)
    a, b = ctx.slipnet.nodes["plato-a"], ctx.slipnet.nodes["plato-b"]
    assert noticings(ctx, a) == 7 and noticings(ctx, "plato-a") == 7
    assert noticings(ctx, b) == 0 and noticings(ctx, ctx.slipnet.nodes["plato-successor"]) == 2
    assert all(type(noticings(ctx, n)) is int for n in ctx.slipnet.nodes.values())
    # no count is 0 for the nodes of the Metacat Standard Configuration and the Base alike
    assert {noticings(fresh_ctx(base), n) for n in ctx_nodes(base)} == {0}


def ctx_nodes(meta):
    return list(fresh_ctx(meta).slipnet.nodes.values())


def test_a_run_that_proposes_a_count_still_reads_the_old_one(counted):
    ctx = fresh_ctx(counted)
    a = ctx.slipnet.nodes["plato-a"]
    propose_ops(ctx, [adjust(1, table="slipnet_node_defs", key={"name": "plato-a"}, field="noticings")])
    assert noticings(ctx, a) == 7  # counts apply from the next run


def test_noticings_of_an_absent_token_or_an_unknown_name_or_a_node_the_run_made_is_zero(counted):
    ctx = fresh_ctx(counted, ("1", "1", "1"))
    assert noticings(ctx, absent("letter.1")) == 0 and noticings(ctx, "no-such-node") == 0
    apply_ops(ctx, [{"op": "add_node", "name": "plato-cp-0031", "fields": {
        "short_name": "1", "glyph": "1", "plain_name": "1", "article_an": False, "conceptual_depth": 10}}])
    assert noticings(ctx, ctx.slipnet.nodes["plato-cp-0031"]) == 0
    assert noticings(ctx, ctx.slipnet.nodes["plato-a"]) == 7


# -- the same seed gives the same run ------------------------------------------------------------------

NOTICER = """
key = {'from_node': 'plato-a', 'to_node': 'plato-b', 'link_type': 'adjacent', 'label_node': ''}
propose_ops([
    {'op': 'add_link', 'from': 'plato-a', 'to': 'plato-b', 'type': 'adjacent', 'fixed': True, 'length': 90.125},
    {'op': 'adjust', 'table': 'slipnet_link_defs', 'key': key, 'field': 'link_length', 'by': -0.125},
    {'op': 'adjust', 'table': 'slipnet_node_defs', 'key': {'name': 'plato-a'}, 'field': 'noticings', 'by': 1},
])
"""


def noticer_provider():
    """A test configuration: the v2.0 Base, without ``consolidator``'s posting rule, plus a codelet type whose body
    proposes a link and counts."""
    doc = tb.resolve_base().document
    ops = [
        {"op": "remove_posting_rule", "rule_key": "consolidator"},
        {"op": "add_codelet_type", "name": "noticer", "fields": {
            "family": "description", "phase": "scout", "description": "a test body", "execute_body": NOTICER}},
        {"op": "add_posting_rule", "rule_key": "noticer", "fields": {
            "codelet_type": "noticer", "direction": "bottom_up", "urgency_level": "low", "posting_formula": "1.0",
            "count_formula": "fixed", "count_values": {"fixed": 1}, "condition": "True"}},
    ]
    resolved, _ = resolve(doc, {"ops": ops})
    return cd.provider(cd.apply_resolved(doc, resolved))


def run_noticer(meta, seed, backend, problem=("abc", "abd", "xyz"), steps=900):
    runner = EngineRunner(meta)
    with use_backend(None if backend == "off" else backend):
        runner.init_mcat(*problem, None, seed=seed)
        runner.run_mcat(max_steps=steps)
    ctx = runner.ctx
    return {"status": runner.status, "codelets": ctx.codelet_count, "draws": ctx.rng.call_count,
            "temperature": float(ctx.temperature.value), "proposals": json.dumps(ctx.proposals),
            "trace": [type(e).__name__ + str(getattr(e, "event_type", "")) for e in ctx.trace.events][:400]}


@pytest.mark.parametrize("backend", ["off", "python", "numpy"])
def test_the_same_seed_gives_the_same_run_proposals_included(backend):
    meta = noticer_provider()
    first, second = run_noticer(meta, 5, backend), run_noticer(meta, 5, backend)
    assert first == second
    ops = json.loads(first["proposals"])
    assert [p["op"] for p in ops] == ["add_link", "adjust", "adjust"]
    assert ops[1]["by"] < 0 and ops[1]["by"] == -0.125 * ops[2]["by"]  # n noticings: -n/8 on the link, +n on the node
    assert ops[2]["by"] >= 2  # the codelet ran more than once, and its repeats are one op


def test_off_python_and_numpy_agree_on_the_run_and_its_proposals():
    meta = noticer_provider()
    for seed in (1, 2, 3):
        ref = run_noticer(meta, seed, "off")
        assert run_noticer(meta, seed, "python") == ref and run_noticer(meta, seed, "numpy") == ref


def test_the_run_task_fingerprint_carries_the_proposal_hash_and_repeats():
    meta = noticer_provider()
    task = SessionTask("abc", "abd", "xyz", None, 4, 900, None, "off")
    one, two = run_task(task, meta), run_task(task, meta)
    assert not one.error and outcome_fingerprint(one) == outcome_fingerprint(two) and one.proposals == two.proposals
    assert outcome_fingerprint(one)[-1] != ()
