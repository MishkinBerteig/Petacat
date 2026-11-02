"""G9 completed (EN11): the engine on every reduced configuration.

For each configuration a run is built on a demo problem and a bounded number of codelets is
stepped.  Nothing may raise except the named run-start message (``RunStartError``,
``ABSENCE-BEHAVIOUR.md`` section 4).

* every one of the 59 nodes removed one at a time with its cascade;
* random subsets of nodes (fixed seeds and sizes; a failing case is reproduced from
  ``subset(seed, size)``), each node removed with its cascade;
* a justify-mode problem in every case;
* Episodic Memory carried from a Metacat Standard Configuration run into the reduced one;
* a small Swarm call (two workers) under a-d/w-z and with ``plato-opposite`` removed.

The default suite runs a rotating sample of the demo problems per configuration; the whole
sweep (every demo problem) is ``@pytest.mark.slow`` like the older G9 sweeps and runs with
``-m slow`` or in a full run.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from server.engine.memory import EpisodicMemory
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.engine.start_check import RunStartError
from tests.support import configuration_cascade as cascade
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc

#: Bounded codelet counts: the default suite's sample, and the slow sweep's longer runs.
STEPS, JUSTIFY_STEPS = 600, 1000
FULL_STEPS, FULL_JUSTIFY_STEPS = 1500, 2500
CARRY_STEPS = 1000
SAMPLE = 2  # discovery problems per configuration in the default suite

TRIPLES, JUSTIFY = gb.demo_problems()
NODES = cascade.node_names(cascade.load_documents())
assert len(NODES) == 59

#: Cases known to fail: ``case id -> "G9-<n>: one line"``.  Each is an exact-case strict xfail.
KNOWN: dict[str, str] = {}


def _mark(case_id: str):
    reason = KNOWN.get(case_id)
    return [pytest.mark.xfail(strict=True, reason=reason)] if reason else []


def step_run(provider, problem, answer=None, seed=1, steps=STEPS, memory=None) -> EngineRunner | None:
    """Build a run and step it; only ``RunStartError`` is allowed to stop it (returns None)."""
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        try:
            kw = {"memory": memory} if memory is not None else {}
            runner.init_mcat(*problem, answer=answer, seed=seed, rng=RNG(seed), **kw)
        except RunStartError:
            return None
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break
        assert_unperceived_symbols(runner, problem)
    return runner


def assert_unperceived_symbols(runner: EngineRunner, problem) -> None:
    """A symbol with no node is not perceived: its letter has no category and no description
    names it; a symbol with a node is perceived as exactly that node."""
    slipnet, workspace = runner.ctx.slipnet, runner.ctx.workspace
    glyphs = slipnet.alphabet.glyph_nodes
    strings = {"initial": workspace.initial_string, "modified": workspace.modified_string,
               "target": workspace.target_string}
    for text, string in zip(problem, strings.values()):
        letters = [o for o in string.objects if hasattr(o, "letter_category")]
        assert [o.letter_category for o in letters] == [glyphs.get(c) for c in text]
        for obj in letters:
            if obj.letter_category is not None:
                assert slipnet.nodes[obj.letter_category.name] is obj.letter_category
            for d in obj.descriptions:
                assert d.descriptor is not None
                assert slipnet.nodes.get(getattr(d.descriptor, "name", None)) is d.descriptor


def _problems(index: int, everything: bool):
    if everything:
        return list(TRIPLES), list(JUSTIFY)
    picks = [TRIPLES[(index * SAMPLE + k) % len(TRIPLES)] for k in range(SAMPLE)]
    return picks, [JUSTIFY[index % len(JUSTIFY)]]


def run_configuration(reduced: rc.Reduced, index: int = 0, everything: bool = False) -> None:
    provider = rc.provider(reduced)
    triples, justify = _problems(index, everything)
    steps, jsteps = (FULL_STEPS, FULL_JUSTIFY_STEPS) if everything else (STEPS, JUSTIFY_STEPS)
    for problem in triples:
        step_run(provider, problem, steps=steps)
    for problem, answer in justify:
        step_run(provider, problem, answer=answer, steps=jsteps)


def subset(seed: int, size: int) -> list[str]:
    """The nodes a random subset removes: deterministic in ``(seed, size)``."""
    return sorted(random.Random(seed).sample(NODES, size))


def subset_configuration(seed: int, size: int) -> rc.Reduced:
    return rc._apply(f"subset seed={seed} size={size}", nodes=subset(seed, size))


# --- every node removed ------------------------------------------------------------------

@pytest.mark.parametrize(
    "index,node", [pytest.param(i, n, id=n, marks=_mark(f"node:{n}")) for i, n in enumerate(NODES)])
def test_g9_each_node_removed_runs_a_sample_of_demos(index, node) -> None:
    run_configuration(rc.node_removed(node), index)


@pytest.mark.slow
@pytest.mark.parametrize(
    "index,node", [pytest.param(i, n, id=n, marks=_mark(f"node-all:{n}")) for i, n in enumerate(NODES)])
def test_g9_each_node_removed_runs_every_demo(index, node) -> None:
    run_configuration(rc.node_removed(node), index, everything=True)


# --- the plan's named configurations on every demo problem -----------------------------

@pytest.mark.parametrize("name", ["a-d/w-z", "ladder-gap", "no-alphabet-successor"])
def test_g9_named_configuration_runs_every_demo_with_unperceived_symbols(name) -> None:
    reduced = {"a-d/w-z": rc.a_d_w_z, "ladder-gap": rc.ladder_with_gap,
               "no-alphabet-successor": lambda: rc.node_removed("plato-successor")}[name]()
    provider = rc.provider(reduced)
    for problem in TRIPLES:
        step_run(provider, problem)
    for problem, answer in JUSTIFY[:3]:
        step_run(provider, problem, answer=answer, steps=JUSTIFY_STEPS)


# --- random subsets ----------------------------------------------------------------------

SUBSET_SEEDS = (11, 23, 37)
SUBSET_SIZES = (3, 8, 15, 30)
SUBSET_CASES = [(s, n) for s in SUBSET_SEEDS for n in SUBSET_SIZES]


def test_subsets_are_deterministic_and_distinct() -> None:
    assert subset(11, 8) == subset(11, 8)
    assert len(set(subset(11, 8))) == 8
    assert subset(11, 8) != subset(23, 8)


@pytest.mark.parametrize(
    "seed,size", [pytest.param(s, n, id=f"seed{s}-size{n}", marks=_mark(f"subset:{s}:{n}"))
                  for s, n in SUBSET_CASES])
def test_g9_random_subset_runs_a_sample_of_demos(seed, size) -> None:
    run_configuration(subset_configuration(seed, size), seed + size)


@pytest.mark.slow
@pytest.mark.parametrize(
    "seed,size", [pytest.param(s, n, id=f"seed{s}-size{n}", marks=_mark(f"subset-all:{s}:{n}"))
                  for s in (11, 23, 37, 41, 53, 67) for n in (2, 5, 10, 20, 30, 40, 50)])
def test_g9_random_subset_runs_every_demo(seed, size) -> None:
    run_configuration(subset_configuration(seed, size), seed + size, everything=True)


# --- Episodic Memory carried across ------------------------------------------------------

CARRY_PROBLEM = ("abc", "abd", "ijk")
CARRY_NODES = ["plato-successor", "plato-opposite", "plato-rightmost", "plato-letter-category",
               "plato-string-position-category", "plato-identity", "plato-a", "plato-sameness"]


@pytest.fixture(scope="module")
def carried():
    memory = EpisodicMemory()
    standard = rc.provider(rc.standard())
    for seed in (1, 2):
        step_run(standard, CARRY_PROBLEM, seed=seed, steps=CARRY_STEPS * 3, memory=memory)
    assert memory.answers
    return memory


def _copy(memory):
    clone = EpisodicMemory()
    clone.answers = [replace(a) for a in memory.answers]
    clone.snags = [replace(s) for s in memory.snags]
    clone.ids = memory.ids
    return clone


@pytest.mark.parametrize(
    "node", [pytest.param(n, id=n, marks=_mark(f"carry:{n}")) for n in CARRY_NODES if n in NODES])
def test_g9_memory_carried_into_a_reduced_configuration(carried, node) -> None:
    provider = rc.provider(rc.node_removed(node))
    step_run(provider, CARRY_PROBLEM, seed=5, steps=CARRY_STEPS, memory=_copy(carried))


# --- the parallel run mode ---------------------------------------------------------------

@pytest.mark.parametrize(
    "reduced_name", [pytest.param("a-d/w-z", marks=_mark("swarm:a-d-w-z")),
                     pytest.param("no-opposite", marks=_mark("swarm:no-opposite"))])
def test_g9_a_small_swarm_call_under_a_reduced_configuration(reduced_name) -> None:
    from server.parallel.swarm import Swarm

    reduced = rc.a_d_w_z() if reduced_name == "a-d/w-z" else rc.node_removed("plato-opposite")
    problem = ("abc", "abd", "ijk") if reduced_name != "a-d/w-z" else ("abc", "abd", "dcb")
    meta = rc.provider(reduced)
    with Swarm(workers=2, meta=meta) as swarm:
        outcomes = swarm.run_seeds(*problem, seeds=[1, 2, 3, 4], max_steps=300, meta=meta)
    assert len(outcomes) == 4
    assert [o.error for o in outcomes] == [None] * 4
