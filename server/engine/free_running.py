"""Free-running execution — codelets across CPU cores, no global barrier (WP4.4).

The three prerequisites are in place: per-codelet random streams (WP4.1) so workers do
not share generator state, read/write sets (WP4.2) so a codelet can be told its premises
moved, and a sharded coderack (WP4.3) so selection is not one hot queue.  This is what
uses them.

What "no global barrier" costs, and what it buys
------------------------------------------------
Two things in the serial loop are barriers by nature, and they are treated differently.

**The update cycle** — recomputing strengths, saliences, activations and temperature
every fifteen codelets — is *not* stopped for.  Whichever worker crosses the boundary
runs it while the others keep executing.  That is deliberately the staleness WP0.5
measured: during an update, other codelets read values mid-recomputation.  WP0.5 put the
tolerance at **five codelets** of read lag before convergence starts to suffer, and one
update cycle overlapping a handful of codelets sits inside that budget.

**Committing a structure** is serialised, and this is the design's central compromise.
A codelet is a long read-and-decide followed by a short mutation: codelet execution is
about 40% of runtime after WP1.1, and the mutation inside it is a list append and a few
field writes.  Serialising only the mutation leaves the expensive part parallel, and it
is what makes the parallelism sound without a full multi-version workspace — the fights
and duplicate checks inside ``build_structure`` are themselves read-modify-write
sequences over shared lists, and running two of those concurrently corrupts the lists
rather than producing a conflict the model can interpret.

**What this is not.** It is not full optimistic concurrency with deferred commit. A
codelet's writes land as it makes them, so a codelet whose premises moved has already
half-applied by the time validation notices. What validation gives here is *telemetry* —
the conflict rate that says how much staleness the configuration is actually producing —
rather than a rollback. Deferring writes into a delta and applying it atomically is the
next step and is deliberately not taken here; WP4.2's delta discipline is the groundwork
for it. This is stated plainly because the difference matters and is easy to overclaim.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from server.engine import hardware
from server.engine.coderack_shards import WorkerShardedCoderack
from server.engine.ids import use_allocator
from server.engine.runner import (
    STATUS_ANSWER_FOUND,
    STATUS_GAVE_UP,
    STATUS_HALTED,
    STATUS_RUNNING,
)
from server.engine.splittable_rng import SplittableRNG

if TYPE_CHECKING:
    from server.engine.runner import EngineRunner


@dataclass
class FreeRunResult:
    """What a free-running execution did, and how contended it was."""

    status: str = STATUS_HALTED
    answers: list[str] = field(default_factory=list)
    codelet_count: int = 0
    workers: int = 1
    seconds: float = 0.0
    #: Codelets whose read-set had moved by the time they committed.
    conflicts: int = 0
    #: Codelets that produced no structure — the architecture's own outcome, which a
    #: lost race is folded into.
    fizzles: int = 0
    update_cycles: int = 0
    per_worker: list[int] = field(default_factory=list)

    @property
    def codelets_per_second(self) -> float:
        return self.codelet_count / self.seconds if self.seconds else 0.0

    @property
    def conflict_rate(self) -> float:
        return self.conflicts / self.codelet_count if self.codelet_count else 0.0

    def summary(self) -> dict:
        return {
            "status": self.status,
            "answers": self.answers,
            "workers": self.workers,
            "codelets": self.codelet_count,
            "seconds": round(self.seconds, 4),
            "codelets_per_second": round(self.codelets_per_second),
            "conflicts": self.conflicts,
            "conflict_rate": round(self.conflict_rate, 4),
            "update_cycles": self.update_cycles,
            "per_worker": self.per_worker,
        }


class FreeRunningEngine:
    """Runs a prepared ``EngineRunner`` across several worker threads.

    Wrapping the runner rather than living inside it, so the serial loop — the permanent
    reference mode that Audit provides and every later phase validates against — keeps
    exactly the shape it has and cannot acquire concurrency bugs by proximity.
    """

    def __init__(
        self,
        runner: EngineRunner,
        workers: int | None = None,
        shards: int | None = None,
    ) -> None:
        self.runner = runner
        # ``None`` asks the machine: one worker per performance core, one shard
        # per worker.  Both are stated in ``server.engine.hardware``, along with
        # the environment variables that pin them, so a run on a 32-core machine
        # uses 32 cores and a run on an 8-core machine is not asked to.
        self.workers = max(1, workers if workers is not None else hardware.worker_count())
        self.shards = shards if shards is not None else hardware.shard_count(self.workers)

        # Reentrant, and it has to be.  ``build_structure`` takes the commit lock and
        # then calls ``break_structure`` for each opponent it defeats, and
        # ``record_event`` for the group, slippage and rule events a build produces —
        # both of which take the same lock.  With a plain ``Lock`` the first codelet that
        # won a fight deadlocked against itself, and the symptom was a run that produced
        # no output at all rather than an error.
        self._commit_lock = threading.RLock()
        self._count_lock = threading.Lock()
        self._stop = threading.Event()
        #: Held shut until every worker thread exists.
        #:
        #: Without it the pool is built *while the first worker is already executing*.
        #: ``Thread.start()`` ends in ``self._started.wait()``, and a worker running
        #: interpreted codelet bodies makes no call that releases the GIL, so the main
        #: thread can lose that handoff for the whole run and threads 2..N are never
        #: constructed.  Measured: one ``start()`` call taking 466 ms of a 465 ms run,
        #: reported as ``[4001, 0, 0, 0]`` because ``_per_worker`` is preallocated to
        #: the requested width and therefore describes workers that never existed.
        #:
        #: ``Event.wait`` releases the GIL, which is exactly what lets the main thread
        #: finish its ``start()`` loop.  Same discipline as
        #: ``scripts/bench_shards.py::measure_contention``'s barrier, as an Event set
        #: by the owner rather than a ``Barrier`` a dying worker could break.
        self._all_started = threading.Event()
        self._conflicts = 0
        self._update_cycles = 0
        self._per_worker: list[int] = []

    # -- preparation ---------------------------------------------------

    def prepare(self) -> None:
        """Install the sharded rack and the shared commit lock.

        Codelets already carried over from ``init_mcat`` are moved across rather than
        discarded: they are the run's opening bottom-up scouts, and dropping them would
        start the run somewhere the serial engine never starts.
        """
        ctx = self.runner.ctx
        if isinstance(ctx.coderack, WorkerShardedCoderack):
            return

        sharded = WorkerShardedCoderack(ctx.meta, self.shards)
        sharded.rng = ctx.rng
        sharded.current_time = ctx.coderack.current_time
        # As a *batch*, not one at a time.  ``post`` routes to the posting thread's own
        # shard, and this runs on the main thread, so posting them individually put the
        # entire opening population into shard 0 — where a shard holds
        # ``max_coderack_size // shards`` and the rest were evicted on the way in.
        # Measured before this: 56 codelets in, ``[25, 0, 0, 0]`` out, 31 discarded,
        # and three of the four workers starting with nothing to draw.
        #
        # ``post_deferred`` deals round-robin across the shards and its own docstring
        # names this hazard — "keeps a 36-codelet opening batch from overflowing one
        # 25-codelet shard while the others sit empty".  It is also the right call on
        # its own terms: these are one batch, and ``post-initial-codelets``
        # (``run.ss:275-283``) lands them through ``post-deferred-codelets``.
        carried = [
            codelet for b in ctx.coderack.bins for codelet in list(b.codelets)
        ]
        sharded.post_deferred(carried, ctx.coderack.current_time, ctx.rng)
        ctx.coderack = sharded

        # The commit lock is read by the mutating builtins through the context, so the
        # engine needs no knowledge of whether it is running in parallel — a serial run
        # simply has none and takes no lock.
        ctx.commit_lock = self._commit_lock
        ctx.enable_access_tracking()

    # -- the loop ------------------------------------------------------

    def run(self, max_steps: int = 0) -> FreeRunResult:
        self.prepare()
        runner = self.runner
        ctx = runner.ctx
        runner.status = STATUS_RUNNING
        ctx.run_ended = False
        self._stop.clear()
        self._conflicts = 0
        self._update_cycles = 0
        self._per_worker = [0] * self.workers

        self._all_started.clear()
        threads = [
            threading.Thread(target=self._worker, args=(index, max_steps), daemon=True)
            for index in range(self.workers)
        ]
        try:
            for t in threads:
                t.start()
        finally:
            # Unconditional, and before any ``join``: a thread that failed to start
            # must not leave the ones that did waiting for it.
            #
            # The clock starts with the pool, so ``seconds`` measures execution rather
            # than thread construction.
            started = time.perf_counter()
            self._all_started.set()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - started

        if runner.status == STATUS_RUNNING:
            runner.status = STATUS_HALTED
        self._reconcile_ending()
        runner.finish()

        return FreeRunResult(
            status=runner.status,
            answers=list(runner._answers),
            codelet_count=ctx.codelet_count,
            workers=self.workers,
            seconds=elapsed,
            conflicts=self._conflicts,
            update_cycles=self._update_cycles,
            per_worker=list(self._per_worker),
        )

    def _worker(self, index: int, max_steps: int) -> None:
        runner = self.runner
        ctx = runner.ctx
        update_cycle = ctx.meta.get_param("update_cycle_length", 15)

        # Wait for the rest of the pool before touching the rack.  See
        # ``_all_started``: without this the first worker starves the main thread of
        # the GIL and the remaining workers are never created.
        self._all_started.wait()

        # Each worker binds the run's identifier allocator for itself.  The binding is a
        # ContextVar, so a thread that did not set it would silently allocate from the
        # process-wide fallback and hand out identifiers that collide with another
        # worker's — the exact defect WP0.3 removed, reintroduced by threading.
        with use_allocator(ctx.ids):
            local_rng = SplittableRNG(ctx.rng.seed if hasattr(ctx.rng, "seed") else 0)

            while not self._stop.is_set():
                if runner.status != STATUS_RUNNING:
                    break

                codelet = ctx.coderack.choose_and_remove(
                    ctx.temperature.value, ctx.rng, worker=index
                )
                if codelet is None:
                    # Nothing to do anywhere, including by stealing.  The serial loop
                    # reposts the opening codelets here; doing that from several workers
                    # at once would flood the rack, so only one may, under the lock.
                    with self._commit_lock:
                        if ctx.coderack.is_empty:
                            runner._post_initial_codelets()
                            ctx.slipnet.clamp_initially_relevant(ctx.meta)
                    continue

                with self._count_lock:
                    ctx.codelet_count += 1
                    step = ctx.codelet_count
                    ctx.coderack.current_time = step
                    # Counted under the same lock as ``codelet_count``, because
                    # ``list[i] += 1`` is a read-modify-write and losing one makes the
                    # telemetry disagree with the run: observed as 900 worker-codelets
                    # against a codelet_count of 901.
                    self._per_worker[index] += 1
                if max_steps > 0 and step > max_steps:
                    self._stop.set()
                    break

                # Each codelet draws from a stream of its own, addressed by where it ran
                # rather than by what ran before it — which is the property that survives
                # an execution order that is not determined (WP4.1).
                #
                # Bound **per thread**.  Assigning ``ctx.rng`` and restoring it, as this
                # did, is a shared attribute: worker A's assignment was visible to worker
                # B, so B ran its codelet against A's stream, and whichever worker
                # restored last left ``ctx.rng`` holding some finished codelet's stream.
                # That defeated the entire purpose of the per-codelet streams and put the
                # run's ``random.Random`` — an object with 19,937 bits of mutable state —
                # in reach of two threads at once.
                codelet_rng = local_rng.for_codelet(worker=index, slot=step)
                with ctx.use_codelet_rng(codelet_rng):
                    ctx.access.begin()
                    try:
                        runner._execute_codelet(codelet)
                    finally:
                        if not ctx.access.validate():
                            with self._count_lock:
                                self._conflicts += 1
                        ctx.access.end()

                self._collect_outcome(step)

                # The update cycle runs *without stopping the other workers*, which is
                # the staleness WP0.5 bounded at five codelets. Whichever worker crosses
                # the boundary runs it.
                if step % update_cycle == 0:
                    with self._commit_lock:
                        runner.update_everything()
                        self._update_cycles += 1
                    runner._emit_new_trace_events(ctx)

    def _collect_outcome(self, step: int) -> None:
        """Claim the run's terminal outcome, once, whichever worker produced it.

        Serially a run has exactly one ending: ``report_answer`` sets the pending answer
        and the runner collects it before any other codelet executes, so a jootser can
        never give up on a run that has just answered.  Free-running removes that
        guarantee — two workers can reach two different terminal outcomes before either
        is collected — and the first version of this collected them in the wrong order.

        It checked give-up first, so a run that had genuinely found an answer was recorded
        as having given up while ``workspace.answer_string`` still held the answer,
        producing the stopping state ``gave_up:b``: a status saying no answer was found
        beside an answer that was. The pending answer was left queued and never collected
        at all.

        **An answer wins.** Both events really happened, but they are not symmetrical: an
        answer is a positive result the program actually produced — the workspace holds
        it and Episodic Memory has stored it — whereas giving up is the claim that no
        answer was found, which by then is false.
        """
        runner = self.runner
        ctx = runner.ctx

        with self._count_lock:
            if runner.status in (STATUS_ANSWER_FOUND, STATUS_GAVE_UP):
                # Already ended. Discard any later terminal event rather than letting it
                # overwrite the outcome or leave its flag set for the next worker to find.
                ctx.run_ended = True
                ctx._pending_answer = None
                ctx._gave_up = False
                return

            pending = getattr(ctx, "_pending_answer", None)
            gave_up = getattr(ctx, "_gave_up", False)
            ctx._pending_answer = None
            ctx._gave_up = False

            if pending is not None:
                runner._answers.append(pending)
                runner.status = STATUS_ANSWER_FOUND
                ctx.run_ended = True
                quality = float(getattr(ctx, "_pending_answer_quality", 0) or 0)
            elif gave_up:
                runner.status = STATUS_GAVE_UP
                ctx.run_ended = True
                quality = None
            else:
                return

        if quality is not None:
            ctx.sink.on_answer(ctx, pending, quality)
        self._stop.set()

    def _reconcile_ending(self) -> None:
        """Make the recorded status and the Workspace agree about the ending.

        A worker can call ``report_answer`` after another has already claimed the ending,
        and ``report_answer`` writes ``workspace.answer_string`` directly.  The stopping
        state the oracle reads is ``status:answer_string``, so an unreconciled run reports
        a status and an answer that contradict each other.

        Resolved toward the answer for the same reason as above — the program did produce
        it — except in justification mode, where the answer string was supplied at the
        start rather than found, and its presence says nothing about how the run ended.
        """
        runner = self.runner
        ctx = runner.ctx
        if ctx.justify_mode or runner.status != STATUS_GAVE_UP:
            return
        answer_string = ctx.workspace.answer_string
        if answer_string is None:
            return
        runner.status = STATUS_ANSWER_FOUND
        if not runner._answers:
            runner._answers.append(answer_string.text)


def run_free(
    runner: EngineRunner,
    workers: int | None = None,
    max_steps: int = 0,
    shards: int | None = None,
) -> FreeRunResult:
    """Convenience: execute a prepared runner free-running and return the telemetry.

    ``workers=None`` takes the machine's own count — see
    :func:`server.engine.hardware.worker_count`.
    """
    return FreeRunningEngine(runner, workers=workers, shards=shards).run(max_steps)
