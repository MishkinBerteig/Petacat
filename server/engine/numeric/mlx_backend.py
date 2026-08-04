"""Metal via MLX, with a hand-written kernel for the sparse traversal.

Two backends live here because two questions have to be told apart.  ``mlx`` runs
on the GPU stream; ``mlx-cpu`` runs the same code on MLX's CPU stream.  Comparing
``mlx`` against ``numpy`` measures GPU-versus-CPU *and* MLX-versus-NumPy at the
same time and cannot separate them; comparing ``mlx`` against ``mlx-cpu`` isolates
the device, and comparing ``mlx-cpu`` against ``numpy`` isolates the framework.

The float32 constraint
----------------------
**MLX does not support float64 on the GPU.**  ``mx.array([1.0], dtype=mx.float64)``
is accepted, but any operation on it raises ``float64 is not supported on the
GPU``.  The GPU backend is therefore float32 throughout, against a reference that
is float64 throughout, and the two cannot agree bit for bit.  What they agree to
is measured rather than assumed: see ``tests/seed_unit/test_numeric_backends.py``,
which compares them element-wise over the real Slipnet across many update cycles.

This is the single largest constraint on the work package, and it is a property of
the hardware more than of MLX — Apple's GPUs have no double-precision units.  The
mitigation is structural rather than numerical: activations are bounded to
[0, 100] and per-edge contributions are rounded to integers *before* they are
summed, so the quantity float32 has to represent accurately is an integer no
larger than a few million, which it represents exactly.  The error that remains
enters through the decayed activation, not through the reduction.

A trap worth naming: Python scalars go through float32
------------------------------------------------------
Mixing a Python ``float`` into an MLX expression does not give it the array's
precision.  ``mx.array([...], dtype=mx.float64) / 7.08e-48`` evaluates to ``inf``,
because the scalar is converted to float32 first and 7.08e-48 is below float32's
smallest denormal.  This is not a float32-versus-float64 issue in the sense the
section above describes — it bites on the *CPU* backend too, which is nominally
exact.

It cost a real defect.  ``round(100 * raw_importance / Σraw)`` is an ordinary
ratio between 0 and 100, but its operands are sums of decayed descriptor
activations and reach 1e-48 in normal running; the denominator flushed to zero and
every relative importance became ``inf``.  Relative importance is now computed on
the host in float64 (``layout.relative_importances``), so nothing outside [0, 100]
ever reaches a device.  The general rule this leaves behind: keep reductions
*inside* the array expression, and treat any Python scalar crossing into MLX as
though it were float32, because it is.

The host round trip that cannot be avoided
------------------------------------------
``jump_candidates`` pulls state back to the host every update cycle, and no amount
of kernel work removes it: the probabilistic jump consumes the engine's RNG, the
RNG is a single seeded ``random.Random`` on the host, and the reference's draw
order is part of what the expected-range oracle holds fixed.  Until WP4.1 replaces
that with a counter-based splittable RNG — which *can* be evaluated on-device,
because a counter-based stream needs no shared state — one GPU→host synchronisation
per update cycle is structural.  On unified memory that synchronisation is a
command-buffer wait rather than a copy, so it costs latency and not bandwidth, but
at 59 nodes latency is the entire cost.
"""

from __future__ import annotations

from typing import Any, Sequence

# Unguarded: ``backend._classes()`` catches the ``ImportError`` and leaves the
# backend unregistered, which is what makes MLX optional.  NumPy is imported too
# and is a real requirement of *this* backend rather than an incidental one — it
# is how a device array is read on the host without a per-element Python call,
# which at 300,000 nodes is the difference between a memory view and a loop.
import mlx.core as mx
import numpy as np

from server.engine.numeric import metal_kernels
from server.engine.numeric.backend import Backend, SlipnetSession
from server.engine.numeric.layout import (
    FULL_ACTIVATION_THRESHOLD,
    MAX_ACTIVATION,
    STRING_ANSWER,
    STRING_INITIAL,
    STRING_MODIFIED,
    STRING_TARGET,
    ObjectValueBatch,
    SlipnetState,
    SlipnetTopology,
    ThemeLayout,
    ThemeParams,
    ThemeState,
)


def _gpu_usable() -> bool:
    """Whether Metal is actually present, not merely whether MLX imported.

    MLX installs on machines with no usable GPU, and a probe that only checks the
    import would hand back a backend whose first kernel launch fails.  One tiny
    evaluated operation is a cheap and complete answer.
    """
    try:
        probe = mx.array([1.0, 2.0], dtype=mx.float32)
        with mx.stream(mx.gpu):
            mx.eval(probe * probe)
    except Exception:  # pragma: no cover - depends on the machine
        return False
    return True


class MlxSlipnetSession(SlipnetSession):
    """Slipnet state resident in MLX arrays for the lifetime of a run."""

    __slots__ = (
        "topology", "device", "dtype", "use_kernel", "n", "lanes",
        "activation", "buffer", "frozen", "clamp_remaining",
        "decay_rate", "indptr", "source", "dest", "weight", "_zero",
    )

    def __init__(
        self,
        topology: SlipnetTopology,
        device: Any,
        dtype: Any,
        use_kernel: bool,
    ) -> None:
        self.topology = topology
        self.device = device
        self.dtype = dtype
        self.use_kernel = use_kernel
        n = topology.n_nodes
        self.n = n
        # Fixed at session open from the graph's own degree statistics, because
        # the topology is static; recomputing it per cycle would be waste, and
        # hard-coding it would be 2.7× too slow at 300,000 nodes.
        self.lanes = metal_kernels.lanes_per_row(
            n, topology.n_edges, metal_kernels.max_in_degree(topology.in_indptr)
        )
        with mx.stream(device):
            self.activation = mx.zeros((n,), dtype=dtype)
            self.buffer = mx.zeros((n,), dtype=dtype)
            self.frozen = mx.zeros((n,), dtype=mx.uint8)
            self.clamp_remaining = mx.zeros((n,), dtype=mx.int32)
            self.decay_rate = mx.array(list(topology.decay_rate), dtype=dtype)
            self.indptr = mx.array(list(topology.in_indptr), dtype=mx.int32)
            self.source = mx.array(list(topology.in_source), dtype=mx.int32)
            self.dest = mx.array(list(topology.in_dest), dtype=mx.int32)
            self.weight = mx.array(list(topology.in_weight), dtype=dtype)
            self._zero = mx.zeros((n,), dtype=dtype)
            mx.eval(
                self.decay_rate, self.indptr, self.source, self.dest,
                self.weight, self._zero,
            )

    # -- host boundary ------------------------------------------------------

    def load(self, state: SlipnetState) -> None:
        with mx.stream(self.device):
            self.activation = mx.array(state.activation, dtype=self.dtype)
            self.buffer = mx.array(state.buffer, dtype=self.dtype)
            self.frozen = mx.array(state.frozen).astype(mx.uint8)
            self.clamp_remaining = mx.array(state.clamp_remaining, dtype=mx.int32)

    def store(self) -> SlipnetState:
        # ``np.array(..., copy=False)`` on an evaluated MLX array is a view into
        # the same unified memory, and ``tolist`` converts it in C.  Iterating the
        # array in Python instead — ``[float(x) for x in ...]`` — costs about a
        # microsecond an element, which is 100 ms per update cycle at 300,000
        # nodes and would dwarf everything this substrate saves.
        mx.eval(self.activation, self.buffer)
        return SlipnetState(
            activation=np.array(self.activation, copy=False).tolist(),
            buffer=np.array(self.buffer, copy=False).tolist(),
            frozen=np.array(self.frozen, copy=False).astype(bool).tolist(),
            clamp_remaining=np.array(self.clamp_remaining, copy=False).tolist(),
        )

    # -- the update cycle ---------------------------------------------------

    def update(self, threshold: float, scale: float) -> None:
        with mx.stream(self.device):
            if self.use_kernel and self.n:
                self._update_fused(threshold, scale)
            else:
                self._update_composed(threshold, scale)
            self.buffer = self._zero
            # Forced here rather than left lazy.  ``jump_candidates`` needs the
            # result on the host in the very next call, so deferring the
            # evaluation would only move the same wait a few microseconds later
            # while making the timing attribution wrong.
            mx.eval(self.activation)

    def _update_fused(self, threshold: float, scale: float) -> None:
        kernel = metal_kernels.slipnet_update_kernel()
        params = mx.array(
            [threshold, scale, float(self.n), float(self.lanes)], dtype=self.dtype
        )
        outputs = kernel(
            inputs=[
                self.activation, self.buffer, self.frozen, self.decay_rate,
                self.indptr, self.source, self.weight, params,
            ],
            grid=metal_kernels.grid_for(self.n, self.lanes),
            threadgroup=metal_kernels.threadgroup_for(self.n, self.lanes),
            output_shapes=[(self.n,)],
            output_dtypes=[self.dtype],
        )
        self.activation = outputs[0]

    def _update_composed(self, threshold: float, scale: float) -> None:
        """The same computation in composed MLX operations.

        Kept as a real code path rather than as a comment, for three reasons: it
        is what the CPU stream must use, since ``mx.fast.metal_kernel`` is
        GPU-only; it is the control that says what the hand-written kernel bought;
        and it is the fallback if a future MLX version changes the custom-kernel
        interface.

        The scatter uses ``at[...].add``, whose float accumulation order is not
        guaranteed — acceptable only because the values being accumulated are
        integers below 2²⁴, which float32 sums exactly in any order.
        """
        act = self.activation
        buf = self.buffer
        decayed = mx.where(
            self.frozen != 0,
            mx.zeros_like(act),
            self.decay_rate * act,
        )
        buf = buf - decayed
        if self.topology.n_edges:
            a = act[self.source]
            gate = mx.logical_and(a > 0.0, a >= threshold)
            contribution = mx.round((scale * self.weight) * a)
            contribution = mx.where(gate, contribution, mx.zeros_like(contribution))
            buf = mx.zeros((self.n,), dtype=self.dtype).at[self.dest].add(
                contribution
            ) + buf
        self.activation = mx.clip(act + buf, 0.0, 100.0)

    # -- the probabilistic jump --------------------------------------------

    def jump_candidates(self) -> tuple[list[int], list[float]]:
        """Eligible nodes and their probabilities, resolved on the host.

        The probability is recomputed in float64 from the float32 activation
        rather than being computed on the device.  The host has to scan the
        activation array anyway to build the index list, so the cube costs
        nothing extra, and doing it in double removes one avoidable divergence
        from the reference: what remains is the difference in the activation
        itself, which is the difference this backend actually has.
        """
        mx.eval(self.activation)
        act = np.array(self.activation, copy=False).astype(np.float64)
        p = (act / MAX_ACTIVATION) ** 3
        # ``partially-active?`` (slipnet.ss:402-404): [50, 100).
        partial = (act >= FULL_ACTIVATION_THRESHOLD) & (act < MAX_ACTIVATION)
        eligible = partial & (p > 0.0) & (p < 1.0)
        idx = np.flatnonzero(eligible)
        return idx.tolist(), p[idx].tolist()

    def apply_jumps(self, indices: Sequence[int]) -> None:
        if not len(indices):
            return
        with mx.stream(self.device):
            self.activation[mx.array(list(indices), dtype=mx.int32)] = mx.array(
                100.0, dtype=self.dtype
            )


class MlxBackend(Backend):
    """MLX on the GPU stream: float32, with the fused Metal kernel."""

    name = "mlx"
    exact = False

    #: Device stream this backend dispatches on.  Overridden by ``MlxCpuBackend``.
    device = mx.gpu
    #: float32 because Apple GPUs have no double-precision units.
    dtype = mx.float32
    #: Whether to use the hand-written kernel.  Turned off by the CPU backend,
    #: which cannot run one, and by the benchmark when measuring what it bought.
    use_kernel = True

    def __init__(self, use_kernel: bool | None = None) -> None:
        if use_kernel is not None:
            self.use_kernel = use_kernel

    @classmethod
    def is_available(cls) -> bool:
        return _gpu_usable()

    def open_slipnet(self, topology: SlipnetTopology) -> SlipnetSession:
        return MlxSlipnetSession(
            topology, self.device, self.dtype, self.use_kernel
        )

    # -- Themespace ---------------------------------------------------------

    def spread_themes(
        self, layout: ThemeLayout, state: ThemeState, params: ThemeParams
    ) -> None:
        """Composed MLX, slots sequential and clusters vectorised.

        ``themes.ss:520-527`` is Jacobi — three passes over a cluster — so the slot
        loop reads a snapshot taken before any write and the writes are deferred.  There
        is no custom kernel here and there should not be: the traversal is a handful of
        steps over a 27-element vector, which is dispatch-bound on any device and would
        be dispatch-bound on a hand-written kernel too.  The reason it is implemented at
        all is that the theme vocabulary grows with the *conceptual* dimensions the
        architecture tracks, not with the letter strings, and the Phase 1-6 plans grow
        it substantially.
        """
        c, s = layout.n_clusters, layout.n_slots
        if c == 0 or s == 0:
            return
        dt = self.dtype
        with mx.stream(self.device):
            act = mx.array(state.activation, dtype=dt).reshape(c, s)
            valid = mx.array(
                [1 if v else 0 for v in layout.valid], dtype=mx.uint8
            ).reshape(c, s)
            frozen = mx.array(
                [1 if v else 0 for v in state.frozen], dtype=mx.uint8
            ).reshape(c, s)
            cluster_live = mx.array(
                [0 if v else 1 for v in state.cluster_frozen], dtype=mx.uint8
            )

            alpha = (
                params.sensitivity
                * (1.0 / 50.0)
                * (1.0 / mx.array(list(layout.n_relations), dtype=dt))
            )
            self_term = params.self_weight / 100.0
            w_nn = params.neg_to_neg / 100.0
            w_np = params.neg_to_pos / 100.0
            w_pn = params.pos_to_neg / 100.0
            w_pp = params.pos_to_pos / 100.0
            zeros = mx.zeros((c,), dtype=dt)

            # Passes one and two: read ``snapshot``, never ``act``.  A genuine copy —
            # ``snapshot = act`` would alias, and the third pass's column writes would
            # then be visible to reads that must not see them, quietly restoring the
            # Gauss-Seidel behaviour this replaces.
            snapshot = mx.array(act)
            effects = []
            lives = []

            for t in range(s):
                live = (cluster_live != 0) & (valid[:, t] != 0) & (frozen[:, t] == 0)
                lives.append(live)
                target = snapshot[:, t]
                target_neg = target < 0.0

                net = mx.full((c,), -params.decay, dtype=dt)
                net = net + mx.where(target > 0.0, target * self_term, zeros)

                for source in range(s):
                    if source == t:
                        continue
                    a = snapshot[:, source]
                    src_neg = a < 0.0
                    weight = mx.where(
                        src_neg,
                        mx.where(target_neg, w_nn, w_np),
                        mx.where(target_neg, w_pn, w_pp),
                    )
                    applies = (valid[:, source] != 0) & (a != 0.0)
                    net = net + mx.where(applies, mx.abs(a) * weight, zeros)

                effects.append(mx.round(params.spread_amount * mx.tanh(alpha * net)))

            # Pass three: apply.  ``act`` is rebuilt column by column, so the reads
            # above cannot see any of these writes.
            new_act = mx.array(act)
            for t in range(s):
                live = lives[t]
                effect = effects[t]
                # ``activation-function`` (``themes.ss:456-459``) branches on the
                # theme's own sign and clips to its own half of the range.
                target_neg = snapshot[:, t] < 0.0
                updated = mx.where(
                    target_neg,
                    mx.clip(act[:, t] - effect, -100.0, 0.0),
                    mx.clip(act[:, t] + effect, 0.0, 100.0),
                )
                new_act[:, t] = mx.where(live, updated, snapshot[:, t])
            act = new_act

            mx.eval(act)
            state.activation = [
                float(x) for x in np.array(act, copy=False).reshape(-1)
            ]

    # -- Workspace object values -------------------------------------------

    def combine_object_values(self, batch: ObjectValueBatch) -> None:
        n = len(batch)
        if n == 0:
            for name in (
                "average_unhappiness", "intra_salience",
                "horizontal_salience", "vertical_salience", "average_salience",
            ):
                setattr(batch, name, [])
            return
        dt = self.dtype
        with mx.stream(self.device):
            rel = mx.array(batch.relative_importance, dtype=dt)
            intra = mx.array(batch.intra_unhappiness, dtype=dt)
            h = mx.array(batch.horizontal_unhappiness, dtype=dt)
            v = mx.array(batch.vertical_unhappiness, dtype=dt)
            clamped = mx.array(
                [1 if c else 0 for c in batch.salience_clamped], dtype=mx.uint8
            ) != 0
            stype = mx.array(batch.string_type, dtype=mx.int32)
            justify = mx.array(
                [1 if j else 0 for j in batch.justify_mode], dtype=mx.uint8
            ) != 0
            prev_h = mx.array(batch.prev_horizontal_salience, dtype=dt)
            prev_v = mx.array(batch.prev_vertical_salience, dtype=dt)

            is_initial = stype == STRING_INITIAL
            is_modified = stype == STRING_MODIFIED
            is_target = stype == STRING_TARGET
            is_answer = stype == STRING_ANSWER

            avg_unhappy = mx.where(
                is_initial, (intra + h + v) / 3.0,
                mx.where(
                    is_modified | is_answer, (intra + h) / 2.0,
                    mx.where(
                        is_target,
                        mx.where(justify, (intra + v + h) / 3.0, (intra + v) / 2.0),
                        intra,
                    ),
                ),
            )

            hundred = mx.full((n,), 100.0, dtype=dt)
            s_intra = mx.where(clamped, hundred, mx.round(0.8 * intra + 0.2 * rel))

            writes_h = is_initial | is_modified | is_answer | (is_target & justify)
            writes_v = is_initial | is_target
            s_h = mx.where(
                clamped, hundred,
                mx.where(writes_h, mx.round(0.2 * h + 0.8 * rel), prev_h),
            )
            s_v = mx.where(
                clamped, hundred,
                mx.where(writes_v, mx.round(0.2 * v + 0.8 * rel), prev_v),
            )

            s_avg = mx.where(
                is_initial, (s_intra + s_h + s_v) / 3.0,
                mx.where(
                    is_modified | is_answer, (s_intra + s_h) / 2.0,
                    mx.where(
                        is_target,
                        mx.where(
                            justify,
                            (s_intra + s_v + s_h) / 3.0,
                            (s_intra + s_v) / 2.0,
                        ),
                        s_intra,
                    ),
                ),
            )

            batch.average_unhappiness = _as_ints(mx.round(avg_unhappy))
            batch.intra_salience = _as_ints(s_intra)
            batch.horizontal_salience = _as_ints(s_h)
            batch.vertical_salience = _as_ints(s_v)
            batch.average_salience = _as_ints(mx.round(s_avg))

    # -- Structures and temperature ----------------------------------------

    def structure_strengths(
        self,
        internal: Sequence[float],
        external: Sequence[float],
        compatibility: Sequence[float],
    ) -> list[int]:
        if len(internal) == 0:
            return []
        dt = self.dtype
        with mx.stream(self.device):
            w_int = mx.array(list(internal), dtype=dt)
            ext = mx.array(list(external), dtype=dt)
            comp = mx.array(list(compatibility), dtype=dt)

            w_ext = 100.0 - w_int
            total = w_int + w_ext
            safe_total = mx.where(total == 0.0, mx.ones_like(total), total)
            intrinsic = mx.where(
                total == 0.0,
                mx.zeros_like(total),
                (w_int * w_int + ext * w_ext) / safe_total,
            )

            weight = mx.abs(comp)
            other = 1.0 - weight
            denominator = weight + other
            safe_denominator = mx.where(
                denominator == 0.0, mx.ones_like(denominator), denominator
            )
            target = mx.where(comp > 0.0, 100.0, 0.0)
            thematic = mx.where(
                denominator == 0.0,
                mx.zeros_like(denominator),
                (target * weight + intrinsic * other) / safe_denominator,
            )
            return _as_ints(mx.round(mx.where(weight == 0.0, intrinsic, thematic)))

    def average_unhappiness(
        self, intra: Sequence[float], relative_importance: Sequence[float]
    ) -> int:
        n = len(intra)
        if n == 0:
            return 100
        with mx.stream(self.device):
            a = mx.array(list(intra), dtype=self.dtype)
            w = mx.array(list(relative_importance), dtype=self.dtype)
            # One host sync, not three.
            #
            # This is the most-dispatched operation in the engine — 557 calls in a
            # 2,229-codelet run, because the temperature update and the posting-probability
            # computation both ask for it — and the cost of a call is dominated by the
            # round trips, not by summing twenty floats.  Reading ``total`` back to decide
            # which branch to take, then reading the branch's result, cost three syncs
            # where the whole decision can be expressed in the graph and read once.
            total = mx.sum(w)
            weighted = mx.where(total > 0, mx.sum(a * w) / total, mx.sum(a) / n)
            return int(round(float(weighted.item())))

    def temperature(
        self,
        avg_unhappiness: float,
        rule_factor: float,
        unhappiness_weight: float,
        rule_weight: float,
    ) -> int:
        # Deliberately not dispatched.  A weighted average of two scalars takes a
        # few nanoseconds on the host and tens of microseconds through any device
        # queue; sending it to the GPU would be a worse implementation wearing the
        # costume of a better one.  When WP4.6 batches K runs this becomes a
        # K-element reduction and moves onto the device with the rest of the batch.
        total_weight = unhappiness_weight + rule_weight
        if total_weight == 0:
            return round(avg_unhappiness)
        return round(
            (avg_unhappiness * unhappiness_weight + rule_factor * rule_weight)
            / total_weight
        )


class MlxCpuBackend(MlxBackend):
    """MLX on the CPU stream: float64, no custom kernel.

    Its value is diagnostic.  It runs the same MLX graph as the GPU backend at the
    reference's precision, so a disagreement that survives here is a disagreement
    in the *formulation*, while one that appears only on ``mlx`` is float32.
    """

    name = "mlx-cpu"
    exact = True
    device = mx.cpu
    dtype = mx.float64
    use_kernel = False

    def __init__(self, use_kernel: bool | None = None) -> None:
        # ``mx.fast.metal_kernel`` is GPU-only; honouring a request for it here
        # would fail at the first dispatch instead of at the point of the mistake.
        super().__init__(use_kernel=False)

    @classmethod
    def is_available(cls) -> bool:
        try:
            with mx.stream(mx.cpu):
                mx.eval(mx.array([1.0], dtype=mx.float64) * 2.0)
        except Exception:  # pragma: no cover - depends on the MLX build
            return False
        return True


def _as_ints(values: Any) -> list[int]:
    """As ``numpy_backend._as_ints``: already rounded, converted in C, not Python."""
    mx.eval(values)
    return np.array(values, copy=False).astype(np.int64).tolist()
