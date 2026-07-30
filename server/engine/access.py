"""Read-set and write-set discipline for codelet execution (WP4.2).

Free-running (WP4.4) lets a codelet decide on a Workspace that has moved on by the time
it commits.  Something has to notice when that has happened, and the architecture
already says what to do about it: **conflict → fizzle**.  A codelet that loses a race
fizzles for the same reason it fizzles when its structure is too weak, so most staleness
needs only to be *detected* — no rollback, no retry queue, no new outcome for the model
to learn.

Detection is what this module provides.  Each codelet execution records the entities it
read, together with the version each entity carried when it was read, and the entities
it wrote.  At commit, a read-set whose versions have all held is a codelet that decided
against a Workspace that still exists; one whose versions have moved decided against a
Workspace that does not.

Why versions rather than locks
------------------------------
Locking the objects a codelet touches would serialise exactly the contention the
parallelism is for, and it invites deadlock — a bridge scout takes objects in two
strings, and two scouts taking them in opposite orders is the textbook case.  Optimistic
validation has neither problem: nothing is held, and a loser fizzles rather than waits.
It suits this engine unusually well, because a fizzle here is not a retry-with-backoff
but a *normal outcome* that the temperature already accounts for.

Granularity
-----------
The unit is a single object, structure or Slipnet node — the finest granularity the
engine's own vocabulary offers, and the one that matches how codelets actually work:
a bond scout touches two adjacent objects, not a string.  The plan flags granularity as
an open question, so it is deliberately a *policy* here rather than something welded in:
:meth:`AccessSet.key_for` is the single place that decides what counts as one entity,
and coarsening it to whole strings is a change to one function.

Too fine and unrelated codelets appear to conflict through a shared container; too
coarse and structures build on premises that moved.  WP4.4 tunes it against the serial
reference, with the fizzle rate as the signal.

Cost when serial
----------------
Nothing here runs unless ``EngineContext.track_access`` is on.  Serial execution is the
permanent reference mode and must not pay for machinery it cannot use, so the recorder
is absent rather than idle by default, and the builtins check one boolean.
"""

from __future__ import annotations

import threading
from typing import Any

#: Entity kinds.  ``COMPONENT`` covers the whole-engine singletons — the coderack, the
#: trace, the temperature — which have no useful sub-identity and are contended by
#: definition.  The coderack in particular is the hottest contended structure in the
#: engine, which is why WP4.3 shards it rather than trying to version it finely.
KIND_OBJECT = "object"
KIND_STRUCTURE = "structure"
KIND_NODE = "node"
KIND_COMPONENT = "component"


class VersionTable:
    """Monotonic version per entity, bumped on every write.

    A plain dict under a lock.  The lock is held only around a dict read or write, and
    under free-threading that is what makes the counter safe; a bare ``+= 1`` here would
    have exactly the lost-update problem that WP0.3 removed from the identifier
    counters, and with the same consequence — two writers believing they were the only
    one.

    Absent keys read as version 0, so an entity that has never been written needs no
    entry. That keeps the table proportional to what the run has actually touched
    rather than to the size of the Workspace.
    """

    __slots__ = ("_lock", "_versions")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._versions: dict[tuple, int] = {}

    def version(self, key: tuple) -> int:
        with self._lock:
            return self._versions.get(key, 0)

    def versions(self, keys) -> dict[tuple, int]:
        """Read several versions under one acquisition.

        A codelet validates its whole read-set at once, and taking the lock per key
        would both cost more and — worse — let the table change mid-validation, so that
        the set was never all observed at any single instant.
        """
        with self._lock:
            return {key: self._versions.get(key, 0) for key in keys}

    def bump(self, key: tuple) -> int:
        with self._lock:
            value = self._versions.get(key, 0) + 1
            self._versions[key] = value
            return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._versions)


class AccessSet:
    """What one codelet execution read and wrote.

    Reads are stored with the version observed, because that is what validation
    compares; writes are stored as bare keys, because a writer does not care what the
    value was before.
    """

    __slots__ = ("reads", "writes")

    def __init__(self) -> None:
        self.reads: dict[tuple, int] = {}
        #: Key to the number of times *this* codelet bumped it.  A count rather than a
        #: set, because validation has to distinguish "the version moved because I moved
        #: it" from "the version moved because somebody else did".  A codelet reads an
        #: object and then, very often, writes it — a bond builder reads the two objects
        #: it is bonding and then changes both — so without this every codelet
        #: invalidates its own read-set and fizzles.  Measured before the fix: 49
        #: self-conflicts in 800 serial codelets, where the true answer is zero.
        self.writes: dict[tuple, int] = {}

    @staticmethod
    def key_for(entity: Any) -> tuple | None:
        """The entity key for a thing a codelet touched, or ``None`` if it is not one.

        **The granularity policy lives here**, and nowhere else. Objects and structures
        are identified by the per-run identifiers WP0.3 made dependable; Slipnet nodes
        by name, since a node's identity is its name. Anything unrecognised returns
        ``None`` and is simply not tracked, which is the safe direction: an untracked
        read cannot cause a false conflict, and the things that matter are all
        recognised.
        """
        if entity is None:
            return None
        # A Slipnet node: named, and its identity is that name.
        if hasattr(entity, "conceptual_depth") and hasattr(entity, "name"):
            return (KIND_NODE, entity.name)
        # A workspace structure carries a proposal level; an object does not.
        identifier = getattr(entity, "id", None)
        if identifier is None:
            return None
        if hasattr(entity, "proposal_level"):
            return (KIND_STRUCTURE, identifier)
        return (KIND_OBJECT, identifier)

    def record_read(self, key: tuple, version: int) -> None:
        # First read wins. A codelet that reads the same entity twice should validate
        # against what it saw when it *began* relying on it; keeping the later version
        # would quietly forgive a change that happened in between.
        self.reads.setdefault(key, version)

    def record_write(self, key: tuple) -> None:
        self.writes[key] = self.writes.get(key, 0) + 1

    @property
    def is_empty(self) -> bool:
        return not self.reads and not self.writes

    def summary(self) -> dict:
        """An inspectable form — the plan asks for these to be recorded and readable."""
        return {
            "reads": sorted(f"{kind}:{ident}" for kind, ident in self.reads),
            "writes": sorted(f"{kind}:{ident}" for kind, ident in self.writes),
            "read_count": len(self.reads),
            "write_count": len(self.writes),
        }

    def __repr__(self) -> str:
        return f"AccessSet(reads={len(self.reads)}, writes={len(self.writes)})"


class AccessRecorder:
    """Tracks the current codelet's accesses and validates them at commit.

    One recorder per worker.  ``current`` is per-thread, because under free-running each
    worker is executing a different codelet and they must not accumulate into each
    other's set.
    """

    def __init__(self, versions: VersionTable | None = None) -> None:
        self.versions = versions if versions is not None else VersionTable()
        self._local = threading.local()
        #: Completed access sets, kept for inspection. Bounded, because a run executes
        #: thousands of codelets and an unbounded log would be the very kind of
        #: write-only accumulation Phase 0 exists to remove.
        self.history: list[AccessSet] = []
        self.history_limit = 200
        self.conflicts = 0

    @property
    def current(self) -> AccessSet | None:
        return getattr(self._local, "access", None)

    def begin(self) -> AccessSet:
        access = AccessSet()
        self._local.access = access
        return access

    def end(self) -> AccessSet | None:
        access = self.current
        self._local.access = None
        if access is not None and not access.is_empty:
            self.history.append(access)
            if len(self.history) > self.history_limit:
                del self.history[: len(self.history) - self.history_limit]
        return access

    # -- recording -----------------------------------------------------

    def read(self, *entities: Any) -> None:
        access = self.current
        if access is None:
            return
        for entity in entities:
            key = AccessSet.key_for(entity)
            if key is not None:
                access.record_read(key, self.versions.version(key))

    def read_component(self, name: str) -> None:
        access = self.current
        if access is None:
            return
        key = (KIND_COMPONENT, name)
        access.record_read(key, self.versions.version(key))

    def write(self, *entities: Any) -> None:
        access = self.current
        for entity in entities:
            key = AccessSet.key_for(entity)
            if key is None:
                continue
            self.versions.bump(key)
            if access is not None:
                access.record_write(key)

    def write_component(self, name: str) -> None:
        key = (KIND_COMPONENT, name)
        self.versions.bump(key)
        access = self.current
        if access is not None:
            access.record_write(key)

    # -- validation ----------------------------------------------------

    def validate(self, access: AccessSet | None = None) -> bool:
        """Have the premises this codelet read held?

        ``True`` means every entity it relied on is at the version it saw, so the
        decision it reached still applies. ``False`` means at least one moved, and the
        caller should fizzle — which is why this returns a verdict rather than raising:
        fizzling is the architecture's own outcome, not an exception.

        Serially this is always ``True``, because nothing else ran between the read and
        the check. That is exactly why serial behaviour is unchanged.
        """
        access = access if access is not None else self.current
        if access is None or not access.reads:
            return True
        observed = self.versions.versions(access.reads.keys())
        for key, version in access.reads.items():
            # A codelet's own writes are not a conflict with itself.  Expected is the
            # version it read plus the bumps it made; anything beyond that came from
            # somebody else, and that is the case worth fizzling for.
            if observed[key] != version + access.writes.get(key, 0):
                self.conflicts += 1
                return False
        return True

    def summary(self) -> dict:
        """Aggregate figures — the telemetry WP4.4 tunes granularity against."""
        return {
            "tracked_entities": len(self.versions),
            "recorded_codelets": len(self.history),
            "conflicts": self.conflicts,
            "mean_read_set": (
                sum(len(a.reads) for a in self.history) / len(self.history)
                if self.history
                else 0.0
            ),
            "mean_write_set": (
                sum(len(a.writes) for a in self.history) / len(self.history)
                if self.history
                else 0.0
            ),
        }
