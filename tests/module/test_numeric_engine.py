"""The engine computes the same thing with the numeric substrate engaged.

The backend agreement tests in ``tests/unit/test_numeric_backends.py`` compare the
backends against each other on arrays.  These compare the *engine* against itself:
a whole run with the substrate forced on, against the same run with it off.  The
distinction matters because the substrate does not only replace arithmetic — it
also reorders the object-value update into three phases and batches structure
strengths per string, and neither of those is visible from an array comparison.

The standard for the float64 backends is bit-identity of the whole run: same
answer, same codelet count, same number of random draws.  That is a much stronger
statement than "the expected range is unchanged", and it is available here because
those backends compute in the reference's precision.  The float32 GPU backend
cannot meet it and is not asked to; what it is asked for is that its runs are
*valid* runs, which is the expected-range oracle's question and is checked in
``tests/module/test_expected_range.py``.
"""

from __future__ import annotations

import copy
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends, get_backend
from server.engine.numeric.backend import select_backend, use_backend
from server.engine.runner import EngineRunner

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED_DIR = os.path.join(REPO_ROOT, "seed_data")

#: Enough problems to reach the parts of the engine that differ: a grouped target
#: (``mrrjjj``) builds groups and therefore batched group strengths, and a snag
#: problem (``xyz``) reaches the jootsing and clamping paths.
PROBLEMS = [
    ("abc", "abd", "xyz"),
    ("abc", "abd", "mrrjjj"),
    ("abc", "abd", "ijk"),
]

EXACT_BACKENDS = [
    name for name in available_backends() if get_backend(name).exact
]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta: MetadataProvider, problem: tuple[str, str, str], seed: int) -> dict:
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=seed)
    runner.run_mcat(max_steps=6000)
    workspace = runner.ctx.workspace
    return {
        "status": runner.status,
        "answer": workspace.answer_string.text if workspace.answer_string else "",
        "codelets": runner.ctx.codelet_count,
        "rng_calls": runner.ctx.rng.call_count,
        "temperature": runner.ctx.temperature.value,
        "activations": {
            name: node.activation for name, node in runner.ctx.slipnet.nodes.items()
        },
    }


@pytest.mark.parametrize("backend_name", EXACT_BACKENDS)
@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: "".join(p))
@pytest.mark.parametrize("seed", [42, 43])
def test_exact_backends_reproduce_the_run_bit_for_bit(
    meta: MetadataProvider, backend_name: str, problem: tuple[str, str, str], seed: int
) -> None:
    """A float64 substrate must not change a single draw of a seeded run.

    The random-draw count is the sharpest of these assertions.  Any disagreement
    about *which* nodes are eligible for the probabilistic jump — one node too
    many, one too few — shifts every subsequent draw and shows up here long before
    it would show up as a different answer.
    """
    # The reference is the engine's *own loops*, not whatever ``auto`` selects.
    #
    # It used to be ``use_backend(None)``, which was the same thing only because
    # ``auto`` declined the substrate at 59 nodes. Now that ``auto`` is the GPU at every
    # size (B1), ``None`` means float32, and these tests would have been comparing
    # float64 backends against float32 and calling the legitimate difference a failure.
    with use_backend("off"):
        reference = _run(meta, problem, seed)
    with use_backend(backend_name):
        observed = _run(meta, problem, seed)

    assert observed["status"] == reference["status"]
    assert observed["answer"] == reference["answer"]
    assert observed["codelets"] == reference["codelets"]
    assert observed["rng_calls"] == reference["rng_calls"], (
        "The substrate consumed a different number of random draws, so the run "
        "diverged from the reference at some point even if it landed in the same "
        "place."
    )
    assert observed["temperature"] == reference["temperature"]
    assert observed["activations"] == reference["activations"]


@pytest.mark.parametrize("backend_name", available_backends())
def test_every_backend_reaches_a_valid_stopping_state(
    meta: MetadataProvider, backend_name: str
) -> None:
    """Including the float32 one, which is allowed to reach a *different* answer.

    Not a substitute for the expected-range check — one run per backend says
    nothing about the reachable set — but it catches a backend that produces
    activations so wrong the engine cannot finish, which an array comparison with
    a generous tolerance might not.
    """
    with use_backend(backend_name):
        result = _run(meta, ("abc", "abd", "mrrjjj"), 42)
    assert result["status"] in ("answer_found", "gave_up", "halted")
    assert 0 < result["codelets"] <= 6000


def test_the_default_policy_puts_the_numeric_substrate_on_the_gpu(
    meta: MetadataProvider,
) -> None:
    """Under ``auto`` the GPU must be engaged, at 59 nodes as at 300,000.

    This test previously asserted the opposite — that the substrate declines at 59
    nodes because it would be slower there. It is inverted rather than deleted, because
    the assertion that was protecting throughput was also, in effect, guaranteeing that
    the GPU substrate never executed at the only size the engine currently runs at.
    Phase 0 B1 states the goal as "the system's numeric work executing on the GPU
    cores", and a substrate that never runs does not satisfy it.

    The throughput cost is real — roughly 9x at 59 nodes, since a Metal dispatch is
    ~0.2 ms whether it carries 200 edges or 340,000 — and is documented rather than
    avoided. ``PETACAT_NUMERIC_MIN_GPU_NODES`` reinstates size gating for anyone
    profiling the CPU path.
    """
    if "mlx" not in available_backends():
        pytest.skip("MLX is not installed on this machine")

    with use_backend(None):
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
        for _ in range(30):
            runner.step_mcat()

        chosen = select_backend(len(runner.ctx.slipnet.nodes))
        assert chosen is not None, "auto declined the substrate at 59 nodes"
        assert chosen.name == "mlx", f"auto chose {chosen.name!r} rather than the GPU"

        # Engaged in the live run, not merely selectable in principle.
        assert runner.ctx.slipnet._numeric_session() is not None
        assert runner.ctx.themespace._numeric_backend() is not None


def test_size_gating_can_be_reinstated_deliberately(meta: MetadataProvider) -> None:
    """The knob survives, so profiling the CPU path stays possible.

    What must not happen is size gating being the *default*, which is what left the GPU
    unexecuted. Being able to ask for it is a different matter.
    """
    import os

    from server.engine.numeric.backend import ENV_MIN_GPU_NODES, reset_backend_cache

    previous = os.environ.get(ENV_MIN_GPU_NODES)
    os.environ[ENV_MIN_GPU_NODES] = "10000"
    reset_backend_cache()
    try:
        chosen = select_backend(59)
        assert chosen is None or chosen.name != "mlx"
    finally:
        if previous is None:
            os.environ.pop(ENV_MIN_GPU_NODES, None)
        else:
            os.environ[ENV_MIN_GPU_NODES] = previous
        reset_backend_cache()


@pytest.mark.parametrize("backend_name", EXACT_BACKENDS)
def test_object_value_phase_split_matches_the_per_object_order(
    meta: MetadataProvider, backend_name: str
) -> None:
    """The regrouping of ``update_object_values`` is a reordering, not a rewrite.

    The reference completes all seven steps for object 0 before starting object 1;
    the substrate does traversals for every object, then arithmetic for every
    object, then description strengths for every object.  That is only sound
    because no step reads another object's unhappiness or salience.  Asserting it
    on a real mid-run workspace — with groups, bonds and bridges built — is what
    turns that argument into a check.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    for _ in range(600):
        runner.step_mcat()
    workspace = runner.ctx.workspace
    assert any(s.groups for s in workspace.all_strings), (
        "600 codelets built no groups, so the grouped-object paths this test "
        "exists to cover were never reached."
    )

    def snapshot() -> list[tuple]:
        return [
            (
                obj.relative_importance,
                obj.average_unhappiness,
                obj.salience["intra"],
                obj.salience["horizontal_inter"],
                obj.salience["vertical_inter"],
                obj.salience["average"],
            )
            for obj in workspace.all_objects
        ]

    with use_backend(None):
        workspace.update_all_object_values()
        reference = snapshot()
    with use_backend(backend_name):
        workspace.update_all_object_values()
        observed = snapshot()

    assert observed == reference


@pytest.mark.parametrize("backend_name", EXACT_BACKENDS)
def test_structure_strength_batching_matches_the_sequential_order(
    meta: MetadataProvider, backend_name: str
) -> None:
    """Bonds and groups may be batched; bridges must not be, and are not.

    ``Group.calculate_internal_strength`` reads its bonds' strengths and
    ``Bridge._get_supporting_bridge_strength`` reads its peers', so the batching
    is only legal for the two kinds that carry no intra-batch dependency.  A run
    with groups *and* bridges built is the configuration where getting that wrong
    shows up.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    for _ in range(600):
        runner.step_mcat()
    workspace = runner.ctx.workspace
    structures = workspace.all_structures
    assert structures, "no structures were built, so nothing was compared"

    with use_backend(None):
        workspace.update_all_structure_strengths()
        reference = [s.strength for s in structures]
    with use_backend(backend_name):
        workspace.update_all_structure_strengths()
        observed = [s.strength for s in structures]

    assert observed == reference


def test_topology_is_built_once_and_reused(meta: MetadataProvider) -> None:
    """The sparse matrix is static, so rebuilding it every cycle would be waste.

    ``intrinsic_degree_of_association`` consults the *intrinsic* link length only
    (slipnet.ss:330-333), never a live activation, which is what makes a CSR the
    right layout rather than merely a convenient one.
    """
    with use_backend("python"):
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
        slipnet = runner.ctx.slipnet
        first = slipnet._numeric_session()
        for _ in range(60):
            runner.step_mcat()
        assert slipnet._numeric_session() is first

        slipnet.invalidate_numeric_layout()
        assert slipnet._numeric_session() is not first
