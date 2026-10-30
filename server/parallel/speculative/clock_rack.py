"""The clock coderack: codelet choice as an exponential race.

The faithful rack chooses in two stages -- a bin weighted by ``count x row[bin]``, then
a codelet uniformly inside it -- and the draws it spends on that are the part of the
run's randomness that depends on *every other draw before it*.  A speculative executor
needs the choice to be a function of the rack alone, so that "which codelet runs at
step k+3" can be predicted, and later checked, without replaying anything.

The replacement has exactly the same probability law.  Give every codelet ``c`` a firing
time ``F_c = t_now + E_c / w_c`` when it is posted, where ``w_c = row[bin(c)]`` is its
bin's urgency value at the current temperature, ``E_c`` is a unit exponential taken from
a stream keyed by the codelet's id, and ``t_now`` is the firing time of the codelet
chosen last.  Each step chooses the smallest ``F``.  By memorylessness of the
exponential, at every step each codelet's *remaining* time is still ``Exp(w_c)`` and
independent of the others, so the probability that ``c`` fires first is ``w_c / sum w``
-- the faithful two-stage probability (bin chosen with probability ``n_b w_b / sum``,
then ``1/n_b`` within it).  Choosing costs ``O(log n)`` from a heap with lazy deletion and
draws **nothing** from any stream.

Two consequences matter to the speculative engine.  A codelet posted later changes a
pending choice only if its own ``F`` is smaller -- a single comparison.  And a codelet
whose weight changes (the temperature moved a row, or a clamp re-filed it into another
bin) keeps its *residual* ``F - t_now`` scaled by ``w_old / w_new``: that is the same
exponential with a new rate, so it is exact in law.

Degenerate case
---------------
A weight of zero gives ``F = inf``.  The shipped urgency table is rounded from
``(bin+1)^((110-T)/15) >= 1`` so a real weight is never zero, but the faithful rack
special-cases "every weight is zero" (it falls back to a uniform pick over the non-empty
bins, then uniformly within the bin) and this rack reproduces that: when the smallest
``F`` is infinite, the fallback draws from the stream keyed by the step being chosen.

Bins
----
The bins are kept exactly as the faithful rack keeps them -- eviction weighs them
(``remove_old_codelets``), the display reads them, and the state graph captures them --
so this class subclasses :class:`~server.engine.coderack.Coderack`, leaves every bin
operation to it, and only *adds* a firing time to each codelet that lands in a bin and
drops it when the codelet leaves.
"""

from __future__ import annotations

import heapq
from typing import Any, Callable

from server.engine.coderack import Codelet, Coderack, CoderackBin
from server.parallel.speculative.streams import Streams

_INF = float("inf")


class ClockCoderack(Coderack):
    """A :class:`Coderack` whose choice is the exponential race described above."""

    def __init__(
        self,
        meta: Any,
        streams: Streams,
        rng_source: Callable[[], Any] | None = None,
        step_source: Callable[[], int] | None = None,
    ) -> None:
        self._rng_explicit: Any = None
        super().__init__(meta)
        self.streams = streams
        #: Where ``post``/``post_deferred`` get the generator for their eviction draw
        #: when the caller passes none: the context's thread-bound stream, so the
        #: eviction a codelet's post causes is drawn from that codelet's body stream.
        self._rng_source = rng_source
        #: The number of the step being chosen (``codelet_count + 1``); names the
        #: fallback stream.
        self._step_source = step_source
        #: ``id -> (F, w)``: the live clocks.  The heap may hold stale entries (lazy
        #: deletion); an entry is live iff ``clock[id][0] == F``.
        self._clock: dict[int, tuple[float, int]] = {}
        self._by_id: dict[int, Codelet] = {}
        self._heap: list[tuple[float, int]] = []
        #: Firing time of the codelet chosen last.
        self.t_now: float = 0.0
        #: The urgency row every live clock is currently weighted with.
        self._row: tuple[int, ...] | None = None
        #: Called before any mutation (the speculative engine traps writes with it).
        self.guard: Callable[[], None] | None = None
        #: Telemetry / tests.
        self.rescales = 0
        self.fallbacks = 0
        #: Prediction bookkeeping for the speculative engine's cached lookahead.  ``gen``
        #: changes whenever the order of codelets already on the rack can change (a
        #: re-weighting to another urgency row, a clamp re-filing codelets, a clear);
        #: ``floor_f`` is the smallest firing time enrolled since the last
        #: :meth:`predict_entries`.  A cached ``(F, id)`` list is therefore still the
        #: exact head of the order while ``gen`` is unchanged and ``F < floor_f``.
        #: Neither is read by the choice itself.
        self.gen = 0
        #: Codelets evicted from the rack (not chosen): lets a reader notice cheaply that
        #: some codelet it knew about is gone.
        self.removed = 0
        self.floor_f = _INF
        self.pred_row: tuple[int, ...] | None = None

    # -- the run's generator, bound per thread by the context ------------

    @property
    def rng(self) -> Any:  # type: ignore[override]
        if self._rng_source is not None:
            return self._rng_source()
        return self._rng_explicit

    @rng.setter
    def rng(self, value: Any) -> None:
        self._rng_explicit = value

    # -- adopting the rack ``init_mcat`` leaves behind ---------------------

    @classmethod
    def adopt(
        cls,
        rack: Coderack,
        streams: Streams,
        rng_source: Callable[[], Any] | None = None,
        step_source: Callable[[], int] | None = None,
    ) -> "ClockCoderack":
        """A clock rack holding *rack*'s codelets, in the same bins in the same order.

        Existing codelets get their clocks deterministically, in rack order (bin-major),
        at ``t_now = 0``.  The order is irrelevant to the values -- a clock is a pure
        function of the codelet's id, ``t_now`` and its weight -- but it is fixed anyway.
        """
        new = cls(rack.meta, streams, rng_source, step_source)
        new.num_bins = rack.num_bins
        new.max_size = rack.max_size
        new.bins = rack.bins
        new.urgency_table = rack.urgency_table
        new._total_count = rack._total_count
        new.clamped_urgencies = rack.clamped_urgencies
        new.current_time = rack.current_time
        new.current_temperature = rack.current_temperature
        new._rng_explicit = rack.rng
        new._enroll_missing()
        return new

    # -- clocks -----------------------------------------------------------

    def _weights(self) -> tuple[int, ...]:
        row = self._row
        if row is None:
            row = self._row = self.urgency_table.row(self.current_temperature)
        return row

    def _enroll(self, codelet: Codelet, bin_number: int) -> None:
        w = self._weights()[bin_number]
        cid = codelet.id
        f = self.t_now + self.streams.clock_exponential(cid) / w if w > 0 else _INF
        self._clock[cid] = (f, w)
        self._by_id[cid] = codelet
        heapq.heappush(self._heap, (f, cid))
        if f < self.floor_f:
            self.floor_f = f

    def _enroll_missing(self) -> None:
        clock = self._clock
        for b in self.bins:
            for c in b.codelets:
                if c.id not in clock:
                    self._enroll(c, b.bin_number)

    def _forget(self, codelet: Codelet) -> None:
        self._clock.pop(codelet.id, None)
        self._by_id.pop(codelet.id, None)

    def _rescaled(self, row: tuple[int, ...]) -> dict[int, tuple[float, int]]:
        """The clocks reweighted to *row*, as a new mapping (nothing is mutated).

        ``F' = t_now + (F - t_now) * w_old / w_new``.  A clock that was infinite (zero
        weight) has no residual to keep, so it draws afresh from its own exponential.
        """
        t = self.t_now
        out: dict[int, tuple[float, int]] = {}
        by_id = self._by_id
        stream_e = self.streams.clock_exponential
        urgency_to_bin = self._urgency_to_bin
        for cid, (f, w_old) in self._clock.items():
            w_new = row[urgency_to_bin(by_id[cid].urgency)]
            if w_new == w_old:
                out[cid] = (f, w_old)
            elif w_new <= 0:
                out[cid] = (_INF, 0)
            elif w_old <= 0 or f == _INF:
                out[cid] = (t + stream_e(cid) / w_new, w_new)
            else:
                out[cid] = (t + (f - t) * w_old / w_new, w_new)
        return out

    def _reweight(self, row: tuple[int, ...]) -> None:
        if row != self.pred_row:
            # A cached prediction was made under another row: its firing times are void.
            # (One made under *this* row used the very same rescaling, so it stays valid.)
            self.gen += 1
        self._clock = self._rescaled(row)
        self._row = row
        self._heap = [(f, cid) for cid, (f, _) in self._clock.items()]
        heapq.heapify(self._heap)
        self.rescales += 1

    def _top_valid(self) -> tuple[float, int] | None:
        heap = self._heap
        clock = self._clock
        while heap:
            f, cid = heap[0]
            ent = clock.get(cid)
            if ent is not None and ent[0] == f:
                return f, cid
            heapq.heappop(heap)
        return None

    def _compact(self) -> None:
        if len(self._heap) > 4 * len(self._clock) + 64:
            self._heap = [(f, cid) for cid, (f, _) in self._clock.items()]
            heapq.heapify(self._heap)

    # -- prediction (no mutation) -------------------------------------------

    def predict(self, temperature: float, count: int) -> list[Codelet]:
        """The next *count* codelets ``choose_and_remove`` would return, in order.

        Valid only while nothing is posted or removed -- that is what the caller
        checks.  Mutates nothing: if the temperature has moved to another row, the
        clocks are reweighted on a *copy*, by the same formula the real choice applies,
        so the prediction and the choice cannot disagree on a rounding.
        """
        return [self._by_id[cid] for _, cid in self._predict(temperature, count)]

    def predict_entries(self, temperature: float, count: int) -> list[tuple[float, int]]:
        """:meth:`predict` as ``(F, id)`` pairs, and restart the cache bookkeeping.

        Records the urgency row the firing times were computed under (``pred_row``) and
        resets ``floor_f``: from now on ``floor_f`` is the smallest firing time posted
        after this call, so every returned pair with ``F < floor_f`` is still exactly
        where the choice will find it -- provided the posts are on the same scale as the
        pairs, which is why this first does :meth:`sync_row` (a non-empty rack's clocks
        move to *temperature*'s row now rather than at the choice).  The caller must
        therefore be about to choose with this temperature and must post nothing before
        it does (the engine calls this from the hook that runs just before a step).
        """
        if self._total_count:
            self.sync_row(temperature)
        self.pred_row = self.urgency_table.row(temperature)
        self.floor_f = _INF
        return self._predict(temperature, count)

    def _smallest_valid(self, count: int) -> list[tuple[float, int]]:
        """The *count* smallest live ``(F, id)`` pairs, in order, read off the heap.

        A best-first walk of the heap array from its root: a node's children sort after
        it, so popping a small frontier yields the heap's entries in increasing order
        having looked at about ``2 * count`` of them, not all (``heapq.nsmallest`` scans
        every entry).  Stale entries (lazily deleted ones) are walked through and skipped.
        """
        heap = self._heap
        n = len(heap)
        entries: list[tuple[float, int]] = []
        if not n:
            return entries
        clock = self._clock
        pop, push = heapq.heappop, heapq.heappush
        frontier = [(heap[0], 0)]
        while frontier:
            (f, cid), i = pop(frontier)
            ent = clock.get(cid)
            if ent is not None and ent[0] == f and (not entries or entries[-1] != (f, cid)):
                entries.append((f, cid))
                if len(entries) == count:
                    break
            j = 2 * i + 1
            if j < n:
                push(frontier, (heap[j], j))
                if j + 1 < n:
                    push(frontier, (heap[j + 1], j + 1))
        return entries

    def _predict(self, temperature: float, count: int) -> list[tuple[float, int]]:
        row = self.urgency_table.row(temperature)
        if self._row is not None and row != self._row:
            clock = self._rescaled(row)
            entries = heapq.nsmallest(count, ((f, cid) for cid, (f, _) in clock.items()))
        else:
            entries = self._smallest_valid(count)
        if entries and entries[0][0] == _INF:
            return []  # the all-zero fallback is not predictable without a step
        return [(f, cid) for f, cid in entries if f != _INF]

    # -- the choice ------------------------------------------------------

    def sync_row(self, temperature: float) -> None:
        """Do now the re-weighting the next :meth:`choose_and_remove` would do first.

        ``choose_and_remove`` begins by moving every clock to the urgency row of the
        temperature it is given.  A caller that is about to choose with *this same
        temperature*, and knows that nothing will be posted in between, may do that part
        early, so that a prediction made first reads the heap as it is instead of
        re-weighting a copy of every clock (and the choice then finds the work done).
        The state afterwards is exactly the state the choice would have left, so the
        sequence of clocks, and with it every later choice, is unchanged.  The caller
        must not use this on an empty rack: codelets posted to it before the choice are
        enrolled under the *previous* row and re-weighted by the choice, a different
        number than enrolling them under the new row.
        """
        row = self.urgency_table.row(temperature)
        if row != self._row:
            self._reweight(row)

    def choose_and_remove(self, temperature: float, rng: Any = None) -> Codelet | None:
        """The codelet with the smallest firing time.  Draws nothing from *rng*."""
        if self._total_count == 0:
            return None
        self.current_temperature = temperature
        row = self.urgency_table.row(temperature)
        if row != self._row:
            self._reweight(row)
        else:
            self._row = row
        top = self._top_valid()
        if top is None:
            return None
        f, cid = top
        if f == _INF:
            return self._fallback_choice()
        heapq.heappop(self._heap)
        codelet = self._by_id.pop(cid)
        del self._clock[cid]
        self.t_now = f
        self._bin_of(codelet).remove(codelet)
        self._total_count -= 1
        self._compact()
        return codelet

    def _fallback_choice(self) -> Codelet | None:
        """Every weight is zero: the faithful rack's uniform-over-bins fallback."""
        step = self._step_source() if self._step_source is not None else 0
        stream = self.streams.fallback(step)
        non_empty = [b for b in self.bins if b.count > 0]
        if not non_empty:
            return None
        self.fallbacks += 1
        self.gen += 1
        chosen_bin: CoderackBin = stream.pick(non_empty)
        codelet = chosen_bin.choose_random(stream)
        chosen_bin.remove(codelet)
        self._total_count -= 1
        self._forget(codelet)
        return codelet

    # -- posting and leaving ------------------------------------------------

    def post(
        self,
        codelet: Codelet,
        current_time: int | None = None,
        rng: Any = None,
        temperature: float | None = None,
    ) -> None:
        if self.guard is not None:
            self.guard()
        super().post(codelet, current_time, rng, temperature)
        self._enroll(codelet, self._urgency_to_bin(codelet.urgency))
        self._compact()

    def post_deferred(
        self,
        batch: list[Codelet],
        current_time: int | None = None,
        rng: Any = None,
        temperature: float | None = None,
    ) -> None:
        if self.guard is not None:
            self.guard()
        super().post_deferred(batch, current_time, rng, temperature)
        self._enroll_missing()
        self._compact()

    def remove_old_codelets(
        self,
        current_time: int,
        num_to_remove: int,
        rng: Any,
        temperature: float | None = None,
    ) -> list[Codelet]:
        if self.guard is not None:
            self.guard()
        removed = super().remove_old_codelets(current_time, num_to_remove, rng, temperature)
        for codelet in removed:
            self._forget(codelet)
        self.removed += len(removed)
        return removed

    def clear(self) -> None:
        if self.guard is not None:
            self.guard()
        super().clear()
        self.gen += 1
        self._clock.clear()
        self._by_id.clear()
        self._heap.clear()

    def _move_urgencies(self, codelet_type: str, urgency_of: Any) -> None:
        """A clamp or its lifting re-files codelets: rescale each one's residual."""
        if self.guard is not None:
            self.guard()
        super()._move_urgencies(codelet_type, urgency_of)
        self.gen += 1
        row = self._weights()
        t = self.t_now
        for cid, (f, w_old) in list(self._clock.items()):
            codelet = self._by_id[cid]
            if codelet.codelet_type != codelet_type:
                continue
            w_new = row[self._urgency_to_bin(codelet.urgency)]
            if w_new == w_old:
                continue
            if w_new <= 0:
                f_new = _INF
            elif w_old <= 0 or f == _INF:
                f_new = t + self.streams.clock_exponential(cid) / w_new
            else:
                f_new = t + (f - t) * w_old / w_new
            self._clock[cid] = (f_new, w_new)
            heapq.heappush(self._heap, (f_new, cid))

    # -- introspection (tests) ---------------------------------------------

    def check_consistency(self) -> None:
        """Raise ``AssertionError`` if bins, counts, clocks and heap disagree."""
        on_rack = {c.id: c for b in self.bins for c in b.codelets}
        assert len(on_rack) == self._total_count, "bin population != total count"
        assert set(on_rack) == set(self._clock), "clock keys != codelets on the rack"
        assert set(on_rack) == set(self._by_id), "by-id map != codelets on the rack"
        live = {(f, cid) for cid, (f, _) in self._clock.items()}
        assert live <= set(self._heap), "a live clock is missing from the heap"
        for b in self.bins:
            for c in b.codelets:
                assert self._urgency_to_bin(c.urgency) == b.bin_number, "codelet in wrong bin"
        row = self._weights()
        for cid, (_, w) in self._clock.items():
            assert w == row[self._urgency_to_bin(on_rack[cid].urgency)], "stale weight"
