"""What a run proposes reaches the session: every op kind, merging, and the pair-link accounting.

The in-worker learner submits **every** op a run proposed (``propose_ops`` as well as ``apply_ops``) through
``finish_run`` as its batch, ``rebase`` and ``skip``, one op per row, journaled as ``learner:in-worker``.  A
test configuration (``tests/support/proposing_configuration.py``) has a codelet whose body proposes the pair
``plato-a`` to ``plato-b`` the way the ``consolidator`` body does: ``add_link`` at ``L + s`` and ``adjust``
by ``-s``.  Whatever order the runs finish in, whichever route ran them, the link is ``L - s * (N - 1)``
long after ``N`` noticings.
"""

from __future__ import annotations

import itertools
import random

import pytest

from server.parallel.swarm import Swarm
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionOutcome, SessionTask, SwarmExecutor, outcome_fingerprint, run_task,
)
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService
from tests.support import proposing_configuration as pc

STEPS = 900
SEEDS = (1, 2, 3, 4, 5, 6)
PROBLEM = ("abc", "abd", "xyz")


def live(doc) -> LiveConfiguration:
    return LiveConfiguration(doc, configuration_id=0, revision=0, episode_version=0)


def land(config: LiveConfiguration, outcome, run: int = 1):
    """What the service does with a finished run's proposals."""
    batch = TrainingModeSessionService._proposal_batch(outcome)
    assert batch is not None
    return config.finish_run(memory_merge=lambda: None, batch=batch, run=(run, outcome.seed),
                             started_revision=0, learner=IN_WORKER_LEARNER)


def length(config, key=pc.PAIR):
    row = config.document.tables["slipnet_link_defs"].get(key)
    return None if row is None else row["link_length"]


def fake(seed, proposals) -> SessionOutcome:
    return SessionOutcome(seed=seed, status="answer_found", answer="x", answers=["x"], codelets=1, seconds=0.0,
                          stopping_state="answer_found:x", proposals=proposals)


@pytest.fixture(scope="module")
def pair_meta():
    return pc.noticer_provider(pc.PAIR_BODY)


@pytest.fixture(scope="module")
def pair_document():
    return pc.noticer_document(pc.PAIR_BODY)


@pytest.fixture(scope="module")
def tasks():
    return [SessionTask(*PROBLEM, None, seed, STEPS, None, "off") for seed in SEEDS]


@pytest.fixture(scope="module")
def outcomes(pair_meta, tasks):
    return [run_task(t, pair_meta) for t in tasks]


# -- every proposal reaches the session --------------------------------------------------------------------


def test_the_learner_submits_every_kind_of_op_and_a_second_run_skips_only_the_duplicates():
    doc = pc.noticer_document(pc.ALL_BODY)
    config = live(doc)
    ops = [
        {"op": "add_link_type", "name": "near", "display_label": "Near"},
        {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True, "length": 90.125},
        {"op": "adjust", "table": "slipnet_link_defs", "key": pc.PAIR_KEY, "field": "link_length", "by": -0.125},
        {"op": "add_link", "from": "plato-b", "to": "plato-c", "type": "near", "fixed": True, "length": 12.5},
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-b"}, "field": "noticings", "by": 3},
        {"op": "add_trigger", "rule_key": "top-down-description-scout", "node": "plato-b"},
    ]
    first = land(config, fake(1, ops), run=1)
    assert first.error is None and config.diagnostics == []
    tables = config.document.tables
    assert ("near",) in tables["link_types"]
    assert length(config) == 90 and type(length(config)) is int  # 90.125 - 0.125: whole again
    assert length(config, ("plato-b", "plato-c", "near", "")) == 12.5
    assert tables["slipnet_node_defs"][("plato-b",)]["noticings"] == 3
    assert "plato-b" in tables["posting_rules"][("top-down-description-scout",)]["triggering_slipnodes"]
    (entry,) = [c.pending for c in config.changes if c.pending.source == "learner"]
    assert entry.actor == f"learner:{IN_WORKER_LEARNER}"
    assert {op["table"] for op in entry.resolved} >= {"link_types", "slipnet_link_defs", "slipnet_node_defs", "posting_rules"}
    first_rows = len(entry.resolved)

    # the second run proposes the same: the type and the links are duplicates, the counts apply again
    second = land(config, fake(2, ops), run=2)
    assert second.error is None and config.diagnostics == []
    tables = config.document.tables  # a change makes a new document
    assert length(config) == 89.875 and tables["slipnet_node_defs"][("plato-b",)]["noticings"] == 6
    assert len([r for r in tables["link_types"] if r == ("near",)]) == 1
    later = config.changes[-1].pending
    assert {(op["table"], op["op"]) for op in later.resolved} == {
        ("slipnet_link_defs", "update"), ("slipnet_node_defs", "update")}
    assert len(later.resolved) < first_rows


def test_under_skip_a_refused_op_is_dropped_and_the_rest_of_the_batch_applies():
    config = live(pc.noticer_document(pc.PAIR_BODY))
    ops = [
        {"op": "add_link", "from": "plato-a", "to": "no-such-node", "type": "adjacent", "fixed": True, "length": 5},
        {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True, "length": float("nan")},
        {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "no-such-type", "fixed": True, "length": 5},
        {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True, "length": 90.125},
        {"op": "adjust", "table": "slipnet_link_defs", "key": pc.PAIR_KEY, "field": "link_length", "by": float("inf")},
        {"op": "adjust", "table": "slipnet_link_defs", "key": pc.PAIR_KEY, "field": "link_length", "by": -0.125},
        {"op": "adjust", "table": "slipnet_link_defs", "key": {**pc.PAIR_KEY, "to_node": "plato-z"}, "field": "link_length", "by": 1},
    ]
    result = land(config, fake(1, ops))
    assert result.error is None and config.diagnostics == []
    assert length(config) == 90
    assert [r for r in config.document.tables["slipnet_link_defs"].values()
            if r["link_type"] == "adjacent" and r["to_node"] != "plato-b"] == []


# -- merging ------------------------------------------------------------------------------------------------


def test_link_type_merge_two_runs_propose_one_type_one_row_and_both_proposals_are_on_record():
    config = live(pc.noticer_document(pc.ALL_BODY))
    kind = {"op": "add_link_type", "name": "near", "display_label": "Near"}
    first, second = fake(1, [kind]), fake(2, [dict(kind)])
    assert first.proposals == second.proposals == [kind]  # on record: each run's outcome carries its proposal
    land(config, first, run=1)
    land(config, second, run=2)
    assert [k for k in config.document.tables["link_types"] if k == ("near",)] == [("near",)]
    assert len([c for c in config.changes if c.pending.source == "learner"]) == 1  # the second applied nothing
    assert config.diagnostics == []


def test_link_merge_two_runs_propose_the_same_link_one_row_and_both_proposals_are_on_record():
    config = live(pc.noticer_document(pc.PAIR_BODY))
    add = {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "adjacent", "fixed": True, "length": 40}
    first, second = fake(1, [add]), fake(2, [dict(add)])
    assert first.proposals == second.proposals == [add]
    land(config, first, run=1)
    land(config, second, run=2)
    links = [k for k, r in config.document.tables["slipnet_link_defs"].items()
             if (r["from_node"], r["to_node"], r["link_type"]) == ("plato-a", "plato-c", "adjacent")]
    assert len(links) == 1 and length(config, links[0]) == 40
    assert config.diagnostics == []


# -- the pair-link accounting ---------------------------------------------------------------------------------


def test_each_run_proposes_the_pair_once_and_sums_its_noticings(outcomes):
    assert all(not o.error for o in outcomes)
    for o in outcomes:
        assert [p["op"] for p in o.proposals] == ["add_link", "adjust"]
        assert o.proposals[0]["length"] == pc.LENGTH + pc.STEP
        assert o.proposals[1]["by"] == -pc.STEP * pc.noticings_of(o)
    assert len({pc.noticings_of(o) for o in outcomes}) > 1  # the runs noticed the pair different numbers of times


def expected(counts, start=None):
    """``L - s * (N - 1)``, or from a link that already held ``start`` noticings."""
    noticings = sum(counts) + (start or 0)
    return pc.LENGTH - pc.STEP * (noticings - 1)


@pytest.mark.parametrize("order", ["forward", "reverse", "shuffled-1", "shuffled-2"])
def test_the_link_is_L_minus_s_times_N_minus_1_in_any_order(pair_document, outcomes, order):
    arranged = list(outcomes)
    if order == "reverse":
        arranged.reverse()
    elif order.startswith("shuffled"):
        random.Random(int(order[-1])).shuffle(arranged)
    config = live(pair_document)
    for n, o in enumerate(arranged, 1):
        land(config, o, run=n)
        assert length(config) == expected([pc.noticings_of(x) for x in arranged[:n]])
    assert config.diagnostics == []
    final = length(config)
    assert final == expected([pc.noticings_of(o) for o in outcomes])
    # the first run alone leaves the link at 90 - s * (n1 - 1): one noticing is 90 exactly
    one = live(pair_document)
    land(one, fake(1, [{"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True,
                        "length": 90.125},
                       {"op": "adjust", "table": "slipnet_link_defs", "key": pc.PAIR_KEY, "field": "link_length",
                        "by": -0.125}]))
    assert length(one) == 90 and type(length(one)) is int


def test_every_order_of_a_few_runs_gives_the_same_length(pair_document, outcomes):
    for subset in itertools.permutations(outcomes[:4]):
        config = live(pair_document)
        for n, o in enumerate(subset, 1):
            land(config, o, run=n)
        assert length(config) == expected([pc.noticings_of(o) for o in subset])


def test_when_the_link_already_exists_when_a_run_starts_its_noticings_are_added_to_the_count(pair_document, outcomes):
    for start in (1, 3, 11):  # the link already holds `start` noticings: it is L - s * (start - 1) long
        seed_ops = [{"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True,
                     "length": pc.LENGTH - pc.STEP * (start - 1)}]
        for arranged in (outcomes, outcomes[::-1]):
            config = live(pair_document)
            config.finish_run(memory_merge=lambda: None, batch={"ops": seed_ops, "base_mode": "rebase"},
                              run=(0, 0), started_revision=0, learner=IN_WORKER_LEARNER)
            assert length(config) == pc.LENGTH - pc.STEP * (start - 1)
            for n, o in enumerate(arranged, 1):
                land(config, o, run=n)
            assert length(config) == expected([pc.noticings_of(o) for o in outcomes], start)
            assert config.diagnostics == []


def test_serial_child_swarm_and_in_process_agree_on_a_run_that_proposes_links_and_adjusts(pair_meta, tasks, outcomes):
    serial = SerialExecutor()
    swarm = SwarmExecutor(Swarm(workers=2, meta=pair_meta))
    try:
        via_serial = serial.submit(tasks, pair_meta).result(timeout=300)
        via_swarm = swarm.submit(tasks, pair_meta).result(timeout=300)
    finally:
        serial.close()
        swarm.swarm.shutdown()
    assert [outcome_fingerprint(o) for o in via_swarm] == [outcome_fingerprint(o) for o in via_serial] \
        == [outcome_fingerprint(o) for o in outcomes]
    assert not any(o.error for o in via_swarm + via_serial)
    assert all(o.proposals == local.proposals for o, local in zip(via_swarm, outcomes))
    # landed in the order the swarm finished them, the link is the same as in any other order
    config = live(pc.noticer_document(pc.PAIR_BODY))
    for n, o in enumerate(via_swarm, 1):
        land(config, o, run=n)
    assert length(config) == expected([pc.noticings_of(o) for o in via_swarm])
