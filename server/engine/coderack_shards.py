"""Three candidate sharded coderacks, for comparison (WP4.3).

The Coderack is the hardest single problem in Phase 0, and the profile says why: it is
*simultaneously* the largest serial fraction of the runtime and the most contended
structure in the engine, touched by the runner on every post and every selection.  So
parallelism does not pay off until it is decomposed — sharding is a prerequisite, not an
optimisation.

What makes it hard is that selection is not a queue pop.  It is a two-stage draw: pick
one of seven urgency bins with probability proportional to
``count x (1 + bin) ** ((110 - temperature) / 15)``, then pick uniformly within the bin.
That distribution is the mechanism by which temperature regulates exploration — at high
temperature the bins are nearly equally weighted and selection is nearly random, at low
temperature the high-urgency bins dominate and it becomes greedy.  A decomposition that
distorts it does not make the engine faster; it makes it a different engine.

The plan lists three candidate strategies without choosing between them, so all three are
implemented here and measured.  ``scripts/bench_shards.py`` is the comparison.

The three
---------

**Locked single rack** (:class:`LockedCoderack`) — the reference. Semantics are exactly
the serial engine's, because it *is* the serial engine's rack with a mutex around it.
Its value is as the control: it establishes what perfect fidelity costs in contention, so
the others can be judged against something.

**Shard by codelet family** (:class:`FamilyShardedCoderack`) — each shard owns a set of
codelet types. Attractive because a scout and an evaluator rarely contend over the same
codelet, and because family is known at post time.

**Per-worker racks with work stealing** (:class:`WorkerShardedCoderack`) — the plan's own
headline phrasing. Each worker posts to and draws from its own rack, stealing from the
busiest when its own is empty.

Why "shard by workspace region" is not among them
-------------------------------------------------
The plan lists it as a third option, and it cannot be built as stated: **a codelet does
not know its region until it runs.** A bottom-up bond scout chooses its object *during*
execution, by salience-weighted draw over the whole Workspace — that choice is the first
thing it does. Only the top-down codelets carry a triggering slipnode, and even they do
not name a string. Partitioning by region would therefore require deciding each codelet's
region before the codelet has decided it, which is not a scheduling problem but a
contradiction. Recorded here rather than silently dropped, because the option looks
reasonable until one checks what the codelets actually do.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from server.engine import hardware
from server.engine.coderack import Codelet, Coderack

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


class ShardedCoderack:
    """What all three candidates provide.

    Deliberately the same surface as :class:`~server.engine.coderack.Coderack`, so the
    runner needs no knowledge of which is installed and a candidate can be swapped in for
    measurement without touching the engine.
    """

    def post(self, codelet: Codelet, current_time: int | None = None,
             rng: RNG | None = None) -> None:
        raise NotImplementedError

    def choose_and_remove(self, temperature: float, rng: RNG) -> Codelet | None:
        raise NotImplementedError

    @property
    def total_count(self) -> int:
        raise NotImplementedError

    @property
    def is_empty(self) -> bool:
        return self.total_count == 0

    #: Contention telemetry. The point of the exercise is to compare these against
    #: fidelity, so every candidate reports them the same way.
    contended_acquisitions: int = 0
    steals: int = 0


class LockedCoderack(ShardedCoderack):
    """One rack, one mutex. The control.

    Fidelity is perfect by construction — this is the serial rack — so what it measures
    is the price of perfect fidelity. That matters more than it sounds: if a locked rack
    turns out not to be the bottleneck at eight workers, the more elaborate candidates
    are solving a problem the engine does not have, and the right answer is the simple
    one.

    ``blocking=False`` first, then blocking, so a contended acquisition can be *counted*
    rather than inferred. That is the only reason for the two-step; an uncontended
    ``acquire(False)`` succeeds and costs the same as a plain acquire.
    """

    def __init__(self, meta: MetadataProvider) -> None:
        self._rack = Coderack(meta)
        self._lock = threading.Lock()
        self.contended_acquisitions = 0
        self.steals = 0

    def _acquire(self) -> None:
        if not self._lock.acquire(blocking=False):
            self.contended_acquisitions += 1
            self._lock.acquire()

    def post(self, codelet: Codelet, current_time: int | None = None,
             rng: RNG | None = None) -> None:
        self._acquire()
        try:
            self._rack.post(codelet, current_time, rng)
        finally:
            self._lock.release()

    def choose_and_remove(self, temperature: float, rng: RNG) -> Codelet | None:
        self._acquire()
        try:
            return self._rack.choose_and_remove(temperature, rng)
        finally:
            self._lock.release()

    @property
    def total_count(self) -> int:
        return self._rack.total_count

    @property
    def rng(self) -> RNG | None:
        return self._rack.rng

    @rng.setter
    def rng(self, value: RNG | None) -> None:
        self._rack.rng = value

    @property
    def current_time(self) -> int:
        return self._rack.current_time

    @current_time.setter
    def current_time(self, value: int) -> None:
        self._rack.current_time = value

    def __getattr__(self, name: str) -> Any:
        # Everything else — clamping, type counts, bins for inspection — delegates.
        return getattr(self._rack, name)

    def __repr__(self) -> str:
        return f"LockedCoderack({self.total_count} codelets)"


#: The fewest codelets a shard may hold.
#:
#: Measured, and the measurement was a surprise.  Dividing the rack's capacity across
#: shards is correct — replicating it would give N shards N times the intended
#: population — but taken literally it makes a shard too small to be a coderack.  At
#: eight shards of twelve on ``eqe -> qeq; abbba?``, the stopping state ``gave_up:``
#: disappeared **entirely**: 0 occurrences in 60 runs where the serial engine gives up
#: 23 times, and it is that problem's most frequent outcome at 38.9%.
#:
#: The cause is that giving up is not a single codelet's decision.  It is the end of a
#: sequence — snags accumulate, a clamp is applied, jootsers observe the repetition —
#: and each step needs its codelets to still be on the rack when the next one looks.  A
#: twelve-codelet shard evicts them first, so the run never gets far enough to conclude
#: it is stuck, and instead answers.  Raising the shard size restores it: 19 at
#: twenty-five per shard, 27 at fifty, against the serial 23.
MIN_SHARD_CAPACITY = 25

#: The shard count follows from it: ``max_coderack_size // MIN_SHARD_CAPACITY``, which is
#: 4 at the default rack of 100.  A machine offering more workers than that runs several
#: against one shard.  `PHASE 1 PLAN.md` carries the measurement that would decide whether
#: a larger rack keeps the reachable set, and records that parallelism past this bound may
#: come from somewhere other than partitioning the Coderack.


class _ShardBase(ShardedCoderack):
    """Shared machinery for the two genuinely sharded candidates."""

    def __init__(self, meta: MetadataProvider, shards: int) -> None:
        self.meta = meta
        capacity = meta.get_param("max_coderack_size", 100)
        # Shard count is bounded by capacity, not by worker count.  More workers than
        # shards means some share, which costs contention; more shards than the capacity
        # supports costs *cognition*, and that is not a trade worth making.
        self.num_shards = max(1, min(int(shards), capacity // MIN_SHARD_CAPACITY or 1))
        # Each shard is a whole Coderack, so within a shard the two-stage
        # urgency-weighted draw is exactly the original. What the candidates differ in is
        # only *which* shard a codelet lands in and which shard a worker draws from —
        # which is the right place for the difference to be, since it isolates the part
        # that can distort the distribution.
        self._racks = [Coderack(meta) for _ in range(self.num_shards)]
        # Divide the capacity, do not replicate it.
        #
        # Each ``Coderack`` enforces ``max_coderack_size`` (100) for itself, so N shards
        # left alone hold N x 100 codelets.  That is not a bookkeeping detail: the cap is
        # why the codelet mix keeps tracking the current Workspace instead of drifting,
        # and on ``mrrjjj`` the rack sits at capacity for 58% of posts, so an eight-fold
        # capacity would remove almost all eviction pressure and change what the engine
        # attends to.  Sharding is supposed to change *where* a codelet waits, not how
        # many may wait.
        whole = self._racks[0].max_size
        for index, rack in enumerate(self._racks):
            # The remainder goes to the first shards rather than being lost, so the
            # shards still total exactly the original capacity.
            rack.max_size = whole // self.num_shards + (
                1 if index < whole % self.num_shards else 0
            )
        self._locks = [threading.Lock() for _ in range(self.num_shards)]
        self.contended_acquisitions = 0
        self.steals = 0
        self._post_cursor = 0
        self._cursor_lock = threading.Lock()
        #: Thread to shard.  Assigned on first touch and never read across threads
        #: afterwards, which is what keeps the hot path shared-nothing.
        self._local = threading.local()
        self._next_worker = 0
        self._worker_lock = threading.Lock()

    def worker_index(self) -> int:
        """This thread's shard, assigned once.

        The first draft used a shared round-robin cursor behind a lock for posting, and
        measurement showed why that was wrong: a lock taken on *every post* is a global
        serialisation point, so the sharding bought nothing and the extra bookkeeping made
        it slower than a single locked rack.  Thread-local assignment costs one lock per
        thread for the lifetime of the run instead of one per operation.
        """
        index = getattr(self._local, "worker", None)
        if index is None:
            with self._worker_lock:
                index = self._next_worker % self.num_shards
                self._next_worker += 1
            self._local.worker = index
        return index

    def _acquire(self, index: int) -> None:
        lock = self._locks[index]
        if not lock.acquire(blocking=False):
            self.contended_acquisitions += 1
            lock.acquire()

    def _post_to(self, index: int, codelet: Codelet,
                 current_time: int | None, rng: RNG | None) -> None:
        self._acquire(index)
        try:
            self._racks[index].post(codelet, current_time, rng)
        finally:
            self._locks[index].release()

    def _draw_from(self, index: int, temperature: float, rng: RNG) -> Codelet | None:
        self._acquire(index)
        try:
            return self._racks[index].choose_and_remove(temperature, rng)
        finally:
            self._locks[index].release()

    def _steal(self, avoid: int, temperature: float, rng: RNG) -> Codelet | None:
        """Take from a neighbouring shard, trying each in turn.

        Rotating from the thief's own index rather than sorting by occupancy.  Sorting
        reads every shard's count on every steal, and that is a read of every other
        worker's hot data — false sharing that showed up in the first measurement as the
        sharded candidates contending *more* than a single lock, not less.  A rotation
        touches one shard at a time and stops at the first that yields.
        """
        for offset in range(1, self.num_shards):
            index = (avoid + offset) % self.num_shards
            if not self._racks[index].codelets_present():
                continue
            codelet = self._draw_from(index, temperature, rng)
            if codelet is not None:
                self.steals += 1
                return codelet
        return None

    @property
    def total_count(self) -> int:
        return sum(rack.total_count for rack in self._racks)

    @property
    def rng(self) -> RNG | None:
        return self._racks[0].rng

    @rng.setter
    def rng(self, value: RNG | None) -> None:
        for rack in self._racks:
            rack.rng = value

    @property
    def current_time(self) -> int:
        return self._racks[0].current_time

    @current_time.setter
    def current_time(self, value: int) -> None:
        for rack in self._racks:
            rack.current_time = value

    @property
    def bins(self) -> list:
        """The seven urgency bins, merged across shards.

        Seven, not ``7 x num_shards``.  A sharded rack still *has* seven urgency levels —
        sharding decides which worker holds a codelet, not what urgency it is — and every
        reader of ``bins`` is asking about urgency: the state capture, the display
        serializer, the codelet-type histogram.  Returning the shards' bins end to end
        made a captured coderack un-restorable, because a restore indexes
        ``bins[bin_index]`` on a plain seven-bin rack.

        Rebuilt per access rather than maintained, since nothing on the hot path uses it —
        ``post`` and ``choose_and_remove`` go straight to a shard.
        """
        from server.engine.coderack import CoderackBin

        merged = []
        for level in range(self._racks[0].num_bins):
            view = CoderackBin(level)
            for rack in self._racks:
                for codelet in rack.bins[level].codelets:
                    view.add(codelet)
            merged.append(view)
        return merged

    @property
    def max_size(self) -> int:
        """The rack's capacity, summed across shards.

        Each shard enforces ``max_coderack_size`` for itself, so a rack of N shards holds
        N times as many codelets as a single rack would. That is a real difference in the
        engine's behaviour and not a bookkeeping detail — the cap exists so the codelet
        mix keeps tracking the current Workspace rather than drifting — and reporting the
        total is what makes it visible in a capture instead of silently multiplied.
        """
        return sum(rack.max_size for rack in self._racks)

    @property
    def clamped_urgencies(self) -> dict[str, int]:
        """The clamping pattern, which every shard holds identically.

        ``clamp_codelet_type`` applies to all of them, so any one is the answer; the
        first is chosen arbitrarily. Present because the state capture reads it, and its
        absence made a free-running Run impossible to capture at all.
        """
        return self._racks[0].clamped_urgencies

    def get_codelet_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rack in self._racks:
            for name, count in rack.get_codelet_type_counts().items():
                counts[name] = counts.get(name, 0) + count
        return counts

    def clear(self) -> None:
        for rack in self._racks:
            rack.clear()

    def clamp_codelet_type(self, codelet_type: str, urgency: int) -> None:
        for rack in self._racks:
            rack.clamp_codelet_type(codelet_type, urgency)

    def unclamp_codelet_type(self, codelet_type: str) -> None:
        for rack in self._racks:
            rack.unclamp_codelet_type(codelet_type)

    def clamp_pattern(self, pattern: list[tuple[str, int]]) -> None:
        for rack in self._racks:
            rack.clamp_pattern(pattern)

    def unclamp_all(self) -> None:
        for rack in self._racks:
            rack.unclamp_all()

    def occupancy(self) -> list[int]:
        """Per-shard counts — the load-balance signal the comparison reports."""
        return [rack.total_count for rack in self._racks]


class FamilyShardedCoderack(_ShardBase):
    """Shard by codelet family.

    The appeal is that family is known at post time and needs no coordination: a hash of
    the codelet type picks the shard, and a scout and an evaluator rarely contend.

    **The distortion is in selection, not posting**, and it is the thing to measure. A
    worker drawing from one shard draws from that shard's urgency distribution, and the
    families are not evenly spread across urgency bins — bottom-up scouts sit at low
    urgency and answer-finders at ``100 - temperature``. So a family shard's bin
    occupancy is systematically unlike the whole rack's, and a worker confined to it sees
    a different temperature response from the one the architecture specifies.

    Whether that matters is an empirical question, which is why this is a candidate rather
    than an argument.
    """

    def _shard_for(self, codelet_type: str) -> int:
        # Stable across processes, unlike ``hash()`` on a string, so a measurement is
        # reproducible. The distribution over 27 codelet types into a handful of shards
        # is uneven whatever is used; that unevenness is part of what is being measured.
        return sum(codelet_type.encode()) % self.num_shards

    def post(self, codelet: Codelet, current_time: int | None = None,
             rng: RNG | None = None) -> None:
        self._post_to(self._shard_for(codelet.codelet_type), codelet, current_time, rng)

    def choose_and_remove(self, temperature: float, rng: RNG) -> Codelet | None:
        # A shard is chosen in proportion to how much work it holds, which is the closest
        # this arrangement can come to the whole-rack distribution: it at least stops
        # empty shards from being drawn and starving the run.
        counts = self.occupancy()
        total = sum(counts)
        if total == 0:
            return None
        index = rng.weighted_pick(list(range(self.num_shards)), counts)
        codelet = self._draw_from(index, temperature, rng)
        if codelet is None:
            codelet = self._steal(index, temperature, rng)
        return codelet

    def __repr__(self) -> str:
        return f"FamilyShardedCoderack({self.num_shards} shards, {self.total_count} codelets)"


class WorkerShardedCoderack(_ShardBase):
    """Per-worker racks with work stealing — the plan's own phrasing.

    A worker posts to its own rack and draws from its own rack, stealing when empty.
    Contention should be near zero in the common case, because the only shared state a
    worker touches is its own lock.

    **Why posting is round-robin rather than worker-affine.** Worker affinity is the
    obvious reading, and it fails: codelets are posted overwhelmingly by the *runner* —
    the bottom-up and top-down posting passes in ``update_everything`` — not by codelets
    themselves. Under affinity those all land in one rack, and the other shards fill only
    from ``post_codelet``, which is a minority. The result is one hot shard and several
    idle ones, with stealing doing all the work. Round-robin posting spreads them evenly
    and costs one atomic increment.

    **The fidelity argument.** Because a codelet's shard is independent of its type and of
    its urgency, each shard's bin occupancy is an unbiased sample of the whole rack's. So
    a shard's two-stage draw has the *same* distribution as the whole rack's in
    expectation, and the temperature response is preserved. The variance is higher, which
    is a real difference — a shard with 12 codelets is a noisier draw than a rack with
    100 — and reads as slightly more exploration than the serial engine at the same
    temperature. Whether the expected range notices is exactly what the comparison
    measures.
    """

    def post(self, codelet: Codelet, current_time: int | None = None,
             rng: RNG | None = None) -> None:
        # Posts go to the posting thread's own shard.  The runner's posting passes and a
        # codelet's ``post_codelet`` both run on the worker that is executing, so this is
        # both shared-nothing and naturally balanced once every worker is running.
        self._post_to(self.worker_index(), codelet, current_time, rng)

    def choose_and_remove(self, temperature: float, rng: RNG,
                          worker: int | None = None) -> Codelet | None:
        if self.total_count == 0:
            return None
        # Without a worker id — which is every serial caller — a shard is chosen in
        # proportion to its occupancy. That is what makes a one-worker run comparable
        # with the serial engine: the marginal distribution over codelets is the same,
        # because choosing a shard by size and then a codelet within it is choosing
        # uniformly over shard membership.
        if worker is not None:
            index = worker % self.num_shards
        elif self.num_shards == 1:
            index = 0
        else:
            # Serial callers — every test, and the engine until WP4.4 turns workers on —
            # get an occupancy-weighted shard choice, which makes the marginal
            # distribution over codelets the same as the unsharded rack's.  Threaded
            # callers get their own shard and never read another's counts, because that
            # read is exactly the false sharing that made the first draft slow.
            if getattr(self._local, "worker", None) is not None:
                index = self._local.worker
            else:
                counts = self.occupancy()
                index = rng.weighted_pick(list(range(self.num_shards)), counts)

        codelet = self._draw_from(index, temperature, rng)
        if codelet is None:
            codelet = self._steal(index, temperature, rng)
        return codelet

    def __repr__(self) -> str:
        return f"WorkerShardedCoderack({self.num_shards} shards, {self.total_count} codelets)"


#: The candidates, by name, for the comparison harness.
CANDIDATES = {
    "locked": LockedCoderack,
    "family": FamilyShardedCoderack,
    "worker": WorkerShardedCoderack,
}


def build_candidate(
    name: str, meta: MetadataProvider, shards: int | None = None
) -> ShardedCoderack:
    """Construct one candidate.

    ``shards=None`` takes this machine's shard count
    (:func:`server.engine.hardware.shard_count`), which follows from its
    performance core count.  ``locked`` ignores ``shards`` — it has exactly one.
    """
    if shards is None:
        shards = hardware.shard_count()
    if name not in CANDIDATES:
        raise ValueError(f"unknown coderack candidate {name!r}; expected one of {sorted(CANDIDATES)}")
    if name == "locked":
        return LockedCoderack(meta)
    return CANDIDATES[name](meta, shards)
