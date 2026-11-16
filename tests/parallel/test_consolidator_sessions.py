"""``consolidator`` over whole runs and sessions: noticings add up, depth does not move, the trigger arrives
after the first run, and the serial child and the swarm give the same outcome.

A session whose later runs see what earlier runs learned depends on which run finishes first on the swarm, so the
tests that compare routes run every seed against one frozen configuration (the Base with the nodes of ``1``, ``2``
and ``3`` and their triggers, as a session keeps them) and land the outcomes in the configuration afterwards.  The
tests of a session as it learns use the serial route, which is reproducible: each run takes the configuration as it
is when the run is dispatched, and its learning lands when it finishes.
"""

from __future__ import annotations

import collections
import contextlib
import json

import pytest

from server.engine.codelet_dsl import interpreter as interp
from server.parallel.swarm import Swarm
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionTask, SwarmExecutor, outcome_fingerprint, run_task,
)
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService
from tests.support.noticing_configuration import every_noticing

pytestmark = pytest.mark.numeric_matrix

STEPS = 900
PROBLEM = ("123", "123", "123")
SEEDS = (1, 2, 3, 4, 5, 6)


def node_op(ch):
    return {"op": "add_node", "name": "plato-cp-%04x" % ord(ch), "fields": {
        "short_name": ch, "glyph": ch, "plain_name": ch, "article_an": False, "conceptual_depth": 10}}


@pytest.fixture(scope="module")
def base_document():
    """The Base with ``consolidator`` posted at every gate pass (``tests/support/noticing_configuration.py``): these tests
    are about what noticings do, and the Base's own rule notices a symbol rarely."""
    return every_noticing(tb.resolve_base().document)


@pytest.fixture(scope="module")
def taught_document(base_document):
    """The Base after a session met ``1``, ``2`` and ``3``: their nodes and their triggers."""
    ops = [node_op(c) for c in "123"] + [
        {"op": "add_trigger", "rule_key": "consolidator", "node": "plato-cp-%04x" % ord(c)} for c in "123"]
    resolved, _ = resolve(base_document, {"ops": ops})
    return cd.apply_resolved(base_document, resolved)


def live(doc) -> LiveConfiguration:
    return LiveConfiguration(doc, configuration_id=0, revision=0, episode_version=0)


def land(config, outcome, run):
    batch = TrainingModeSessionService._proposal_batch(outcome)
    if batch is None:
        return None
    return config.finish_run(memory_merge=lambda: None, batch=batch, run=(run, outcome.seed), started_revision=0,
                             learner=IN_WORKER_LEARNER)


@contextlib.contextmanager
def counting_consolidators():
    """Per node, how many consolidator codelets ran and how many of them fizzled (in this process)."""
    ran, fizzled, current = collections.Counter(), collections.Counter(), [None]
    execute, fizzle = interp.CodeletInterpreter.execute, interp._fizzle

    def counting_execute(self, compiled, ctx, **args):
        if getattr(compiled, "name", "") != "consolidator":
            return execute(self, compiled, ctx, **args)
        current[0] = args["slipnode"].name
        ran[current[0]] += 1
        try:
            return execute(self, compiled, ctx, **args)
        finally:
            current[0] = None

    def counting_fizzle():
        if current[0] is not None:
            fizzled[current[0]] += 1
        return fizzle()

    interp.CodeletInterpreter.execute, interp._fizzle = counting_execute, counting_fizzle
    try:
        yield ran, fizzled
    finally:
        interp.CodeletInterpreter.execute, interp._fizzle = execute, fizzle


def counts_of(outcome) -> dict[str, int]:
    return {p["key"]["name"]: p["by"] for p in outcome.proposals
            if p["op"] == "adjust" and p["table"] == "slipnet_node_defs"}


# -- noticings add up ------------------------------------------------------------------------------------------


def test_within_a_run_the_noticings_adjust_equals_the_consolidator_runs_that_did_not_fizzle(taught_document):
    meta = cd.provider(taught_document)
    seen = set()
    for seed in SEEDS:
        with counting_consolidators() as (ran, fizzled):
            outcome = run_task(SessionTask(*PROBLEM, None, seed, STEPS, None, "off"), meta)
        assert not outcome.error
        proposed = counts_of(outcome)
        assert sum(ran.values()) > 0
        for name in ran:
            assert proposed.get(name, 0) == ran[name] - fizzled[name], (seed, name)
        assert set(proposed) <= set(ran)
        seen |= set(proposed)
    assert {"plato-cp-0031", "plato-cp-0032", "plato-cp-0033"} <= seen


def test_across_a_session_the_configurations_count_is_the_sum_over_its_runs_and_the_routes_agree(taught_document):
    meta = cd.provider(taught_document)
    tasks = [SessionTask(*PROBLEM, None, seed, STEPS, None, "off") for seed in SEEDS]
    local = [run_task(t, meta) for t in tasks]
    serial, swarm = SerialExecutor(), SwarmExecutor(Swarm(workers=2, meta=meta))
    try:
        via_serial = serial.submit(tasks, meta).result(timeout=300)
        via_swarm = swarm.submit(tasks, meta).result(timeout=300)
    finally:
        serial.close()
        swarm.swarm.shutdown()
    assert [outcome_fingerprint(o) for o in via_swarm] == [outcome_fingerprint(o) for o in via_serial] \
        == [outcome_fingerprint(o) for o in local]
    assert all(o.proposals == l.proposals for o, l in zip(via_swarm, local))
    for arranged in (via_swarm, via_serial[::-1]):  # landed in the order the swarm finished, or reversed
        config = live(taught_document)
        for n, o in enumerate(arranged, 1):
            land(config, o, n)
        assert config.diagnostics == []
        table = config.document.tables["slipnet_node_defs"]
        total = collections.Counter()
        for o in local:
            total.update(counts_of(o))
        assert total and {k[0]: v["noticings"] for k, v in table.items() if v["noticings"]} == dict(total)


# -- a session as it learns, on the serial route --------------------------------------------------------------


def session(doc, problems, seeds):
    """The serial route's session: each run takes the configuration as it is when it is dispatched, and its
    learning lands when it finishes.  Returns the live configuration and the outcomes."""
    config, outcomes = live(doc), []
    for n, (problem, seed) in enumerate(((p, s) for p in problems for s in seeds), 1):
        meta = cd.provider(config.document)
        outcome = run_task(SessionTask(*problem, None, seed, STEPS, None, "off"), meta)
        assert not outcome.error
        land(config, outcome, n)
        outcomes.append(outcome)
    assert config.diagnostics == []
    return config, outcomes


def test_a_session_that_meets_a_new_symbol_makes_it_a_trigger_after_the_first_run_and_notices_it_from_the_second(
        base_document):
    name = "plato-cp-%04x" % ord("ψ")
    problem = ("ψ", "ψ", "ψ")
    config, first = live(base_document), None
    meta = cd.provider(config.document)
    with counting_consolidators() as (ran, _):
        first = run_task(SessionTask(*problem, None, 1, STEPS, None, "off"), meta)
    assert not ran  # the symbol had no node, so no trigger: nothing to notice it in the first run
    assert {"op": "add_trigger", "rule_key": "consolidator", "node": name} in first.proposals
    land(config, first, 1)
    rule = config.document.tables["posting_rules"][("consolidator",)]
    assert name in rule["triggering_slipnodes"]
    assert name in json.loads(config.document.tables["engine_params"][("top_down_slipnodes",)]["value"])
    with counting_consolidators() as (ran, fizzled):
        second = run_task(SessionTask(*problem, None, 2, STEPS, None, "off"), cd.provider(config.document))
    assert ran[name] > 0 and counts_of(second)[name] == ran[name] - fizzled[name] > 0
    land(config, second, 2)
    assert config.document.tables["slipnet_node_defs"][(name,)]["noticings"] == counts_of(second)[name]


def test_a_second_run_that_proposes_the_same_trigger_leaves_one_entry_in_each_list(base_document):
    config = live(base_document)
    meta = cd.provider(config.document)
    first = run_task(SessionTask("ψ", "ψ", "ψ", None, 1, STEPS, None, "off"), meta)
    second = run_task(SessionTask("ψ", "ψ", "ψ", None, 2, STEPS, None, "off"), meta)  # same configuration
    assert [p for p in first.proposals if p["op"] == "add_trigger"] == [p for p in second.proposals
                                                                         if p["op"] == "add_trigger"] != []
    land(config, first, 1)
    result = land(config, second, 2)
    # the second run's ops are all duplicates: the learner skips them cleanly and applies nothing
    assert result.error is None and result.applied is False and config.diagnostics == []
    name = "plato-cp-03c8"
    doc = config.document
    assert list(doc.tables["posting_rules"][("consolidator",)]["triggering_slipnodes"]).count(name) == 1
    assert json.loads(doc.tables["engine_params"][("top_down_slipnodes",)]["value"]).count(name) == 1
    assert len([k for k in doc.tables["slipnet_node_defs"] if k == (name,)]) == 1


def test_depth_does_not_move_in_a_session_of_many_runs(base_document):
    problems = [("123", "123", "123"), ("12", "12", "12"), ("ace", "acg", "bdf"), ("ψ", "ψ", "ψ")]
    config, outcomes = session(base_document, problems, range(1, 9))
    depth = lambda doc: {k[0]: r["conceptual_depth"] for k, r in doc.tables["slipnet_node_defs"].items()}  # noqa: E731
    before, after = depth(base_document), depth(config.document)
    new_depth = int(base_document.tables["engine_params"][("new_node_conceptual_depth",)]["value"])
    discovered = {n for n in after if n not in before}
    assert discovered == {"plato-cp-%04x" % ord(c) for c in "123ψ"}
    assert {n: d for n, d in after.items() if n in before} == before  # every configured node keeps its depth
    assert {after[n] for n in discovered} == {new_depth}
    assert any(r["noticings"] for r in config.document.tables["slipnet_node_defs"].values())  # it did learn


def test_a_seed_letter_counts_its_noticings_and_gains_adjacent_links_in_the_base(base_document):
    config, outcomes = session(base_document, [("aceg", "acei", "bdfh")], [3, 4, 5])
    table = config.document.tables["slipnet_node_defs"]
    assert any(table[(f"plato-{c}",)]["noticings"] for c in "acegi")
    links = [(k, r["link_length"]) for k, r in config.document.tables["slipnet_link_defs"].items()
             if r["link_type"] == "adjacent"]
    assert links and all(k[3] == "plato-adjacent" and l <= 90 for k, l in links)
