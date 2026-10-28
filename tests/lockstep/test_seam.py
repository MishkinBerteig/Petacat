"""The engine seam changes nothing for an ordinary run (spec §6.5).

The numbers below were measured on the engine *before* the seam was added (with the
whole-number ``~`` of A-1 already in place, since that fix deliberately changes the
stream): same seed, same answer, same codelet count and same number of draws.
"""

from __future__ import annotations

import pytest

from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG, TraceSeam
from tests.lockstep.faithful import _metadata

pytestmark = pytest.mark.lockstep

#: (problem, seed, cap) -> (codelets run, RNG.call_count, answers, status)
BEFORE_THE_SEAM = {
    (("abc", "abd", "xyz"), 1, 3000): (683, 5031, ["xyz"], "answer_found"),
    (("abc", "abd", "xyz"), 2, 3000): (2285, 16758, ["wyz"], "answer_found"),
    (("abc", "abd", "ijk"), 3, 2000): (467, 3509, ["ijl"], "answer_found"),
    (("abc", "abd", "mrrjjj"), 4, 2500): (1068, 9038, ["mrrkkk"], "answer_found"),
}


@pytest.mark.parametrize("case", sorted(BEFORE_THE_SEAM))
def test_an_ordinary_run_draws_exactly_as_it_did_before_the_seam(case):
    from server.engine.runner import EngineRunner

    problem, seed, cap = case
    runner = EngineRunner(_metadata())
    with use_backend("off"):
        runner.init_mcat(*problem, seed=seed)
        result = runner.run_mcat(max_steps=cap)
    got = (runner.ctx.codelet_count, runner.ctx.rng.call_count, result.answers, runner.status)
    assert got == BEFORE_THE_SEAM[case]


def test_the_seam_methods_of_a_plain_rng_do_nothing():
    rng = RNG(1)
    assert isinstance(rng, TraceSeam)
    assert rng.trace_unit(3, "codelet", "x") is None
    assert rng.trace_about("anything") is None
    rng.trace_restore(None)
    rng.trace_snapshot(object())
    assert rng.call_count == 0


def test_composite_choice_on_a_plain_rng_just_runs_the_pick():
    rng = RNG(1)

    def build():
        raise AssertionError("an ordinary RNG never describes the choice")

    assert rng.composite_choice("choose", build, lambda: "picked") == "picked"
    assert rng.call_count == 0


def test_init_mcat_hands_the_given_rng_to_the_context_and_the_coderack():
    from server.engine.runner import EngineRunner

    mine = RNG(99)
    runner = EngineRunner(_metadata())
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, rng=mine)
    assert runner.ctx.rng is mine and runner.ctx.coderack.rng is mine
    runner.step_mcat()
    assert mine.call_count > 0  # the first codelet's draws came from it, not from RNG(1)


# -- the clamp-expiry switch (spec §6.1, README step 6, run.ss:151-154) ---------------


def _step_to(runner, count):
    while runner.ctx.codelet_count < count:
        runner.step_mcat()


def _initial_nodes(runner):
    return [runner.ctx.slipnet.nodes[n] for n in
            ("plato-letter-category", "plato-string-position-category")]


def test_the_default_clamp_lapses_on_an_update_cycle_countdown():
    from server.engine.runner import EngineRunner

    runner = EngineRunner(_metadata())
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=2)
    assert all(n.frozen and n.clamp_cycles_remaining == 50 for n in _initial_nodes(runner))
    assert runner._initial_unclamp_time == 0


def test_faithful_clamp_holds_until_metacats_fixed_unclamp_time():
    from server.engine.runner import EngineRunner
    from tests.lockstep.faithful import FAITHFUL_PARAMETERS

    runner = EngineRunner(_metadata())
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=2, parameters=dict(FAITHFUL_PARAMETERS))
        # no countdown: the nodes are frozen until the codelet count reaches 50 x 15
        assert runner._initial_unclamp_time == 750
        assert all(n.frozen and n.clamp_cycles_remaining == 0 for n in _initial_nodes(runner))
        _step_to(runner, 749)
        assert all(n.frozen for n in _initial_nodes(runner))
        runner.step_mcat()
        assert runner.ctx.codelet_count == 750
        assert not any(n.frozen for n in _initial_nodes(runner))
