"""The speculative executor: one run across threads, bit-identical to the stream-serial run.

The shape in one paragraph
--------------------------
A *coordinator* (the calling thread) runs the engine's own ``run_mcat`` loop.  It chooses
each codelet exactly as the stream-serial reference (SSR) does -- from the clock rack --
so the sequence of choices is the SSR's by construction.  Only one engine method is
replaced: ``_execute_codelet``.  For a codelet whose *read prefix* a worker thread has
already run speculatively, the coordinator does not execute the body; it hands that
worker the **commit token** for this step and waits for it to finish.  The worker
validates its prefix against the live state, then continues *live* (it holds the token, so
it is the only writer) and runs the codelet's writes in serial order.  A prefix that fails
validation is discarded and re-executed live from scratch, from the same body stream, so
it draws the same numbers.  Everything else the step does -- the increment, the trace
emission, the sink calls, the rack-empty repost, the answer collection, the update cycle
-- is the engine's own code, run by the coordinator, in serial order.

Why the result is exact
-----------------------
1. *Randomness*: a codelet body draws only from the stream keyed by its id; the clock rack
   draws nothing at choice time; an update cycle draws from the stream keyed by its index
   (:mod:`.streams`).  No draw depends on which thread ran, or when.
2. *Choice*: the coordinator chooses at step ``k`` from the rack exactly as the SSR does.
   A prediction ("the next W codelets in clock order") is only a hint for what to speculate
   on; the token is granted to the codelet the real choice returned, and a speculation for
   a codelet that was not chosen is simply abandoned.  A choice that differs from the
   prediction therefore costs speed, never exactness.
3. *State*: everything a speculative prefix is allowed to do is *read shared state*, and
   every shared-state component carries a seqlock version.  Whoever writes a component
   (the token holder going live, the coordinator at an update cycle or inline) bumps its
   version to odd before and to even after.  A prefix records the versions it started
   under; at its commit it must find every component it may have read unchanged.  Reads
   that happen under an odd version, or across a write, fail validation.  A prefix may not
   write shared state at all: every write builtin, id allocation, trace record and rack
   mutation is trapped and waits for the token first (``ensure_live``), after which the
   codelet is the sole writer and the rest of it is plain serial code.
4. *Step-relative values*: ``ctx.codelet_count`` is a property that answers the
   *predicted* count to a speculating thread and notes that it was read; a prefix that
   read it is only valid if the real count turned out to be the predicted one.
5. *Anything surprising is an abort*: any exception inside a prefix (a torn read can
   produce one) is an abort, not an error; the codelet is re-executed live, where a real
   error will recur and propagate exactly as it would serially.

What is *not* parallel: choosing, the token hand-off, everything after the codelet, the
update cycle, and the ``meta``/``answer`` codelet families (which run on the coordinator
with a version bump over every component).  That is the Amdahl floor: see ``bench``.

The cost of the machinery (WP10)
--------------------------------
The overlap this engine can win is small and the machinery that wins it is not free, so
most of the design is about not paying where nothing is won.  What was measured on an M5
Max (``measurements/parallel/speculative-engine.md`` has the figures) and what was done:

* **One worker is the SSR.**  With a single worker nothing can overlap, so the engine
  installs nothing and runs the reference's own loop (``direct_single``).
* **A prefix that never writes commits on the coordinator.**  Such a prefix (about half
  of all speculations) needs neither the token nor its worker to commit: it parks its
  result (``S_RO_DONE``) and the worker is free for the next codelet at once; the
  coordinator compares the versions when the step comes up (``_commit_read_only``).  A
  stale one is undone and re-run through the SSR's own ``_execute_codelet``.
* **Run ahead only what pays.**  The codelets chosen to run ahead are a scheduling
  decision, never a result: the effects table marks types whose prefix is too short to
  repay a hand-off (``profitable``), and nothing runs ahead of, or behind, a step that
  may write what prefixes read (``_type_plan``: it would only abort them).
* **One prediction per epoch.**  The coordinator reads the upcoming codelets off a cached
  ``predict_entries`` list, trusted while ``gen`` is unchanged and ``F < floor_f`` (the
  clock rack keeps both), with a scan pointer so that a step handles about one new entry.
* **Idle workers park while the update cycle runs**, and nowhere else do they cost the
  coordinator anything: spinning cores slowed the update cycle by 10-20%.
* **No class swaps in a hot loop.**  Assigning an object's ``__class__`` is a
  stop-the-world pause on the free-threaded interpreter (it cost 300 us per update cycle
  when tried), so the guards stay installed for the whole run.  Workers bind their own
  guarded id allocator (``_WorkerIds``), so the coordinator's allocations pay no guard.
* **The step-relative ``codelet_count`` is the workers' alone.**  A Python-level property
  on the run's context, read a dozen times a step, was 3% of a run.  The real context
  stays a plain ``EngineContext``; the workers use a second context object that shares its
  ``__dict__`` and carries the property (``_wctx``).  Every builtin a prefix runs is bound
  to that object, and the engine objects that keep the real context (the trace) read it
  only on write paths, which a prefix cannot reach before it holds the token
  (``test_prefixes_never_read_the_step_through_the_real_context`` instruments it).

What it still costs, and why it does not pay at today's sizes: a codelet is 6-40 us, the
update cycle (serial) is more than half of a run, and every object a worker reads
becomes a cache line the coordinator must fetch back (free-threaded reference counts are
writes), which costs the coordinator a few microseconds per speculated codelet afterwards.
The net effect of speculating any one codelet type is within a few percent of zero.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

from server.engine.codelet_dsl.interpreter import (
    CodeletFizzle,
    CodeletInterpreter,
    VERBOSE_ONLY,
    _fizzle,
)
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.ids import IdAllocator, use_allocator
from server.engine.runner import EngineContext
from server.engine.slipnet import SlipnetNode
from server.engine.workspace_structures import WorkspaceStructure
from server.engine.trace import TemporalTrace
from server.engine.workspace_structures import set_structure_clock
from server.parallel.speculative import effects as fx
from server.parallel.speculative.reference import StreamSerial

# ---------------------------------------------------------------------------
# Thread-local speculation record, and the plugin classes swapped in
# ---------------------------------------------------------------------------


class _Local(threading.local):
    #: The speculation this thread is running, or ``None`` (coordinator, or live).
    spec: "Spec | None" = None
    #: The ``codelet_count`` a speculating thread should see.
    cc: int = 0
    #: ``(ctx, namespace template)`` for this thread.
    template: Any = None


_tl = _Local()


class SpeculationAbort(BaseException):
    """Unwinds a speculative prefix.

    A ``BaseException`` on purpose: codelet bodies and engine helpers contain
    ``except Exception`` clauses, and an abort must pass straight through them.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


R_CONFLICT = "conflict"
R_STEP = "step-relative"
R_EXCEPTION = "exception"
R_ABANDONED = "abandoned"
R_CHAOS = "chaos"

S_PENDING, S_RUNNING, S_WAITING, S_LIVE, S_DONE, S_GONE, S_RO_DONE = range(7)


class Spec:
    """One codelet's speculative execution."""

    __slots__ = (
        "codelet", "type", "info", "compiled", "pred_cc", "status", "go", "abandon",
        "arbiter", "start", "reads", "step_rel", "live", "worker", "error", "reason",
        "reexec", "token_held", "snapshot", "committed", "fp0", "deferred", "left",
    )

    def __init__(self, codelet: Any, info: Any, compiled: Any, pred_cc: int, worker: int) -> None:
        self.codelet = codelet
        self.type = codelet.codelet_type
        self.info = info
        self.compiled = compiled
        self.pred_cc = pred_cc
        self.status = S_PENDING
        #: -1 until the coordinator grants the token; then the real ``codelet_count``.
        self.go = -1
        self.abandon = False
        #: Whoever acquires this first decides the spec's fate: the worker (to take the
        #: token) or the coordinator (to abandon it).  Exactly one wins.
        self.arbiter = threading.Lock()
        self.start: list[int] | None = None
        self.reads = info.reads
        self.step_rel = False
        self.live = False
        self.worker = worker
        self.error: BaseException | None = None
        self.reason: str | None = None
        self.reexec = False
        self.token_held = False
        self.snapshot: Any = None
        self.committed = False
        self.fp0: Any = None
        #: Slipnet nodes whose buffer a prefix would have jolted (applied at commit).
        self.deferred: list[Any] = []
        #: True once the worker has fully left this spec (touches its arguments no more).
        self.left = False


class _SpecContext(EngineContext):
    """``EngineContext`` whose ``codelet_count`` is step-relative to a speculating thread.

    A data descriptor on the class wins over the instance ``__dict__`` entry the base
    class writes, so the serial code (``ctx.codelet_count += 1``) keeps working through
    the property while a thread with a live speculation record sees the predicted count.

    The coordinator does not pay for the property: with worker threads, the run's own
    context stays a plain ``EngineContext`` (the engine reads ``codelet_count`` a dozen
    times a step, and a Python-level property made that 3% of a run) and the workers use
    a second object of this class that *shares its ``__dict__``* with the real one
    (``SpeculativeEngine._wctx``), so every other attribute is the same storage.  Only
    the inline and detect modes, where the coordinator itself plays the speculating
    thread, swap the real context's class.
    """

    @property
    def codelet_count(self) -> int:  # type: ignore[override]
        spec = _tl.spec
        if spec is not None and not spec.live:
            spec.step_rel = True
            return _tl.cc
        return self.__dict__["codelet_count"]

    @codelet_count.setter
    def codelet_count(self, value: int) -> None:
        self.__dict__["codelet_count"] = value


#: What a prefix reads that another step's commit may have written: a step that may write
#: any of it is a *blocker* for the prefixes behind it (see ``SpeculativeEngine._type_plan``).
_CONFLICT_MASK = (fx.BIT["workspace"] | fx.BIT["slipnet_act"] | fx.BIT["themespace"]
                  | fx.BIT["temperature"])

#: Set to the running engine's trap while one is installed (one engine per process).
_GUARD: Callable[["Spec"], None] | None = None


def _trap(spec: "Spec") -> None:
    assert _GUARD is not None
    _GUARD(spec)


class _DeferredNode(SlipnetNode):
    """A Slipnet node whose ``activate_from_workspace`` is deferred while speculating.

    Codelets only ever ``+= 100`` into ``activation_buffer`` and nothing reads it until
    the update cycle (``ConceptMapping.activate_label`` flushes it, but only live).  So
    the jolt commutes with everything a concurrent prefix can see -- but it must not be
    *applied* by a prefix that may yet abort (it would be applied twice by the
    re-execution) or race with another thread's ``+=``.  A speculating thread therefore
    records the call and the commit applies it, in order, once the step has the token.
    The ``frozen`` test inside the real method is evaluated at that point, which is
    equivalent because ``slipnet_act`` is in every speculation's read set.
    """

    __slots__ = ()

    def activate_from_workspace(self) -> None:
        spec = _tl.spec
        if spec is not None and not spec.live:
            spec.deferred.append(self)
            spec.reads |= fx.BIT["slipnet_act"]
            return
        SlipnetNode.activate_from_workspace(self)


def _pure_all_concept_mappings(self: Any) -> list[Any]:
    """``Bridge.get_all_concept_mappings`` without the cache store, for speculating threads.

    The real method *reconciles* ``_all_concept_mappings`` against the two source lists
    and rebinds it on every call -- a write on a read path, to a list the committing
    builder mutates in place (``insert(0, cm)``).  A speculating thread's rebind can
    therefore lose a concurrent insertion.  In real runs every addition goes through the
    ``add_*`` methods, which keep the cache in step, so the reconciliation changes
    nothing and the store is dead; computing the same answer without storing it is exact.
    """
    current = {id(cm) for cm in self.concept_mappings}
    current.update(id(cm) for cm in self.bond_concept_mappings)
    ordered = [cm for cm in self._all_concept_mappings if id(cm) in current]
    known = {id(cm) for cm in ordered}
    ordered.extend(
        cm for cm in self.concept_mappings + self.bond_concept_mappings if id(cm) not in known
    )
    return ordered


def _install_class_patches() -> None:
    """Process-wide, thread-gated patches: inert unless the calling thread is speculating."""
    from server.engine.bridges import Bridge

    if getattr(Bridge, "_spec_patched", 0):
        Bridge._spec_patched += 1
        return
    original = Bridge.get_all_concept_mappings

    def get_all_concept_mappings(self: Any) -> list[Any]:
        spec = _tl.spec
        if spec is not None and not spec.live:
            return _pure_all_concept_mappings(self)
        return original(self)

    Bridge._spec_original = original
    Bridge.get_all_concept_mappings = get_all_concept_mappings
    Bridge._spec_patched = 1


def _remove_class_patches() -> None:
    from server.engine.bridges import Bridge

    n = getattr(Bridge, "_spec_patched", 0)
    if n > 1:
        Bridge._spec_patched = n - 1
    elif n == 1:
        Bridge.get_all_concept_mappings = Bridge._spec_original
        del Bridge._spec_patched, Bridge._spec_original


class _GuardedIds(IdAllocator):
    """Allocating an id is a write whose value depends on serial order: wait for the token."""

    __slots__ = ()

    def next(self, kind: str) -> int:  # type: ignore[override]
        spec = _tl.spec
        if spec is not None and not spec.live:
            _trap(spec)
        return IdAllocator.next(self, kind)


class _WorkerIds(IdAllocator):
    """The allocator a worker thread binds: the run's, behind the commit-token guard.

    The engine reaches the run's id allocator only through ``ids.next_id``, which reads a
    ``ContextVar`` that each thread binds for itself.  The coordinator keeps the run's own
    allocator, so its allocations (an update cycle makes thousands) pay no guard; a worker
    binds this proxy, whose ``next`` waits for the token like any other write.  (In the
    inline and detect modes the coordinator itself plays the speculating thread, and the
    run's allocator is given the guarded class instead -- see ``install``.)
    """

    __slots__ = ("_real",)

    def __init__(self, real: IdAllocator) -> None:  # no counters of its own
        self._real = real

    def next(self, kind: str) -> int:  # type: ignore[override]
        spec = _tl.spec
        if spec is not None and not spec.live:
            _trap(spec)
        return self._real.next(kind)

    def peek(self, kind: str) -> int:
        return self._real.peek(kind)

    def reserve(self, kind: str, value: int) -> None:
        self._real.reserve(kind, value)

    def snapshot(self) -> dict[str, int]:
        return self._real.snapshot()

    def restore(self, counters: dict[str, int]) -> None:
        self._real.restore(counters)


class _GuardedTrace(TemporalTrace):
    """Recording a trace event is a shared write."""

    def record_event(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        spec = _tl.spec
        if spec is not None and not spec.live:
            _trap(spec)
        return TemporalTrace.record_event(self, *args, **kwargs)


def _rack_guard() -> None:
    spec = _tl.spec
    if spec is not None and not spec.live:
        _trap(spec)


def _make_guarded(fn: Callable[..., Any], ctx: Any) -> Callable[..., Any]:
    def bound(*args: Any, **kwargs: Any) -> Any:
        spec = _tl.spec
        if spec is not None and not spec.live:
            _trap(spec)
        return fn(ctx, *args, **kwargs)

    bound.fn = fn  # type: ignore[attr-defined]
    return bound


# ---------------------------------------------------------------------------
# The interpreter plugin
# ---------------------------------------------------------------------------


class SpecInterpreter(CodeletInterpreter):
    """Replaces ``execute`` completely; relies on nothing in ``_bind_ctx``.

    The base class builds ~60 closures and sets ``__name__``/``__doc__`` on each, per
    codelet; setting those is a stop-the-world pause on free-threaded CPython.  Here the
    bound builtins are built once per thread and the namespace is a copy of that template.
    """

    def __init__(self, engine: "SpeculativeEngine") -> None:
        super().__init__(builtins=engine._builtins)
        self._engine = engine

    def execute(self, compiled: Any, ctx: Any, **codelet_args: Any) -> None:  # type: ignore[override]
        if compiled.is_empty:
            return
        template = _tl.template
        if template is None or template[0] is not ctx:
            template = _tl.template = (ctx, self._engine._make_template(ctx))
        ns = dict(template[1])
        ns["ctx"] = ctx
        ns["args"] = codelet_args
        ns["workspace"] = ctx.workspace
        ns["slipnet"] = ctx.slipnet
        ns["coderack"] = ctx.coderack
        ns["themespace"] = ctx.themespace
        ns["trace"] = ctx.trace
        ns["memory"] = ctx.memory
        ns["temperature"] = ctx.temperature
        ns["commentary"] = ctx.commentary
        ns["rng"] = ctx.rng
        ns["meta"] = ctx.meta
        # Read through the property only when the body names it: that read is what marks
        # a speculation step-relative.
        ns["codelet_count"] = (
            ctx.codelet_count if self._engine._uses_cc(compiled.name) else _tl.cc
        )
        ns["justify_mode"] = ctx.justify_mode
        ns["self_watching"] = ctx.self_watching_enabled
        ns["verbose"] = ctx.verbose
        try:
            exec(compiled.code, ns)  # noqa: S102
        except CodeletFizzle:
            pass


# ---------------------------------------------------------------------------
# Rolling back a private mutation
# ---------------------------------------------------------------------------


def _snapshot_private(codelet: Any) -> list[tuple[Any, dict, list]]:
    """What a speculative attempt may leave behind on the codelet's own arguments.

    A proposed structure is held by exactly one codelet (as its ``structure`` argument),
    so it is private to whoever runs that codelet -- but an *aborted* attempt may have
    mutated it (``update_strength`` writes the strength, an evaluator the proposal level,
    ``get_all_concept_mappings`` caches), and the live re-execution must start from what
    the serial run would have seen.  Saved: each argument object's own attributes, and a
    shallow copy of each list/dict/set attribute.
    """
    saved = []
    for value in codelet.arguments.values():
        # Only a *proposed or evaluated structure* is private to its codelet.  Other
        # argument objects (a ``WorkspaceString``, a built structure) are shared, and
        # restoring a shared object's lists would undo other steps' commits.
        if not isinstance(value, WorkspaceStructure) or value.proposal_level == "built":
            continue
        d = value.__dict__
        containers = [
            (k, v, list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else set(v))
            for k, v in d.items() if isinstance(v, (list, dict, set))
        ]
        saved.append((value, dict(d), containers))
    return saved


def _restore_private(saved: list[tuple[Any, dict, list]]) -> None:
    for obj, attrs, containers in saved:
        for _, container, content in containers:
            if isinstance(container, list):
                container[:] = content
            else:
                container.clear()
                container.update(content)
        d = obj.__dict__
        d.clear()
        d.update(attrs)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class _Flags:
    """The two flags idle workers poll, on an object of their own.

    A worker spins on these (and on its slot) while it waits.  Kept as attributes of the
    engine they would share cache lines with the many fields the coordinator writes every
    step, and each write would pull the line away from the spinning cores and back.
    """

    __slots__ = ("stop", "parking")

    def __init__(self) -> None:
        self.stop = False
        self.parking = False


class _Slot:
    """One worker's mailbox: the spec to run, and its park lock."""

    __slots__ = ("spec", "parked", "lock")

    def __init__(self) -> None:
        self.spec: Spec | None = None
        #: True while the worker blocks on ``lock`` instead of spinning on ``spec``.
        self.parked = False
        #: A binary semaphore held locked: releasing it wakes a parked worker.
        self.lock = threading.Lock()
        self.lock.acquire()


class SpeculativeEngine:
    """Runs a prepared ``EngineRunner`` across *workers* threads, serial-equivalent.

    ``update`` / ``update_threads`` choose the update cycle exactly as for
    :class:`~server.parallel.speculative.reference.StreamSerial`; the SSR it is compared
    with must use the same pair.

    Test knobs (never needed in production): ``inline`` runs every codelet on the
    coordinator through the plugin interpreter (no threads); ``detect`` additionally
    fingerprints the shared state around every read prefix and records any change as a
    hidden-write violation; ``chaos`` forces a fraction of otherwise-valid speculations
    to abort, to exercise the re-execution path; ``direct_single=False`` keeps the
    machinery with one worker (otherwise one worker is just the SSR); ``only_types``
    restricts which codelet types may run ahead (a scheduling choice that cannot change a
    result); ``window`` is how many positions past the next codelet may be run ahead.
    """

    def __init__(
        self,
        runner: Any,
        workers: int = 1,
        *,
        update: str = "engine",
        update_threads: int = 1,
        inline: bool = False,
        detect: bool = False,
        chaos: float = 0.0,
        window: int | None = None,
        use_qos: bool = True,
        grant_timeout: float = 1.0,
        idle_spins: int = 100,
        idle_long_spins: int = 3000,
        idle_nap: float = 0.0,
        direct_single: bool = True,
        only_types: Any = None,
    ) -> None:
        if workers < 0:
            raise ValueError("workers must be >= 0")
        self.runner = runner
        self.workers = workers
        self.inline = inline or detect or workers == 0
        self.detect = detect
        self.chaos = chaos
        self.window = window if window is not None else min(max(2, 2 * workers), 6)
        self.use_qos = use_qos
        self.grant_timeout = grant_timeout
        #: An idle worker spins this many polls, then parks on a lock until it is given
        #: work (``idle_nap`` is accepted for compatibility and unused).
        self.idle_spins = idle_spins
        self.idle_long_spins = idle_long_spins
        self.idle_nap = idle_nap
        #: If given, only these codelet types are ever speculated (an experiment knob:
        #: which codelets run ahead never changes a result, only who executes them).
        self._only = None if only_types is None else frozenset(only_types)
        #: With one worker there is nothing to overlap: the machinery would only add its
        #: own cost, so the run is the stream-serial reference itself (see ``install``).
        #: Test knobs that exercise the machinery (chaos, detect, inline) keep it.
        self._direct = (direct_single and workers == 1 and not (inline or detect or chaos))
        self.ssr = StreamSerial(runner, update=update, update_threads=update_threads)
        self.effects = fx.load()
        self._builtins = get_builtins()
        self.ver = [0] * fx.NCOMP
        self._idx_cache: dict[int, tuple[int, ...]] = {}
        self._specs: dict[int, Spec] = {}
        self._free: list[int] = []
        self._slots: list[_Slot] = []
        self._threads: list[threading.Thread] = []
        self._flags = _Flags()
        self._installed = False
        self._stale: dict[int, Spec] = {}
        self._wtele: list[dict[str, int]] = []
        #: Counters bumped on the coordinator (merged with the workers' at the end).
        self._ctele: dict[str, int] = {}
        #: The cached prediction: ``(F, codelet)`` in clock order, valid while the rack's
        #: ``gen`` is unchanged and ``F`` is below the rack's ``floor_f`` (see ``_refill``).
        self._pq: list[tuple[float, Any]] = []
        self._pq_gen = -1
        self._pq_head = 0
        self._pq_scan = 0
        self._seen_removed = 0
        self._plans: dict[str, tuple[Any, bool, bool]] = {}
        self._registry_get = runner._registry.get_compiled
        #: What worker threads see as ``ctx`` (see ``_SpecContext``); ``None`` when the
        #: coordinator itself plays the speculating thread.
        self._wctx: Any = None
        self.telemetry = _new_telemetry(workers)
        self.violations: list[dict[str, Any]] = []
        #: Optional per-step log of how each speculated step committed (debugging).
        self.outcomes: list[tuple] | None = None
        self._eligible = False
        self._t_update = 0.0
        self._t_codelets = 0.0
        self.ucl = 15
        self._skip = 0

    # -- namespace template ------------------------------------------------

    def _uses_cc(self, name: str) -> bool:
        info = self.effects.types.get(name)
        return True if info is None else info.uses_cc

    def _make_template(self, ctx: Any) -> dict[str, Any]:
        """Bound builtins and the safe Python builtins, built once per thread.

        READ builtins are bound with ``functools.partial`` (C speed, no closure, no
        ``__name__`` write).  WRITE and BARRIER builtins get a guard that waits for the
        token first.  ``VERBOSE_ONLY`` builtins are absent, as in the base interpreter
        when verbose mode is off (this engine does not speculate with verbose on).
        """
        import functools
        import math

        t: dict[str, Any] = {
            "fizzle": _fizzle,
            "CodeletFizzle": CodeletFizzle,
            "math": math, "min": min, "max": max, "abs": abs, "round": round,
            "len": len, "range": range, "sum": sum, "any": any, "all": all,
            "isinstance": isinstance, "getattr": getattr, "hasattr": hasattr,
            "print": print,
        }
        kinds = self.effects.builtins
        for name, fn in self._builtins.items():
            if name in VERBOSE_ONLY and not ctx.verbose:
                continue
            kind = kinds[name].kind if name in kinds else fx.WRITE
            if kind == fx.READ:
                t[name] = functools.partial(fn, ctx)
            else:
                t[name] = _make_guarded(fn, ctx)
        return t

    # -- seqlock versions ----------------------------------------------------

    def _indices(self, mask: int) -> tuple[int, ...]:
        got = self._idx_cache.get(mask)
        if got is None:
            got = tuple(i for i in range(fx.NCOMP) if mask >> i & 1)
            self._idx_cache[mask] = got
        return got

    def _bump(self, mask: int) -> None:
        ver = self.ver
        for i in self._indices(mask):
            ver[i] += 1

    # -- install / remove -------------------------------------------------

    def _eligible_run(self) -> bool:
        ctx = self.runner.ctx
        return not (ctx.verbose or ctx.track_access or ctx.staleness_delay
                    or ctx.commit_lock is not None)

    def install(self) -> None:
        global _GUARD
        if self._installed:
            return
        runner = self.runner
        ctx = runner.ctx
        ssr = self.ssr
        ssr.install()
        if self._direct:
            # One worker: the stream-serial reference *is* the exact answer, with no
            # plugin classes, hooks or threads on top of it.
            self._installed = True
            return
        self._eligible = self._eligible_run() and not self.inline
        self.ucl = runner.meta.get_param("update_cycle_length", 15)

        # Plugin classes: step-relative codelet_count; guards on ids, the trace, the rack.
        self._orig_classes = (ctx.__class__, ctx.ids.__class__, ctx.trace.__class__)
        if self.inline:
            ctx.__class__ = _SpecContext
            ctx.ids.__class__ = _GuardedIds
        else:
            # Workers get a context of their own that shares the real one's attributes.
            wctx = object.__new__(_SpecContext)
            wctx.__dict__ = ctx.__dict__
            self._wctx = wctx
        ctx.trace.__class__ = _GuardedTrace
        ctx.coderack.guard = _rack_guard
        self._nodes = list(ctx.slipnet.nodes.values())
        for node in self._nodes:
            node.__class__ = _DeferredNode
        _GUARD = self._probe_trap if self.detect else self._ensure_live
        _install_class_patches()

        # The interpreter.
        self._orig_interpreter = runner._interpreter
        runner._interpreter = SpecInterpreter(self)

        # Hooks, composed over the SSR's.
        self._ssr_step = runner.step_mcat
        self._ssr_execute = runner._execute_codelet
        self._ssr_update = runner._update_everything
        runner.step_mcat = self._step_hook
        runner._execute_codelet = self._execute_hook
        runner._update_everything = self._update_hook
        for name in ("_post_initial_codelets", "_clamp_initial_slipnodes",
                     "_unclamp_initial_slipnodes"):
            setattr(runner, name, self._wrapped_all(getattr(runner, name)))

        if self._eligible:
            self._start_workers()
        self._installed = True

    def _wrapped_all(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Run *fn* (a coordinator-side mutation outside any codelet) under ALL versions."""

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._bump(fx.ALL)
            try:
                return fn(*args, **kwargs)
            finally:
                self._bump(fx.ALL)

        return wrapped

    def uninstall(self) -> None:
        global _GUARD
        if not self._installed:
            return
        if self._direct:
            self.ssr.uninstall()
            self._installed = False
            return
        self._shutdown_workers()
        runner = self.runner
        ctx = runner.ctx
        for name in ("_post_initial_codelets", "_clamp_initial_slipnodes",
                     "_unclamp_initial_slipnodes"):
            runner.__dict__.pop(name, None)
        runner._interpreter = self._orig_interpreter
        orig_ctx, orig_ids, orig_trace = self._orig_classes
        if self.inline:
            ctx.__class__, ctx.ids.__class__ = orig_ctx, orig_ids
        ctx.trace.__class__ = orig_trace
        self._wctx = None
        ctx.coderack.guard = None
        for node in self._nodes:
            node.__class__ = SlipnetNode
        _GUARD = None
        _remove_class_patches()
        self.ssr.uninstall()
        self._installed = False

    close = uninstall

    def __enter__(self) -> "SpeculativeEngine":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.uninstall()

    # -- running -------------------------------------------------------------

    def run(self, max_steps: int = 0) -> Any:
        """``run_mcat`` with the speculative executor installed."""
        self.install()
        t0 = time.perf_counter()
        try:
            result = self.runner.run_mcat(max_steps)
        finally:
            self._abandon_all()
        self._merge_telemetry()
        self.telemetry["wall_seconds"] = time.perf_counter() - t0
        self.telemetry["update_seconds"] = self._t_update
        self.telemetry["codelet_seconds"] = max(0.0, self.telemetry["wall_seconds"] - self._t_update)
        return result

    def _merge_telemetry(self) -> None:
        tele = self.telemetry
        c = self._ctele
        for key in ("speculated", "committed_speculated", "committed_read_only",
                    "aborted_conflict", "aborted_step", "aborted_exception",
                    "aborted_chaos", "reexecuted", "abandoned"):
            tele[key] = sum(w.get(key, 0) for w in self._wtele) + c.get(key, 0)
        tele["abandoned_read_only"] = c.get("abandoned_read_only", 0)
        tele["per_worker"] = [w.get("committed_speculated", 0) + w.get("reexecuted", 0)
                              for w in self._wtele]

    # -- worker pool -----------------------------------------------------------

    def _start_workers(self) -> None:
        self._flags.stop = False
        self._slots = [_Slot() for _ in range(self.workers)]
        self._wtele = [dict() for _ in range(self.workers)]
        #: Idle workers.  A worker returns itself here once it has left its spec; only the
        #: coordinator pops (``list.append`` / ``pop`` are atomic).
        self._free = list(range(self.workers))
        self._threads = []
        ready = threading.Event()
        for i in range(self.workers):
            t = threading.Thread(
                target=self._worker_main, args=(i, ready), daemon=True,
                name=f"spec-worker-{i}",
            )
            self._threads.append(t)
            t.start()
        ready.set()

    def _shutdown_workers(self) -> None:
        self._flags.stop = True
        self._abandon_all()
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads = []

    def _worker_main(self, index: int, ready: threading.Event) -> None:
        ready.wait()
        if self.use_qos:
            try:
                from server.parallel import qos

                qos.set_thread_qos(qos.USER_INTERACTIVE)
            except Exception:  # noqa: BLE001 - placement is best effort
                pass
        ctx = self.runner.ctx
        slot = self._slots[index]
        free = self._free
        flags = self._flags
        spins = self.idle_spins
        long_spins = self.idle_long_spins
        # The id allocator is a ContextVar, so it must be bound in *this* thread.
        with use_allocator(_WorkerIds(ctx.ids)):
            idle = 0
            while not flags.stop:
                spec = slot.spec
                if spec is None:
                    idle += 1
                    if idle > spins and (flags.parking or idle > long_spins):
                        # Nothing assigned: either an update cycle is running (park at
                        # once) or the worker has idled for a few hundred microseconds
                        # (a run of inline codelets): stop competing for the
                        # coordinator's cores.  The coordinator releases ``slot.lock``
                        # when the cycle ends or when it assigns work.  The wait is
                        # timed so that a wake-up lost to memory ordering costs 1 ms,
                        # never a hang (a shorter timeout makes the idle workers wake
                        # often enough to slow the coordinator by 2%).
                        slot.parked = True
                        if slot.spec is None and not flags.stop:
                            slot.lock.acquire(True, 0.001)
                        slot.parked = False
                        idle = 0
                    continue
                idle = 0
                slot.spec = None
                self._run_spec(spec)
                spec.left = True
                free.append(index)

    # -- a speculation ----------------------------------------------------------

    def _bump_tele(self, spec: Spec, key: str) -> None:
        w = self._wtele[spec.worker]
        w[key] = w.get(key, 0) + 1

    def _run_spec(self, spec: Spec) -> None:
        ctx = self._wctx
        if spec.abandon:
            # The coordinator gave up on it before we picked it up: nothing was touched.
            self._bump_tele(spec, "abandoned")
            spec.status = S_GONE
            return
        spec.status = S_RUNNING
        _tl.spec = spec
        _tl.cc = spec.pred_cc
        try:
            self._bump_tele(spec, "speculated")
            spec.snapshot = _snapshot_private(spec.codelet)
            try:
                self._attempt(spec, ctx)
            except SpeculationAbort as ab:
                self._after_failed_attempt(spec, ab.reason, ctx)
            except BaseException as exc:  # noqa: BLE001
                if spec.live:
                    self._fail_live(spec, exc)
                else:
                    # An exception in a speculative prefix is an abort, never an error.
                    self._after_failed_attempt(spec, R_EXCEPTION, ctx)
        finally:
            _tl.spec = None
            _tl.cc = 0
            if spec.status != S_DONE and spec.status != S_RO_DONE:
                spec.status = S_GONE

    def _after_failed_attempt(self, spec: Spec, reason: str, ctx: Any) -> None:
        """The prefix is stale or was abandoned: undo it, then (if chosen) redo it live."""
        _restore_private(spec.snapshot)
        spec.deferred = []  # the aborted attempt's jolts were never applied: drop them
        if spec.abandon or reason == R_ABANDONED:
            self._bump_tele(spec, "abandoned")
            spec.status = S_GONE
            return
        self._bump_tele(spec, "aborted_" + (reason if reason in (R_CONFLICT, R_EXCEPTION, R_CHAOS)
                                            else "step"))
        spec.reason = reason
        if not spec.token_held and not self._await_token(spec):
            self._bump_tele(spec, "abandoned")
            spec.status = S_GONE
            return
        # Token held: re-execute from scratch, live, from the same body stream.
        spec.reexec = True
        self._bump_tele(spec, "reexecuted")
        self._go_live(spec)
        try:
            with ctx.use_codelet_rng(self.ssr.streams.body(spec.codelet.id)):
                self.runner._interpreter.execute(spec.compiled, ctx, **spec.codelet.arguments)
        except BaseException as exc:  # noqa: BLE001 - a real error: serial raises it too
            self._fail_live(spec, exc)
            return
        self._finish_live(spec)

    def _fail_live(self, spec: Spec, exc: BaseException) -> None:
        spec.error = exc
        self._finish_live(spec)

    def _attempt(self, spec: Spec, ctx: Any) -> None:
        """Run the body speculatively; it either goes live at a trap or validates at its end."""
        spec.start = self.ver[:]
        set_structure_clock(spec.pred_cc)
        with ctx.use_codelet_rng(self.ssr.streams.body(spec.codelet.id)):
            self.runner._interpreter.execute(spec.compiled, ctx, **spec.codelet.arguments)
        if not spec.live:
            # A prefix that never wrote needs no token and no worker to commit: park the
            # result and let the coordinator validate it against the versions when the
            # step comes up (``_commit_read_only``).  The worker is free at once.  Taking
            # the arbiter is what stops the coordinator abandoning the spec under us:
            # whoever holds it decides who restores the prefix's private mutations.
            if not spec.arbiter.acquire(False):
                raise SpeculationAbort(R_ABANDONED)
            spec.status = S_RO_DONE
            return
        self._finish_live(spec)

    def _await_token(self, spec: Spec) -> bool:
        """Spin until the coordinator grants this step the token.  False if abandoned."""
        spec.status = S_WAITING
        n = 0
        while spec.go < 0:
            if spec.abandon:
                return False
            n += 1
            if n > 100:
                time.sleep(0)
        if not spec.arbiter.acquire(False):
            return False  # the coordinator gave up on us first
        spec.token_held = True
        return True

    def _validate(self, spec: Spec) -> None:
        """With the token: is what the prefix saw still what the serial run would see?"""
        if not self._await_token(spec):
            raise SpeculationAbort(R_ABANDONED)
        if spec.step_rel and spec.pred_cc != spec.go:
            raise SpeculationAbort(R_STEP)
        if self.chaos and _chaos_hit(spec.codelet.id, self.chaos):
            raise SpeculationAbort(R_CHAOS)
        ver = self.ver
        start = spec.start
        for i in self._indices(spec.reads):
            if ver[i] != start[i]:  # type: ignore[index]
                raise SpeculationAbort(R_CONFLICT)

    def _go_live(self, spec: Spec) -> None:
        spec.live = True
        spec.status = S_LIVE
        set_structure_clock(spec.go)
        self._bump(spec.info.writes | fx.BIT["slipnet_buf"])
        self._apply_deferred(spec)

    def _apply_deferred(self, spec: Spec) -> None:
        if spec.deferred:
            for node in spec.deferred:
                SlipnetNode.activate_from_workspace(node)
            spec.deferred = []

    def _finish_live(self, spec: Spec) -> None:
        self._bump(spec.info.writes | fx.BIT["slipnet_buf"])
        spec.committed = True
        if not spec.reexec and spec.error is None:
            self._bump_tele(spec, "committed_speculated")
        spec.status = S_DONE

    def _ensure_live(self, spec: Spec) -> None:
        """The trap: called before any shared write.  Waits for the token, validates, goes live."""
        if spec.live:
            return
        self._validate(spec)
        self._go_live(spec)

    # -- the coordinator's hooks ------------------------------------------------

    def _step_hook(self) -> Any:
        if self._free and self._eligible:
            self._refill()
        return self._ssr_step()

    def _update_hook(self, ctx: Any) -> None:
        t0 = time.perf_counter()
        eligible = self._eligible
        if eligible:
            self._quiesce()
            # The update cycle moves the temperature, the urgencies and the rack: the
            # prediction made before it says nothing about the epoch that follows.
            self._pq_gen = -1
            # Nothing runs ahead during the cycle, so idle workers should not burn the
            # cores (and the memory system) the coordinator is using: they block on
            # their locks until the cycle is over.
            self._flags.parking = True
        self._bump(fx.ALL)
        # The rack's guard is a plain attribute, so it can come off while every worker is
        # quiesced.  (The guards that are *classes* -- ids, trace, Slipnet nodes -- stay on:
        # assigning an object's ``__class__`` is a stop-the-world pause on free-threaded
        # CPython, far dearer than the guards themselves.)
        rack = ctx.coderack
        if eligible:
            rack.guard = None
        try:
            self._ssr_update(ctx)
        finally:
            if eligible:
                rack.guard = _rack_guard
                self._unpark()
            self._bump(fx.ALL)
            self._t_update += time.perf_counter() - t0
            self.telemetry["update_cycles"] += 1

    def _unpark(self) -> None:
        """The update cycle is over: wake every parked worker so it is spinning for work."""
        self._flags.parking = False
        for slot in self._slots:
            if slot.parked:
                try:
                    slot.lock.release()
                except RuntimeError:
                    pass

    def _execute_hook(self, codelet: Any) -> None:
        ctype = codelet.codelet_type
        plan = self._plans.get(ctype) or self._type_plan(ctype)
        info = plan[0]
        spec = self._specs.pop(codelet.id, None) if self._specs else None
        if spec is not None and not info.barrier:
            self.runner.ctx.last_codelet_type = ctype
            self._commit_speculated(spec, codelet)
            return
        if spec is not None:
            self._abandon(spec)
        if self._stale and codelet.id in self._stale:
            self._wait_stale(codelet.id)
        if info.barrier:
            self.telemetry["barriers"] += 1
            self._run_inline(codelet, fx.ALL)
        elif self.detect:
            compiled = self.runner._registry.get_compiled(ctype)
            self.runner.ctx.last_codelet_type = ctype
            if not compiled.is_empty:
                self._run_detect(codelet, compiled, info)
        else:
            self.telemetry["inline"] += 1
            self._run_inline(codelet, info.writes)

    def _run_inline(self, codelet: Any, mask: int) -> None:
        """The step as the serial run executes it, with *mask*'s versions held odd.

        An empty-bodied type needs no special case: the engine's own ``_execute_codelet``
        (which ``_ssr_execute`` ends in) returns before running anything.
        """
        indices = self._idx_cache.get(mask) or self._indices(mask)
        ver = self.ver
        for i in indices:
            ver[i] += 1
        try:
            self._ssr_execute(codelet)
        finally:
            for i in indices:
                ver[i] += 1

    def _commit_speculated(self, spec: Spec, codelet: Any) -> None:
        """Commit the step the chosen codelet's speculation was running.

        A prefix that has already finished without writing (``S_RO_DONE``) is validated
        and committed right here, by the coordinator, with no worker involved.  One that
        is still running, or is waiting at its first write, is granted the commit token
        and the coordinator waits for the worker to finish it.
        """
        tele = self.telemetry
        cc = self.runner.ctx.__dict__["codelet_count"]
        if spec.status != S_RO_DONE:
            if spec.status != S_WAITING:
                tele["granted_not_ready"] += 1  # the prefix had not finished: the chain stalls
            spec.go = cc
            deadline = 0.0
            n = 0
            while True:
                st = spec.status
                if st == S_RO_DONE or st == S_DONE or st == S_GONE:
                    break
                n += 1
                if n > 100:
                    time.sleep(0)
                    now = time.perf_counter()
                    if not deadline:
                        deadline = now + self.grant_timeout
                    elif now > deadline:
                        if spec.arbiter.acquire(False):
                            # The worker never reached the token: take the step back.
                            spec.abandon = True
                            self._stale[codelet.id] = spec
                            tele["timeouts"] += 1
                            tele["inline"] += 1
                            self._run_inline(codelet, spec.info.writes)
                            return
                        deadline = now + self.grant_timeout
        if spec.status == S_RO_DONE:
            self._commit_read_only(spec, codelet, cc)
            return
        # Done or gone: the worker has finished with the spec (or is about to leave it).
        n = 0
        while not spec.left:
            n += 1
            if n > 100:
                time.sleep(0)
        if self.outcomes is not None:
            self.outcomes.append((spec.go + 1, spec.type, codelet.id,
                                  "reexec:" + str(spec.reason) if spec.reexec else "spec",
                                  spec.pred_cc + 1))
        if spec.status == S_GONE:
            # The worker could not take the token: run the step here.
            tele["inline"] += 1
            self._run_inline(codelet, spec.info.writes)
            return
        if spec.error is not None:
            raise spec.error

    def _commit_read_only(self, spec: Spec, codelet: Any, cc: int) -> None:
        """Validate a finished read-only prefix on the coordinator and commit it.

        This is ``_validate`` without the token hand-off: the coordinator is the only
        thread that can write anything while the step is being committed (every worker
        that holds a token is waiting for *this* step), so comparing the versions now
        is comparing them at the moment the serial run would have run the codelet.  A
        prefix that fails is undone and re-executed live, here, through the SSR's own
        ``_execute_codelet`` -- the very statements the serial run executes.
        """
        reason = None
        if spec.step_rel and spec.pred_cc != cc:
            reason = R_STEP
        elif self.chaos and _chaos_hit(codelet.id, self.chaos):
            reason = R_CHAOS
        else:
            ver = self.ver
            start = spec.start
            for i in self._indices(spec.reads):
                if ver[i] != start[i]:  # type: ignore[index]
                    reason = R_CONFLICT
                    break
        c = self._ctele
        if reason is None:
            if spec.deferred:
                buf = fx.BIT["slipnet_buf"]
                self._bump(buf)
                self._apply_deferred(spec)
                self._bump(buf)
            spec.committed = True
            c["committed_read_only"] = c.get("committed_read_only", 0) + 1
            if self.outcomes is not None:
                self.outcomes.append((cc + 1, spec.type, codelet.id, "read-only", spec.pred_cc + 1))
            return
        # Stale: undo the prefix's private mutations and run the step for real.
        _restore_private(spec.snapshot)
        spec.deferred = []
        key = "aborted_" + (reason if reason in (R_CONFLICT, R_EXCEPTION, R_CHAOS) else "step")
        c[key] = c.get(key, 0) + 1
        c["reexecuted"] = c.get("reexecuted", 0) + 1
        spec.reason = reason
        spec.reexec = True
        if self.outcomes is not None:
            self.outcomes.append((cc + 1, spec.type, codelet.id, "reexec:" + reason, spec.pred_cc + 1))
        self._run_inline(codelet, spec.info.writes | fx.BIT["slipnet_buf"])

    def _wait_stale(self, cid: int) -> None:
        """An abandoned worker may still be reading this codelet's arguments: let it stop."""
        spec = self._stale.get(cid)
        if spec is None:
            return
        deadline = time.perf_counter() + 2.0
        n = 0
        while not spec.left and time.perf_counter() < deadline:
            n += 1
            if n > 100:
                time.sleep(0)
        self._reap_stale()

    # -- prediction and assignment -----------------------------------------------

    def _type_plan(self, codelet_type: str) -> tuple[Any, bool, bool]:
        """``(info, may run ahead, blocks what comes after)`` for a codelet type, cached.

        *May run ahead*: the type is classified speculable and profitable (and is in the
        experiment allow-list, if one was given).  *Blocks*: the type may write what
        other prefixes read (workspace, Slipnet activations, themespace, temperature) or
        is a barrier, so a prefix started *behind* it would find its premises changed
        and abort; it is therefore not run ahead of, and nothing past it is.
        """
        got = self._plans.get(codelet_type)
        if got is None:
            info = self.effects.info(codelet_type)
            ok = (info.speculate and info.profitable and not info.barrier
                  and (self._only is None or codelet_type in self._only))
            blocks = bool(info.barrier or info.writes & _CONFLICT_MASK)
            got = self._plans[codelet_type] = (info, ok and not blocks, blocks)
        return got

    def _refill(self) -> None:
        """Hand upcoming codelets to free workers (positions 1..window past the head).

        The codelets that will run next are read off a cached prediction of the clock
        rack -- the ``(F, codelet)`` pairs ``predict_entries`` returned -- and the cache
        stays exact for as long as nothing could have been posted ahead of an entry: an
        entry is trusted while its ``F`` is below the smallest ``F`` enrolled since the
        cache was built (``rack.floor_f``), and the cache is void once the rack
        re-weights (``rack.gen``).  Codelets that have left the rack (chosen, evicted)
        are skipped.  None of this decides what runs: it only decides what to run
        *ahead of time*, and a wrong guess costs speed, never exactness (the real
        choice is made by the coordinator, and a speculation is committed only for the
        codelet the choice returned).

        A scan pointer remembers how far into the cache entries have been handled, so a
        step examines about one new entry, not the whole window again.
        """
        free = self._free
        if not free:
            return
        if self._stale:
            self._reap_stale()
        if self._skip:
            self._skip -= 1
            return
        ctx = self.runner.ctx
        cc = ctx.__dict__["codelet_count"]
        left = self.ucl - (cc % self.ucl)
        depth = min(left - 1, self.window)  # the head (position 0) runs inline
        if depth <= 0:
            return
        rack = ctx.coderack
        by_id = rack._by_id
        specs = self._specs
        if rack.removed != self._seen_removed and specs:
            # Some codelet was evicted: drop speculations whose codelet has left the rack.
            for cid in [c for c in specs if c not in by_id]:
                self._abandon(specs.pop(cid))
        self._seen_removed = rack.removed
        stale = self._stale
        plans = self._plans
        slots = self._slots
        tele = self.telemetry
        satisfied = False
        for attempt in (0, 1):
            if self._pq_gen != rack.gen:
                queue = self._pq = []
                self._pq_head = self._pq_scan = 0
            else:
                queue = self._pq
            n = len(queue)
            head = self._pq_head
            while head < n and queue[head][1].id not in by_id:
                head += 1  # chosen or evicted since: not ahead of us any more
            scan = self._pq_scan
            if scan < head:
                scan = head
            pos = 0  # on-rack entries in [head, scan): the window already handled
            for j in range(head, scan):
                if queue[j][1].id in by_id:
                    pos += 1
            floor = rack.floor_f
            while scan < n:
                f, codelet = queue[scan]
                if f >= floor:
                    break  # something posted after the cache may sort before this entry
                cid = codelet.id
                if cid in by_id:
                    plan = plans.get(codelet.codelet_type) or self._type_plan(codelet.codelet_type)
                    if plan[2]:
                        satisfied = True  # a writer/barrier: nothing past it is worth running ahead
                        break
                    if pos:
                        if plan[1] and cid not in specs and cid not in stale:
                            if not free:
                                break
                            compiled = self._compiled(codelet.codelet_type)
                            if compiled is not None:
                                widx = free.pop()
                                spec = Spec(codelet, plan[0], compiled, cc + pos, widx)
                                specs[cid] = spec
                                slot = slots[widx]
                                tele["assigned"] += 1
                                slot.spec = spec
                                if slot.parked:
                                    try:
                                        slot.lock.release()  # wake the parked worker
                                    except RuntimeError:
                                        pass
                        if pos >= depth:
                            scan += 1
                            satisfied = True
                            break
                    pos += 1
                scan += 1
            self._pq_head = head
            self._pq_scan = scan
            if satisfied or attempt or scan < n or not free:
                break
            # The cache ran dry before the window was full: predict afresh.  The step about
            # to run chooses with this very temperature and nothing is posted before it,
            # so ``predict_entries`` may do the choice's own re-weighting now, once,
            # instead of on a copy for the prediction and again for the choice.
            entries = rack.predict_entries(ctx.temperature.value, max(8, min(left, 16) + depth))
            self._pq = [(f, by_id[cid]) for f, cid in entries]
            self._pq_gen = rack.gen
            self._pq_head = self._pq_scan = 0
            tele["repredicts"] += 1
        # Either nothing (more) to speculate on right now (don't rescan every step), or the
        # window is full: the next step moves it by one codelet, so look every other step.
        self._skip = 1 if satisfied else 2

    def _compiled(self, codelet_type: str) -> Any:
        c = self._registry_get(codelet_type)
        return None if c.is_empty else c

    def _reap_stale(self) -> None:
        for cid, spec in list(self._stale.items()):
            if spec.left:
                del self._stale[cid]

    def _abandon(self, spec: Spec) -> None:
        """Mark a speculation dead.  Its worker returns to the pool once it has stopped."""
        spec.abandon = True
        if spec.arbiter.acquire(False):
            # Nobody has the token, and nobody will: a worker still on the spec finds the
            # arbiter taken, restores its own private mutations and leaves.
            self._stale[spec.codelet.id] = spec
            return
        # The arbiter was already taken: the worker finished a read-only prefix.  It has
        # stopped touching the codelet, so undo the prefix's private mutations here.
        deadline = time.perf_counter() + 1.0
        while spec.status != S_RO_DONE and time.perf_counter() < deadline:
            pass
        if spec.status == S_RO_DONE:
            _restore_private(spec.snapshot)
            spec.deferred = []
            c = self._ctele
            c["abandoned"] = c.get("abandoned", 0) + 1
            c["abandoned_read_only"] = c.get("abandoned_read_only", 0) + 1
        else:  # pragma: no cover - the worker never left the arbiter taken
            self._stale[spec.codelet.id] = spec

    def _abandon_all(self) -> None:
        for cid in list(self._specs):
            self._abandon(self._specs.pop(cid))

    def _quiesce(self, timeout: float = 0.05) -> None:
        """Before an update cycle: abandon everything in flight and wait for it to stop."""
        self._abandon_all()
        deadline = time.perf_counter() + timeout
        n = 0
        while self._stale:
            self._reap_stale()
            n += 1
            if n > 100:
                time.sleep(0)
                if time.perf_counter() > deadline:
                    break

    # -- the hidden-write detector -------------------------------------------------

    def _run_detect(self, codelet: Any, compiled: Any, info: Any) -> None:
        """Run a codelet inline as a speculation would, fingerprinting around its prefix."""
        from server.parallel.speculative.fingerprint import state

        ctx = self.runner.ctx
        cc = ctx.__dict__["codelet_count"]
        probe = Spec(codelet, info, compiled, cc, -1)
        probe.go = cc
        probe.fp0 = state(ctx)
        self.telemetry["inline"] += 1
        _tl.spec = probe
        _tl.cc = cc
        try:
            self._bump(info.writes)
            try:
                self._ssr_execute(codelet)
            finally:
                self._bump(info.writes)
            if not probe.live:
                self._probe_compare(probe, "<end of body>")
                self._apply_deferred(probe)
        finally:
            _tl.spec = None
            _tl.cc = 0

    def _probe_trap(self, spec: Spec) -> None:
        """Detect mode's trap: the first write is about to happen; has anything moved yet?"""
        site = "?"
        frame = sys._getframe(2)
        for _ in range(6):
            if frame is None:
                break
            fn = frame.f_locals.get("fn")
            if fn is not None and getattr(fn, "__name__", None):
                site = fn.__name__
                break
            if frame.f_code.co_name in ("next", "record_event", "_rack_guard"):
                site = frame.f_code.co_name
            frame = frame.f_back
        self._probe_compare(spec, site)
        spec.live = True
        self._apply_deferred(spec)

    def _probe_compare(self, spec: Spec, site: str) -> None:
        from server.parallel.speculative.fingerprint import first_differences, state

        now = state(self.runner.ctx)
        before = spec.fp0
        moved = sorted(c for c in now if repr(now[c]) != repr(before.get(c)))
        if moved:
            self.violations.append({
                "codelet": spec.type, "id": spec.codelet.id, "first_trap": site,
                "components": moved, "step": spec.pred_cc + 1,
                "where": {c: first_differences(before[c], now[c], c) for c in moved},
            })


def _chaos_hit(codelet_id: int, rate: float) -> bool:
    return ((codelet_id * 2654435761) & 0xFFFF) / 65536.0 < rate


def _new_telemetry(workers: int) -> dict[str, Any]:
    return {
        "workers": workers,
        "assigned": 0,
        "speculated": 0,
        "committed_speculated": 0,
        "committed_read_only": 0,
        "aborted_conflict": 0,
        "aborted_step": 0,
        "aborted_exception": 0,
        "aborted_chaos": 0,
        "reexecuted": 0,
        "abandoned": 0,
        "barriers": 0,
        "inline": 0,
        "timeouts": 0,
        "update_cycles": 0,
        "per_worker": [0] * workers,
        "wall_seconds": 0.0,
        "update_seconds": 0.0,
        "codelet_seconds": 0.0,
        "granted_not_ready": 0,
        "lost_workers": 0,
        "repredicts": 0,
        "abandoned_read_only": 0,
        # No longer measured (a clock read per step cost more than it explained); the keys
        # stay so that a consumer of the telemetry dict (the run service passes it on to
        # the API) finds what it found before.
        "refill_seconds": 0.0,
        "quiesce_seconds": 0.0,
        "grant_seconds": 0.0,
    }


class SpeculativeExecutor:
    """The registry's ``"speculative"`` executor: ``run(max_steps)`` on a thread pool.

    Builds the pool, runs, and always tears the pool down; the result is the engine's own
    ``RunResult`` with the engine's telemetry on ``result.telemetry``.
    """

    def __init__(self, runner: Any, *, workers: int | None = None, **options: Any) -> None:
        if workers is None:
            from server.engine import hardware

            workers = max(1, hardware.worker_count())
        self.engine = SpeculativeEngine(runner, workers, **options)

    def run(self, max_steps: int = 0) -> Any:
        try:
            result = self.engine.run(max_steps)
            result.telemetry = self.engine.telemetry
            return result
        finally:
            self.engine.close()
