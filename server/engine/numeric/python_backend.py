"""The reference backend: pure Python, no third-party import, always available.

This is not a fallback that happens to work — it is the definition of what the
other backends must compute.  Every loop here is a transcription of the
corresponding loop in ``slipnet.py``, ``themes.py``, ``workspace_objects.py`` or
``formulas.py`` onto the flat layouts, with the arithmetic left character for
character where it is at all possible to do so, because a numeric substrate that
quietly re-associates a sum is exactly the kind of change that moves an expected
range without anyone noticing.

The one place where an ordering difference is unavoidable is documented at
``_spread`` below, along with how large it is and why it is acceptable.
"""

from __future__ import annotations

import math
from typing import Sequence

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


class PythonSlipnetSession(SlipnetSession):
    """Holds the state as plain lists — ``load``/``store`` are shallow copies."""

    __slots__ = ("topology", "state", "_scaled_weight", "_scaled_for")

    def __init__(self, topology: SlipnetTopology) -> None:
        self.topology = topology
        self.state = SlipnetState(
            activation=[0.0] * topology.n_nodes,
            buffer=[0.0] * topology.n_nodes,
            frozen=[False] * topology.n_nodes,
            clamp_remaining=[0] * topology.n_nodes,
        )
        self._scaled_weight: list[float] = list(topology.in_weight)
        self._scaled_for = 1.0

    def load(self, state: SlipnetState) -> None:
        self.state = SlipnetState(
            activation=list(state.activation),
            buffer=list(state.buffer),
            frozen=list(state.frozen),
            clamp_remaining=list(state.clamp_remaining),
        )

    def store(self) -> SlipnetState:
        s = self.state
        return SlipnetState(
            activation=list(s.activation),
            buffer=list(s.buffer),
            frozen=list(s.frozen),
            clamp_remaining=list(s.clamp_remaining),
        )

    def _weights(self, scale: float) -> list[float]:
        """``scale * (association/100)`` per edge, cached.

        The reference computes ``scale * (assoc/100.0) * activation`` and Python
        evaluates that left to right, so folding the first product into a stored
        weight is not merely equivalent in exact arithmetic — it produces the same
        float64 value bit for bit.  ``scale`` is ``update_cycle_length/15``, which
        is 1.0 for every configuration in the seed data, so the cache is hit on
        every call after the first.
        """
        if scale != self._scaled_for:
            self._scaled_weight = [scale * w for w in self.topology.in_weight]
            self._scaled_for = scale
        return self._scaled_weight

    def update(self, threshold: float, scale: float) -> None:
        st = self.state
        top = self.topology
        act = st.activation
        buf = st.buffer
        pct = top.decay_percent

        # Decay (slipnet.ss:174-177).  Frozen nodes do not decay; every other
        # node loses ``round(rate * activation)`` from its buffer, not from its
        # activation, so the value spreading reads below is the pre-decay one.
        #
        # The amount is a whole number, and multiplying by the percentage before
        # dividing by 100 is what makes it the *same* whole number on every
        # backend — see ``SlipnetNode.decay`` for the reference and for the
        # plateau the rounding produces.
        for i, frozen in enumerate(st.frozen):
            if not frozen:
                buf[i] -= round(pct[i] * act[i] / 100.0)

        self._spread(threshold, scale)

        # Flush (slipnet.ss:583-585).  Applies to every node including frozen
        # ones: a clamped node that received spreading is clipped back to 100
        # rather than being skipped, which is what keeps ``clamp`` idempotent.
        for i in range(top.n_nodes):
            a = act[i] + buf[i]
            act[i] = 0.0 if a < 0.0 else (100.0 if a > 100.0 else a)
            buf[i] = 0.0

    def _spread(self, threshold: float, scale: float) -> None:
        """Sparse traversal: for each destination, sum its incoming contributions.

        The reference iterates sources and scatters (``slipnet.ss:201-214``); this
        iterates destinations and gathers.  The set of contributions is identical
        — the edge list is the same edges, regrouped — but the *summation order*
        into ``buffer[d]`` is not.

        That matters for exactly one reason and to exactly one degree.  Each
        contribution is ``round(...)``, an integer no greater than 100, and a sum
        of integers is exact in float64 however it is ordered.  The buffer may
        also hold a non-integer term when the contributions arrive, so the
        reference computes ``((b + a₁) + a₂) + a₃`` where this computes
        ``b + (a₁ + a₂ + a₃)``.  Those differ by at most a few units in the last
        place of a quantity bounded by ~200, i.e. below 1e-13.

        Since decay was rounded (slipnet.ss:174-177) that residual cannot arise
        from anything the engine itself does: the buffer's decay term is now an
        integer too, as are the Workspace jolt (100) and the Themespace's, so
        every addend is a whole number and the reassociation is exact.  What is
        left is a state *restored* with a fractional activation, or a synthetic
        one, for which the bound above still stands.

        The only place that difference can become visible is the probabilistic
        jump, where a perturbed activation shifts the threshold ``(a/100)³`` that
        a uniform draw is compared against.  A shift of 1e-15 in a threshold flips
        an outcome with probability ~1e-15 per draw; across the entire
        expected-range check (1,300 runs, ~150 cycles each) the expected number of
        flipped draws is ~1e-9.

        Measured, the difference is not merely small but *absent*: every float64
        backend reproduces whole runs bit for bit — same answer, same codelet
        count, same number of random draws — across the problems in
        ``tests/module/test_numeric_engine.py`` and all thirteen problems of the
        expected-range check.  That is luckier than the analysis promises, because
        the decay term and the integer contributions are usually far enough apart
        in magnitude for no rounding to occur at all; the bound above is what can
        be relied on, and the observation is what actually happens.

        Gathering rather than scattering is what buys a deterministic, atomic-free
        GPU kernel, which is the whole point of the layout.  Paying a bounded
        1e-13 for it is the right trade, and it is stated here rather than
        discovered later.
        """
        top = self.topology
        act = self.state.activation
        buf = self.state.buffer
        weight = self._weights(scale)
        indptr = top.in_indptr
        source = top.in_source

        for d in range(top.n_nodes):
            total = 0.0
            for e in range(indptr[d], indptr[d + 1]):
                a = act[source[e]]
                # ``spread_activation_to_neighbors`` returns early on
                # ``activation <= 0`` and the caller gates on ``>= threshold``;
                # both conditions are needed, because the threshold is
                # configurable down to 0 and a zero-activation node must still
                # not spread.
                if a > 0.0 and a >= threshold:
                    amount = round(weight[e] * a)
                    if amount > 0:
                        total += amount
            if total:
                buf[d] += total

    def jump_candidates(self) -> tuple[list[int], list[float]]:
        act = self.state.activation
        indices: list[int] = []
        probs: list[float] = []
        for i, a in enumerate(act):
            # ``partially-active?`` (slipnet.ss:402-404): the reference filters
            # the jump's candidates to [50, 100) before drawing at all.
            if not (FULL_ACTIVATION_THRESHOLD <= a < MAX_ACTIVATION):
                continue
            p = (a / MAX_ACTIVATION) ** 3
            # ``RNG.prob`` short-circuits at both ends without touching the
            # stream.  The window above already excludes p == 1 and p == 0, but
            # the guard is kept so this list is defined by the property that
            # matters — these are exactly the nodes that consume a draw.
            if 0.0 < p < 1.0:
                indices.append(i)
                probs.append(p)
        return indices, probs

    def apply_jumps(self, indices: Sequence[int]) -> None:
        act = self.state.activation
        for i in indices:
            act[i] = 100.0


class PythonBackend(Backend):
    name = "python"
    exact = True

    @classmethod
    def is_available(cls) -> bool:
        return True

    def open_slipnet(self, topology: SlipnetTopology) -> SlipnetSession:
        return PythonSlipnetSession(topology)

    # -- Themespace ---------------------------------------------------------

    def spread_themes(
        self, layout: ThemeLayout, state: ThemeState, params: ThemeParams
    ) -> None:
        """Intra-cluster dynamics (themes.ss, ``ThemeCluster.spread_activation``).

        Two properties of the reference dictate the loop structure and are easy to
        lose:

        *It is Jacobi, not Gauss-Seidel.*  ``themes.ss:520-527`` runs three separate
        passes over a cluster — clear every buffer, let every theme spread, then let
        every theme update — so every net input is computed from the activations as
        they stood at the *start* of the step.  Updating a theme at the end of its own
        iteration, so later themes read already-updated neighbours, is a different
        dynamical system: same fixed points, different trajectories, and a result that
        depends on slot order.  The activations are therefore snapshotted below before
        any of them is written.

        *The source sum is order-sensitive.*  The reference accumulates
        ``net_input`` over sources in slot order; the terms are arbitrary floats,
        so re-associating them would perturb the result.  The loop below walks
        sources in the same order for the same reason.
        """
        act = state.activation
        n_slots = layout.n_slots
        decay = params.decay
        self_w = params.self_weight
        spread = params.spread_amount

        for c in range(layout.n_clusters):
            if state.cluster_frozen[c]:
                continue
            base = c * n_slots
            alpha = params.sensitivity * (1.0 / 50.0) * (1.0 / layout.n_relations[c])

            # Pass one and two: read only the activations as they stand now.
            snapshot = [act[base + s] for s in range(n_slots)]
            net_effects: list[float | None] = [None] * n_slots

            for t in range(n_slots):
                ti = base + t
                if not layout.valid[ti] or state.frozen[ti]:
                    continue
                target_act = snapshot[t]
                net_input = -decay
                if target_act > 0:
                    net_input += target_act * (self_w / 100.0)

                for s in range(n_slots):
                    if s == t:
                        continue
                    si = base + s
                    if not layout.valid[si]:
                        continue
                    source_act = snapshot[s]
                    if source_act == 0:
                        continue
                    if source_act < 0 and target_act < 0:
                        weight = params.neg_to_neg
                    elif source_act < 0:
                        weight = params.neg_to_pos
                    elif target_act < 0:
                        weight = params.pos_to_neg
                    else:
                        weight = params.pos_to_pos
                    net_input += abs(source_act) * (weight / 100.0)

                net_effects[t] = round(spread * math.tanh(alpha * net_input))

            # Pass three: apply.
            for t in range(n_slots):
                net_effect = net_effects[t]
                if net_effect is None:
                    continue
                ti = base + t
                # ``activation-function`` (``themes.ss:456-459``): a positive theme is
                # pushed toward +100 by excitation and toward 0 by inhibition; a
                # negative theme is pushed toward -100 and toward 0 respectively.
                if snapshot[t] >= 0:
                    a = act[ti] + net_effect
                    act[ti] = 0.0 if a < 0.0 else (100.0 if a > 100.0 else a)
                else:
                    a = act[ti] - net_effect
                    act[ti] = -100.0 if a < -100.0 else (0.0 if a > 0.0 else a)

    # -- Workspace object values -------------------------------------------

    def combine_object_values(self, batch: ObjectValueBatch) -> None:
        """The unhappiness and salience combinations.

        Every output is a bare ``round()`` in the reference and therefore an
        ``int``; that is preserved, because these values are serialised, compared
        in tests, and used as stochastic weights, and silently promoting them to
        floats would show up in all three places.
        """
        n = len(batch)
        rel = batch.relative_importance

        avg_unhappy: list[int] = []
        s_intra: list[int] = []
        s_h: list[int] = []
        s_v: list[int] = []
        s_avg: list[int] = []

        for i in range(n):
            intra = batch.intra_unhappiness[i]
            h = batch.horizontal_unhappiness[i]
            v = batch.vertical_unhappiness[i]
            stype = batch.string_type[i]
            justify = batch.justify_mode[i]
            ri = rel[i]

            # average unhappiness (workspace-objects.ss:492-517)
            if stype == STRING_INITIAL:
                avg_unhappy.append(round((intra + h + v) / 3))
            elif stype == STRING_MODIFIED:
                avg_unhappy.append(round((intra + h) / 2))
            elif stype == STRING_TARGET:
                if justify:
                    avg_unhappy.append(round((intra + v + h) / 3))
                else:
                    avg_unhappy.append(round((intra + v) / 2))
            elif stype == STRING_ANSWER:
                avg_unhappy.append(round((intra + h) / 2))
            else:
                avg_unhappy.append(round(intra))

            # intra-string salience (workspace-objects.ss:524-530)
            if batch.salience_clamped[i]:
                s_intra.append(100)
            else:
                s_intra.append(round(0.8 * intra + 0.2 * ri))

            # inter-string salience (workspace-objects.ss:532-559).  Slots the
            # reference leaves alone keep their previous value.
            prev_h = batch.prev_horizontal_salience[i]
            prev_v = batch.prev_vertical_salience[i]
            if batch.salience_clamped[i]:
                new_h, new_v = 100, 100
            elif stype == STRING_INITIAL:
                new_h = round(0.2 * h + 0.8 * ri)
                new_v = round(0.2 * v + 0.8 * ri)
            elif stype == STRING_MODIFIED:
                new_h, new_v = round(0.2 * h + 0.8 * ri), prev_v
            elif stype == STRING_TARGET:
                new_v = round(0.2 * v + 0.8 * ri)
                new_h = round(0.2 * h + 0.8 * ri) if justify else prev_h
            elif stype == STRING_ANSWER:
                new_h, new_v = round(0.2 * h + 0.8 * ri), prev_v
            else:
                new_h, new_v = prev_h, prev_v
            s_h.append(new_h)
            s_v.append(new_v)

            # average salience (workspace-objects.ss:562-587)
            si = s_intra[i]
            if stype == STRING_INITIAL:
                s_avg.append(round((si + new_h + new_v) / 3))
            elif stype == STRING_MODIFIED:
                s_avg.append(round((si + new_h) / 2))
            elif stype == STRING_TARGET:
                if justify:
                    s_avg.append(round((si + new_v + new_h) / 3))
                else:
                    s_avg.append(round((si + new_v) / 2))
            elif stype == STRING_ANSWER:
                s_avg.append(round((si + new_h) / 2))
            else:
                s_avg.append(round(si))

        batch.average_unhappiness = avg_unhappy
        batch.intra_salience = s_intra
        batch.horizontal_salience = s_h
        batch.vertical_salience = s_v
        batch.average_salience = s_avg

    # -- Structures and temperature ----------------------------------------

    def structure_strengths(
        self,
        internal: Sequence[float],
        external: Sequence[float],
        compatibility: Sequence[float],
    ) -> list[int]:
        """``WorkspaceStructure.update_strength``'s arithmetic, for many structures.

        ``weighted_average`` is inlined rather than called: the intrinsic term
        weights internal strength by itself and external strength by its
        complement, so the denominator is always exactly 100 unless internal
        strength is outside [0, 100], and the zero-weight guard the shared helper
        carries can never fire here.  Inlining keeps this one expression instead of
        two list-building passes through a generic helper.
        """
        out: list[int] = []
        for i in range(len(internal)):
            w_int = internal[i]
            w_ext = 100.0 - w_int
            total = w_int + w_ext
            intrinsic = (
                0.0 if total == 0 else (internal[i] * w_int + external[i] * w_ext) / total
            )
            comp = compatibility[i]
            weight = abs(comp)
            if weight == 0.0:
                out.append(round(intrinsic))
                continue
            other = 1.0 - weight
            denominator = weight + other
            target = 100.0 if comp > 0 else 0.0
            if denominator == 0:
                out.append(0)
            else:
                out.append(round((target * weight + intrinsic * other) / denominator))
        return out

    def average_unhappiness(
        self, values: Sequence[float], relative_importance: Sequence[float]
    ) -> int:
        n = len(values)
        if n == 0:
            return 100
        total_weight = sum(relative_importance)
        if total_weight == 0:
            # ``weighted-average`` (``utilities.ss:388-392``) returns 0 on zero
            # total weight.  An unweighted mean here would report ~100 unhappiness
            # where the reference reports none.
            return 0
        weighted = sum(values[i] * relative_importance[i] for i in range(n))
        return round(weighted / total_weight)

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
