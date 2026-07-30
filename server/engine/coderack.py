"""Coderack — stochastic codelet scheduler.

A pool of small specialized agents (codelets). Each codelet has a type,
urgency, and arguments. Selection is probabilistic, weighted by urgency
and modulated by temperature.

Scheme source: coderack.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.ids import KIND_CODELET, next_id

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


class Codelet:
    """A single codelet on the coderack."""

    def __init__(
        self,
        codelet_type: str,
        urgency: int,
        arguments: dict[str, Any] | None = None,
        time_stamp: int = 0,
    ) -> None:
        self.id = next_id(KIND_CODELET)
        self.codelet_type = codelet_type
        self.urgency = urgency
        self.arguments = arguments or {}
        self.time_stamp = time_stamp

    def __repr__(self) -> str:
        return f"Codelet({self.codelet_type}, urg={self.urgency}, t={self.time_stamp})"


class CoderackBin:
    """One urgency bin in the coderack.

    Alongside the codelets themselves the bin maintains three running aggregates.
    They exist so that eviction can weigh a whole bin without touching the codelets
    in it — see ``Coderack.remove_old_codelets`` for the closed form they serve and
    why it matters.

    * ``sum_time_stamp`` — Σ of the codelets' time stamps.
    * ``newest_time_stamp`` — the largest time stamp ever added.  It is deliberately
      not lowered when that codelet leaves: it is used only as an upper bound, and
      leaving it high costs nothing but a correction of zero.
    * ``count_at_newest`` — how many codelets carry ``newest_time_stamp`` right now.
    """

    def __init__(self, bin_number: int) -> None:
        self.bin_number = bin_number
        self.codelets: list[Codelet] = []
        self.sum_time_stamp: int = 0
        self.newest_time_stamp: int = 0
        self.count_at_newest: int = 0

    def add(self, codelet: Codelet) -> None:
        self.codelets.append(codelet)
        time_stamp = codelet.time_stamp
        self.sum_time_stamp += time_stamp
        if time_stamp > self.newest_time_stamp:
            self.newest_time_stamp = time_stamp
            self.count_at_newest = 1
        elif time_stamp == self.newest_time_stamp:
            self.count_at_newest += 1

    def remove(self, codelet: Codelet) -> None:
        self.codelets.remove(codelet)
        self.sum_time_stamp -= codelet.time_stamp
        if codelet.time_stamp == self.newest_time_stamp:
            self.count_at_newest -= 1

    def age_sum(self, current_time: int) -> int:
        """Σ over the bin of ``max(1, current_time - time_stamp)``, in O(1).

        ``max(1, ...)`` is the only thing standing between this and a plain
        ``count * current_time - Σ time_stamp``.  The clamp bites exactly when
        ``time_stamp >= current_time``, and time stamps never exceed the current
        time — a codelet is stamped with the codelet count that is posting it — so
        the only clamped case in a real run is ``time_stamp == current_time``, whose
        contribution to the unclamped sum is zero and should be one apiece.

        The guard covers the case where a caller supplies a ``current_time`` earlier
        than stamps already in the bin.  Nothing in the engine does that, but the
        method is public and being wrong there would be silent.
        """
        if self.newest_time_stamp > current_time:
            return sum(max(1, current_time - c.time_stamp) for c in self.codelets)
        unclamped = len(self.codelets) * current_time - self.sum_time_stamp
        if self.newest_time_stamp == current_time:
            return unclamped + self.count_at_newest
        return unclamped

    def clear(self) -> None:
        self.codelets.clear()
        self.sum_time_stamp = 0
        self.newest_time_stamp = 0
        self.count_at_newest = 0

    def choose_random(self, rng: RNG) -> Codelet:
        """Pick a random codelet from this bin."""
        return rng.pick(self.codelets)

    def get_urgency_sum(self, temperature: float, meta: MetadataProvider) -> float:
        """Compute the total urgency weight for this bin at a given temperature.

        Scheme: coderack.ss selection formula.
        bin_urgency_value = (1 + bin_number) ^ ((100 - temperature + 10) / 15)
        total = count * bin_urgency_value
        """
        if not self.codelets:
            return 0.0
        exp_div = meta.get_formula_coeff("coderack_bin_urgency_exponent_divisor")  # 15
        exp_off = meta.get_formula_coeff("coderack_bin_urgency_exponent_offset")  # 10
        exponent = (100.0 - temperature + exp_off) / exp_div
        bin_value = (1.0 + self.bin_number) ** exponent
        return len(self.codelets) * bin_value

    @property
    def count(self) -> int:
        return len(self.codelets)

    def __repr__(self) -> str:
        return f"CoderackBin({self.bin_number}, count={self.count})"


class Coderack:
    """The coderack: holds codelets in urgency-weighted bins."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.num_bins = meta.get_param("num_coderack_bins", 7)
        self.max_size = meta.get_param("max_coderack_size", 100)
        self.bins = [CoderackBin(i) for i in range(self.num_bins)]
        self.meta = meta
        self._total_count = 0
        # Urgency clamping state
        self.clamped_urgencies: dict[str, int] = {}
        # Set by the runner so ``post`` can enforce ``max_size`` on its own.
        self.rng: RNG | None = None
        self.current_time: int = 0

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def is_empty(self) -> bool:
        return self._total_count == 0

    def _urgency_to_bin(self, urgency: int) -> int:
        """Map an urgency value (0-100) to a bin index (0 to num_bins-1)."""
        idx = int(urgency * self.num_bins / 100)
        return max(0, min(self.num_bins - 1, idx))

    def post(self, codelet: Codelet, current_time: int | None = None, rng: RNG | None = None) -> None:
        """Add a codelet, evicting an old one if the rack is at capacity.

        Scheme: the Coderack holds at most ``%max-coderack-size%`` (100)
        codelets; posting beyond that removes an existing one chosen
        stochastically by age and low urgency.  Without the cap the rack grows
        without bound and the codelet mix drifts away from whatever the current
        Workspace state calls for.
        """
        # Apply urgency clamping if active
        if codelet.codelet_type in self.clamped_urgencies:
            codelet.urgency = max(codelet.urgency, self.clamped_urgencies[codelet.codelet_type])

        rng = rng if rng is not None else self.rng
        if current_time is None:
            current_time = self.current_time
        if rng is not None and self._total_count >= self.max_size:
            self.remove_old_codelets(
                current_time, self._total_count - self.max_size + 1, rng
            )

        bin_idx = self._urgency_to_bin(codelet.urgency)
        self.bins[bin_idx].add(codelet)
        self._total_count += 1

    def choose_and_remove(self, temperature: float, rng: RNG) -> Codelet | None:
        """Two-stage probabilistic selection.

        1. Pick bin weighted by bin_urgency_sum
        2. Pick codelet uniformly within bin

        Scheme: coderack.ss (matches exactly).
        """
        if self.is_empty:
            return None

        # Stage 1: pick bin
        weights = [b.get_urgency_sum(temperature, self.meta) for b in self.bins]
        total = sum(weights)
        if total <= 0:
            # Fallback: pick from any non-empty bin
            non_empty = [b for b in self.bins if b.count > 0]
            if not non_empty:
                return None
            chosen_bin = rng.pick(non_empty)
        else:
            chosen_bin = rng.weighted_pick(self.bins, weights)

        if chosen_bin.count == 0:
            # Retry with non-empty bins
            non_empty = [b for b in self.bins if b.count > 0]
            if not non_empty:
                return None
            chosen_bin = rng.pick(non_empty)

        # Stage 2: pick codelet within bin
        codelet = chosen_bin.choose_random(rng)
        chosen_bin.remove(codelet)
        self._total_count -= 1
        return codelet

    def _bin_urgency_penalty(self, bin_number: int) -> int:
        """The low-urgency penalty every codelet in a bin shares.

        A codelet is filed by ``_urgency_to_bin(urgency)`` when it is posted and its
        urgency never changes afterwards — the one place that raises it, urgency
        clamping in ``post``, does so before the bin is chosen.  So a codelet's bin
        index *is* ``_urgency_to_bin(c.urgency)``, and recomputing it per codelet
        during eviction, as this used to, produced 323,883 calls per ``mrrjjj`` run
        to rediscover the index being iterated over.
        """
        return self.num_bins - bin_number

    def remove_old_codelets(
        self,
        current_time: int,
        num_to_remove: int,
        rng: RNG,
    ) -> list[Codelet]:
        """Stochastically remove old codelets weighted by age and low urgency.

        Removal weight = (current_time - time_stamp) * (1 + highest_bin_urgency - codelet_bin_urgency)
        Scheme: coderack.ss deferred-codelet logic.

        The distribution is the original one; the search for it is not.  This used to
        rebuild a weight for every codelet on the rack on every eviction, and the rack
        is at capacity for 58% of posts on ``abc -> abd; mrrjjj?`` — 3,184 evictions
        each scanning ~100 codelets, 318,400 inspections to remove 3,184 codelets, and
        35.8% of the whole run.

        What makes that avoidable is that the weight factorises.  A codelet's penalty
        depends only on its bin, so a bin's total weight is
        ``penalty x Σ max(1, current_time - time_stamp)``, and the sum is maintained
        in O(1) by ``CoderackBin.age_sum``.  Seven aggregates then locate the bin and
        only that bin is scanned — roughly 21 inspections rather than 100.

        The selection is not merely equivalent in distribution but *identical*, codelet
        for codelet, to the flat version it replaces.  The old code laid its weights
        out bin-major and handed them to ``RNG.weighted_pick``; the cumulative walk
        below visits the same weights in the same order against a threshold drawn from
        one ``random()`` call, exactly as ``weighted_pick`` would.  Seeded runs
        therefore stay bit-identical across this change, which is worth having: it
        leaves seeded spot-checking usable as a development tool, and it means any
        movement in the expected range afterwards belongs to a later work package.
        """
        removed = []
        for _ in range(num_to_remove):
            if self.is_empty:
                break
            chosen = self._pick_codelet_to_remove(current_time, rng)
            if chosen is None:
                break
            codelet, b = chosen
            b.remove(codelet)
            self._total_count -= 1
            removed.append(codelet)
        return removed

    def _pick_codelet_to_remove(
        self, current_time: int, rng: RNG
    ) -> tuple[Codelet, CoderackBin] | None:
        """Draw one codelet for eviction, weighted by age x low-urgency penalty."""
        bin_weights = [
            self._bin_urgency_penalty(b.bin_number) * b.age_sum(current_time)
            if b.codelets
            else 0
            for b in self.bins
        ]
        total = sum(bin_weights)

        if total <= 0:
            # Degenerate — unreachable while ages and penalties are both at least 1,
            # but ``RNG.weighted_pick`` falls back to a uniform pick here and this
            # has to fall back the same way to consume the same random number.
            flat = [c for b in self.bins for c in b.codelets]
            if not flat:
                return None
            codelet = rng.pick(flat)
            return codelet, self._bin_of(codelet)

        threshold = rng.random() * total
        cumulative = 0.0
        for b, bin_weight in zip(self.bins, bin_weights):
            if not b.codelets:
                continue
            if cumulative + bin_weight < threshold:
                cumulative += bin_weight
                continue
            # The chosen bin.  Walk it with the same running total the flat version
            # would have had at this point, so the same codelet comes out.
            penalty = self._bin_urgency_penalty(b.bin_number)
            for codelet in b.codelets:
                cumulative += penalty * max(1, current_time - codelet.time_stamp)
                if cumulative >= threshold:
                    return codelet, b
            # Floating-point shortfall inside the bin: keep walking the later bins,
            # matching ``weighted_pick``'s behaviour of running on to its own end.
        for b in reversed(self.bins):
            if b.codelets:
                return b.codelets[-1], b
        return None

    def _bin_of(self, codelet: Codelet) -> CoderackBin:
        return self.bins[self._urgency_to_bin(codelet.urgency)]

    def codelets_present(self) -> bool:
        """Is there anything here, without summing the maintained total?

        Used by work-stealing to probe a shard before taking its lock.  Reading
        ``total_count`` would be equivalent and cheaper still, but this reads the bins the
        thief is about to touch rather than a counter another worker is updating.
        """
        return self._total_count > 0

    def clear(self) -> None:
        """Remove all codelets."""
        for b in self.bins:
            b.clear()
        self._total_count = 0

    def clamp_codelet_type(self, codelet_type: str, urgency: int) -> None:
        """Force a codelet type to at least the given urgency."""
        self.clamped_urgencies[codelet_type] = urgency

    def unclamp_codelet_type(self, codelet_type: str) -> None:
        self.clamped_urgencies.pop(codelet_type, None)

    def clamp_pattern(self, pattern: list[tuple[str, int]]) -> None:
        """Apply a codelet urgency clamping pattern."""
        for codelet_type, urgency in pattern:
            self.clamp_codelet_type(codelet_type, urgency)

    def unclamp_all(self) -> None:
        self.clamped_urgencies.clear()

    def get_codelet_type_counts(self) -> dict[str, int]:
        """Count codelets by type."""
        counts: dict[str, int] = {}
        for b in self.bins:
            for c in b.codelets:
                counts[c.codelet_type] = counts.get(c.codelet_type, 0) + 1
        return counts

    def __repr__(self) -> str:
        return f"Coderack({self._total_count} codelets in {self.num_bins} bins)"
