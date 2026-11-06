"""The episode memory of a Training Mode Session: copy at start, merge at finish.

The rules (the user's, exactly):

* "Episodic memory changes should only affect runs that start after the change is made."
* "A run holds a copy of the current episodic memory static through its duration."

So a run starts from a *copy* of the episode's :class:`EpisodicMemory` at the version
current when it started, and its own additions go into that copy as in any run (so it does
not record the same snag twice).  When it finishes, the descriptions that are new in its
copy -- **its additions**, oldest first -- are merged into the episode memory with
``store_answer`` / ``store_snag`` (which re-stamp ids), skipping any the episode already
holds by Metacat's own presence checks.  A merge bumps the memory's **version**; a run
records the version it started with (``memory_version``) and its merge order (``seq``).
Replaying the merges in order rebuilds the memory exactly, and re-running a run against the
memory of its version reproduces it.

With one run in flight at a time this is exactly Metacat's serial episode: each run
starts after the previous one merged, the copy has the ids and descriptions the shared
object would have, and nothing is ever skipped.

Shipping memory to workers
--------------------------
Memory grows, so a task does not carry it.  Workers cache each episode's master by
``(session_id, epoch, version)``; a task carries a :class:`MemoryRef`: its start version
and the *tail* of the last few merges (pre-pickled once, so a task costs a memcpy).  A
worker applies the merges it has not seen, which gives the same master as the scheduler's
because the merge is deterministic.  A worker too far behind (or ahead, after a retry)
returns ``need_snapshot`` and the scheduler resubmits that task with a full snapshot.

Shipping the configuration to workers
-------------------------------------
A session's configuration is shipped the other way: a task carries a :class:`ConfigShip`, the
pickled provider (about 135 KB) its run starts under, with a *key* the sender gives each
distinct provider.  The sender pickles a provider once, when it first sees it; a worker
unpickles a key once and keeps the provider (:func:`worker_provider`).  Measured
(``agents-workspace/v2-S4/spike_transport.out``), carrying the 135 KB with every task adds
about 0.03 ms to a task's round trip and nothing measurable to a pipelined task, against
runs of tens of milliseconds, so there is no tail, no snapshot request and no rebinding of
any pool when a configuration changes.  A task for another configuration is just a task
with another key, so sessions with different configurations share one pool.

Storage uses :mod:`server.engine.state_graph`'s record encoding (JSON); transport uses
pickle of the same objects, which is smaller and faster.  Tuples come back from JSON as
lists, so :func:`decode_additions` restores ``problem`` to a tuple, the one tuple field.
"""

from __future__ import annotations

import pickle
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Protocol

from server.engine.ids import KIND_ANSWER, KIND_SNAG, IdAllocator
from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription, answers_equal
from server.engine.metadata import MetadataProvider

#: Merges kept in a worker task's tail, at least; the service raises it with the workers.
MIN_TAIL = 16
#: Episodes a worker keeps cached.
CACHE_LIMIT = 8
#: Configurations (providers) a worker keeps cached: a few sessions' current versions.
PROVIDER_CACHE_LIMIT = 8


@dataclass
class Additions:
    """What one run added to its copy of the memory, oldest first."""

    answers: list[AnswerDescription] = field(default_factory=list)
    snags: list[SnagDescription] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.answers and not self.snags


@dataclass
class MemoryRef:
    """Where a task's memory comes from (see the module docstring)."""

    session_id: int
    epoch: str
    #: The version this run starts with.
    version: int
    #: The tail covers merges ``tail_from + 1 .. version``; ``len(tail) == version - tail_from``.
    tail_from: int = 0
    tail: list[bytes] = field(default_factory=list)
    #: A full snapshot of the master at ``version``; replaces the tail when set.
    snapshot: bytes | None = None


@dataclass(frozen=True)
class ConfigShip:
    """The configuration a task's run starts under: ``blob`` is ``pickle.dumps(provider)``,
    ``key`` names that provider (unique per provider object among those one sender ships)."""

    key: int
    blob: bytes


class NeedSnapshot(Exception):
    """The worker cannot reach the task's version from its cache and the tail."""


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------


def copy_for_run(master: EpisodicMemory) -> EpisodicMemory:
    """A run's private view: the descriptions are shared (a run never edits one other than
    the activation, which ``init_mcat`` clears), the lists and the id counters are not."""
    mem = EpisodicMemory()
    mem.answers = list(master.answers)
    mem.snags = list(master.snags)
    mem.ids = IdAllocator(master.ids.snapshot())
    return mem


def additions_of(copy: EpisodicMemory, base_answers: int, base_snags: int) -> Additions:
    """The descriptions new in *copy*, oldest first (new ones are consed on the front)."""
    n_a = len(copy.answers) - base_answers
    n_s = len(copy.snags) - base_snags
    return Additions(
        answers=list(reversed(copy.answers[:n_a])) if n_a > 0 else [],
        snags=list(reversed(copy.snags[:n_s])) if n_s > 0 else [],
    )


def answer_present(master: EpisodicMemory, d: AnswerDescription) -> bool:
    """``EpisodicMemory.answer_present`` on an already-built description (``memory.ss:90-97``),
    through the engine's one comparison of two answers, ``memory.answers_equal``."""
    return any(answers_equal(past, d) for past in master.answers)


def snag_present(master: EpisodicMemory, d: SnagDescription) -> bool:
    """``EpisodicMemory.snag_present`` on an already-built description (``memory.ss:78-83``)."""
    problem = tuple(d.problem)
    return any(s.equal(problem, d.rule_signature) for s in master.snags)


def apply_merge(master: EpisodicMemory, adds: Additions) -> tuple[int, int]:
    """Merge a run's additions into the master; returns how many answers and snags landed.

    Oldest first, so the master's newest-first order matches the order they were found in.
    """
    n_a = n_s = 0
    for d in adds.answers:
        if not answer_present(master, d):
            master.store_answer(d)
            n_a += 1
    for s in adds.snags:
        if not snag_present(master, s):
            master.store_snag(s)
            n_s += 1
    return n_a, n_s


# ---------------------------------------------------------------------------
# Encodings: JSON records for storage, pickle for transport
# ---------------------------------------------------------------------------


def encode_additions(adds: Additions) -> tuple[dict, dict]:
    """``state_graph`` records for the answers and for the snags (JSON-able)."""
    from server.engine import state_graph as sg

    out = []
    for group in (adds.answers, adds.snags):
        writer = sg._Writer({})
        roots = [writer.ref(d) for d in group]
        out.append({"records": writer.records, "roots": roots})
    return out[0], out[1]


def decode_additions(answers: dict | None, snags: dict | None) -> Additions:
    from server.engine import state_graph as sg

    def _decode(blob: dict | None) -> list:
        if not blob or not blob.get("roots"):
            return []
        reader = sg._Reader(blob["records"], None, {})
        reader.build()
        return [reader.resolve(r) for r in blob["roots"]]

    adds = Additions(answers=_decode(answers), snags=_decode(snags))
    for d in (*adds.answers, *adds.snags):
        d.problem = tuple(d.problem)  # JSON has no tuples
    return adds


def dump_additions(adds: Additions) -> bytes:
    return pickle.dumps(adds, protocol=pickle.HIGHEST_PROTOCOL)


def snapshot_blob(master: EpisodicMemory) -> bytes:
    return pickle.dumps(
        (master.answers, master.snags, master.ids.snapshot()), protocol=pickle.HIGHEST_PROTOCOL
    )


def memory_from_snapshot(blob: bytes) -> EpisodicMemory:
    answers, snags, counters = pickle.loads(blob)
    mem = EpisodicMemory()
    mem.answers, mem.snags = list(answers), list(snags)
    mem.ids = IdAllocator(counters)
    return mem


def memory_fingerprint(mem: EpisodicMemory) -> Any:
    """Everything that identifies a memory's content, for equality checks."""
    # ``activation`` is how strongly the *last run* was reminded of an answer
    # (``clear_activations`` zeroes it at the next ``init_mcat``): transient, not content.
    return (
        [{k: v for k, v in vars(a).items() if k != "activation"} for a in mem.answers],
        [dict(vars(s)) for s in mem.snags],
        mem.ids.snapshot(),
    )


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[int, str], tuple[int, EpisodicMemory]] = {}


def worker_master(ref: MemoryRef) -> EpisodicMemory:
    """The master at ``ref.version``, from this process's cache plus the task's tail."""
    key = (ref.session_id, ref.epoch)
    if ref.snapshot is not None:
        master = memory_from_snapshot(ref.snapshot)
        version = ref.version
    else:
        cached = _CACHE.get(key)
        if cached is not None and ref.tail_from <= cached[0] <= ref.version:
            version, master = cached
        elif cached is None and ref.tail_from == 0:
            version, master = 0, EpisodicMemory()
        else:
            raise NeedSnapshot()
        for blob in ref.tail[version - ref.tail_from:]:
            apply_merge(master, pickle.loads(blob))
            version += 1
        if version != ref.version:
            raise NeedSnapshot()
    _CACHE.pop(key, None)
    _CACHE[key] = (version, master)
    while len(_CACHE) > CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    return master


def begin(ref: MemoryRef) -> tuple[EpisodicMemory, int, int]:
    """A run's copy of the episode memory, with the sizes its additions are measured from."""
    master = worker_master(ref)
    copy = copy_for_run(master)
    return copy, len(copy.answers), len(copy.snags)


_PROVIDERS: OrderedDict[int, MetadataProvider] = OrderedDict()


def worker_provider(ship: ConfigShip) -> MetadataProvider:
    """The provider for *ship*: unpickled once per key in this process, then cached (LRU)."""
    got = _PROVIDERS.get(ship.key)
    if got is not None:
        _PROVIDERS.move_to_end(ship.key)
        return got
    got = pickle.loads(ship.blob)
    _PROVIDERS[ship.key] = got
    while len(_PROVIDERS) > PROVIDER_CACHE_LIMIT:
        _PROVIDERS.popitem(last=False)
    return got


def begin_run(
    ref: MemoryRef | None, ship: ConfigShip | None, fallback: MetadataProvider | None
) -> tuple[EpisodicMemory | None, int, int, MetadataProvider | None]:
    """Everything a run starts from: ``(memory copy, base answers, base snags, provider)``.

    The one compose step, used by ``swarm.run_one`` and the session executor's ``run_task``
    so the swarm, the serial child and an in-process run start identically.  The provider
    is the shipped one, else *fallback* (a caller that passes the provider directly); the
    memory is ``None`` for a task with no ``MemoryRef``.  Raises :class:`NeedSnapshot`.
    """
    memory, base_a, base_s = (None, 0, 0) if ref is None else begin(ref)
    provider = worker_provider(ship) if ship is not None else fallback
    return memory, base_a, base_s, provider


def end(copy: EpisodicMemory, base_answers: int, base_snags: int) -> bytes:
    return dump_additions(additions_of(copy, base_answers, base_snags))


def forget_worker_cache() -> None:
    _CACHE.clear()
    _PROVIDERS.clear()


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayEntry:
    """One entry of a session's record, in ``seq`` order.  ``kind`` names what ``data`` is
    (``memory_merge``: an :class:`Additions`)."""

    seq: int
    kind: str
    data: Any


class ReplaySource(Protocol):
    """Where a replay reads its entries from: the stored rows or a live in-memory list.

    Pure: it holds no connection and does no work but hand entries over in ``seq`` order, so
    a replay is the same code over either (the stored rows are read into a
    :class:`ListReplaySource`)."""

    def entries(self, after: int = 0, upto: int | None = None) -> Iterator[ReplayEntry]:
        """The entries with ``after < seq <= upto`` (no upper bound when ``upto`` is None), by ``seq``."""
        ...


class ListReplaySource:
    """The in-memory :class:`ReplaySource`."""

    def __init__(self, entries: Iterable[ReplayEntry] = ()) -> None:
        self._entries = sorted(entries, key=lambda e: e.seq)

    def append(self, entry: ReplayEntry) -> None:
        self._entries.append(entry)
        if len(self._entries) > 1 and self._entries[-2].seq > entry.seq:
            self._entries.sort(key=lambda e: e.seq)

    def entries(self, after: int = 0, upto: int | None = None) -> Iterator[ReplayEntry]:
        for e in self._entries:
            if e.seq > after and (upto is None or e.seq <= upto):
                yield e


def replay_memory(source: ReplaySource, upto: int | None = None) -> EpisodicMemory:
    """Rebuild the Episodic Memory by applying the ``memory_merge`` entries (to version *upto*)."""
    memory = EpisodicMemory()
    for e in source.entries(upto=upto):
        if e.kind == "memory_merge":
            apply_merge(memory, e.data)
    return memory
