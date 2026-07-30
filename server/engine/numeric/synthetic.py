"""Synthetic Slipnets, for measuring the scaling curve before the real one grows.

The Phase 0 plan asks for kernel timings at 59, 10³, 10⁴ and 10⁵ nodes "so the
scaling curve is known before the Slipnet grows into it".  There is no 10⁵-node
Slipnet to measure, so one is generated — and the only thing that makes such a
measurement worth anything is whether the generated graph resembles the real one
in the properties the kernel is sensitive to.

Three properties, measured off the real 59-node Slipnet and reproduced here:

**Density: 202 links over 59 nodes, 3.42 links per node.**  This is the headline
number and it is what ``links_per_node`` defaults to.  It is a modest density, and
that is itself a finding: the traversal is bound by the irregular gather
``activation[source[e]]`` rather than by arithmetic, so a sparser graph is a
*harder* problem per unit of work, not an easier one.

**Degree distribution: heavy-tailed in both directions.**  Out-degrees are 2, 3 or
4 for 51 of the 59 nodes — and 28 for one of them, ``plato-letter-category``,
which has an instance link to every letter.  In-degrees run the same way, with a
29 at the top.  A category node in a vocabulary-scale Slipnet will have far more
than 28 instances, so the tail is the part that grows.

The **in**-degree is the one that has to be right.  The kernel parallelises over
destinations, so a row's length is a node's in-degree, and a synthetic graph with
uniform in-degrees would make the one-SIMD-group-per-row decomposition look
pointless — which is exactly the wrong conclusion to draw about a graph whose
longest row is nine times its mean.  The generator therefore draws in-degrees from
the observed in-degree histogram and picks each edge's source with a probability
proportional to a weight drawn from the out-degree histogram, so both
distributions come out with the measured shape.  (Drawing destinations uniformly,
which is the obvious thing to do, gives Poisson in-degrees with a maximum around
13 at 10,000 nodes: no tail at all.)

One way in which this is deliberately *conservative*: because the histogram is
reproduced rather than extrapolated, the longest row stays around 29 at every
size, where a real 300,000-node Slipnet's category nodes would have in-degrees in
the thousands.  The synthetic graph therefore understates the load imbalance the
kernel will actually face, which means the SIMD-group-per-row decomposition is
worth more at scale than these measurements show, not less.

**Association weights: strongly multi-modal.**  ``degree_of_association`` takes 13
distinct values across the 202 links, clustered at 40 (61 links), 80 (28), 3 (26)
and 70 (18).  Weights do not affect the traversal's cost, but they do affect how
many per-edge contributions round to zero, which affects nothing on the CPU and
nothing on the GPU — it is reproduced because a synthetic graph that is realistic
in two of three respects invites the question about the third.

Nothing here imports the engine's Slipnet.  A synthetic topology is built straight
into the flat layout, with no ``SlipnetNode`` objects anywhere, because that is
what a 300,000-node Slipnet will do and measuring the object-graph adapter at that
size would measure the adapter.
"""

from __future__ import annotations

import random

from server.engine.numeric.layout import SlipnetState, SlipnetTopology

#: Out-degree histogram of the real Slipnet, as ``(degree, count)`` over 59 nodes.
#: Measured, not assumed — see the module docstring.
REAL_OUT_DEGREE_HISTOGRAM: tuple[tuple[int, int], ...] = (
    (0, 2), (1, 1), (2, 11), (3, 33), (4, 7), (5, 1), (6, 2), (7, 1), (28, 1),
)

#: In-degree histogram, same 59 nodes and 202 links.  This is the distribution the
#: kernel's load balance actually depends on, because rows are destinations.
REAL_IN_DEGREE_HISTOGRAM: tuple[tuple[int, int], ...] = (
    (0, 2), (1, 1), (2, 14), (3, 33), (4, 2), (5, 3), (6, 2), (10, 1), (29, 1),
)

#: ``degree_of_association`` histogram of the real Slipnet's 202 links.
REAL_ASSOCIATION_HISTOGRAM: tuple[tuple[float, int], ...] = (
    (0.0, 36), (3.0, 26), (5.0, 5), (10.0, 11), (20.0, 10), (25.0, 2), (30.0, 1),
    (40.0, 61), (50.0, 1), (70.0, 18), (80.0, 28), (90.0, 1), (100.0, 2),
)

#: Conceptual depths in the real Slipnet, which set the per-node decay rate.
REAL_DEPTHS: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90)

#: 202 / 59.  Stated as a constant so a caller that overrides it is visibly
#: choosing a different experiment.
REAL_LINKS_PER_NODE = 202 / 59


def _expand(histogram: tuple[tuple[float, int], ...]) -> list[float]:
    values: list[float] = []
    for value, count in histogram:
        values.extend([value] * count)
    return values


def synthetic_topology(
    n_nodes: int,
    links_per_node: float = REAL_LINKS_PER_NODE,
    seed: int = 0,
    update_cycle_length: int = 15,
) -> SlipnetTopology:
    """Build a ``SlipnetTopology`` of ``n_nodes`` with realistic structure.

    Deterministic in ``seed``, so a scaling measurement is reproducible and two
    backends can be compared on literally the same graph.
    """
    rng = random.Random(seed)
    target_edges = int(round(links_per_node * n_nodes))

    in_degree_pool = _expand(REAL_IN_DEGREE_HISTOGRAM)
    out_degree_pool = _expand(REAL_OUT_DEGREE_HISTOGRAM)
    association_pool = _expand(REAL_ASSOCIATION_HISTOGRAM)

    # In-degrees come from the observed histogram, then the total is corrected to
    # the requested density.  Correcting afterwards rather than rescaling the
    # histogram keeps the *shape* — in particular the hub tail — intact.
    in_degree = [int(rng.choice(in_degree_pool)) for _ in range(n_nodes)]
    total = sum(in_degree)
    while total > target_edges and total > 0:
        i = rng.randrange(n_nodes)
        if in_degree[i] > 0:
            in_degree[i] -= 1
            total -= 1
    while total < target_edges:
        in_degree[rng.randrange(n_nodes)] += 1
        total += 1

    # Sources are drawn with probability proportional to a weight taken from the
    # out-degree histogram.  A pool of repeated indices rather than a weighted
    # choice per edge: at 340,000 edges the pool is built once and each draw is a
    # single ``randrange``, where ``random.choices`` would rebuild or carry
    # cumulative weights across the whole node set.
    source_pool: list[int] = []
    for i in range(n_nodes):
        source_pool.extend([i] * int(rng.choice(out_degree_pool)))
    if not source_pool:  # pragma: no cover - only if every draw was degree 0
        source_pool = list(range(n_nodes))

    # Edges are emitted destination-major directly, which is the layout the
    # kernels want; the source-major intermediate the object graph would produce
    # is skipped entirely.
    indptr = [0]
    source: list[int] = []
    weight: list[float] = []
    dest_of_edge: list[int] = []
    pool_size = len(source_pool)
    for d in range(n_nodes):
        for _ in range(in_degree[d]):
            src = source_pool[rng.randrange(pool_size)]
            if src == d:  # the real Slipnet has no self-links
                src = (src + 1) % n_nodes
            source.append(src)
            weight.append(rng.choice(association_pool) / 100.0)
            dest_of_edge.append(d)
        indptr.append(len(source))

    depths = [rng.choice(REAL_DEPTHS) for _ in range(n_nodes)]
    exponent = update_cycle_length / 15.0
    decay = [1.0 - (d / 100.0) ** exponent for d in depths]

    return SlipnetTopology(
        node_names=tuple(f"synthetic-{i}" for i in range(n_nodes)),
        decay_rate=tuple(decay),
        conceptual_depth=tuple(float(d) for d in depths),
        in_indptr=tuple(indptr),
        in_source=tuple(source),
        in_weight=tuple(weight),
        in_dest=tuple(dest_of_edge),
    )


def synthetic_state(
    topology: SlipnetTopology,
    active_fraction: float = 0.12,
    seed: int = 1,
) -> SlipnetState:
    """A plausible mid-run activation state.

    ``active_fraction`` is the share of nodes carrying non-zero activation.
    Measured on the real engine over the profile problem, between 8% and 16% of
    nodes are active at any update cycle, so 12% is the middle of that band.

    It matters more than it looks.  The spreading kernel gates on
    ``activation >= threshold``, and at the default threshold of 100 only *fully*
    active nodes contribute at all — so a state where every node is active would
    measure a workload the engine never presents, and one where none is would
    measure an early-out.  A tenth of the nodes active, a few of them at exactly
    100, is the regime the kernel actually runs in.
    """
    rng = random.Random(seed)
    n = topology.n_nodes
    activation = [0.0] * n
    for i in range(n):
        if rng.random() < active_fraction:
            # A minority sit at exactly 100 — clamped, or having just jumped —
            # and those are the only ones that spread at the default threshold.
            activation[i] = 100.0 if rng.random() < 0.25 else rng.uniform(1.0, 99.0)
    return SlipnetState(
        activation=activation,
        buffer=[0.0] * n,
        frozen=[False] * n,
        clamp_remaining=[0] * n,
    )
