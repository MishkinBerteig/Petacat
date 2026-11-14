"""A configuration with fractional link lengths on every numeric engine.

``off``, ``python``, ``numpy``, ``mlx-cpu`` and ``mlx`` agree in answers, codelets, draws, temperature and
every node's activation on a configuration whose links have fractional lengths, among them lengths reached
by repeated addition (``90 - 0.125 * n``) and lengths that are not exact in binary.  The Slipnet's rounding
is unchanged: a fractional spread is rounded as a whole one is.  ``float32_exactness_problem`` reads only
the activation ceiling, the full-activation threshold and the spread scale, never a link length, so it
gives the same answer for these configurations as for the Standard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends
from server.engine.numeric.backend import float32_exactness_problem, use_backend
from server.engine.runner import EngineRunner
from server.engine.numeric.layout import SlipnetTopology
from server.engine.slipnet import Slipnet
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve

pytestmark = pytest.mark.numeric_matrix

SEED_DATA = str(Path(__file__).resolve().parents[2] / "seed_data")
BACKENDS = ["off", "python", "numpy", "mlx-cpu", "mlx"]
LETTERS = "abcdefghij"
PROBLEMS = [("abc", "abd", "xyz"), ("aceg", "acei", "bdfh"), ("abc", "abd", "ijk")]


def provider(forward, backward) -> MetadataProvider:
    """The v2.0 Base plus an ``adjacent`` link between neighbouring letters in both directions, with the
    lengths ``forward(n)`` and ``backward(n)``."""
    doc = tb.resolve_base().document
    ops = []
    for n, (x, y) in enumerate(zip(LETTERS, LETTERS[1:]), 1):
        for src, dst, length in ((x, y, forward(n)), (y, x, backward(n))):
            ops.append({"op": "add_link", "from": f"plato-{src}", "to": f"plato-{dst}", "type": "adjacent",
                        "fixed": True, "length": length})
    resolved, _ = resolve(doc, {"ops": ops})
    return cd.provider(cd.apply_resolved(doc, resolved))


@pytest.fixture(scope="module")
def dyadic() -> MetadataProvider:
    # a length reached by repeated addition, 90 - 0.125 * k, and a long one 37 steps down
    length = 90.0
    reached = []
    for _ in range(40):
        length -= 0.125
        reached.append(length)
    return provider(lambda n: reached[n - 1] - 0.125 * 37 * n / 10, lambda n: reached[n * 3 % 40])


@pytest.fixture(scope="module")
def inexact() -> MetadataProvider:
    return provider(lambda n: 37.3 + n * 3.1, lambda n: 22.7 + n * 1.37)


def run(meta, backend, problem, seed, steps=800):
    runner = EngineRunner(meta)
    with use_backend(None if backend == "off" else backend):
        runner.init_mcat(*problem, None, seed=seed)
        runner.run_mcat(max_steps=steps)
    ctx = runner.ctx
    answer = ctx.workspace.answer_string
    return {
        "status": runner.status, "answer": answer.text if answer else "", "codelets": ctx.codelet_count,
        "draws": ctx.rng.call_count, "temperature": float(ctx.temperature.value),
        "activations": [n.activation for n in ctx.slipnet.nodes.values()],
        "proposals": list(ctx.proposals),
    }


_REFERENCE: dict = {}


def reference(meta, problem, seed):
    key = (id(meta), problem, seed)
    if key not in _REFERENCE:
        _REFERENCE[key] = run(meta, "off", problem, seed)
    return _REFERENCE[key]


def check(meta, backend, seeds=(1, 2, 3)):
    if backend not in ("off", *available_backends()):
        pytest.skip(f"{backend} is not available")
    for problem in PROBLEMS:
        for seed in seeds:
            assert run(meta, backend, problem, seed) == reference(meta, problem, seed), (backend, problem, seed)


@pytest.mark.parametrize("backend", BACKENDS[1:])
def test_every_engine_agrees_on_fractional_link_lengths_reached_by_repeated_addition(dyadic, backend):
    check(dyadic, backend)


@pytest.mark.parametrize("backend", BACKENDS[1:])
def test_every_engine_agrees_on_lengths_that_are_not_exact_in_binary(inexact, backend):
    check(inexact, backend)


def test_the_fractional_lengths_are_what_the_engine_reads(dyadic):
    lengths = {l.link_length() for n in Slipnet.from_metadata(dyadic).nodes.values() for l in n.outgoing_links
               if l.link_type == "adjacent"}
    assert lengths and any(x != int(x) for x in lengths) and min(lengths) < 90
    standard = tb.resolve_base().document
    assert run(provider(lambda n: 1000, lambda n: 1000), "off", PROBLEMS[0], 1) != run(dyadic, "off", PROBLEMS[0], 1)
    assert cd.provider(standard) != dyadic


class _NeverJumps:
    def __init__(self):
        self.call_count = 0

    def prob(self, p):
        self.call_count += 1
        return False


def spread(meta, backend, cycles=1):
    slipnet = Slipnet.from_metadata(meta)
    slipnet.nodes["plato-a"].activation = 100.0
    rng = _NeverJumps()
    with use_backend(None if backend == "off" else backend):
        for _ in range(cycles):
            slipnet.update_activations(rng, threshold=100)
    return {n: node.activation for n, node in slipnet.nodes.items()}


@pytest.mark.parametrize("backend", BACKENDS[1:])
def test_a_fractional_link_spreads_the_same_on_every_engine_and_is_rounded_as_a_whole_one_is(dyadic, inexact, backend):
    if backend not in available_backends():
        pytest.skip(f"{backend} is not available")
    for meta in (dyadic, inexact):
        got = spread(meta, backend)
        assert got == spread(meta, "off")
    reference = spread(dyadic, "off")
    # plato-b: reached through a fractional link, and its activation is a whole number (the Slipnet rounds)
    assert reference["plato-b"] > 0 and all(v == int(v) for v in reference.values())


def test_the_float32_guard_does_not_read_link_lengths_so_it_answers_as_it_does_for_the_standard(dyadic, inexact):
    """What ``float32_exactness_problem`` does with a fractional configuration: nothing different.  Its
    inputs are the activation ceiling, the full-activation threshold and the spread scale, which a link
    length does not touch, so the guard neither refuses these configurations nor changes its answer."""
    standard = Slipnet.from_metadata(MetadataProvider.from_standard_configuration(SEED_DATA))

    def problem(slipnet):
        topology = SlipnetTopology.from_slipnet(slipnet)
        scale = slipnet.update_cycle_length / slipnet.reference_update_cycle_length
        return topology.activation, float32_exactness_problem(topology.activation, scale)

    reference = problem(standard)
    assert reference[1] is None
    for meta in (dyadic, inexact):
        assert problem(Slipnet.from_metadata(meta)) == reference
