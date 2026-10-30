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

S_PENDING, S_RUNNING, S_WAITING, S_LIVE, S_DONE, S_GONE = range(6)


class Spec:
    """One codelet's speculative execution."""

    __slots__ = (
        "codelet", "type", "info", "compiled", "pred_cc", "status", "go", "abandon",
        "arbiter", "start", "reads", "step_rel", "live", "worker", "error", "reason",
        "reexec", "token_held", "snapshot", "committed", "fp0", "deferred",
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


class _SpecContext(EngineContext):
    """``EngineContext`` whose ``codelet_count`` is step-relative to a speculating thread.

    A data descriptor on the class wins over the instance ``__dict__`` entry the base
    class writes, so the serial code (``ctx.codelet_count += 1``) keeps working through
    the property while a thread with a live speculation record sees the predicted count.
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


class _Slot:
    __slots__ = ("spec", "done", "current")

    def __init__(self) -> None:
        self.spec: Spec | None = None
        self.done = True
        self.current: Spec | None = None


class SpeculativeEngine:
    """Runs a prepared ``EngineRunner`` across *workers* threads, serial-equivalent.

    ``update`` / ``update_threads`` choose the update cycle exactly as for
    :class:`~server.parallel.speculative.reference.StreamSerial`; the SSR it is compared
    with must use the same pair.

    Test knobs (never needed in production): ``inline`` runs every codelet on the
    coordinator through the plugin interpreter (no threads); ``detect`` additionally
    fingerprints the shared state around every read prefix and records any change as a
    hidden-write violation; ``chaos`` forces a fraction of otherwise-valid speculations
    to abort, to exercise the re-execution path.
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
        idle_spins: int = 200,
        idle_nap: float = 0.0,
    ) -> None:
        if workers < 0:
            raise ValueError("workers must be >= 0")
        self.runner = runner
        self.workers = workers
        self.inline = inline or detect or workers == 0
        self.detect = detect
        self.chaos = chaos
        self.window = window if window is not None else max(1, workers)
        self.use_qos = use_qos
        self.grant_timeout = grant_timeout
        #: An idle worker spins this many polls, then sleeps ``idle_nap`` per poll.
        self.idle_spins = idle_spins
        self.idle_nap = idle_nap
        self.ssr = StreamSerial(runner, update=update, update_threads=update_threads)
        self.effects = fx.load()
        self._builtins = get_builtins()
        self.ver = [0] * fx.NCOMP
        self._idx_cache: dict[int, tuple[int, ...]] = {}
        self._specs: dict[int, Spec] = {}
        self._free: list[int] = []
        self._slots: list[_Slot] = []
        self._threads: list[threading.Thread] = []
        self._stop = False
        self._installed = False
        self._stale: dict[int, Spec] = {}
        self._wtele: list[dict[str, int]] = []
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
        self._eligible = self._eligible_run() and not self.inline
        self.ucl = runner.meta.get_param("update_cycle_length", 15)

        # Plugin classes: step-relative codelet_count; guards on ids, the trace, the rack.
        self._orig_classes = (ctx.__class__, ctx.ids.__class__, ctx.trace.__class__)
        ctx.__class__ = _SpecContext
        ctx.ids.__class__ = _GuardedIds
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
        self._shutdown_workers()
        runner = self.runner
        ctx = runner.ctx
        for name in ("_post_initial_codelets", "_clamp_initial_slipnodes",
                     "_unclamp_initial_slipnodes"):
            runner.__dict__.pop(name, None)
        runner._interpreter = self._orig_interpreter
        ctx.__class__, ctx.ids.__class__, ctx.trace.__class__ = self._orig_classes
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
        self.telemetry["codelet_seconds"] = self._t_codelets
        return result

    def _merge_telemetry(self) -> None:
        tele = self.telemetry
        for key in ("speculated", "committed_speculated", "committed_read_only",
                    "aborted_conflict", "aborted_step", "aborted_exception",
                    "aborted_chaos", "reexecuted", "abandoned"):
            tele[key] = sum(w.get(key, 0) for w in self._wtele)
        tele["per_worker"] = [w.get("committed_speculated", 0) + w.get("reexecuted", 0)
                              for w in self._wtele]

    # -- worker pool -----------------------------------------------------------

    def _start_workers(self) -> None:
        self._stop = False
        self._slots = [_Slot() for _ in range(self.workers)]
        self._wtele = [dict() for _ in range(self.workers)]
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
        self._stop = True
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
        # The id allocator is a ContextVar, so it must be bound in *this* thread.
        with use_allocator(ctx.ids):
            idle = 0
            while not self._stop:
                spec = slot.spec
                if spec is None:
                    idle += 1
                    if idle > self.idle_spins:
                        # Nothing assigned: stop competing for the coordinator's cores.
                        time.sleep(self.idle_nap)
                    continue
                idle = 0
                slot.spec = None
                self._run_spec(spec)
                slot.done = True

    # -- a speculation ----------------------------------------------------------

    def _bump_tele(self, spec: Spec, key: str) -> None:
        w = self._wtele[spec.worker]
        w[key] = w.get(key, 0) + 1

    def _run_spec(self, spec: Spec) -> None:
        ctx = self.runner.ctx
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
            if spec.status != S_DONE:
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
            # A prefix that never wrote: validate at its end; there is nothing to apply.
            self._validate(spec)
            if spec.deferred:
                self._bump(fx.BIT["slipnet_buf"])
                self._apply_deferred(spec)
                self._bump(fx.BIT["slipnet_buf"])
            spec.committed = True
            spec.status = S_DONE
            self._bump_tele(spec, "committed_read_only")
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
        if self._eligible:
            t0 = time.perf_counter()
            self._maybe_refill()
            self.telemetry["refill_seconds"] += time.perf_counter() - t0
        return self._ssr_step()

    def _update_hook(self, ctx: Any) -> None:
        t0 = time.perf_counter()
        if self._eligible:
            tq = time.perf_counter()
            self._quiesce()
            self.telemetry["quiesce_seconds"] += time.perf_counter() - tq
        self._bump(fx.ALL)
        try:
            self._ssr_update(ctx)
        finally:
            self._bump(fx.ALL)
            self._t_update += time.perf_counter() - t0
            self.telemetry["update_cycles"] += 1

    def _execute_hook(self, codelet: Any) -> None:
        runner = self.runner
        ctx = runner.ctx
        ctx.last_codelet_type = codelet.codelet_type
        compiled = runner._registry.get_compiled(codelet.codelet_type)
        if compiled.is_empty:
            return
        t0 = time.perf_counter()
        info = self.effects.info(codelet.codelet_type)
        spec = self._specs.pop(codelet.id, None) if self._eligible else None
        if spec is not None and not info.barrier:
            self._commit_speculated(spec, codelet)
        else:
            if spec is not None:
                self._abandon(spec)
            if codelet.id in self._stale:
                self._wait_stale(codelet.id)
            if info.barrier:
                self.telemetry["barriers"] += 1
                self._run_inline(codelet, fx.ALL)
            elif self.detect:
                self._run_detect(codelet, compiled, info)
            else:
                self.telemetry["inline"] += 1
                self._run_inline(codelet, info.writes)
        self._t_codelets += time.perf_counter() - t0

    def _run_inline(self, codelet: Any, mask: int) -> None:
        self._bump(mask)
        try:
            self._ssr_execute(codelet)
        finally:
            self._bump(mask)

    def _commit_speculated(self, spec: Spec, codelet: Any) -> None:
        """Grant the token to the worker holding this step and wait for it to finish."""
        tele = self.telemetry
        if spec.status != S_WAITING:
            tele["granted_not_ready"] += 1  # the prefix had not finished: the chain stalls
        t_grant = time.perf_counter()
        spec.go = self.runner.ctx.__dict__["codelet_count"]
        deadline = t_grant + self.grant_timeout
        n = 0
        while spec.status != S_DONE and spec.status != S_GONE:
            n += 1
            if n > 100:
                time.sleep(0)
                if time.perf_counter() > deadline:
                    if spec.arbiter.acquire(False):
                        # The worker never reached the token: take the step back.
                        spec.abandon = True
                        self._stale[codelet.id] = spec
                        self.telemetry["timeouts"] += 1
                        self.telemetry["inline"] += 1
                        self._run_inline(codelet, spec.info.writes)
                        return
                    deadline = time.perf_counter() + self.grant_timeout
        tele["grant_seconds"] += time.perf_counter() - t_grant
        self._recycle(spec)
        if self.outcomes is not None:
            self.outcomes.append((spec.go + 1, spec.type, codelet.id,
                                  "reexec:" + str(spec.reason) if spec.reexec
                                  else ("read-only" if not spec.info.writes or spec.deferred is None else "spec"),
                                  spec.pred_cc + 1))
        if spec.status == S_GONE:
            # The worker could not take the token: run the step here.
            self.telemetry["inline"] += 1
            self._run_inline(codelet, spec.info.writes)
            return
        if spec.error is not None:
            raise spec.error

    def _wait_stale(self, cid: int) -> None:
        """An abandoned worker may still be reading this codelet's arguments: let it stop."""
        spec = self._stale.get(cid)
        if spec is None:
            return
        slot = self._slots[spec.worker]
        deadline = time.perf_counter() + 2.0
        n = 0
        while not slot.done and time.perf_counter() < deadline:
            n += 1
            if n > 100:
                time.sleep(0)
        self._reclaim()

    # -- prediction and assignment -----------------------------------------------

    def _maybe_refill(self) -> None:
        if self._stale:
            self._reclaim()
        # Hysteresis: predicting costs a scan of the rack, so refill in batches.
        if self._free and len(self._specs) <= self.window // 2:
            if self._skip:
                self._skip -= 1
                return
            assigned = self.telemetry["assigned"]
            self._refill()
            if self.telemetry["assigned"] == assigned:
                self._skip = 2  # nothing to speculate on right now: don't rescan every step

    def _refill(self) -> None:
        runner = self.runner
        ctx = runner.ctx
        rack = ctx.coderack
        cc = ctx.__dict__["codelet_count"]
        left = self.ucl - (cc % self.ucl)
        want = min(left, self.window)
        by_id = rack._by_id
        # Drop speculations whose codelet has left the rack (evicted or cleared).
        for cid in [c for c in self._specs if c not in by_id]:
            self._abandon(self._specs.pop(cid))
        if want <= 0 or not self._free:
            return
        predicted = rack.predict(ctx.temperature.value, want)
        registry = runner._registry
        info_of = self.effects.info
        for i, codelet in enumerate(predicted):
            info = info_of(codelet.codelet_type)
            if info.barrier:
                break
            if not info.speculate:
                continue
            cid = codelet.id
            if cid in self._specs or cid in self._stale:
                continue
            compiled = registry.get_compiled(codelet.codelet_type)
            if compiled.is_empty:
                continue
            if not self._free:
                break
            widx = self._free.pop()
            spec = Spec(codelet, info, compiled, cc + i, widx)
            self._specs[cid] = spec
            slot = self._slots[widx]
            slot.done = False
            slot.current = spec
            self.telemetry["assigned"] += 1
            slot.spec = spec

    def _recycle(self, spec: Spec) -> None:
        slot = self._slots[spec.worker]
        n = 0
        deadline = time.perf_counter() + 2.0
        while not slot.done:  # the worker has fully left the spec
            n += 1
            if n > 100:
                time.sleep(0)
                if time.perf_counter() > deadline:
                    self.telemetry["lost_workers"] += 1  # never returned to the pool
                    return
        slot.current = None
        self._free.append(spec.worker)

    def _abandon(self, spec: Spec) -> None:
        """Mark a speculation dead.  Its worker returns to the pool once it has stopped."""
        spec.abandon = True
        spec.arbiter.acquire(False)  # nobody may ever take its token
        self._stale[spec.codelet.id] = spec

    def _reclaim(self) -> None:
        for cid, spec in list(self._stale.items()):
            slot = self._slots[spec.worker]
            if slot.done:
                slot.current = None
                self._free.append(spec.worker)
                del self._stale[cid]

    def _abandon_all(self) -> None:
        for cid in list(self._specs):
            self._abandon(self._specs.pop(cid))

    def _quiesce(self, timeout: float = 0.05) -> None:
        """Before an update cycle: abandon everything in flight and wait for it to stop."""
        self._abandon_all()
        deadline = time.perf_counter() + timeout
        n = 0
        while self._stale:
            self._reclaim()
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
