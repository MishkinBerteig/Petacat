"""A plugin-side update cycle whose data-parallel parts run on a thread team (WP5).

``EngineRunner._update_everything`` is half of a run's wall time (about 560 us every 15
codelets), so it is the Amdahl wall for any within-run parallelism.  This module
re-implements that one cycle, phase for phase, outside ``server/engine/`` (which stays
single-threaded and never imports this package), under two policies:

``faithful``
    The engine's own cycle, line for line, drawing from ``ctx.rng`` in the engine's
    order.  Bit-identical to ``runner.update_everything()`` under the same generator;
    that is what lets it replace the engine's cycle in the serial corpus.  It runs on
    one thread.  (With ``threads > 1`` it fans out only the one phase that draws
    nothing, the object-value update, which stays exact; see :meth:`UpdateCycle.run`.)

``stream``
    Each random decision draws from a substream of the bound update stream (a
    ``SplittableRNG``), keyed by ``(update index, phase, item identity)``.  No draw
    depends on the order or the thread that made the neighbouring draws, so the result
    is bit-identical for *any* thread count, and the independent loops can be spread
    over a persistent thread team.

What is, and is not, parallel
-----------------------------
Per phase (the full analysis, with timings, is in the WP5 report):

=============================  ===============================================  =========
phase                          dependencies                                     parallel?
=============================  ===============================================  =========
bond and group strengths       Jacobi.  Neither reads a peer's strength: a      yes
                               group's internal strength is category x length
                               (``groups.py:201``), external strength is counts
                               and a density walk over *salience*, which this
                               phase does not write.  Draws: one density walk
                               per item, keyed by the item.
bridge and rule strengths      Gauss-Seidel.  ``Bridge._get_supporting_bridge_  no
                               strength`` reads other bridges' fresh strengths.
object importance              per object, writes only itself                   yes
relative importance            one ratio over a string's objects                serial
object unhappiness, salience,  per object; reads bond/group/bridge strengths    yes
description strengths          the previous phase fixed; writes only itself
workspace averages             reductions over the above                        serial
snag exit, clamp expiry        a handful of branches, at most one draw          serial
workspace -> themespace        ``boost_theme`` accumulates into shared theme    serial
                               activations (a reduction)
themespace spreading           Gauss-Seidel over a small graph                  serial
themespace -> Slipnet          one draw per active theme, in theme order        serial
Slipnet update                 59 nodes; spreading is a matrix step, jumps draw  serial
                               per partially-active node in index order
temperature                    scalar                                           serial
posting rules                  each rule reads the workspace and draws only     yes (decide)
                               its own coins; Codelet ids are allocated in      serial (build)
                               construction order, so the codelets themselves
                               are built serially in the engine's rule order
``post_deferred``              sequential weighted evictions, each re-weighing  serial
                               the rack
EEG, trace snapshot            appends                                          serial
=============================  ===============================================  =========

Equality in law
---------------
Every decision in the cycle is either a coin ``prob(p)`` or a categorical pick, and in
both policies it is made with fresh independent uniforms: the faithful policy takes them
from one Mersenne Twister in a fixed order, the stream policy from a counter-based
generator addressed by ``(update, phase, item)``.  The probabilities ``p`` are functions
of the state at the start of the phase, and that state is the same in both, because the
phases are ordered identically and no draw in a parallel phase changes what another
item in the same phase reads (the Jacobi condition above).  So the joint law of the
cycle's outcomes is the same.  Places that need care:

* *Reusing a key.* Two decisions that share a key share uniforms.  Every key here
  includes the update index, the phase and a stable identity, and a repeated identity
  within a phase (two top-down rules triggered by one node) is disambiguated by the
  rule's codelet type.
* *Serial phases draw from a phase stream* rather than one stream per decision: the
  draws within a phase are ordered by the same deterministic loop in both policies, so
  there is no ordering ambiguity to key away.
* ``SplittableRNG.weighted_pick`` takes the first item whose running total is ``>=`` the
  threshold, whereas ``RNG.weighted_pick`` uses a strict ``>``.  The two differ only on
  the measure-zero event of a draw landing exactly on a running total, except that the
  strict version can never pick a zero-weight *first* item and the non-strict one can
  when the draw is exactly 0.0 (probability 2**-53).  This is the one asymmetry in the
  generators themselves.
* The density walk consumes a data-dependent number of uniforms.  Keying it by item
  makes that harmless: an item's walk cannot shift anybody else's draws, which is what
  a single shared stream could not promise under reordering.

Thread safety
-------------
The team is persistent and spins on a generation counter; workers write only their own
slot, so no shared read-modify-write exists.  Anything that must run on the thread that
owns the numeric backend (MLX streams belong to the thread that made them) is called on
the caller's thread: the batched strength and object-value combines are always serial.
Under a GIL build threads cannot run Python in parallel and a spinning thread would take
the interpreter from the caller, so ``threads`` is silently clamped to 1 there; the
result is the same by construction (``force_threads=True`` overrides, for tests).
"""

from __future__ import annotations

import hashlib
import sys
import threading
import time
from typing import Any, Callable, Sequence

from server.engine.coderack import Codelet
from server.engine.ids import use_allocator
from server.engine.numeric.backend import select_backend
from server.engine.numeric.layout import (
    gather_object_values,
    relative_importances,
    scatter_object_values,
)
from server.engine.posting import (
    PostingContext,
    evaluate_count_formula,
    evaluate_urgency,
)
from server.engine.trace import MAX_CLAMP_PERIOD_DEFAULT

POLICIES = ("faithful", "stream")

#: Fewer items than this and a fan-out costs more than it saves (measured, see the
#: report): a handoff is ~1-3 us in this implementation and an item is ~5-10 us.
DEFAULT_MIN_ITEMS = 8


def _gil_enabled() -> bool:
    check = getattr(sys, "_is_gil_enabled", None)
    return True if check is None else bool(check())


def _label(*parts: Any) -> int:
    """A stable 64-bit key for ``(update, phase, identity...)``.

    Built from text, never from ``id()`` or ``hash()``: a memory address or a salted
    string hash would make the stream differ between processes.
    """
    text = "\x1f".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.blake2b(text, digest_size=8).digest(), "little")


def structure_identity(structure: Any) -> str:
    """A bond's, group's or other structure's stable identity: class name and run id.

    Ids are allocated per run in construction order (``server/engine/ids.py``), so the
    same run gives the same ids whatever the thread count.
    """
    return f"{type(structure).__name__}:{structure.id}"


# ---------------------------------------------------------------------------
# The thread team
# ---------------------------------------------------------------------------


class _Team:
    """A persistent team of ``size - 1`` spinning workers plus the calling thread.

    One job at a time.  The caller publishes ``(job, generation)``; worker *i* runs
    ``job(i)`` and then writes the generation into its own ``_done[i]`` slot; the
    caller runs ``job(0)`` itself and spins until every slot shows the generation.
    There is no shared counter to increment, so nothing needs a lock or an atomic
    read-modify-write (which a free-threaded interpreter would turn into a contended
    cache line).  A spin handoff measured about 0.6 us one way.

    Idle workers spin for ``spin_ns`` after their last job and then sleep in short
    naps, so a team costs cores only around an update cycle (which comes every ~15
    codelets, ~500 us apart) and not for the whole run.
    """

    def __init__(self, size: int, spin_ns: int = 400_000, nap: float = 50e-6) -> None:
        self.size = size
        self._spin_ns = spin_ns
        self._nap = nap
        #: Under a GIL a spinning thread starves the thread it waits for (the
        #: interpreter hands the lock over only every 5 ms), so there every spin step
        #: yields.  It is slow, which is why ``threads`` is clamped to 1 there unless
        #: forced; forcing is for tests that must exercise the fan-out anyway.
        self._yield = _gil_enabled()
        self._gen = 0
        self._job: Callable[[int], None] | None = None
        self._stop = False
        self._done = [0] * size
        self._errors: list[BaseException | None] = [None] * size
        self._threads = [
            threading.Thread(target=self._worker, args=(i,), daemon=True,
                             name=f"update-cycle-{i}")
            for i in range(1, size)
        ]
        for t in self._threads:
            t.start()

    def _worker(self, index: int) -> None:
        seen = 0
        clock = time.perf_counter_ns
        last = clock()
        spins = 0
        while True:
            gen = self._gen
            if gen != seen:
                if self._stop:
                    return
                seen = gen
                try:
                    self._job(index)  # type: ignore[misc]
                except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
                    self._errors[index] = exc
                self._done[index] = gen
                last = clock()
                spins = 0
                continue
            spins += 1
            if self._yield:
                time.sleep(0)
            if spins & 63 == 0 and clock() - last > self._spin_ns:
                time.sleep(self._nap)

    def run(self, job: Callable[[int], None]) -> None:
        """Run ``job(i)`` for every member ``i`` (0 is the caller) and wait."""
        self._job = job
        for i in range(1, self.size):
            self._errors[i] = None
        gen = self._gen + 1
        self._gen = gen  # publishes the job: workers read ``_job`` after seeing this
        error: BaseException | None = None
        try:
            job(0)
        except BaseException as exc:  # noqa: BLE001
            error = exc
        done = self._done
        for i in range(1, self.size):
            spins = 0
            while done[i] != gen:
                spins += 1
                if self._yield or spins > 200_000:
                    time.sleep(0)
        if error is None:
            for e in self._errors:
                if e is not None:
                    error = e
                    break
        if error is not None:
            raise error

    def close(self) -> None:
        self._stop = True
        self._gen += 1
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []


class _LazyStream:
    """A keyed substream that is only derived if something actually draws from it.

    Most items never draw: a posting coin whose probability is 0 or 1 short-circuits,
    and a bond with no supporting bonds never walks.  Deriving the substream costs a
    SHA-256, which is as much as a draw, so deriving it eagerly for every item roughly
    doubled the stream policy's cost.  Laziness cannot change a value: the substream is
    a pure function of its key, and each item's stream is touched by one thread only.
    """

    __slots__ = ("_root", "_key", "_real")

    def __init__(self, root: Any, key: int) -> None:
        self._root = root
        self._key = key
        self._real = None

    def _stream(self) -> Any:
        real = self._real
        if real is None:
            real = self._real = self._root.split(self._key)
        return real

    def prob(self, p: float) -> bool:
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        return self._stream().random() < p

    def random(self) -> float:
        return self._stream().random()

    def randint(self, n: int) -> int:
        return self._stream().randint(n)

    def pick(self, items: Any) -> Any:
        return self._stream().pick(items)

    def weighted_pick(self, items: Any, weights: Any) -> Any:
        return self._stream().weighted_pick(items, weights)

    def perturb(self, n: float) -> float:
        return self._stream().perturb(n)

    def stochastic_filter(self, items: Any, prob_fn: Any) -> list[Any]:
        return self._stream().stochastic_filter(items, prob_fn)

    def trace_about(self, about: Any) -> Any:
        return None

    def trace_unit(self, *a: Any, **k: Any) -> Any:
        return None

    def trace_restore(self, token: Any) -> None:
        return None

    def trace_snapshot(self, ctx: Any) -> None:
        return None


class _RngCtx:
    """The engine context with ``rng`` replaced, for one thread's use.

    ``PostingContext`` reads ``ctx.rng`` for the stochastically blurred object counts.
    ``EngineContext.rng`` is the shared stream (a codelet-local override is per
    thread), so a worker handed the real context would draw from the caller's stream.
    Everything else is read through.
    """

    __slots__ = ("_ctx", "rng")

    def __init__(self, ctx: Any, rng: Any) -> None:
        self._ctx = ctx
        self.rng = rng

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)


# ---------------------------------------------------------------------------
# The update cycle
# ---------------------------------------------------------------------------


class UpdateCycle:
    """One update cycle of *runner*, under a chosen policy and thread count.

    >>> cycle = UpdateCycle(runner, policy="stream", threads=4)
    >>> cycle.run()          # exactly one cycle, drawing from runner.ctx.rng
    >>> cycle.close()        # stops the thread team

    ``runner.ctx.rng`` is bound by the caller.  Under ``stream`` it must be a
    ``SplittableRNG``; bind a fresh one per cycle (keyed by the update index) or one
    for the run, since the update index is part of every key either way.

    ``phase_times`` (when ``profile=True``) accumulates seconds per phase.
    """

    def __init__(
        self,
        runner: Any,
        policy: str = "faithful",
        threads: int = 1,
        *,
        force_threads: bool = False,
        min_items: int = DEFAULT_MIN_ITEMS,
        profile: bool = False,
        parallel_posting: bool = False,
        spin_us: float = 3000.0,
    ) -> None:
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
        if threads < 1:
            raise ValueError("threads must be >= 1")
        self.runner = runner
        self.policy = policy
        self.requested_threads = threads
        self.min_items = min_items
        self.parallel_posting = parallel_posting
        effective = threads
        if threads > 1 and _gil_enabled() and not force_threads:
            effective = 1
        self.threads = effective
        self._team = _Team(effective, spin_ns=int(spin_us * 1000)) if effective > 1 else None
        self.profile = profile
        self.phase_times: dict[str, float] = {}
        self.cycles = 0

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        if self._team is not None:
            self._team.close()
            self._team = None

    def __enter__(self) -> "UpdateCycle":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- fan-out ------------------------------------------------------------

    def _map(self, fn: Callable[[Any], Any], items: Sequence[Any],
             collect: bool = False) -> list[Any] | None:
        """``fn`` over *items*: contiguous chunks across the team, results by index.

        Falls back to a plain loop when there is no team or too few items to repay a
        handoff.  Chunking is static, so which thread ran which item never matters to
        the result.
        """
        n = len(items)
        out: list[Any] | None = [None] * n if collect else None
        team = self._team
        if team is None or n < self.min_items:
            if collect:
                for i in range(n):
                    out[i] = fn(items[i])  # type: ignore[index]
            else:
                for it in items:
                    fn(it)
            return out
        size = team.size
        chunk = -(-n // size)

        def job(member: int) -> None:
            lo = member * chunk
            hi = min(n, lo + chunk)
            if collect:
                for i in range(lo, hi):
                    out[i] = fn(items[i])  # type: ignore[index]
            else:
                for i in range(lo, hi):
                    fn(items[i])

        team.run(job)
        return out

    def _timed(self, name: str, t0: float) -> float:
        now = time.perf_counter()
        if self.profile:
            self.phase_times[name] = self.phase_times.get(name, 0.0) + (now - t0)
        return now

    # -- the cycle ----------------------------------------------------------

    def run(self, stream: Any = None) -> None:
        """Perform exactly one update cycle (``EngineRunner._update_everything``).

        Binds the run's id allocator as the engine's entry point does, so codelets
        built here are numbered in the run's own sequence.  *stream*, if given, is
        bound as ``ctx.rng`` for the duration (``ctx.use_codelet_rng``), which is the
        caller-binds contract in one call; omit it when the caller has bound one.
        """
        runner = self.runner
        ctx = runner.ctx
        if ctx is None:
            return
        if stream is not None:
            with ctx.use_codelet_rng(stream):
                self.run()
            return
        stream = self.policy == "stream"
        if stream and not hasattr(ctx.rng, "split"):
            raise TypeError(
                "stream policy needs a SplittableRNG bound as ctx.rng "
                f"(got {type(ctx.rng).__name__})"
            )
        with use_allocator(ctx.ids):
            self._cycle(ctx, stream)
        self.cycles += 1

    def _cycle(self, ctx: Any, stream: bool) -> None:
        runner = self.runner
        rng = ctx.rng
        runner._update_cycle += 1
        u = runner._update_cycle
        c = ctx.codelet_count + (1 if runner._in_codelet else 0)
        outer = rng.trace_unit(c, "update", "rules-possible", u)
        T = time.perf_counter
        t = T()

        # 1. Check if rules are possible (run.ss:297)
        ctx.workspace.check_if_rules_possible()
        t = self._timed("rules-possible", t)

        # 2-3. Structure strengths, object values, workspace averages (run.ss:306).
        rng.trace_unit(c, "update", "workspace-values", u)
        if stream:
            self._workspace_values_stream(ctx, rng, u)
        else:
            self._workspace_values_faithful(ctx, rng)
        t = self._timed("workspace-values", t)

        # 4. Snag-period stochastic exit (run.ss:299-302)
        rng.trace_unit(c, "update", "snag-exit", u)
        if ctx.trace.within_snag_period:
            progress = ctx.trace.progress_since_last_snag(ctx.workspace)
            snag_rng = rng.split(_label(u, "snag-exit")) if stream else ctx.rng
            if snag_rng.prob(progress / 100.0):
                ctx.trace.undo_snag_condition(
                    ctx.themespace, ctx.slipnet, ctx.temperature, ctx.workspace,
                )

        # 5. Clamp-period expiration check (run.ss:303-304)
        rng.trace_unit(c, "update", "clamp-expiry", u)
        if ctx.trace.clamp_period_expired(
            ctx.codelet_count,
            runner.meta.get_param("max_clamp_period", MAX_CLAMP_PERIOD_DEFAULT),
        ):
            ctx.trace.undo_last_clamp(
                ctx.themespace, ctx.slipnet, ctx.codelet_count, ctx.coderack,
            )

        # 6. Tick clamp expirations
        ctx.slipnet.tick_clamps()
        ctx.temperature.tick_clamp()
        t = self._timed("snag-clamp", t)

        # 7-8. Workspace -> themespace, then within themespace
        rng.trace_unit(c, "update", "themespace", u)
        if ctx.self_watching_enabled:
            runner._spread_activation_to_themespace()
        if ctx.self_watching_enabled:
            ctx.themespace.spread_activation()
        t = self._timed("themespace", t)

        # 9. Themespace -> Slipnet, then the Slipnet update
        rng.trace_unit(c, "update", "slipnet", u)
        slip_rng = rng.split(_label(u, "slipnet")) if stream else ctx.rng
        if ctx.self_watching_enabled:
            ctx.themespace.spread_activation_to_slipnet(ctx.slipnet, slip_rng)
        threshold = getattr(ctx, "spreading_activation_threshold", 100)
        activations_before = {
            name: node.activation for name, node in ctx.slipnet.nodes.items()
        }
        activations_flushed: dict[str, float] = {}
        ctx.slipnet.update_activations(
            slip_rng,
            threshold=threshold,
            on_flushed=lambda: activations_flushed.update(
                {name: node.activation for name, node in ctx.slipnet.nodes.items()}
            ),
        )
        runner._record_concept_activation_events(activations_before, activations_flushed)
        t = self._timed("slipnet", t)

        # 10. Temperature
        rng.trace_unit(c, "update", "temperature", u)
        avg_unhappiness = ctx.workspace.get_average_unhappiness()
        ctx.temperature.update(
            avg_unhappiness, ctx.workspace.rule_established(), runner.meta
        )
        ctx.coderack.current_temperature = ctx.temperature.value
        t = self._timed("temperature", t)

        # 11-12. Post the cycle's codelets as one deferred batch
        if stream:
            rng.trace_unit(c, "update", "post-bottom-up", u)
            batch = self._build_batch_stream(ctx, rng, u)
            t = self._timed("posting", t)
            rng.trace_unit(c, "update", "post-deferred", u)
            ctx.coderack.post_deferred(
                batch, ctx.codelet_count, rng.split(_label(u, "post-deferred"))
            )
        else:
            batch: list[Codelet] = []
            rng.trace_unit(c, "update", "post-bottom-up", u)
            runner._post_bottom_up_codelets(batch)
            rng.trace_unit(c, "update", "post-top-down", u)
            runner._post_top_down_codelets(batch)
            runner._post_thematic_codelets(batch)
            t = self._timed("posting", t)
            rng.trace_unit(c, "update", "post-deferred", u)
            ctx.coderack.post_deferred(batch, ctx.codelet_count, ctx.rng)
        t = self._timed("post-deferred", t)

        # run.ss:320-322: the EEG samples once per update cycle
        ctx.eeg.record(
            ctx.workspace.get_activity(ctx.codelet_count, ctx.meta),
            ctx.temperature.value,
            ctx.codelet_count,
        )
        rng.trace_snapshot(ctx)
        rng.trace_restore(outer)
        self._timed("eeg", t)

    # -- workspace values ---------------------------------------------------

    def _workspace_values_faithful(self, ctx: Any, rng: Any) -> None:
        ws = ctx.workspace
        if self._team is None:
            # The engine's own code path, verbatim.
            self.runner._update_workspace_values(ws, ctx.rng)
            return
        # Strengths draw from the shared stream in a fixed order and stay serial and
        # exact; the object values draw nothing, so they may fan out without changing
        # a single bit.
        ws.update_all_structure_strengths(ctx.rng)
        self._object_values(ws)
        ws.update_average_unhappiness_values()

    def _workspace_values_stream(self, ctx: Any, rng: Any, u: int) -> None:
        ws = ctx.workspace
        # Raw importance reads only descriptor activations, never a structure's
        # strength, so it shares the strength phase's fan-out (one handoff saved).
        flat = [o for st in ws.aggregate_strings for o in st.objects]
        self._strengths_stream(ws, rng, u, importance_of=flat)
        self._object_values(ws, importance_done=True)
        ws.update_average_unhappiness_values()

    # Structure strengths (stream policy) ------------------------------------

    def _strengths_stream(self, ws: Any, root: Any, u: int,
                          importance_of: Sequence[Any] = ()) -> None:
        """``Workspace.update_all_structure_strengths`` with keyed draws.

        Bonds and groups are one Jacobi wave (see the module table).  Bridges and
        rules are a Gauss-Seidel chain and run afterwards, in order, on the caller.
        """
        backend = select_backend(len(ws.all_structures))
        strings = ws.aggregate_strings

        def item_rng(s: Any) -> Any:
            return _LazyStream(root, _label(u, "strength", structure_identity(s)))

        importance = [(None, o) for o in importance_of]
        if backend is None:
            wave = [
                s for st in strings for s in (*st.bonds, *st.groups)
                if hasattr(s, "update_strength")
            ]

            def one(s: Any) -> None:
                if type(s) is tuple:
                    s[1].update_importance()
                else:
                    s.update_strength(item_rng(s))

            self._map(one, wave + importance)
        else:
            groups_of_work: list[list[Any]] = []
            for st in strings:
                groups_of_work.append(list(st.bonds))
                groups_of_work.append(list(st.groups))
            flat = [s for g in groups_of_work for s in g]

            def compute(s: Any) -> tuple[float, float, float]:
                return (
                    s.calculate_internal_strength(),
                    s.calculate_external_strength(item_rng(s)),
                    s.get_thematic_compatibility(),
                )

            def one_or_imp(s: Any) -> Any:
                if type(s) is tuple:
                    s[1].update_importance()
                    return None
                return compute(s)

            parts = self._map(one_or_imp, flat + importance, collect=True) or []
            pos = 0
            # The backend is called here, on the caller's thread, one batch per
            # (string, kind) exactly as the engine batches them.
            for g in groups_of_work:
                if not g:
                    continue
                chunk = parts[pos:pos + len(g)]
                pos += len(g)
                strengths = backend.structure_strengths(
                    [p[0] for p in chunk], [p[1] for p in chunk], [p[2] for p in chunk]
                )
                for structure, strength in zip(g, strengths):
                    structure.strength = strength
        tail_rng = root.split(_label(u, "strength-chain"))
        for structure in (
            ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges
            + ws.top_rules + ws.bottom_rules
        ):
            if hasattr(structure, "update_strength"):
                structure.update_strength(tail_rng)

    # Object values (both policies; draws nothing) ---------------------------

    def _object_values(self, ws: Any, importance_done: bool = False) -> None:
        """``Workspace.update_all_object_values`` with the per-object steps fanned out.

        Mirrors ``WorkspaceString.update_object_values`` step for step (workspace.py
        :674-726), including its per-string backend choice.  The only reordering is
        across objects within a step, and every step writes only the object it reads
        from (plus that object's own descriptions), so the reordering is exact.
        """
        strings = list(ws.aggregate_strings)
        all_objs = [(s, list(s.objects)) for s in strings]
        flat = [o for _, objs in all_objs for o in objs]

        # 1. raw importances
        if not importance_done:
            self._map(lambda o: o.update_importance(), flat)

        # 2. relative importances: a ratio over each string's objects
        # Strings are independent of one another, so the ratios fan out per string
        # (they are the costliest serial step: exact rationals, ~55 us a cycle).
        ratios = self._map(lambda pair: relative_importances(pair[1]), all_objs,
                           collect=True) or []
        plans = []
        for (s, objs), rels in zip(all_objs, ratios):
            for obj, rel in zip(objs, rels):
                obj.relative_importance = rel
            plans.append((objs, select_backend(len(objs))))

        # 3-9. full per-object update where there is no backend, traversals otherwise
        full: list[Any] = []
        partial: list[Any] = []
        for objs, backend in plans:
            (full if backend is None else partial).extend(objs)

        if not partial:
            self._map(lambda o: o.update_object_values(), full)
        else:
            full_set = {id(o) for o in full}

            def per_object(o: Any) -> None:
                if id(o) in full_set:
                    o.update_object_values()
                else:
                    o.update_intra_string_unhappiness()
                    o.update_inter_string_unhappiness()

            self._map(per_object, full + partial)
            for objs, backend in plans:
                if backend is None:
                    continue
                batch = gather_object_values(objs)
                backend.combine_object_values(batch)
                scatter_object_values(batch, objs)
            self._map(lambda o: o.update_description_strengths(), partial)
        ws._average_unhappiness = None

    # Posting (stream policy) -------------------------------------------------

    def _build_batch_stream(self, ctx: Any, root: Any, u: int) -> list[Codelet]:
        """The cycle's bottom-up, top-down and thematic posts, in the engine's order.

        Deciding (condition, probability, coin, urgency, count) is read-only on the
        workspace and draws only from the rule's own keyed stream, so those decisions
        fan out.  Building the ``Codelet``s does not: ``Codelet.id`` is allocated at
        construction, so they are built here, serially, in the engine's order.
        """
        runner = self.runner
        meta = runner.meta
        time_stamp = ctx.codelet_count
        # Warm the lazily cached workspace metrics once, serially, so the decisions
        # only read them (a read that fills a cache is a write under free-threading).
        ws = ctx.workspace
        ws.get_average_unhappiness()

        tasks: list[tuple] = []  # (kind, rule, node, key)
        for rule in runner.bottom_up_posting_rules():
            tasks.append(("bu", rule, None, rule.codelet_type))
        top_down_nodes = meta.get_param("top_down_slipnodes", [])
        for node_name in top_down_nodes:
            node = ctx.slipnet.nodes.get(node_name)
            if node is None or not node.above_threshold():
                continue
            for rule in meta.posting_rules:
                if rule.direction != "top_down":
                    continue
                if rule.triggering_slipnodes and node_name not in rule.triggering_slipnodes:
                    continue
                tasks.append(("td", rule, node, f"{rule.codelet_type}({node_name})"))
        thematic_rule = runner.posting_rule_for("thematic-bridge-scout")
        if thematic_rule is not None:
            tasks.append(("th", thematic_rule, None, thematic_rule.codelet_type))

        def decide(task: tuple) -> tuple[int, int] | None:
            kind, rule, node, key = task
            if kind == "bu":
                if not runner._rule_condition_holds(rule):
                    return None
                urgency = None
            elif kind == "th":
                if not runner._rule_condition_holds(rule):
                    return None
                urgency = None
            else:
                urgency = evaluate_urgency(
                    rule, PostingContext(ctx, node=node),
                    default=meta.get_urgency("low"),
                )
            prob = runner._compute_posting_probability(rule)
            item = _LazyStream(root, _label(u, "post", kind, key))
            if not item.prob(prob):
                return None
            if kind == "bu":
                urgency = runner._compute_bottom_up_urgency(rule)
            elif kind == "th":
                urgency = evaluate_urgency(
                    rule, PostingContext(ctx), default=meta.get_urgency("low")
                )
            num = evaluate_count_formula(rule, PostingContext(_RngCtx(ctx, item)))
            return urgency, num

        if self.parallel_posting:
            decisions = self._map(decide, tasks, collect=True) or []
        else:
            decisions = [decide(task) for task in tasks]

        batch: list[Codelet] = []
        for (kind, rule, node, _), decision in zip(tasks, decisions):
            if decision is None:
                continue
            urgency, num = decision
            for _ in range(num):
                if kind == "td":
                    batch.append(Codelet(rule.codelet_type, urgency,
                                         arguments={"slipnode": node},
                                         time_stamp=time_stamp))
                else:
                    batch.append(Codelet(rule.codelet_type, urgency,
                                         time_stamp=time_stamp))
        return batch
