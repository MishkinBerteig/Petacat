"""The numeric backends agree with the reference, and the engine survives without them.

Three things are being defended here, in descending order of importance.

**Agreement.**  The pure-Python backend is the reference; NumPy and MLX must
compute what it computes.  For the float64 backends that means *exactly*, and the
tests assert exact equality rather than a tolerance, because anything looser would
let a real re-association hide.  For the GPU backend it means within a stated
tolerance, because Apple's GPUs have no double-precision units and MLX therefore
cannot offer float64 there at all.

**Absence.**  MLX is optional.  The suite has to stay green on a machine that has
never heard of it, and that is checked by making it genuinely unimportable in a
fresh interpreter rather than by asserting that a fallback branch exists.  On such
a machine most of this file skips, reporting an empty parameter set: there is only
one implementation, so there is nothing to compare it against.  That is the right
outcome rather than a gap — what has to keep running there is the *engine*, and
``test_engine_runs_identically_with_mlx_and_numpy_absent`` is the test that says
so.

**Realism.**  The agreement tests run on the *real* Slipnet, seeded from the real
metadata and driven through many update cycles, not only on synthetic arrays.  A
59-node graph with a 28-way hub and thirteen distinct association weights exercises
paths a uniform random graph does not, and the divergence that matters is the one
that accumulates over cycles rather than the one visible after one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends, get_backend
from server.engine.numeric.layout import (
    ObjectValueBatch,
    SlipnetState,
    SlipnetTopology,
    ThemeLayout,
    ThemeParams,
    ThemeState,
)
from server.engine.numeric.synthetic import synthetic_state, synthetic_topology
from server.engine.slipnet import Slipnet
from server.engine.themes import Themespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED_DIR = os.path.join(REPO_ROOT, "seed_data")


# The tolerance, and how it was arrived at
# ----------------------------------------
# Activations live in [0, 100].  float32 carries 24 bits of significand, so the
# representation error at 100 is 2⁻¹⁷ ≈ 7.6e-6, and a chain of a few operations
# per update cycle can accumulate a handful of those.  Measured over 40 update
# cycles on the real Slipnet the largest observed elementwise difference is about
# 4e-5; 1e-3 is therefore roughly twenty-five times the observed worst case, which
# is loose enough not to be flaky and tight enough that a genuine formulation
# error — which would show up as a difference of *ones*, since these quantities
# are sums of integers — could not slip past it.
#
# The tolerance is deliberately absolute rather than relative: a relative
# tolerance is meaningless for a quantity that is legitimately zero, and half the
# Slipnet is at zero activation at any moment.
GPU_ACTIVATION_TOLERANCE = 1e-3

#: Backends that compute in float64 and must therefore match the reference bit for
#: bit.  ``Backend.exact`` is the property being asserted, not assumed.
EXACT_BACKENDS = [
    name for name in available_backends()
    if name != "python" and get_backend(name).exact
]
INEXACT_BACKENDS = [
    name for name in available_backends() if not get_backend(name).exact
]
ALL_ALTERNATIVES = EXACT_BACKENDS + INEXACT_BACKENDS


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture(scope="module")
def real_slipnet(meta: MetadataProvider) -> Slipnet:
    return Slipnet.from_metadata(meta)


def _seeded_state(slipnet: Slipnet, seed: int = 5) -> SlipnetState:
    """A mid-run-looking activation state over the real Slipnet.

    Built from the real node order so that index *i* is the *i*-th node the
    reference visits, which is what makes an elementwise comparison meaningful.
    """
    import random

    rng = random.Random(seed)
    names = list(slipnet.nodes)
    activation = []
    buffer = []
    for _ in names:
        if rng.random() < 0.3:
            activation.append(100.0 if rng.random() < 0.3 else rng.uniform(1.0, 99.0))
        else:
            activation.append(0.0)
        buffer.append(100.0 if rng.random() < 0.15 else 0.0)
    return SlipnetState(
        activation=activation,
        buffer=buffer,
        frozen=[rng.random() < 0.05 for _ in names],
        clamp_remaining=[0] * len(names),
    )


def _drive(backend_name: str, topology, state: SlipnetState, cycles: int) -> list[float]:
    """Run ``cycles`` update cycles and return the final activations.

    The probabilistic jump is applied deterministically — every third candidate —
    rather than from an RNG, so that the backends are compared on their arithmetic
    and not on whether they happened to draw the same numbers.  Which nodes are
    *candidates* is itself part of what is being compared, and a backend that
    disagreed about that would show up as a different final activation vector.
    """
    session = get_backend(backend_name).open_slipnet(topology)
    session.load(state)
    for _ in range(cycles):
        session.update(100.0, 1.0)
        indices, _ = session.jump_candidates()
        session.apply_jumps(indices[::3])
    return session.store().activation


# --- Slipnet spreading ------------------------------------------------------


@pytest.mark.parametrize("backend_name", EXACT_BACKENDS)
def test_float64_backends_match_the_reference_exactly_on_the_real_slipnet(
    backend_name: str, real_slipnet: Slipnet
) -> None:
    """No tolerance: a float64 backend that differs has re-associated something."""
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = _seeded_state(real_slipnet)
    reference = _drive("python", topology, state, cycles=40)
    observed = _drive(backend_name, topology, state, cycles=40)
    assert observed == reference


@pytest.mark.parametrize("backend_name", INEXACT_BACKENDS)
def test_float32_backend_matches_the_reference_within_tolerance(
    backend_name: str, real_slipnet: Slipnet
) -> None:
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = _seeded_state(real_slipnet)
    reference = _drive("python", topology, state, cycles=40)
    observed = _drive(backend_name, topology, state, cycles=40)
    assert len(observed) == len(reference)
    worst = max(abs(a - b) for a, b in zip(reference, observed))
    assert worst <= GPU_ACTIVATION_TOLERANCE, (
        f"{backend_name} drifted {worst:.3g} from the reference over 40 update "
        f"cycles on the real Slipnet, against a tolerance of "
        f"{GPU_ACTIVATION_TOLERANCE:g}. float32 rounding accounts for ~1e-5; a "
        f"difference much larger than that is a formulation error, not precision."
    )


# --- decay is rounded, on every backend, with no tolerance ------------------
#
# ``decay-activation`` (slipnet.ss:174-177) is ``(round (* rate-of-decay
# activation))`` over exact rationals.  A whole number is subtracted, so a
# Slipnet that starts on the integers stays there and deep nodes reach a fixed
# point — depth 90 at 5, depth 80 at 2 — instead of tending to zero.
#
# These are the only Slipnet tests here that hold *every* backend, float32
# included, to exact equality.  They can, because the quantities involved are
# integers: the percentage is ``100 - depth``, the product with an activation is
# at most 10,000, and a quotient that is exactly a half is exactly representable
# in both precisions.  Getting that wrong would not show up as drift — it would
# show up as a whole unit, on one node, on one cycle, which is why a tolerance
# would be the wrong instrument here.


def _integral_state(topology: SlipnetTopology, seed: int = 17) -> SlipnetState:
    """Every activation a whole number, as the engine's own always are."""
    import random

    rng = random.Random(seed)
    n = topology.n_nodes
    return SlipnetState(
        activation=[float(rng.randrange(0, 101)) for _ in range(n)],
        buffer=[0.0] * n,
        frozen=[False] * n,
        clamp_remaining=[0] * n,
    )


def _exact_decay_only(topology: SlipnetTopology, state: SlipnetState, cycles: int):
    """The reference's arithmetic, in exact rationals rather than in floats.

    Decay only: the caller drives the backends at the default spreading
    threshold with no node at full activation, so nothing spreads and this is the
    whole of the update.  Comparing against ``Fraction`` rather than against the
    pure-Python backend is deliberate — it is the Scheme's semantics being
    asserted, not one implementation's agreement with another.
    """
    from fractions import Fraction

    out = []
    for start, depth in zip(state.activation, topology.conceptual_depth):
        a = int(start)
        for _ in range(cycles):
            a -= round(Fraction(100 - int(depth), 100) * a)
        out.append(float(a))
    return out


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES + ["python"])
def test_every_backend_rounds_decay_the_way_the_reference_does(
    backend_name: str, real_slipnet: Slipnet
) -> None:
    """Exact rational arithmetic, matched unit for unit on all four backends."""
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = _integral_state(topology)
    expected = _exact_decay_only(topology, state, cycles=30)

    session = get_backend(backend_name).open_slipnet(topology)
    session.load(state)
    for _ in range(30):
        session.update(100.0, 1.0)
    observed = session.store().activation

    assert observed == expected


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES + ["python"])
def test_every_backend_reaches_the_same_decay_plateaus(
    backend_name: str, real_slipnet: Slipnet
) -> None:
    """The fixed points themselves, keyed by conceptual depth.

    Stated as a table rather than as agreement with a reference run, because the
    plateau is the observable the fix exists for: a depth-90 concept the program
    has finished with stays at 5 rather than vanishing, and every backend has to
    agree about that or a run means something different on the GPU.
    """
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    n = topology.n_nodes
    state = SlipnetState(
        activation=[100.0] * n,
        buffer=[0.0] * n,
        frozen=[False] * n,
        clamp_remaining=[0] * n,
    )

    session = get_backend(backend_name).open_slipnet(topology)
    session.load(state)
    for _ in range(400):
        session.update(100.0, 1.0)
        # Nothing may re-enter: without this the nodes still at 100 would spread
        # and the fixed points would never be visible.
        session.load(
            SlipnetState(
                activation=session.store().activation,
                buffer=[0.0] * n,
                frozen=[False] * n,
                clamp_remaining=[0] * n,
            )
        )
    final = session.store().activation

    plateau_by_depth = {
        int(d): a for d, a in zip(topology.conceptual_depth, final)
    }
    assert plateau_by_depth == {
        10: 0.0, 20: 0.0, 30: 0.0, 40: 0.0,
        50: 1.0, 60: 1.0, 70: 1.0, 80: 2.0, 90: 5.0,
    }


def _drive_integral(backend_name: str, topology, threshold: float, cycles: int):
    session = get_backend(backend_name).open_slipnet(topology)
    session.load(_integral_state(topology, seed=topology.n_nodes + 3))
    for _ in range(cycles):
        session.update(threshold, 1.0)
    return session.store().activation


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES + ["python"])
@pytest.mark.parametrize("n_nodes", [1, 200, 5000])
def test_an_integral_slipnet_stays_integral_on_synthetic_sizes(
    backend_name: str, n_nodes: int
) -> None:
    """At sizes the real Slipnet cannot reach, and with spreading switched on.

    The threshold is 0 here, so every active node spreads and the buffer carries
    contributions as well as the decay term.  Every one of those is a rounded
    integer, so the activation must still be a whole number afterwards — on the
    float32 backend too, where the sums stay far inside the 2²⁴ it represents
    exactly.  A fractional activation anywhere means something on the path
    stopped rounding.
    """
    observed = _drive_integral(backend_name, synthetic_topology(n_nodes, seed=n_nodes), 0.0, 5)
    assert all(a == int(a) for a in observed), (
        f"{backend_name} left a fractional activation at {n_nodes} nodes"
    )


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
@pytest.mark.parametrize("n_nodes", [1, 200, 5000])
def test_backends_agree_unit_for_unit_when_only_full_nodes_spread(
    backend_name: str, n_nodes: int
) -> None:
    """The shipped threshold: 100, so a node spreads only at full activation.

    Exact equality with no tolerance, float32 included, because every quantity
    in play is a whole number — the decay amount by ``round``, and a
    contribution from a node at exactly 100 by ``round(assoc/100 · 100)``, which
    is the association itself.

    **The threshold is load-bearing here, and that is worth stating.**  Below it,
    a node spreads at some activation *a* < 100 and the contribution is
    ``round(assoc/100 · a)`` over a genuine fraction, which the backends do
    *not* all round alike: at (assoc 70, a 45) the exact value is 31.5 and
    float64 computes 31.499999999999996, and at (assoc 30, a 95) the exact value
    is 28.5 and float32 computes 28.500002.  That is the same defect this file's
    decay tests exist for, one function along — ``spread_activation_to_neighbors``
    still pre-divides the association — and it is reachable only through
    Petacat's own ``spreading_activation_threshold``, never through the
    reference, which spreads from fully-active nodes alone.  The companion test
    above therefore asserts integrality at threshold 0 rather than agreement.
    """
    topology = synthetic_topology(n_nodes, seed=n_nodes)
    assert _drive_integral(backend_name, topology, 100.0, 5) == _drive_integral(
        "python", topology, 100.0, 5
    )


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
@pytest.mark.parametrize("n_nodes", [1, 200, 5000])
def test_backends_agree_on_synthetic_slipnets(backend_name: str, n_nodes: int) -> None:
    """Sizes the real Slipnet cannot reach, including the degenerate single node."""
    topology = synthetic_topology(n_nodes, seed=n_nodes)
    state = synthetic_state(topology, seed=n_nodes + 1)
    reference = _drive("python", topology, state, cycles=5)
    observed = _drive(backend_name, topology, state, cycles=5)
    worst = max(
        (abs(a - b) for a, b in zip(reference, observed)), default=0.0
    )
    tolerance = 0.0 if get_backend(backend_name).exact else GPU_ACTIVATION_TOLERANCE
    assert worst <= tolerance


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
def test_jump_candidates_match_the_rngs_own_short_circuits(
    backend_name: str, real_slipnet: Slipnet
) -> None:
    """The draw set is exactly the nodes ``RNG.prob`` would consume a draw for.

    ``probabilistic_jump_to_full`` asks only about ``partially-active?`` nodes —
    activation in [50, 100), slipnet.ss:387-389 — and ``RNG.prob`` returns
    without touching the stream at probability 0 or 1.  A backend that returned
    one candidate too many or too few would shift every subsequent draw in the
    run, which is the one way this substrate could move the expected range
    without any arithmetic being wrong.
    """
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = _seeded_state(real_slipnet, seed=9)
    # A state deliberately containing every boundary: a node at exactly 100
    # (probability 1, no draw), a node at zero and a node below the threshold
    # (neither is a candidate), and a node at exactly 50 (the first that is).
    state.activation[0] = 100.0
    state.activation[1] = 0.0
    state.activation[2] = 50.0
    state.activation[3] = 49.0

    session = get_backend(backend_name).open_slipnet(topology)
    session.load(state)
    indices, probabilities = session.jump_candidates()

    assert 0 not in indices, "a node at full activation must not consume a draw"
    assert 1 not in indices, "a node at zero activation is never asked"
    assert 2 in indices, "50 is the floor of partially-active?, inclusive"
    assert 3 not in indices, "a node below the threshold never jumps"
    assert all(0.0 < p < 1.0 for p in probabilities)
    expected = [
        i for i, a in enumerate(state.activation) if 50.0 <= a < 100.0
    ]
    assert indices == expected


# --- Themespace, object values, structure strengths -------------------------


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
def test_theme_spreading_matches_the_cluster_loop(
    backend_name: str, meta: MetadataProvider
) -> None:
    """Against ``ThemeCluster.spread_activation`` itself, not against a transcription."""
    import copy
    import random

    themespace = Themespace(meta)
    rng = random.Random(7)
    for cluster in themespace.clusters:
        for theme in cluster.themes:
            theme.activation = rng.choice(
                [0.0, 12.0, 45.0, 88.0, 100.0, -30.0, -70.0, -100.0]
            )
        cluster.frozen = rng.random() < 0.1

    reference = copy.deepcopy(themespace)
    reference.meta = meta
    for cluster in reference.clusters:
        cluster.spread_activation(meta)
    expected = [t.activation for c in reference.clusters for t in c.themes]

    layout = ThemeLayout.from_themespace(themespace)
    state = ThemeState.from_themespace(themespace, layout)
    get_backend(backend_name).spread_themes(
        layout, state, ThemeParams.from_metadata(meta)
    )
    state.apply_to_themespace(themespace, layout)
    observed = [t.activation for c in themespace.clusters for t in c.themes]

    assert len(observed) == len(expected)
    assert max(abs(a - b) for a, b in zip(expected, observed)) <= (
        0.0 if get_backend(backend_name).exact else 1e-4
    )


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
def test_object_value_combination_agrees_exactly(backend_name: str) -> None:
    """Every output is an integer, so every backend must produce the same integers.

    That is a stronger claim than a tolerance and it holds even for float32,
    because these quantities are bare ``round()`` results over inputs bounded by
    100 — well inside the range float32 represents exactly.
    """
    import random

    rng = random.Random(11)
    n = 40
    inputs = dict(
        relative_importance=[rng.randrange(0, 101) for _ in range(n)],
        intra_unhappiness=[rng.uniform(0, 100) for _ in range(n)],
        horizontal_unhappiness=[rng.uniform(0, 100) for _ in range(n)],
        vertical_unhappiness=[rng.uniform(0, 100) for _ in range(n)],
        salience_clamped=[rng.random() < 0.2 for _ in range(n)],
        string_type=[rng.randrange(5) for _ in range(n)],
        justify_mode=[rng.random() < 0.5 for _ in range(n)],
        prev_horizontal_salience=[float(rng.randrange(101)) for _ in range(n)],
        prev_vertical_salience=[float(rng.randrange(101)) for _ in range(n)],
    )

    def run(name: str) -> tuple:
        batch = ObjectValueBatch(**{k: list(v) for k, v in inputs.items()})
        get_backend(name).combine_object_values(batch)
        return (
            batch.average_unhappiness,
            batch.intra_salience,
            batch.horizontal_salience,
            batch.vertical_salience,
            batch.average_salience,
        )

    assert run(backend_name) == run("python")


def test_relative_importance_survives_denormal_raw_importances() -> None:
    """A regression: raw importances around 1e-48 are ordinary, and their ratio is not.

    ``eqe->qeq; abbbc?`` at seed 1,000,019 reaches an update cycle where all three
    objects in a string have a raw importance of 2.36e-48 — the descriptor
    activations behind them have decayed almost to nothing, but they have decayed
    *together*, so the relative importances are still 33, 33, 33.

    Computing that ratio on a device is where it went wrong.  float32 cannot
    represent 1e-48 at all, and MLX routes Python scalars through float32 even in
    a float64 graph, so the denominator flushed to zero and every relative
    importance became ``inf`` — which then raised ``OverflowError`` on the way
    back to an ``int``.  The fix is structural rather than defensive: relative
    importance is computed on the host in float64, as the reference's own separate
    pass already does, and no backend ever sees a value outside [0, 100].

    Found by the expected-range check, which is the reason it is run against a
    forced backend rather than only against the default policy.
    """
    from server.engine.numeric.layout import relative_importances

    class FakeObject:
        def __init__(self, raw: float) -> None:
            self.raw_importance = raw

    tiny = [FakeObject(2.3611832414347897e-48) for _ in range(3)]
    assert relative_importances(tiny) == [33, 33, 33]

    # The all-zero case the ``or 1.0`` guard exists for: no descriptor is active
    # yet, so nothing is relatively more important than anything else.
    # Scheme: ``update-all-relative-importances`` (workspace-strings.ss:326-329)
    # spreads importance evenly when nothing is described yet.
    assert relative_importances([FakeObject(0.0) for _ in range(4)]) == [25, 25, 25, 25]
    assert relative_importances([]) == []


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
def test_structure_strengths_agree_exactly(backend_name: str) -> None:
    import random

    rng = random.Random(13)
    n = 60
    internal = [rng.uniform(0, 100) for _ in range(n)]
    external = [rng.uniform(0, 100) for _ in range(n)]
    compatibility = [
        rng.uniform(-1, 1) if rng.random() < 0.6 else 0.0 for _ in range(n)
    ]
    assert get_backend(backend_name).structure_strengths(
        internal, external, compatibility
    ) == get_backend("python").structure_strengths(internal, external, compatibility)


@pytest.mark.parametrize("backend_name", ALL_ALTERNATIVES)
def test_temperature_and_average_unhappiness_agree(backend_name: str) -> None:
    import random

    rng = random.Random(17)
    intra = [rng.uniform(0, 100) for _ in range(30)]
    importance = [float(rng.randrange(0, 40)) for _ in range(30)]
    backend = get_backend(backend_name)
    reference = get_backend("python")
    assert backend.average_unhappiness(intra, importance) == reference.average_unhappiness(
        intra, importance
    )
    assert backend.average_unhappiness(intra, [0.0] * 30) == reference.average_unhappiness(
        intra, [0.0] * 30
    )
    for unhappiness in (0.0, 37.4, 100.0):
        for rule_factor in (0.0, 100.0):
            assert backend.temperature(unhappiness, rule_factor, 70.0, 30.0) == (
                reference.temperature(unhappiness, rule_factor, 70.0, 30.0)
            )


# --- The layout itself ------------------------------------------------------


def test_topology_reproduces_the_object_graphs_edges(real_slipnet: Slipnet) -> None:
    """The flattened CSR holds the same edges, regrouped — none added, none lost."""
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    index = {name: i for i, name in enumerate(topology.node_names)}

    expected: list[tuple[int, int, float]] = []
    for node in real_slipnet.nodes.values():
        for link in node.outgoing_links:
            expected.append(
                (
                    index[node.name],
                    index[link.to_node.name],
                    link.intrinsic_degree_of_association() / 100.0,
                )
            )
    observed = list(zip(topology.in_source, topology.in_dest, topology.in_weight))
    assert sorted(observed) == sorted(expected)
    assert topology.n_edges == 202
    assert topology.n_nodes == 59


def test_topology_indptr_is_consistent_with_the_edge_arrays(
    real_slipnet: Slipnet,
) -> None:
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    assert len(topology.in_indptr) == topology.n_nodes + 1
    assert topology.in_indptr[0] == 0
    assert topology.in_indptr[-1] == topology.n_edges
    for d in range(topology.n_nodes):
        for e in range(topology.in_indptr[d], topology.in_indptr[d + 1]):
            assert topology.in_dest[e] == d


def test_synthetic_topology_matches_the_real_density() -> None:
    """The scaling curve is only meaningful if the synthetic graph resembles the real one."""
    topology = synthetic_topology(10_000, seed=1)
    assert topology.n_nodes == 10_000
    assert abs(topology.n_edges / 10_000 - 202 / 59) < 0.01
    in_degrees = [
        topology.in_indptr[i + 1] - topology.in_indptr[i] for i in range(10_000)
    ]
    # Heavy-tailed *in the direction the kernel parallelises over*.  Rows are
    # destinations, so it is the in-degree that decides load balance, and the real
    # Slipnet's longest row is 29 against a mean of 3.4.  Drawing destinations
    # uniformly instead gives a Poisson maximum around 13 here, which would make
    # the SIMD-group-per-row decomposition look unnecessary.
    assert max(in_degrees) >= 25
    assert max(in_degrees) / (topology.n_edges / 10_000) >= 7

    # And in the other direction too, so that the gather's source addresses are as
    # unevenly distributed as they really are.
    from collections import Counter

    out_degrees = Counter(topology.in_source)
    assert max(out_degrees.values()) >= 25


# --- Optionality ------------------------------------------------------------


# --- The Metal kernel's decomposition ---------------------------------------


@pytest.mark.skipif("mlx" not in available_backends(), reason="MLX is not installed")
def test_the_metal_kernel_and_the_composed_mlx_graph_agree() -> None:
    """Two implementations of the same computation on the same device.

    The composed path is not dead code: it is what the CPU stream must use, since
    ``mx.fast.metal_kernel`` is GPU-only, and it is the control the benchmark uses
    to say what the hand-written kernel bought.  If they ever disagreed, the
    scaling comparison between them would be meaningless.
    """
    from server.engine.numeric.mlx_backend import MlxBackend

    topology = synthetic_topology(3000, seed=3)
    state = synthetic_state(topology, seed=4)

    def drive(backend) -> list[float]:
        session = backend.open_slipnet(topology)
        session.load(state)
        for _ in range(6):
            session.update(100.0, 1.0)
            indices, _ = session.jump_candidates()
            session.apply_jumps(indices[::3])
        return session.store().activation

    assert drive(MlxBackend(use_kernel=True)) == drive(MlxBackend(use_kernel=False))


@pytest.mark.skipif("mlx" not in available_backends(), reason="MLX is not installed")
@pytest.mark.parametrize("lanes", [1, 2, 4, 8, 16, 32])
def test_every_lane_count_computes_the_same_answer(lanes: int) -> None:
    """The shuffle-down sweep is correct at every width the rule can pick.

    ``lanes`` is chosen from the graph's statistics, so which width a given
    Slipnet gets is not something a reader can see at the call site.  All six must
    agree, including 1 — where the sweep has no iterations and the kernel becomes
    one thread per row — and 32, where it spans a whole SIMD group.
    """
    from server.engine.numeric import metal_kernels
    from server.engine.numeric.mlx_backend import MlxBackend

    topology = synthetic_topology(4000, seed=8)
    state = synthetic_state(topology, seed=9)
    reference = _drive("python", topology, state, cycles=4)

    session = MlxBackend(use_kernel=True).open_slipnet(topology)
    session.lanes = lanes
    session.load(state)
    for _ in range(4):
        session.update(100.0, 1.0)
        indices, _ = session.jump_candidates()
        session.apply_jumps(indices[::3])
    observed = session.store().activation

    assert max(abs(a - b) for a, b in zip(reference, observed)) <= (
        GPU_ACTIVATION_TOLERANCE
    )
    # Belt and braces: the rule must never pick something outside the tested set.
    assert metal_kernels.lanes_per_row(4000, topology.n_edges, 29) in (
        1, 2, 4, 8, 16, 32
    )


#: The thread target the lane table in ``metal_kernels`` was measured at: a
#: 38-core GPU asking for 1,024 threads per core, rounded up to a power of two.
MEASURED_TARGET_THREADS = 1 << 16


@pytest.mark.parametrize(
    "n_rows,n_edges,max_degree,expected",
    [
        # Few rows: latency-bound, split each row as widely as the SIMD allows.
        (59, 202, 29, 32),
        (1_000, 3_424, 29, 32),
        # Enough rows to fill the GPU: stop splitting, follow the mean degree.
        (10_000, 34_237, 29, 8),
        (100_000, 342_373, 29, 4),
        (300_000, 1_026_000, 29, 4),
        # A vocabulary-scale category node. The mean says 4; the tail says 32,
        # and the tail is what would otherwise serialise a whole lane group.
        (300_000, 1_026_000, 5_000, 32),
        # Degenerate inputs must not divide by zero or return 0 lanes.
        (0, 0, 0, 1),
        (1, 0, 0, 32),
    ],
)
def test_lane_count_follows_the_measured_rule(
    n_rows: int, n_edges: int, max_degree: int, expected: int
) -> None:
    """The tuning decision, pinned to the table in ``metal_kernels``.

    Not an arbitrary regression lock: each row here is a regime the measurement
    distinguishes, and the module docstring records the milliseconds behind them.
    The thread target is passed explicitly, because it is read from the GPU this
    process is running on and the table is an answer for the GPU it was measured
    on — a change to ``MAX_EDGES_PER_LANE`` should move these rows, a bigger GPU
    should not.
    """
    from server.engine.numeric.metal_kernels import lanes_per_row

    assert (
        lanes_per_row(n_rows, n_edges, max_degree, threads=MEASURED_TARGET_THREADS)
        == expected
    )


def test_a_larger_gpu_splits_rows_more_widely_in_the_latency_bound_regime() -> None:
    """The lane rule scales with the machine, in the regime where that matters.

    Below the point where there are enough rows to fill the GPU, a row is split
    across as many lanes as the GPU can keep busy, so twice the cores buys twice
    the lanes.  Above it the mean in-degree governs and the two agree, because a
    row with 3.4 edges has nothing more to hand out however large the GPU is.
    """
    from server.engine.numeric.metal_kernels import lanes_per_row

    small, large = 1 << 16, 1 << 17
    assert lanes_per_row(10_000, 34_237, 29, threads=small) == 8
    assert lanes_per_row(10_000, 34_237, 29, threads=large) == 16
    assert lanes_per_row(300_000, 1_026_000, 29, threads=small) == 4
    assert lanes_per_row(300_000, 1_026_000, 29, threads=large) == 4


def test_the_default_thread_target_comes_from_the_detected_gpu() -> None:
    """``lanes_per_row`` with no target asks the machine for one."""
    from server.engine import hardware
    from server.engine.numeric import metal_kernels

    assert metal_kernels.target_threads() == hardware.gpu_target_threads()
    assert metal_kernels.lanes_per_row(10_000, 34_237, 29) == metal_kernels.lanes_per_row(
        10_000, 34_237, 29, threads=hardware.gpu_target_threads()
    )


def test_max_in_degree_reads_the_longest_csr_row(real_slipnet: Slipnet) -> None:
    from server.engine.numeric.metal_kernels import max_in_degree

    topology = SlipnetTopology.from_slipnet(real_slipnet)
    # ``plato-letter-category`` receives a category link from each of 26 letters.
    assert max_in_degree(topology.in_indptr) == 29
    assert max_in_degree([0]) == 0


# --- Optionality ------------------------------------------------------------


def test_python_backend_is_always_available() -> None:
    assert "python" in available_backends()
    assert get_backend("python").exact


def test_named_but_missing_backend_raises_rather_than_falling_back() -> None:
    """Asking for a backend that is not installed must fail loudly.

    A silent fallback would mean a benchmark reporting GPU numbers that were
    measured on the CPU, which is worse than an error.
    """
    from server.engine.numeric.backend import BackendUnavailable

    with pytest.raises(BackendUnavailable):
        get_backend("no-such-backend")


#: Run in a *separate* interpreter with MLX made unimportable before the first
#: engine import — the same technique, and for the same reason, as the database
#: absence probe in ``test_engine_purity.py``.  Blocking MLX inside the pytest
#: process would prove nothing, because by the time this file runs MLX is already
#: in ``sys.modules`` and would be found there regardless of what the engine does.
#:
#: The probe does not merely import the engine: it runs a complete problem to an
#: answer and checks the run is *identical* to one taken with MLX present, which
#: is the property that matters. "Optional" means the engine does not change
#: behaviour when the option is absent, not merely that it starts.
_ABSENT_MLX_PROBE = r'''
import importlib.abc
import json
import sys

REPO_ROOT, SEED_DIR = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO_ROOT)

BLOCKED = ("mlx", "numpy")


class PackageAbsent(importlib.abc.MetaPathFinder):
    """Makes MLX and NumPy unimportable, as on a checkout without them."""

    def find_spec(self, fullname, path=None, target=None):
        for root in BLOCKED:
            if fullname == root or fullname.startswith(root + "."):
                raise ModuleNotFoundError(
                    "deliberately absent from this interpreter: " + fullname,
                    name=fullname,
                )
        return None


sys.meta_path.insert(0, PackageAbsent())

from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends
from server.engine.runner import EngineRunner

runner = EngineRunner(MetadataProvider.from_seed_data(SEED_DIR))
runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
runner.run_mcat(max_steps=6000)
workspace = runner.ctx.workspace

leaked = sorted({name for name in list(sys.modules)
                 for root in BLOCKED
                 if name == root or name.startswith(root + ".")})

print(json.dumps({
    "backends": available_backends(),
    "status": runner.status,
    "answer": workspace.answer_string.text if workspace.answer_string else "",
    "codelets": runner.ctx.codelet_count,
    "rng_calls": runner.ctx.rng.call_count,
    "leaked": leaked,
}))
'''


@pytest.mark.slow
def test_engine_runs_identically_with_mlx_and_numpy_absent() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _ABSENT_MLX_PROBE, REPO_ROOT, SEED_DIR],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        "The engine failed in an interpreter with MLX and NumPy unimportable. "
        "Something under server/engine/ now imports one of them unconditionally, "
        "which would make an optional dependency a required one.\n\n"
        f"--- stderr ---\n{completed.stderr}\n--- stdout ---\n{completed.stdout}"
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["leaked"] == [], (
        f"These modules were imported despite the block: {result['leaked']}. "
        f"The probe does not prove what it claims to."
    )
    assert result["backends"] == ["python"], (
        f"With MLX and NumPy absent the only backend should be the pure-Python "
        f"reference; got {result['backends']}."
    )

    # The run itself, compared against this interpreter — where MLX *is*
    # available and the default policy still declines to use it at 59 nodes.
    runner = _reference_run()
    assert result["status"] == runner["status"]
    assert result["answer"] == runner["answer"]
    assert result["codelets"] == runner["codelets"]
    assert result["rng_calls"] == runner["rng_calls"], (
        "The run consumed a different number of random draws with the optional "
        "packages absent, so their presence is changing the engine's behaviour."
    )


def _reference_run() -> dict:
    from server.engine.runner import EngineRunner

    runner = EngineRunner(MetadataProvider.from_seed_data(SEED_DIR))
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    runner.run_mcat(max_steps=6000)
    workspace = runner.ctx.workspace
    return {
        "status": runner.status,
        "answer": workspace.answer_string.text if workspace.answer_string else "",
        "codelets": runner.ctx.codelet_count,
        "rng_calls": runner.ctx.rng.call_count,
    }

