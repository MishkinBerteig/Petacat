"""The episode memory of a Training: copy at start, merge at finish.

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
``(training_id, epoch, version)``; a task carries a :class:`MemoryRef`: its start version
and the *tail* of the last few merges (pre-pickled once, so a task costs a memcpy).  A
worker applies the merges it has not seen, which gives the same master as the scheduler's
because the merge is deterministic.  A worker too far behind (or ahead, after a retry)
returns ``need_snapshot`` and the scheduler resubmits that task with a full snapshot.

Storage uses :mod:`server.engine.state_graph`'s record encoding (JSON); transport uses
pickle of the same objects, which is smaller and faster.  Tuples come back from JSON as
lists, so :func:`decode_additions` restores ``problem`` to a tuple, the one tuple field.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import Any

from server.engine.ids import KIND_ANSWER, KIND_SNAG, IdAllocator
from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription

#: Merges kept in a worker task's tail, at least; the service raises it with the workers.
MIN_TAIL = 16
#: Episodes a worker keeps cached.
CACHE_LIMIT = 8


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

    training_id: int
    epoch: str
    #: The version this run starts with.
    version: int
    #: The tail covers merges ``tail_from + 1 .. version``; ``len(tail) == version - tail_from``.
    tail_from: int = 0
    tail: list[bytes] = field(default_factory=list)
    #: A full snapshot of the master at ``version``; replaces the tail when set.
    snapshot: bytes | None = None


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
    """``EpisodicMemory.answer_present`` on an already-built description: the three problem
    strings and the answer, and both rules' clause lists (``memory.ss:90-97``)."""
    for past in master.answers:
        if (
            tuple(past.problem) == tuple(d.problem)
            and past.top_rule_signature == d.top_rule_signature
            and past.bottom_rule_signature == d.bottom_rule_signature
        ):
            return True
    return False


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
    key = (ref.training_id, ref.epoch)
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


def end(copy: EpisodicMemory, base_answers: int, base_snags: int) -> bytes:
    return dump_additions(additions_of(copy, base_answers, base_snags))


def forget_worker_cache() -> None:
    _CACHE.clear()
