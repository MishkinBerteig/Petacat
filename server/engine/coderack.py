"""Coderack — stochastic codelet scheduler.

A pool of small specialized agents (codelets). Each codelet has a type,
urgency, and arguments. Selection is probabilistic, weighted by urgency
and modulated by temperature.

Scheme source: coderack.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


class Codelet:
    """A single codelet on the coderack."""

    _next_id = 0

    def __init__(
        self,
        codelet_type: str,
        urgency: int,
        arguments: dict[str, Any] | None = None,
        time_stamp: int = 0,
    ) -> None:
        Codelet._next_id += 1
        self.id = Codelet._next_id
        self.codelet_type = codelet_type
        self.urgency = urgency
        self.arguments = arguments or {}
        self.time_stamp = time_stamp

    def __repr__(self) -> str:
        return f"Codelet({self.codelet_type}, urg={self.urgency}, t={self.time_stamp})"


class CoderackBin:
    """One urgency bin in the coderack."""

    def __init__(self, bin_number: int) -> None:
        self.bin_number = bin_number
        self.codelets: list[Codelet] = []

    def add(self, codelet: Codelet) -> None:
        self.codelets.append(codelet)

    def remove(self, codelet: Codelet) -> None:
        self.codelets.remove(codelet)

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

    def post(self, codelet: Codelet) -> None:
        """Add a codelet to the appropriate bin."""
        # Apply urgency clamping if active
        if codelet.codelet_type in self.clamped_urgencies:
            codelet.urgency = max(codelet.urgency, self.clamped_urgencies[codelet.codelet_type])
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

    def remove_old_codelets(
        self,
        current_time: int,
        num_to_remove: int,
        rng: RNG,
    ) -> list[Codelet]:
        """Stochastically remove old codelets weighted by age and low urgency.

        Removal weight = (current_time - time_stamp) * (1 + highest_bin_urgency - codelet_bin_urgency)
        Scheme: coderack.ss deferred-codelet logic.
        """
        removed = []
        for _ in range(num_to_remove):
            if self.is_empty:
                break
            all_codelets = []
            for b in self.bins:
                for c in b.codelets:
                    age = max(1, current_time - c.time_stamp)
                    urgency_penalty = 1 + (self.num_bins - 1) - self._urgency_to_bin(c.urgency)
                    weight = age * urgency_penalty
                    all_codelets.append((c, b, weight))
            if not all_codelets:
                break
            items = [x[0] for x in all_codelets]
            weights = [x[2] for x in all_codelets]
            chosen = rng.weighted_pick(items, weights)
            # Find and remove
            for c, b, _ in all_codelets:
                if c is chosen:
                    b.remove(c)
                    self._total_count -= 1
                    removed.append(c)
                    break
        return removed

    def clear(self) -> None:
        """Remove all codelets."""
        for b in self.bins:
            b.codelets.clear()
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
