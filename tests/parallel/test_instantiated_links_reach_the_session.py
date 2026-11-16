"""What an instantiator built in a run reaches the session, and the pair-link accounting with instantiators.

A test configuration (``tests/support/proposing_configuration.py``) has a codelet whose body proposes the pair
``plato-a`` to ``plato-b`` for the instantiator ``pair-instantiator``, every time it runs, in the shape the
``consolidator`` body uses (``add_link`` at ``L / r`` and ``scale`` by ``r = 1 - s / L``, ``L`` = 90, ``s`` = 1/16),
and counts each proposal with a plain ``adjust``.  The instantiator builds whatever it takes.  Some proposals are
built before the turn ends and some are not (an instantiator waits on the Coderack at its urgency), so a run's
``B`` is how many noticings' changes were built: its recorded ``scale`` factor is ``r ** B``.  Whatever order the
runs finish in, whichever route ran them, and whether or not the link existed when the runs started, the
session's link is ``L * r ** (B - 1)`` long, with ``B`` summed over the runs (or ``L * r ** (B + start - 1)`` from
a link that already held ``start``), to a relative error of ``pc.TOLERANCE``.  The run's own Slipnet holds the same
length at the end of the run when the session's configuration did not change in between.
"""

from __future__ import annotations

import itertools
import random
from types import SimpleNamespace

import pytest

from server.engine.runner import EngineRunner
from server.parallel.swarm import Swarm
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionTask, SwarmExecutor, outcome_fingerprint, run_task,
)
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService
from tests.support import proposing_configuration as pc

pytestmark = pytest.mark.numeric_matrix

STEPS = 900
SEEDS = (1, 2, 3, 4, 5, 6)
PROBLEM = ("abc", "abd", "xyz")
ERRORS: list[float] = []


def live(doc) -> LiveConfiguration:
    return LiveConfiguration(doc, configuration_id=0, revision=0, episode_version=0)


def land(config: LiveConfiguration, outcome, run: int = 1):
    batch = TrainingModeSessionService._proposal_batch(outcome)
    assert batch is not None
    return config.finish_run(memory_merge=lambda: None, batch=batch, run=(run, outcome.seed),
                             started_revision=0, learner=IN_WORKER_LEARNER)


def length(config, key=pc.PAIR):
    row = config.document.tables["slipnet_link_defs"].get(key)
    return None if row is None else row["link_length"]


def same(got, want):
    assert got > 0
    error = abs(got - want) / want
    assert error <= pc.TOLERANCE, (got, want, error)
    ERRORS.append(error)


@pytest.fixture(scope="module")
def meta():
    return pc.instantiating_provider()


@pytest.fixture(scope="module")
def document():
    return pc.instantiating_document()


@pytest.fixture(scope="module")
def tasks():
    return [SessionTask(*PROBLEM, None, seed, STEPS, None, "off") for seed in SEEDS]


@pytest.fixture(scope="module")
def outcomes(meta, tasks):
    return [run_task(t, meta) for t in tasks]


def built(outcomes):
    return [pc.noticings_of(o) for o in outcomes]


# -- one run -----------------------------------------------------------------------------------------------------------


def test_a_run_records_the_pair_once_with_the_noticings_whose_changes_were_built_and_drops_the_rest(outcomes):
    assert all(not o.error for o in outcomes)
    proposed = [pc.proposed_of(o) for o in outcomes]
    b = built(outcomes)
    assert all(0 <= x <= n for x, n in zip(b, proposed)) and sum(b) > 0
    assert any(x < n for x, n in zip(b, proposed)), "some proposals were still held at the end of a turn and dropped"
    assert len(set(b)) > 1, "the runs built different numbers of noticings"
    for o in outcomes:
        links = [p for p in o.proposals if p["op"] == "add_link"]
        scales = [p for p in o.proposals if p["op"] == "scale"]
        assert len(links) == len(scales) == (1 if pc.noticings_of(o) else 0)  # one of each, or nothing was built
        assert not any(p["op"] == "scale" and p["factor"] == 1 for p in o.proposals)


def test_the_runs_own_slipnet_holds_the_length_the_session_will_hold(meta, tasks):
    for task in tasks[:4]:
        runner = EngineRunner(meta)
        runner.init_mcat(task.initial, task.modified, task.target, None, seed=task.seed)
        runner.run_mcat(max_steps=STEPS)
        ctx = runner.ctx
        link = ctx.slipnet.find_link("plato-a", "plato-b", "adjacent", None)
        recorded = {p["op"]: p for p in ctx.proposals if p["op"] in ("add_link", "scale")}
        if link is None:
            assert not recorded
            continue
        # the link the session gets: the recorded add_link's length times the recorded scale factor
        want = recorded["add_link"]["length"] * recorded["scale"]["factor"]
        same(link.link_length(), want)
        same(link.link_length(), pc.expected_length(pc.noticings_of(SimpleNamespace(proposals=ctx.proposals))))


# -- the accounting, in any order, on every route ------------------------------------------------------------------------


@pytest.mark.parametrize("order", ["forward", "reverse", "shuffled-1", "shuffled-2"])
def test_the_session_link_is_L_times_r_to_the_B_minus_1_in_any_order(document, outcomes, order):
    arranged = [o for o in outcomes if pc.noticings_of(o)]
    if order == "reverse":
        arranged.reverse()
    elif order.startswith("shuffled"):
        random.Random(int(order[-1])).shuffle(arranged)
    config = live(document)
    for n, o in enumerate(arranged, 1):
        land(config, o, run=n)
        same(length(config), pc.expected_length(sum(built(arranged[:n]))))
    assert config.diagnostics == []
    final = length(config)
    same(final, pc.expected_length(sum(built(outcomes))))
    assert 0 < final < pc.LENGTH


def test_a_run_that_built_nothing_leaves_the_session_untouched_apart_from_its_count(document, outcomes):
    empty = [o for o in outcomes if not pc.noticings_of(o)]
    config = live(document)
    for o in empty:
        land(config, o)
    assert length(config) is None
    assert config.diagnostics == []


def test_every_order_of_four_runs_gives_the_same_length(document, outcomes):
    chosen = [o for o in outcomes if pc.noticings_of(o)][:4]
    for subset in itertools.permutations(chosen):
        config = live(document)
        for n, o in enumerate(subset, 1):
            land(config, o, run=n)
        same(length(config), pc.expected_length(sum(built(subset))))


def test_when_the_link_already_exists_when_a_run_starts_the_built_noticings_are_added_to_the_count(document, outcomes):
    chosen = [o for o in outcomes if pc.noticings_of(o)]
    for start in (1, 3, 11):  # the link already holds `start` noticings: it is L * r ** (start - 1) long
        seed_ops = [{"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True,
                     "length": pc.expected_length(start)}]
        for arranged in (chosen, chosen[::-1]):
            config = live(document)
            config.finish_run(memory_merge=lambda: None, batch={"ops": seed_ops, "base_mode": "rebase"},
                              run=(0, 0), started_revision=0, learner=IN_WORKER_LEARNER)
            assert length(config) == pytest.approx(pc.expected_length(start), rel=pc.TOLERANCE)
            for n, o in enumerate(arranged, 1):
                land(config, o, run=n)
            same(length(config), pc.expected_length(sum(built(chosen)) + start))
            assert config.diagnostics == []


def test_runs_that_start_with_the_link_in_their_slipnet_build_by_scaling_it(document, outcomes):
    """A run that starts from a configuration that has the link (at ``start`` noticings) scales that link in its own
    Slipnet, and what it records, applied to a session that has the link, gives the same length."""
    start = 7
    ops = [{"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "adjacent", "fixed": True,
            "length": pc.expected_length(start)}]
    from server.services import config_document as cd
    from server.services.change_resolve import resolve

    resolved, _ = resolve(document, {"ops": ops})
    started_doc = cd.apply_resolved(document, resolved)
    started = cd.provider(started_doc)
    config = live(started_doc)
    total = 0
    for seed in SEEDS[:4]:
        o = run_task(SessionTask(*PROBLEM, None, seed, STEPS, None, "off"), started)
        assert not o.error
        total += pc.noticings_of(o)
        land(config, o, run=seed)
    same(length(config), pc.expected_length(total + start))


def test_serial_child_swarm_and_in_process_agree_and_land_in_any_order(meta, tasks, outcomes):
    serial = SerialExecutor()
    swarm = SwarmExecutor(Swarm(workers=2, meta=meta))
    try:
        via_serial = serial.submit(tasks, meta).result(timeout=300)
        via_swarm = swarm.submit(tasks, meta).result(timeout=300)
    finally:
        serial.close()
        swarm.swarm.shutdown()
    assert [outcome_fingerprint(o) for o in via_swarm] == [outcome_fingerprint(o) for o in via_serial] \
        == [outcome_fingerprint(o) for o in outcomes]
    assert not any(o.error for o in via_swarm + via_serial)
    assert all(o.proposals == local.proposals for o, local in zip(via_swarm, outcomes))
    for route in (via_swarm, via_serial[::-1]):
        config = live(pc.instantiating_document())
        for n, o in enumerate([o for o in route if pc.noticings_of(o)], 1):
            land(config, o, run=n)
        same(length(config), pc.expected_length(sum(built(route))))
