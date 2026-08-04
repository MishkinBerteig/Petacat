"""Hand-written Metal for the one traversal MLX cannot express.

MLX composes elementwise operations, gathers, reductions along an axis, and
matrix products.  The Slipnet's activation spreading is none of those.  It is a
*segmented* reduction over a ragged CSR row structure with a rounding step applied
to each edge before it is summed, and the closest thing MLX offers is a scatter
with atomic accumulation (``array.at[idx].add(...)``), which has two problems that
matter here rather than in general:

1. **Atomic float addition is not deterministic.**  The order in which competing
   threads land on the same accumulator is a property of how the GPU happened to
   schedule them.  Petacat's whole verification strategy — the expected-range
   oracle, seeded spot-checks, Audit-mode replay — rests on a run being a function
   of its seed.  A non-deterministic reduction would put a source of variation
   into the engine that no seed controls.

2. **The rounding is per edge, not on the sum.**  ``slipnet.ss:183-185`` rounds
   each contribution to an integer *before* accumulating it, so the sum of the
   rounded parts is not the rounded sum.  Expressing that in MLX means
   materialising an edge-length intermediate — at 10⁵ nodes and 3.4 links per
   node, 340,000 float32 values written to memory and immediately read back — and
   then dispatching the reduction as a second kernel.

The kernel below does the whole update cycle in one dispatch and one pass over
memory: decay, the gather-round-sum over incoming edges, and the flush with its
clip into [0, 100].  Nothing is materialised between the stages.  That fusion is
the actual argument for writing Metal by hand — not that MLX cannot compute the
answer, but that computing it in MLX costs six dispatches and two edge-length
round trips where one dispatch and zero round trips will do.

Choosing the parallel decomposition
-----------------------------------
Each destination node's incoming edges are reduced by a *group of lanes*, and how
many lanes to give a row is the one tuning decision in this file.  It is not
obvious and it is not size-independent, so it was measured, on synthetic Slipnets
at the real link density, milliseconds per update cycle, fastest of fifteen:

     nodes      1 lane   2 lanes   4 lanes   8 lanes  16 lanes  32 lanes
     1,000       0.214     0.281     0.269     0.228   *0.183     0.196
    10,000       0.219     0.206     0.219    *0.195    0.209     0.244
   100,000       0.292     0.260     0.247    *0.226    0.277     0.464
   300,000       0.307     0.288    *0.243     0.431    0.514     0.664

Two effects pull in opposite directions, and the table is the two of them
crossing.

*Below about 10,000 rows the kernel is latency-bound*: there are not enough rows
to fill the GPU's cores, so splitting each row across more lanes buys parallelism
that would otherwise go unused.  A full SIMD group per row — the obvious choice,
and the one ``metal::simd_sum`` makes natural — is right here.  How many rows
count as "not enough" scales with the GPU, which is why the thread target below
is read from the machine rather than fixed.

*Above it the kernel is occupancy-bound*: with a mean in-degree of 3.4, giving a
row 32 lanes leaves 29 of them with no edge to fetch, and the wasted launches
dominate.  At 300,000 nodes the full-SIMD-group version is **2.7× slower** than
the four-lane one.  That is the number that mattered for this work package: the
naive decomposition is the wrong one at exactly the scale the Slipnet is growing
toward.

``lanes_per_row`` below therefore picks from the graph's own statistics.  Because
the lane count is a runtime value rather than 32, the reduction is a shuffle-down
sweep rather than ``metal::simd_sum``; at one lane the sweep has zero iterations
and the kernel degenerates exactly into one thread per row, with no reduction at
all.
"""

from __future__ import annotations

from typing import Any, Sequence

from server.engine import hardware

#: Lanes per SIMD group on Apple silicon.  Not configurable — it is a property of
#: the hardware, and it caps how many lanes can cooperate on one row, because a
#: shuffle cannot cross a SIMD group.
SIMD_WIDTH = 32

#: Threads per threadgroup.
THREADGROUP_SIZE = 256

#: How many edges one lane may serialise before the row is split further.  This is
#: what keeps a hub node from stalling its whole group: today's longest row is 29
#: edges, so it does nothing yet, but a vocabulary-scale Slipnet's category nodes
#: will have in-degrees in the thousands and this is the term that responds to
#: them.
MAX_EDGES_PER_LANE = 32


def _next_power_of_two(value: float) -> int:
    n = 1
    while n < value:
        n <<= 1
    return n


def target_threads() -> int:
    """Threads the dispatch aims for before it stops splitting rows further.

    ``hardware.gpu_target_threads`` computes it from the detected GPU core count,
    at 1,024 threads per core rounded up to a power of two.  A 38-core GPU asks
    for 65,536 threads, which is the target the lane table above was measured at;
    a GPU with twice the cores asks for twice as many and splits rows twice as
    widely in the latency-bound regime.
    """
    return hardware.gpu_target_threads()


def lanes_per_row(
    n_rows: int,
    n_edges: int,
    max_in_degree: int,
    threads: int | None = None,
) -> int:
    """How many lanes cooperate on one destination node.  See the module docstring.

    Three demands, and the largest wins: enough total threads to fill the GPU,
    enough lanes that an average row's edges are fetched in parallel rather than
    serially, and enough lanes that the *longest* row does not serialise its
    group.  Rounded up to a power of two because the shuffle-down sweep halves its
    offset each step, and capped at the SIMD width because a shuffle cannot cross
    a SIMD group.

    ``threads`` is the total thread target the first demand is measured against,
    and defaults to :func:`target_threads` — this machine's GPU.  Passing it
    explicitly asks what the rule would produce for a GPU of a stated size.
    """
    if n_rows <= 0:
        return 1
    mean_degree = n_edges / n_rows
    demand = max(
        mean_degree,
        (target_threads() if threads is None else threads) / n_rows,
        max_in_degree / MAX_EDGES_PER_LANE,
    )
    return max(1, min(SIMD_WIDTH, _next_power_of_two(demand)))


def max_in_degree(indptr: Sequence[int]) -> int:
    """Longest CSR row.  O(n) once, at session open, never per cycle."""
    return max(
        (indptr[i + 1] - indptr[i] for i in range(len(indptr) - 1)), default=0
    )


#: The fused decay → spread → flush kernel.
#:
#: ``params`` carries ``[threshold, scale, n_nodes, lanes]`` as floats rather than
#: as four scalar inputs, because every input becomes a buffer binding and four
#: bindings for four numbers is worse than one.
SLIPNET_UPDATE_SOURCE = """
    uint lanes = (uint) params[3];
    uint gid = thread_position_in_grid.x;
    uint row = gid / lanes;
    uint lane = gid % lanes;

    float threshold = params[0];
    float scale = params[1];
    uint n_nodes = (uint) params[2];

    // Whole lane groups fall out together, because `row` is uniform across a
    // group: the shuffles below require every lane of the group to reach them.
    if (row >= n_nodes) {
        return;
    }

    int start = indptr[row];
    int end = indptr[row + 1];

    float partial = 0.0f;
    for (int e = start + (int) lane; e < end; e += (int) lanes) {
        float a = activation[source[e]];
        // Both conditions are in the reference: `spread_activation_to_neighbors`
        // returns early at zero activation, and the caller gates on the
        // configurable spreading threshold.
        if (a > 0.0f && a >= threshold) {
            partial += metal::rint((scale * weight[e]) * a);
        }
    }

    // Shuffle-down sweep across the row's lanes.  Lanes at or above `lanes/2`
    // read across the group boundary and end up with values nobody uses; lane 0
    // reads only lanes that hold correct partial sums at each step, which is the
    // standard down-sweep invariant.  At `lanes == 1` this loop does not execute.
    for (uint off = lanes >> 1; off > 0u; off >>= 1) {
        partial += metal::simd_shuffle_down(partial, off);
    }

    if (lane == 0u) {
        float a_d = activation[row];
        float b = buffer[row];
        // The decay amount is rounded, and `metal::rint` is round-half-to-even
        // like Python's `round`.  `precise::divide` rather than `/` because MLX
        // compiles its kernels with fast math, under which `/` may be an
        // approximate reciprocal-multiply — and this division has to be
        // correctly rounded, or a quotient of exactly n + 0.5 (which is what
        // produces the reference's decay plateaus) would land on either side of
        // the tie at the compiler's discretion.
        // A frozen node neither decays nor *receives*: `increment-activation-buffer`
        // (slipnet.ss:157-160) refuses while the node is frozen, which is what makes
        // a clamp hold a value rather than merely start it there.
        if (frozen[row] == 0u) {
            b -= metal::rint(metal::precise::divide(decay_percent[row] * a_d, 100.0f));
            b += partial;
        }
        float updated = a_d + b;
        out[row] = metal::min(100.0f, metal::max(0.0f, updated));
    }
"""

SLIPNET_UPDATE_INPUTS = (
    "activation",
    "buffer",
    "frozen",
    "decay_percent",
    "indptr",
    "source",
    "weight",
    "params",
)

_CACHE: dict[str, Any] = {}


def slipnet_update_kernel() -> Any:
    """Compile (once) and return the fused update kernel.

    Imported lazily and cached, because ``mx.fast.metal_kernel`` JIT-compiles on
    first call and there is no reason for a process to pay that twice — nor for a
    process that never uses MLX to pay it at all.
    """
    if "slipnet_update" not in _CACHE:
        import mlx.core as mx

        _CACHE["slipnet_update"] = mx.fast.metal_kernel(
            name="petacat_slipnet_update",
            input_names=list(SLIPNET_UPDATE_INPUTS),
            output_names=["out"],
            source=SLIPNET_UPDATE_SOURCE,
        )
    return _CACHE["slipnet_update"]


def grid_for(n_nodes: int, lanes: int) -> tuple[int, int, int]:
    return (max(SIMD_WIDTH, n_nodes * lanes), 1, 1)


def threadgroup_for(n_nodes: int, lanes: int) -> tuple[int, int, int]:
    return (min(THREADGROUP_SIZE, max(SIMD_WIDTH, n_nodes * lanes)), 1, 1)
