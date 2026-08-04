"""Coderack — stochastic codelet scheduler.

A pool of small specialized agents (codelets). Each codelet has a type,
urgency, and arguments. Selection is probabilistic, weighted by urgency
and modulated by temperature.

Both places temperature enters — which codelet is *selected* and which is *evicted*
when the rack is full — read the same precomputed 7 x 101 table of rounded bin
urgencies (:class:`UrgencyValueTable`), exactly as the Scheme does.

Scheme source: coderack.ss
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

from server.engine.ids import KIND_CODELET, next_id

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


class UrgencyValueTable:
    """``%urgency-value-table%`` — ``coderack.ss:55-61``.

    The Scheme precomputes a 7 x 101 table once at load time::

        (table-set! table coderack-bin-number temperature
          (round (expt (add1 coderack-bin-number)
                       (/ (+ (100- temperature) 10) 15.0))))

    Two things about it matter and both were missing from the port.

    **It is rounded to an integer.**  ``(round ...)`` is applied to the exponential,
    so the row at T=100 is ``[1, 2, 2, 3, 3, 3, 4]``, not
    ``[1, 1.587, 2.080, 2.520, 2.924, 3.302, 3.659]``.  Bin 1 therefore carries 26%
    more selection weight in the reference than the raw exponential gives it, and
    bins 1/2 and 3/4/5 are *tied* rather than ordered.  Chez's ``round`` and
    Python's ``round`` both break ties to even, and no entry of this table lands
    within 1e-6 of a half, so the two agree entry for entry.

    **The same table is what scales eviction.**  ``get-removal-weight``
    (``coderack.ss:237-240``) reads bin urgency out of it, so the low-urgency
    penalty a codelet pays for being evictable is temperature-dependent:
    ``1 + table[last][T] - table[bin][T]``.  At T=100 that is ``[4,3,3,2,2,2,1]``;
    at T=50 ``[2401, ..., 1]``; at T=0 ``[1575381, ..., 1]``.  Cold, a bin-6
    codelet is a million times safer than a bin-0 one — which is the point, since a
    cold run has found something worth protecting.

    Indexed by an integer temperature because the Scheme's ``*temperature*`` is one:
    ``update-temperature`` rounds (``formulas.ss:76``).  Petacat carries temperature
    as a float, so it is rounded and clamped to ``[0, 100]`` at the index.
    """

    __slots__ = ("num_bins", "_values", "_penalties")

    def __init__(
        self, num_bins: int, exponent_offset: float, exponent_divisor: float
    ) -> None:
        self.num_bins = num_bins
        # Stored temperature-major: a whole row is what both callers want, and one
        # tuple lookup then serves all seven bins.
        self._values: tuple[tuple[int, ...], ...] = tuple(
            tuple(
                round(
                    (bin_number + 1)
                    ** ((100 - temperature + exponent_offset) / exponent_divisor)
                )
                for bin_number in range(num_bins)
            )
            for temperature in range(101)
        )
        self._penalties: tuple[tuple[int, ...], ...] = tuple(
            tuple(1 + row[-1] - value for value in row) for row in self._values
        )

    @staticmethod
    def index(temperature: float) -> int:
        """The integer the Scheme would have been holding in ``*temperature*``."""
        rounded = int(round(temperature))
        if rounded < 0:
            return 0
        if rounded > 100:
            return 100
        return rounded

    def row(self, temperature: float) -> tuple[int, ...]:
        """Bin urgency values at this temperature, one per bin."""
        return self._values[self.index(temperature)]

    def value(self, bin_number: int, temperature: float) -> int:
        return self._values[self.index(temperature)][bin_number]

    def removal_penalties(self, temperature: float) -> tuple[int, ...]:
        """``1 + highest-bin-urgency - bin-urgency`` at this temperature, per bin.

        ``get-highest-bin-urgency`` (``coderack.ss:376``) is the *last* bin's value
        whether or not that bin holds anything, so the penalty row depends on
        temperature alone.
        """
        return self._penalties[self.index(temperature)]


@lru_cache(maxsize=None)
def urgency_value_table(
    num_bins: int, exponent_offset: float, exponent_divisor: float
) -> UrgencyValueTable:
    """The table, built once per shape — as the Scheme builds it once at load."""
    return UrgencyValueTable(num_bins, exponent_offset, exponent_divisor)


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

    Alongside the codelets themselves the bin maintains two running aggregates.
    They exist so that eviction can weigh a whole bin without touching the codelets
    in it — see ``Coderack.remove_old_codelets`` for the closed form they serve and
    why it matters.

    * ``sum_time_stamp`` — Σ of the codelets' time stamps.
    * ``newest_time_stamp`` — the largest time stamp ever added.  It is deliberately
      not lowered when that codelet leaves: it is used only as an upper bound, and
      leaving it high costs nothing but a correction of zero.
    """

    def __init__(self, bin_number: int) -> None:
        self.bin_number = bin_number
        self.codelets: list[Codelet] = []
        self.sum_time_stamp: int = 0
        self.newest_time_stamp: int = 0

    def add(self, codelet: Codelet) -> None:
        self.codelets.append(codelet)
        time_stamp = codelet.time_stamp
        self.sum_time_stamp += time_stamp
        if time_stamp > self.newest_time_stamp:
            self.newest_time_stamp = time_stamp

    def remove(self, codelet: Codelet) -> None:
        self.codelets.remove(codelet)
        self.sum_time_stamp -= codelet.time_stamp

    def age_sum(self, current_time: int) -> int:
        """Σ over the bin of ``current_time - time_stamp``, in O(1).

        The age carries no floor, because the Scheme's does not:
        ``get-removal-weight`` is ``(- *codelet-count* time-stamp)`` outright
        (``coderack.ss:238``).  A codelet is stamped with the codelet count that
        posts it, so one posted on the current tick has age 0 and *weight* 0 — it
        cannot be evicted while anything older is on the rack.  That is the
        reference behaviour and it is deliberate: a codelet that has not yet had a
        chance to be selected is not what the rack should be shedding.  Petacat
        used to floor the age at 1, which made the freshest codelet as evictable as
        a one-tick-old one.

        Without the floor the sum is exactly ``count * current_time - Σ time_stamp``.
        The guard covers the case where a caller supplies a ``current_time`` earlier
        than stamps already in the bin, which would otherwise make the bin's weight
        negative and corrupt the draw.  Nothing in the engine does that — the guard
        is here because the method is public and being wrong there would be silent.
        """
        if self.newest_time_stamp > current_time:
            return sum(max(0, current_time - c.time_stamp) for c in self.codelets)
        return len(self.codelets) * current_time - self.sum_time_stamp

    def clear(self) -> None:
        self.codelets.clear()
        self.sum_time_stamp = 0
        self.newest_time_stamp = 0

    def choose_random(self, rng: RNG) -> Codelet:
        """Pick a random codelet from this bin."""
        return rng.pick(self.codelets)

    def get_urgency_sum(self, temperature: float, table: UrgencyValueTable) -> int:
        """This bin's selection weight — ``coderack.ss:297-299``.

        ``(* current-index (table-ref %urgency-value-table% bin-number
        *temperature*))``: the count times the **rounded** integer table value, not
        the raw exponential.  See :class:`UrgencyValueTable`.
        """
        if not self.codelets:
            return 0
        return len(self.codelets) * table.value(self.bin_number, temperature)

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
        self.urgency_table = urgency_value_table(
            self.num_bins,
            meta.get_formula_coeff("coderack_bin_urgency_exponent_offset"),  # 10
            meta.get_formula_coeff("coderack_bin_urgency_exponent_divisor"),  # 15
        )
        self._total_count = 0
        # Urgency clamping state
        self.clamped_urgencies: dict[str, int] = {}
        # Set by the runner so ``post`` can enforce ``max_size`` on its own.
        self.rng: RNG | None = None
        self.current_time: int = 0
        #: The temperature eviction is weighed at when a caller does not supply one.
        #:
        #: The Scheme reads the global ``*temperature*`` inside ``get-removal-weight``,
        #: so eviction is temperature-scaled with no plumbing.  Petacat passes
        #: temperature in at selection, so the rack remembers the last value it was
        #: given: every step calls ``choose_and_remove`` before anything can post, and
        #: temperature only moves once per update cycle, so the remembered value is the
        #: live one everywhere except the posting burst at the tail of an update cycle,
        #: which runs after ``update-temperature``.  A caller that cares can pass
        #: ``temperature=`` to ``post``/``remove_old_codelets`` explicitly, and the
        #: runner setting this attribute alongside ``current_time`` would close the gap
        #: entirely.
        self.current_temperature: float = 100.0

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

    def post(
        self,
        codelet: Codelet,
        current_time: int | None = None,
        rng: RNG | None = None,
        temperature: float | None = None,
    ) -> None:
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
                current_time, self._total_count - self.max_size + 1, rng, temperature
            )

        bin_idx = self._urgency_to_bin(codelet.urgency)
        self.bins[bin_idx].add(codelet)
        self._total_count += 1

    def choose_and_remove(self, temperature: float, rng: RNG) -> Codelet | None:
        """Two-stage probabilistic selection — ``choose-codelet``, ``coderack.ss:417``.

        1. Pick a bin weighted by ``count x table[bin][T]``  (``coderack.ss:297-299``)
        2. Pick a codelet uniformly within it                 (``coderack.ss:307-308``)

        The bin weight uses the **rounded** urgency table.  The port evaluated the
        same exponential and left it unrounded (DISCREPANCIES2 CR-2), which at T=100
        weighted bin 1 at 1.587 where the reference weights it 2 — 26% light — and
        ordered bins the reference ties.
        """
        if self.is_empty:
            return None

        # Remember it for eviction, which the Scheme reads off the global
        # ``*temperature*`` and Petacat has to be handed.  See ``current_temperature``.
        self.current_temperature = temperature

        # Stage 1: pick bin, weighted by count x the rounded table value
        row = self.urgency_table.row(temperature)
        weights = [len(b.codelets) * row[b.bin_number] for b in self.bins]
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

    def _bin_urgency_penalties(self, temperature: float) -> tuple[int, ...]:
        """The low-urgency penalty every codelet in a bin shares, one per bin.

        ``1 + highest-bin-urgency - bin-urgency`` off the rounded urgency table
        (``coderack.ss:237-240``), so it depends on temperature and on nothing about
        the codelets — seven integers, looked up once per eviction.

        A codelet is filed by ``_urgency_to_bin(urgency)`` when it is posted and its
        urgency never changes afterwards — the one place that raises it, urgency
        clamping in ``post``, does so before the bin is chosen.  So a codelet's bin
        index *is* ``_urgency_to_bin(c.urgency)``, and recomputing it per codelet
        during eviction, as this used to, produced 323,883 calls per ``mrrjjj`` run
        to rediscover the index being iterated over.
        """
        return self.urgency_table.removal_penalties(temperature)

    def remove_old_codelets(
        self,
        current_time: int,
        num_to_remove: int,
        rng: RNG,
        temperature: float | None = None,
    ) -> list[Codelet]:
        """Stochastically remove old codelets weighted by age and low urgency.

        ``get-removal-weight`` (``coderack.ss:237-240``)::

            (* (- *codelet-count* time-stamp)
               (add1 (- (tell *coderack* 'get-highest-bin-urgency)
                        (tell coderack-bin 'get-urgency))))

        Age is unfloored — a codelet posted on the current tick weighs 0 and cannot
        be evicted while anything older is present — and the urgency penalty comes
        off the temperature-indexed rounded table, so it ranges from ``[4,3,3,2,2,2,1]``
        when hot to ``[1575381, ..., 1]`` when cold.  Cold, a high-urgency codelet is
        effectively unevictable.  Petacat previously used a flat ``num_bins - bin``
        at every temperature and floored the age at 1 (DISCREPANCIES2 CR-1).

        The *search* for that distribution is not the Scheme's, and deliberately.  A
        flat rebuild of a weight per codelet per eviction was 35.8% of the whole run
        on ``abc -> abd; mrrjjj?`` — the rack is at capacity for 58% of posts, so
        3,184 evictions each scanned ~100 codelets.

        What makes that avoidable is that the weight factorises.  A codelet's penalty
        depends only on its bin, so a bin's total weight is
        ``penalty x Σ (current_time - time_stamp)``, and the sum is maintained in
        O(1) by ``CoderackBin.age_sum``.  Seven aggregates then locate the bin and
        only that bin is scanned — roughly 21 inspections rather than 100.  Making
        the penalty temperature-dependent costs one tuple lookup per eviction and
        leaves that property intact: it is still seven O(1) bin weights and one
        scanned bin.

        The cumulative walk below visits the same weights in the same order, against
        a threshold from one ``random()`` call, as ``RNG.weighted_pick`` would over
        the bin-major flat list — so the incremental form picks the same codelet as a
        brute-force enumeration from the same RNG state, and consumes the same number
        of draws.  ``tests/seed_unit/test_coderack_eviction.py`` holds it to that.
        """
        if temperature is None:
            temperature = self.current_temperature
        removed = []
        for _ in range(num_to_remove):
            if self.is_empty:
                break
            chosen = self._pick_codelet_to_remove(current_time, rng, temperature)
            if chosen is None:
                break
            codelet, b = chosen
            b.remove(codelet)
            self._total_count -= 1
            removed.append(codelet)
        return removed

    def _pick_codelet_to_remove(
        self, current_time: int, rng: RNG, temperature: float | None = None
    ) -> tuple[Codelet, CoderackBin] | None:
        """Draw one codelet for eviction, weighted by age x low-urgency penalty."""
        if temperature is None:
            temperature = self.current_temperature
        penalties = self._bin_urgency_penalties(temperature)
        bin_weights = [
            penalties[b.bin_number] * b.age_sum(current_time) if b.codelets else 0
            for b in self.bins
        ]
        total = sum(bin_weights)

        if total <= 0:
            # Reachable now that the age has no floor: every codelet on the rack was
            # posted on this very tick, so every weight is 0.  ``RNG.weighted_pick``
            # falls back to a uniform pick here — as does the Scheme, whose
            # ``stochastic-pick`` defers to ``random-pick`` on a zero weight-sum
            # (``utilities.ss:443-448``) — and this has to fall back the same way to
            # consume the same random number.
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
            penalty = penalties[b.bin_number]
            for codelet in b.codelets:
                # ``max(0, ...)`` only to stay consistent with ``age_sum``'s guard
                # against a stamp ahead of the clock; a no-op in every real run.
                cumulative += penalty * max(0, current_time - codelet.time_stamp)
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
