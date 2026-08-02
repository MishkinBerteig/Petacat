"""Vectorised float64 on the CPU.

Two jobs, and it is worth being clear that they are different jobs.

The first is to be the *fast exact* backend.  NumPy computes in float64, the same
precision the reference uses, so where this backend and the reference disagree the
disagreement is attributable to a specific re-association and can be bounded,
rather than being lost in a general float32 fog.  That makes it the backend to
reach for when a large Slipnet needs to run and reproducibility matters more than
raw speed.

The second is to be the *honest CPU baseline* for the scaling curve.  A GPU
compared against a Python loop is not being compared against a CPU; it is being
compared against the CPython interpreter, and it will win by two orders of
magnitude at every problem size for reasons that have nothing to do with Metal.
The crossover point this work package is asked to find is only meaningful against
a CPU implementation that is itself competent, which is what this is.

Where NumPy's primitive choice matters
--------------------------------------
The segmented reduction over incoming edges is done with ``np.bincount``, not with
``np.add.at``.  ``np.add.at`` would let the contributions be accumulated in the
reference's own scatter order and would therefore be bit-exact, but it is
unbuffered and runs at roughly a tenth of ``bincount``'s rate — at 10⁵ nodes that
is the difference between the backend being worth using and not.  The ordering
difference this accepts is analysed in ``python_backend.PythonSlipnetSession._spread``
and is bounded below 1e-13.
"""

from __future__ import annotations

from typing import Sequence

# Unguarded, and that is the contract: this module is imported only through
# ``backend._classes()``, which catches the ``ImportError`` and simply does not
# register the backend.  Guarding here as well would mean a half-imported module
# that fails later at a call site instead of at the point of absence.
import numpy as np

from server.engine.numeric.backend import Backend, SlipnetSession
from server.engine.numeric.layout import (
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


class NumpySlipnetSession(SlipnetSession):
    """Node state and the CSR graph as float64/int32 arrays."""

    __slots__ = (
        "topology", "n", "activation", "buffer", "frozen", "clamp_remaining",
        "decay_rate", "src", "dst", "weight", "_scaled_weight", "_scaled_for",
    )

    def __init__(self, topology: SlipnetTopology) -> None:
        self.topology = topology
        n = topology.n_nodes
        self.n = n
        self.activation = np.zeros(n, dtype=np.float64)
        self.buffer = np.zeros(n, dtype=np.float64)
        self.frozen = np.zeros(n, dtype=bool)
        self.clamp_remaining = np.zeros(n, dtype=np.int32)
        self.decay_rate = np.asarray(topology.decay_rate, dtype=np.float64)
        # int32 rather than the platform default: at 10⁵ nodes and 3.4 links per
        # node the index arrays are the largest thing in the layout, and halving
        # them halves the memory traffic of the gather, which is what this kernel
        # is bound by.
        self.src = np.asarray(topology.in_source, dtype=np.int32)
        self.dst = np.asarray(topology.in_dest, dtype=np.int32)
        self.weight = np.asarray(topology.in_weight, dtype=np.float64)
        self._scaled_weight = self.weight
        self._scaled_for = 1.0

    def load(self, state: SlipnetState) -> None:
        self.activation = np.asarray(state.activation, dtype=np.float64)
        self.buffer = np.asarray(state.buffer, dtype=np.float64)
        self.frozen = np.asarray(state.frozen, dtype=bool)
        self.clamp_remaining = np.asarray(state.clamp_remaining, dtype=np.int32)

    def store(self) -> SlipnetState:
        return SlipnetState(
            activation=self.activation.tolist(),
            buffer=self.buffer.tolist(),
            frozen=self.frozen.tolist(),
            clamp_remaining=self.clamp_remaining.tolist(),
        )

    def _weights(self, scale: float) -> "np.ndarray":
        if scale != self._scaled_for:
            self._scaled_weight = scale * self.weight
            self._scaled_for = scale
        return self._scaled_weight

    def update(self, threshold: float, scale: float) -> None:
        act = self.activation
        buf = self.buffer

        # Decay.  Subtracting a ``where``-masked term rather than indexing keeps
        # this one pass over contiguous memory; subtracting exact zero from the
        # frozen entries is bit-identical to skipping them.
        buf -= np.where(self.frozen, 0.0, self.decay_rate * act)

        if self.src.size:
            a = act[self.src]
            gate = (a > 0.0) & (a >= threshold)
            contrib = np.rint(self._weights(scale) * a)
            # ``np.rint`` is round-half-to-even, which is what Python's ``round``
            # does for a float, so the per-edge contribution is the same integer
            # the reference computes.
            np.multiply(contrib, gate, out=contrib)
            buf += np.bincount(self.dst, weights=contrib, minlength=self.n)

        np.add(act, buf, out=act)
        np.clip(act, 0.0, 100.0, out=act)
        buf.fill(0.0)

    def jump_candidates(self) -> tuple[list[int], list[float]]:
        act = self.activation
        p = (act / 100.0) ** 3
        eligible = (act > 0.0) & (p > 0.0) & (p < 1.0)
        idx = np.flatnonzero(eligible)
        return idx.tolist(), p[idx].tolist()

    def apply_jumps(self, indices: Sequence[int]) -> None:
        if len(indices):
            self.activation[np.asarray(indices, dtype=np.int64)] = 100.0


class NumpyBackend(Backend):
    name = "numpy"
    exact = True

    @classmethod
    def is_available(cls) -> bool:
        return True  # the module does not import without numpy

    def open_slipnet(self, topology: SlipnetTopology) -> SlipnetSession:
        return NumpySlipnetSession(topology)

    # -- Themespace ---------------------------------------------------------

    def spread_themes(
        self, layout: ThemeLayout, state: ThemeState, params: ThemeParams
    ) -> None:
        """Slots sequentially, clusters in parallel.

        ``themes.ss:520-527`` is Jacobi — three passes over a cluster, so every net
        input is computed from the activations as they stood at the start of the step.
        The slot loop therefore reads a snapshot taken before any write, and the writes
        are deferred to a second loop.  Clusters are independent and become the vector
        dimension: with nine dimensions and three bridge types that is 27 lanes today —
        small, but it grows with the theme vocabulary rather than with the string
        length, which is the axis this is sized for.
        """
        c, s = layout.n_clusters, layout.n_slots
        if c == 0 or s == 0:
            return
        act = np.asarray(state.activation, dtype=np.float64).reshape(c, s)
        valid = np.asarray(layout.valid, dtype=bool).reshape(c, s)
        frozen = np.asarray(state.frozen, dtype=bool).reshape(c, s)
        cluster_live = ~np.asarray(state.cluster_frozen, dtype=bool)

        alpha = (
            params.sensitivity
            * (1.0 / 50.0)
            * (1.0 / np.asarray(layout.n_relations, dtype=np.float64))
        )
        self_term = params.self_weight / 100.0
        w_nn = params.neg_to_neg / 100.0
        w_np = params.neg_to_pos / 100.0
        w_pn = params.pos_to_neg / 100.0
        w_pp = params.pos_to_pos / 100.0

        # Passes one and two: every read below is of ``snapshot``, never of ``act``,
        # which the third pass is about to overwrite.
        snapshot = act.copy()
        effects = np.zeros((c, s), dtype=np.float64)
        live_slots = np.zeros((c, s), dtype=bool)

        for t in range(s):
            live = cluster_live & valid[:, t] & ~frozen[:, t]
            live_slots[:, t] = live
            if not live.any():
                continue
            target = snapshot[:, t]
            target_neg = target < 0.0

            net = np.full(c, -params.decay, dtype=np.float64)
            net += np.where(target > 0.0, target * self_term, 0.0)

            for source in range(s):
                if source == t:
                    continue
                a = snapshot[:, source]
                src_neg = a < 0.0
                weight = np.where(
                    src_neg,
                    np.where(target_neg, w_nn, w_np),
                    np.where(target_neg, w_pn, w_pp),
                )
                contribution = np.where(
                    valid[:, source] & (a != 0.0), np.abs(a) * weight, 0.0
                )
                net += contribution

            effects[:, t] = np.rint(params.spread_amount * np.tanh(alpha * net))

        # Pass three: apply.
        for t in range(s):
            live = live_slots[:, t]
            if not live.any():
                continue
            effect = effects[:, t]
            # ``activation-function`` (``themes.ss:456-459``) branches on the theme's
            # own sign and clips to its own half of the range.
            target_neg = snapshot[:, t] < 0.0
            updated = np.where(
                target_neg,
                np.clip(act[:, t] - effect, -100.0, 0.0),
                np.clip(act[:, t] + effect, 0.0, 100.0),
            )
            act[:, t] = np.where(live, updated, act[:, t])

        state.activation = act.reshape(-1).tolist()

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

        rel = np.asarray(batch.relative_importance, dtype=np.float64)
        intra = np.asarray(batch.intra_unhappiness, dtype=np.float64)
        h = np.asarray(batch.horizontal_unhappiness, dtype=np.float64)
        v = np.asarray(batch.vertical_unhappiness, dtype=np.float64)
        clamped = np.asarray(batch.salience_clamped, dtype=bool)
        stype = np.asarray(batch.string_type, dtype=np.int64)
        justify = np.asarray(batch.justify_mode, dtype=bool)
        prev_h = np.asarray(batch.prev_horizontal_salience, dtype=np.float64)
        prev_v = np.asarray(batch.prev_vertical_salience, dtype=np.float64)

        is_initial = stype == STRING_INITIAL
        is_modified = stype == STRING_MODIFIED
        is_target = stype == STRING_TARGET
        is_answer = stype == STRING_ANSWER
        target_justifying = is_target & justify

        # Average unhappiness: which terms are averaged is a function of the
        # string type only, so the three candidate means are all computed and
        # selected between rather than branched over.
        mean3_hv = (intra + h + v) / 3.0
        mean3_vh = (intra + v + h) / 3.0
        mean_h = (intra + h) / 2.0
        mean_v = (intra + v) / 2.0
        avg_unhappy = np.where(
            is_initial, mean3_hv,
            np.where(
                is_modified | is_answer, mean_h,
                np.where(is_target, np.where(justify, mean3_vh, mean_v), intra),
            ),
        )

        s_intra = np.where(clamped, 100.0, np.rint(0.8 * intra + 0.2 * rel))

        h_formula = np.rint(0.2 * h + 0.8 * rel)
        v_formula = np.rint(0.2 * v + 0.8 * rel)
        writes_h = is_initial | is_modified | is_answer | target_justifying
        writes_v = is_initial | is_target
        s_h = np.where(clamped, 100.0, np.where(writes_h, h_formula, prev_h))
        s_v = np.where(clamped, 100.0, np.where(writes_v, v_formula, prev_v))

        sal3_hv = (s_intra + s_h + s_v) / 3.0
        sal3_vh = (s_intra + s_v + s_h) / 3.0
        sal_h = (s_intra + s_h) / 2.0
        sal_v = (s_intra + s_v) / 2.0
        s_avg = np.where(
            is_initial, sal3_hv,
            np.where(
                is_modified | is_answer, sal_h,
                np.where(is_target, np.where(justify, sal3_vh, sal_v), s_intra),
            ),
        )
        # The innermost ``np.where`` default is the ``STRING_OTHER`` branch of
        # ``update_average_unhappiness`` / ``update_average_salience``: neither
        # inter-string term applies, so the intra-string value stands alone.

        batch.average_unhappiness = _as_ints(np.rint(avg_unhappy))
        batch.intra_salience = _as_ints(s_intra)
        batch.horizontal_salience = _as_ints(s_h)
        batch.vertical_salience = _as_ints(s_v)
        batch.average_salience = _as_ints(np.rint(s_avg))

    # -- Structures and temperature ----------------------------------------

    def structure_strengths(
        self,
        internal: Sequence[float],
        external: Sequence[float],
        compatibility: Sequence[float],
    ) -> list[int]:
        if len(internal) == 0:
            return []
        w_int = np.asarray(internal, dtype=np.float64)
        ext = np.asarray(external, dtype=np.float64)
        comp = np.asarray(compatibility, dtype=np.float64)

        w_ext = 100.0 - w_int
        total = w_int + w_ext
        intrinsic = np.divide(
            w_int * w_int + ext * w_ext,
            total,
            out=np.zeros_like(total),
            where=total != 0,
        )

        weight = np.abs(comp)
        other = 1.0 - weight
        denominator = weight + other
        target = np.where(comp > 0.0, 100.0, 0.0)
        thematic = np.divide(
            target * weight + intrinsic * other,
            denominator,
            out=np.zeros_like(denominator),
            where=denominator != 0,
        )
        return _as_ints(np.rint(np.where(weight == 0.0, intrinsic, thematic)))

    def average_unhappiness(
        self, intra: Sequence[float], relative_importance: Sequence[float]
    ) -> int:
        n = len(intra)
        if n == 0:
            return 100
        a = np.asarray(intra, dtype=np.float64)
        w = np.asarray(relative_importance, dtype=np.float64)
        total = float(w.sum())
        if total > 0:
            return int(np.rint(float((a * w).sum()) / total))
        return int(np.rint(float(a.sum()) / n))

    def temperature(
        self,
        avg_unhappiness: float,
        rule_factor: float,
        unhappiness_weight: float,
        rule_weight: float,
    ) -> int:
        total_weight = unhappiness_weight + rule_weight
        if total_weight == 0:
            return round(avg_unhappiness)
        return round(
            (avg_unhappiness * unhappiness_weight + rule_factor * rule_weight)
            / total_weight
        )


def _as_ints(values: "np.ndarray") -> list[int]:
    """Round-tripped to Python ``int``, because that is what ``round()`` returns.

    These values are serialised, compared in unit tests and used as stochastic
    weights.  Handing back ``np.float64`` would work everywhere and be visible in
    two of those three places, which is the worst kind of difference.

    ``astype`` truncates rather than rounds, which is safe only because every
    caller has already applied ``np.rint`` — and it is worth the care, because the
    obvious ``[int(x) for x in values]`` is a Python loop and this is not.
    """
    return values.astype(np.int64).tolist()
